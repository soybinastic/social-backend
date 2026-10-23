from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Like(TimeStampedModel):
    """One row per (user, post).

    The unique constraint is the real guarantee that a like is idempotent:
    a double-tap or a retried request hits a duplicate key error instead of
    inflating the counter.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="likes",
        on_delete=models.CASCADE,
    )
    post = models.ForeignKey(
        "posts.Post",
        related_name="likes",
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = "likes"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "post"), name="unique_like_per_user_post"),
        ]
        indexes = [
            # Serves "which of these posts have I liked?" for a whole feed page.
            models.Index(fields=("user", "post"), name="like_user_post_idx"),
            models.Index(fields=("post", "-created_at"), name="like_post_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} likes {self.post_id}"


class Follow(TimeStampedModel):
    """One directed edge of the follow graph, one row per (follower, followee).

    Two people following each other is two rows, which is what lets the graph
    answer "do they follow me back?" without a second concept.

    The unique constraint makes following idempotent the same way it does for
    likes, and the check constraint is the real guarantee that an account
    cannot follow itself: a crafted request fails in the database rather than
    relying on every caller to look first.
    """

    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="following",
        on_delete=models.CASCADE,
    )
    followee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="followers",
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = "follows"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("follower", "followee"),
                name="unique_follow_per_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("followee")),
                name="follow_is_not_self",
            ),
        ]
        indexes = [
            # Serves "which of these accounts do I follow?" for a whole page.
            models.Index(fields=("follower", "followee"), name="follow_pair_idx"),
            models.Index(fields=("followee", "-created_at"), name="follow_followers_idx"),
            models.Index(fields=("follower", "-created_at"), name="follow_following_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.follower_id} follows {self.followee_id}"
