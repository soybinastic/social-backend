"""Conversation and message use cases."""

from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.accounts.repositories import UserRepository
from apps.chat.models import Conversation, Message, Participant
from apps.chat.repositories import (
    ConversationRepository,
    MessageRepository,
    ParticipantRepository,
)
from apps.core.exceptions import InvalidInput, ResourceNotFound
from apps.media.kinds import MediaKind
from apps.media.kinds import registry as media_registry
from apps.media.services import MediaUploadService
from apps.media.storage.base import MediaStorage

# A chat carries photos and voice notes; video belongs in a post.
CHAT_MEDIA_REGISTRY = media_registry.subset(MediaKind.IMAGE, MediaKind.AUDIO)

# Lower than a post's limit: a message is a message, not an album.
MAX_ATTACHMENTS_PER_MESSAGE = 4


class ChatService:
    """Everything a conversation can be asked to do.

    Sending is an HTTP call, not a WebSocket frame. Attachments need a multipart
    body, and one write path means validation, media cleanup and unread counters
    live in a single place; the socket exists to deliver what was written. See
    `apps.chat.consumers`.
    """

    def __init__(
        self,
        conversations: ConversationRepository | None = None,
        participants: ParticipantRepository | None = None,
        messages: MessageRepository | None = None,
        users: UserRepository | None = None,
        storage: MediaStorage | None = None,
    ):
        self._conversations = conversations or ConversationRepository()
        self._participants = participants or ParticipantRepository()
        self._messages = messages or MessageRepository()
        self._users = users or UserRepository()
        # The upload service is built here rather than injected, unlike
        # `PostService`, because the narrowed registry is a rule of this service
        # and not something a caller may substitute. Storage is still a seam.
        self._uploads = MediaUploadService(storage=storage, registry=CHAT_MEDIA_REGISTRY)

    def start_direct(self, *, user: User, username: str) -> tuple[Conversation, bool]:
        """Open the thread with someone, creating it the first time.

        Returns the thread and whether it was created, so the view can answer
        201 or 200 without the caller having to care which happened.
        """
        other = self._require_user(username)
        if other.id == user.id:
            raise InvalidInput("You cannot start a conversation with yourself.")

        key = Conversation.key_for(user.id, other.id)
        existing = self._conversations.by_direct_key(key)
        if existing is not None:
            return existing, False

        try:
            with transaction.atomic():
                conversation = self._conversations.create_direct(key=key, users=[user, other])
        except IntegrityError:
            # Two "Message" clicks landing at once: the unique key let one
            # through, and the loser reuses the winner's thread.
            conversation = self._conversations.by_direct_key(key)
            if conversation is None:
                raise
            return conversation, False
        return conversation, True

    def inbox(self, *, user: User) -> QuerySet:
        return self._conversations.for_user(user.id)

    def get_for(self, *, user: User, conversation_id) -> Conversation:
        self._require_participant(conversation_id=conversation_id, user_id=user.id)
        return self._conversations.require_by_id(conversation_id)

    def history(self, *, user: User, conversation_id) -> QuerySet:
        self._require_participant(conversation_id=conversation_id, user_id=user.id)
        return self._messages.in_conversation(conversation_id)

    def send(
        self,
        *,
        sender: User,
        conversation_id,
        body: str = "",
        files: list[UploadedFile] | None = None,
        reply_to_id=None,
    ) -> Message:
        participant = self._require_participant(
            conversation_id=conversation_id,
            user_id=sender.id,
        )
        files = files or []
        body = (body or "").strip()
        if not body and not files:
            raise InvalidInput("A message needs text or an attachment.")
        if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise InvalidInput(
                f"A message may carry at most {MAX_ATTACHMENTS_PER_MESSAGE} attachments.",
                details={"received": len(files)},
            )

        reply_to = None
        if reply_to_id is not None:
            reply_to = self._messages.get_in_conversation(
                conversation_id=conversation_id,
                message_id=reply_to_id,
            )
            if reply_to is None:
                # Scoped to this thread deliberately: quoting a message from
                # another conversation would republish its contents here.
                raise InvalidInput("You can only reply to a message in this conversation.")

        # Uploading has to happen before the transaction, because the rows
        # record the URLs the provider hands back.
        assets = self._uploads.upload_many(files) if files else []
        try:
            with transaction.atomic():
                message = self._messages.create_with_media(
                    conversation_id=conversation_id,
                    sender=sender,
                    body=body,
                    reply_to=reply_to,
                    media=assets,
                )
                self._conversations.touch(conversation_id=conversation_id, message=message)
                self._participants.bump_unread(
                    conversation_id=conversation_id,
                    except_user_id=sender.id,
                )
                # Replying means you read what you replied to.
                self._participants.mark_read(participant)
                return message
        except Exception:
            # The files already reached the storage provider, which no database
            # rollback can undo, so they are removed explicitly.
            self._uploads.discard_many(assets)
            raise

    def mark_read(self, *, user: User, conversation_id) -> Participant:
        participant = self._require_participant(
            conversation_id=conversation_id,
            user_id=user.id,
        )
        return self._participants.mark_read(participant)

    def unread_total(self, *, user: User) -> int:
        return self._participants.unread_total(user.id)

    def participant_ids(self, conversation_id) -> list[int]:
        """Who should hear about activity in a thread."""
        return self._participants.user_ids_in(conversation_id)

    def _require_participant(self, *, conversation_id, user_id) -> Participant:
        participant = self._participants.get_for(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if participant is None:
            # Someone else's conversation is indistinguishable from one that
            # does not exist, so this cannot be used to probe for threads.
            raise ResourceNotFound("Conversation not found.")
        return participant

    def _require_user(self, username: str) -> User:
        user = self._users.get_by_username(username)
        if user is None:
            raise ResourceNotFound("No user with that username.")
        return user
