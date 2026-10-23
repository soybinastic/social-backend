"""Keeps denormalized counters in step with the tables they summarize."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.accounts.repositories import UserRepository
from apps.interactions.models import Follow, Like
from apps.posts.repositories import PostRepository


@receiver(post_save, sender=Like, dispatch_uid="interactions.bump_like_count")
def bump_like_count(sender, instance: Like, created: bool, **kwargs) -> None:
    if created:
        PostRepository().increment_counter(instance.post_id, "like_count")


@receiver(post_delete, sender=Like, dispatch_uid="interactions.drop_like_count")
def drop_like_count(sender, instance: Like, **kwargs) -> None:
    # When a post is deleted its likes cascade, and this update simply matches
    # no rows. That is harmless and keeps the receiver branch-free.
    PostRepository().decrement_counter(instance.post_id, "like_count")


@receiver(post_save, sender=Follow, dispatch_uid="interactions.bump_follow_counts")
def bump_follow_counts(sender, instance: Follow, created: bool, **kwargs) -> None:
    if created:
        # One edge moves two counters: the followee gained a follower and the
        # follower is now following one more account.
        users = UserRepository()
        users.increment_counter(instance.followee_id, "follower_count")
        users.increment_counter(instance.follower_id, "following_count")


@receiver(post_delete, sender=Follow, dispatch_uid="interactions.drop_follow_counts")
def drop_follow_counts(sender, instance: Follow, **kwargs) -> None:
    # A deleted account cascades its edges, so one of these updates may match
    # no rows. That is harmless and keeps the receiver branch-free.
    users = UserRepository()
    users.decrement_counter(instance.followee_id, "follower_count")
    users.decrement_counter(instance.follower_id, "following_count")
