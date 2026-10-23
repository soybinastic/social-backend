from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    """One thing somebody else did that the recipient may want to know about.

    A notification is derived from an interaction rather than owned by it: the
    receivers in signals.py create one when a like, follow or share happens and
    remove it when that interaction is undone, so the list never claims someone
    likes a post they have since unliked.

    `post` is the thing to open when the notification is clicked, which is why a
    share points at the reshare rather than the original: opening it shows what
    the sharer said with the original quoted inside.

    `comment` is what the row is about when it concerns one, so it can be quoted
    in the list instead of leaving "liked your comment" to stand for any of them.
    """

    class Kind(models.TextChoices):
        FOLLOW = "follow", "Started following you"
        LIKE = "like", "Liked your post"
        SHARE = "share", "Shared your post"
        COMMENT = "comment", "Commented on your post"
        REPLY = "reply", "Replied to your comment"
        COMMENT_LIKE = "comment_like", "Liked your comment"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="notifications",
        on_delete=models.CASCADE,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="triggered_notifications",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(max_length=16, choices=Kind)
    post = models.ForeignKey(
        "posts.Post",
        null=True,
        blank=True,
        related_name="notifications",
        on_delete=models.CASCADE,
    )
    # Cascading is what withdraws these: deleting a comment takes the news of it
    # with it, the way unliking does through the receivers in signals.py.
    comment = models.ForeignKey(
        "comments.Comment",
        null=True,
        blank=True,
        related_name="notifications",
        on_delete=models.CASCADE,
    )

    # Null until read, rather than a boolean, because when it was read is worth
    # keeping and "unread" stays a single index lookup either way.
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ("-created_at", "-id")
        constraints = [
            # Your own likes and reshares are not news to you. The service skips
            # them; this is what guarantees it.
            models.CheckConstraint(
                condition=~models.Q(recipient=models.F("actor")),
                name="notification_actor_is_not_recipient",
            ),
        ]
        indexes = [
            models.Index(fields=("recipient", "-created_at"), name="notification_recent_idx"),
            # Serves the unread badge.
            models.Index(fields=("recipient", "read_at"), name="notification_unread_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.actor_id} -> {self.recipient_id}: {self.kind}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
