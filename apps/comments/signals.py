"""Keeps denormalized comment counters in step with the tables they summarize."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.comments.models import Comment, CommentLike
from apps.comments.repositories import CommentRepository
from apps.posts.repositories import PostRepository


@receiver(post_save, sender=Comment, dispatch_uid="comments.bump_comment_counts")
def bump_comment_counts(sender, instance: Comment, created: bool, **kwargs) -> None:
    if not created:
        return

    # A reply moves two counters: the post's conversation grew, and so did the
    # thread under the comment it answers.
    PostRepository().increment_counter(instance.post_id, "comment_count")
    if instance.parent_id:
        CommentRepository().increment_counter(instance.parent_id, "reply_count")


@receiver(post_delete, sender=Comment, dispatch_uid="comments.drop_comment_counts")
def drop_comment_counts(sender, instance: Comment, **kwargs) -> None:
    # A deleted post cascades its comments, and a deleted comment cascades its
    # replies, so either update may match no rows. That is harmless and keeps
    # the receiver branch-free.
    PostRepository().decrement_counter(instance.post_id, "comment_count")
    if instance.parent_id:
        CommentRepository().decrement_counter(instance.parent_id, "reply_count")


@receiver(post_save, sender=CommentLike, dispatch_uid="comments.bump_comment_like_count")
def bump_comment_like_count(sender, instance: CommentLike, created: bool, **kwargs) -> None:
    if created:
        CommentRepository().increment_counter(instance.comment_id, "like_count")


@receiver(post_delete, sender=CommentLike, dispatch_uid="comments.drop_comment_like_count")
def drop_comment_like_count(sender, instance: CommentLike, **kwargs) -> None:
    CommentRepository().decrement_counter(instance.comment_id, "like_count")
