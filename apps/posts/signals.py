"""Keeps `Post.share_count` in step with the reshares that reference a post.

Using receivers rather than bookkeeping inside `ShareService` means the counter
stays correct no matter who creates a reshare -- a service, the admin, a shell
session, or a data migration.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.posts.models import Post
from apps.posts.repositories import PostRepository


@receiver(post_save, sender=Post, dispatch_uid="posts.bump_share_count")
def bump_share_count(sender, instance: Post, created: bool, **kwargs) -> None:
    if created and instance.shared_from_id:
        PostRepository().increment_counter(instance.shared_from_id, "share_count")


@receiver(post_delete, sender=Post, dispatch_uid="posts.drop_share_count")
def drop_share_count(sender, instance: Post, **kwargs) -> None:
    if instance.shared_from_id:
        PostRepository().decrement_counter(instance.shared_from_id, "share_count")
