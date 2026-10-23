from django.db.models import F, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User
from apps.chat.models import Conversation, Message, Participant
from apps.core.repositories import BaseRepository
from apps.media.models import MediaAsset


class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    def get_queryset(self) -> QuerySet:
        # An inbox row renders the other person and a preview of the newest
        # message, so both are resolved up front rather than per row.
        return (
            super()
            .get_queryset()
            .select_related("last_message", "last_message__sender")
            .prefetch_related("participants__user__avatar")
        )

    def for_user(self, user_id) -> QuerySet:
        return self.get_queryset().filter(participants__user_id=user_id)

    def by_direct_key(self, key: str) -> Conversation | None:
        return self.get_queryset().filter(direct_key=key).first()

    def create_direct(self, *, key: str, users: list[User]) -> Conversation:
        """Insert a thread and both sides of it.

        Callers must wrap this in a transaction so a conversation is never left
        with only one participant.
        """
        conversation = self.model._default_manager.create(direct_key=key)
        Participant.objects.bulk_create(
            [Participant(conversation=conversation, user=user) for user in users]
        )
        return conversation

    def touch(self, *, conversation_id, message: Message) -> None:
        """Point a thread at its newest message in one statement.

        `updated_at` is passed explicitly because `auto_now` only applies to
        saves, not to an UPDATE.
        """
        self.model._default_manager.filter(pk=conversation_id).update(
            last_message=message,
            last_message_at=message.created_at,
            updated_at=timezone.now(),
        )


class ParticipantRepository(BaseRepository[Participant]):
    model = Participant

    def get_for(self, *, conversation_id, user_id) -> Participant | None:
        return (
            self.get_queryset()
            .filter(conversation_id=conversation_id, user_id=user_id)
            .first()
        )

    def user_ids_in(self, conversation_id) -> list[int]:
        return list(
            self.get_queryset()
            .filter(conversation_id=conversation_id)
            .values_list("user_id", flat=True)
        )

    def bump_unread(self, *, conversation_id, except_user_id) -> None:
        """Raise the unread count for every recipient in one UPDATE."""
        self.get_queryset().filter(conversation_id=conversation_id).exclude(
            user_id=except_user_id
        ).update(unread_count=F("unread_count") + 1, updated_at=timezone.now())

    def mark_read(self, participant: Participant) -> Participant:
        participant.unread_count = 0
        participant.last_read_at = timezone.now()
        participant.save(update_fields=["unread_count", "last_read_at", "updated_at"])
        return participant

    def unread_total(self, user_id) -> int:
        """Unread messages across every thread, for the header badge."""
        return self.get_queryset().filter(user_id=user_id).aggregate(
            total=Coalesce(Sum("unread_count"), 0)
        )["total"]


class MessageRepository(BaseRepository[Message]):
    model = Message

    def get_queryset(self) -> QuerySet:
        # Every bubble renders its sender, its attachments, and the message it
        # quotes; resolving them here keeps a page of history at a fixed few
        # queries instead of several per message.
        return (
            super()
            .get_queryset()
            .select_related("sender", "sender__avatar", "reply_to", "reply_to__sender")
            .prefetch_related("media", "reply_to__media")
        )

    def in_conversation(self, conversation_id) -> QuerySet:
        return self.get_queryset().filter(conversation_id=conversation_id)

    def get_in_conversation(self, *, conversation_id, message_id) -> Message | None:
        return self.in_conversation(conversation_id).filter(pk=message_id).first()

    def create_with_media(
        self,
        *,
        conversation_id,
        sender: User,
        body: str,
        reply_to: Message | None,
        media: list[MediaAsset],
    ) -> Message:
        """Insert a message and its attachments.

        Callers must wrap this in a transaction so a message is never left with
        a partial set of attachments.
        """
        message = self.model._default_manager.create(
            conversation_id=conversation_id,
            sender=sender,
            body=body,
            reply_to=reply_to,
        )
        if media:
            for position, asset in enumerate(media):
                asset.message = message
                asset.position = position
            # One statement for every attachment rather than one apiece.
            MediaAsset.objects.bulk_create(media)
        return message
