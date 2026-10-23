from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class Conversation(TimeStampedModel):
    """A thread between two people.

    `direct_key` is the two participant ids in a fixed order ("3:11"). Opening a
    chat with someone must not create a second thread when one already exists,
    and a unique index on that key is what enforces it: two simultaneous
    requests cannot both win, whereas a look-before-insert check could.

    `last_message` and `last_message_at` are denormalized. The inbox lists
    threads newest-activity-first with a preview of the latest message, and
    without these that is a query per row ordered by something the database
    cannot index.
    """

    direct_key = models.CharField(max_length=64, unique=True)

    last_message = models.ForeignKey(
        "chat.Message",
        null=True,
        blank=True,
        # Nothing reads a message through this, and a reverse accessor here
        # would collide with the one `Message.conversation` already provides.
        related_name="+",
        on_delete=models.SET_NULL,
    )
    # Seeded with the creation time so a thread nobody has written in yet still
    # sorts and pages correctly; cursor pagination cannot compare nulls.
    last_message_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "conversations"
        ordering = ("-last_message_at", "-id")
        indexes = [
            models.Index(fields=("-last_message_at",), name="conversation_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"conversation {self.pk} ({self.direct_key})"

    @staticmethod
    def key_for(*user_ids) -> str:
        """Order-independent identity for a pair, so A→B and B→A agree."""
        return ":".join(str(pk) for pk in sorted(int(pk) for pk in user_ids))


class Participant(TimeStampedModel):
    """One person's side of a conversation.

    `unread_count` is denormalized the way post counters are: bumped for
    everyone but the sender when a message lands, zeroed when they read the
    thread. Deriving it instead — counting messages newer than `last_read_at` —
    is a correlated subquery per row on every inbox load and every badge poll.
    """

    conversation = models.ForeignKey(
        Conversation,
        related_name="participants",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="conversations",
        on_delete=models.CASCADE,
    )
    unread_count = models.PositiveIntegerField(default=0)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "conversation_participants"
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "user"),
                name="participant_unique_per_conversation",
            ),
        ]
        indexes = [
            # The unique constraint indexes (conversation, user); this serves
            # the other direction, "every thread this person is in".
            models.Index(fields=("user",), name="participant_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in conversation {self.conversation_id}"


class Message(TimeStampedModel):
    """One message in a thread.

    `body` may be empty when the message is nothing but attachments, which are
    `MediaAsset` rows pointing back here. The service refuses a message that has
    neither.
    """

    conversation = models.ForeignKey(
        Conversation,
        related_name="messages",
        on_delete=models.CASCADE,
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="sent_messages",
        on_delete=models.CASCADE,
    )
    body = models.TextField(blank=True)

    # SET_NULL, not CASCADE: losing the quoted message must not take the
    # replies to it with it. Serializers stop at one level, so a long reply
    # chain never nests without bound.
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="replies",
        on_delete=models.SET_NULL,
    )

    class Meta:
        db_table = "messages"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("conversation", "-created_at"), name="message_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"message {self.pk} from {self.sender_id}"
