from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Comment(TimeStampedModel):
    """Something somebody said about a post, or in answer to another comment.

    Threads are two levels deep on purpose. `parent` is null for a comment on
    the post itself and set for a reply, and `CommentService.reply` attaches a
    reply to a reply's parent rather than nesting further — the same flattening
    `ShareService.share` applies to reshares. Rendering therefore never recurses
    and a thread costs two queries however long the conversation runs.

    `post` is stored on replies too, denormalized from the parent, so every
    comment on a post can be counted or deleted without walking the chain.
    """

    post = models.ForeignKey(
        "posts.Post",
        related_name="comments",
        on_delete=models.CASCADE,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="comments",
        on_delete=models.CASCADE,
    )
    body = models.TextField(max_length=1000)

    # Deleting a comment takes its replies with it, which is why this cascades:
    # an orphaned answer to a withdrawn remark reads as nonsense.
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="replies",
        on_delete=models.CASCADE,
    )

    # Denormalized so rendering a thread never counts rows. Maintained by the
    # receivers in signals.py inside the same transaction as the write that
    # caused the change.
    like_count = models.PositiveIntegerField(default=0)
    reply_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "comments"
        ordering = ("-created_at", "-id")
        indexes = [
            # The thread under a post: top-level rows only, newest first. The
            # condition keeps the replies out of the index that serves it.
            models.Index(
                fields=("post", "-created_at"),
                condition=models.Q(parent__isnull=True),
                name="comment_toplevel_idx",
            ),
            models.Index(fields=("parent", "-created_at"), name="comment_replies_idx"),
            # Serves the comment_count reconciliation query.
            models.Index(fields=("post",), name="comment_post_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.author_id} on {self.post_id}: {self.body[:40]}"

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None


class CommentLike(TimeStampedModel):
    """One row per (user, comment), the same shape as a like on a post.

    The unique constraint is the real guarantee that liking is idempotent: a
    double-tap or a retried request hits a duplicate key error instead of
    inflating the counter.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="comment_likes",
        on_delete=models.CASCADE,
    )
    comment = models.ForeignKey(
        Comment,
        related_name="likes",
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = "comment_likes"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "comment"),
                name="unique_like_per_user_comment",
            ),
        ]
        indexes = [
            # Serves "which of these comments have I liked?" for a whole page.
            models.Index(fields=("user", "comment"), name="comment_like_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} likes comment {self.comment_id}"
