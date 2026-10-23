from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Post(TimeStampedModel):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="posts",
        on_delete=models.CASCADE,
    )
    caption = models.TextField(max_length=2200, blank=True)

    # A share is a post that points at the post it reshared, which keeps the
    # feed a single homogeneous table instead of merging two streams.
    shared_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="shares",
        on_delete=models.SET_NULL,
    )

    # Denormalized so rendering a feed page never counts rows. Maintained by
    # the signal receivers in signals.py, apps/interactions/signals.py and
    # apps/comments/signals.py, inside the same transaction as the write that
    # caused the change.
    like_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)
    # Replies included: this is the size of the whole conversation, which is
    # what the number beside the comment button is read as.
    comment_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "posts"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("-created_at",), name="post_recent_idx"),
            models.Index(fields=("author", "-created_at"), name="post_author_recent_idx"),
            # Serves the share_count reconciliation query.
            models.Index(fields=("shared_from",), name="post_shared_from_idx"),
        ]

    def __str__(self) -> str:
        label = self.caption[:40] or "(media only)"
        return f"{self.author_id}: {label}"

    @property
    def is_share(self) -> bool:
        return self.shared_from_id is not None
