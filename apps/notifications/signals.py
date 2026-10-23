"""Turns likes, follows, reshares and comments into notifications.

Receivers live here rather than in the services that cause the events, so the
interactions and posts apps stay unaware that notifications exist. Like the
counter receivers, these run inside the transaction of the write that triggered
them: an interaction and its notification commit together or not at all.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.comments.models import Comment, CommentLike
from apps.interactions.models import Follow, Like
from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from apps.posts.models import Post


@receiver(post_save, sender=Like, dispatch_uid="notifications.notify_like")
def notify_like(sender, instance: Like, created: bool, **kwargs) -> None:
    if created:
        NotificationService().record(
            recipient_id=instance.post.author_id,
            actor_id=instance.user_id,
            kind=Notification.Kind.LIKE,
            post_id=instance.post_id,
        )


@receiver(post_delete, sender=Like, dispatch_uid="notifications.withdraw_like")
def withdraw_like(sender, instance: Like, **kwargs) -> None:
    # Unliking takes the notification with it. When the post itself was deleted
    # the notification is already gone by cascade and this matches no rows.
    NotificationService().withdraw(
        kind=Notification.Kind.LIKE,
        actor_id=instance.user_id,
        post_id=instance.post_id,
    )


@receiver(post_save, sender=Follow, dispatch_uid="notifications.notify_follow")
def notify_follow(sender, instance: Follow, created: bool, **kwargs) -> None:
    if created:
        NotificationService().record(
            recipient_id=instance.followee_id,
            actor_id=instance.follower_id,
            kind=Notification.Kind.FOLLOW,
        )


@receiver(post_delete, sender=Follow, dispatch_uid="notifications.withdraw_follow")
def withdraw_follow(sender, instance: Follow, **kwargs) -> None:
    NotificationService().withdraw(
        kind=Notification.Kind.FOLLOW,
        actor_id=instance.follower_id,
        recipient_id=instance.followee_id,
    )


@receiver(post_save, sender=Comment, dispatch_uid="notifications.notify_comment")
def notify_comment(sender, instance: Comment, created: bool, **kwargs) -> None:
    """Tell whoever is owed an answer, and only once.

    A reply concerns two people: the comment it answers and the post it is on.
    Both are told, except that the post's author hears about it as a reply when
    they wrote the parent, rather than twice. `record` drops anything addressed
    to its own actor, so commenting under yourself is silent either way.
    """
    if not created:
        return

    service = NotificationService()
    if instance.parent_id is None:
        service.record(
            recipient_id=instance.post.author_id,
            actor_id=instance.author_id,
            kind=Notification.Kind.COMMENT,
            post_id=instance.post_id,
            comment_id=instance.id,
        )
        return

    parent_author_id = instance.parent.author_id
    service.record(
        recipient_id=parent_author_id,
        actor_id=instance.author_id,
        kind=Notification.Kind.REPLY,
        post_id=instance.post_id,
        comment_id=instance.id,
    )
    if instance.post.author_id != parent_author_id:
        service.record(
            recipient_id=instance.post.author_id,
            actor_id=instance.author_id,
            kind=Notification.Kind.COMMENT,
            post_id=instance.post_id,
            comment_id=instance.id,
        )


@receiver(post_save, sender=CommentLike, dispatch_uid="notifications.notify_comment_like")
def notify_comment_like(sender, instance: CommentLike, created: bool, **kwargs) -> None:
    if created:
        NotificationService().record(
            recipient_id=instance.comment.author_id,
            actor_id=instance.user_id,
            kind=Notification.Kind.COMMENT_LIKE,
            # The post is what opens on click; the comment is what the row quotes.
            post_id=instance.comment.post_id,
            comment_id=instance.comment_id,
        )


@receiver(post_delete, sender=CommentLike, dispatch_uid="notifications.withdraw_comment_like")
def withdraw_comment_like(sender, instance: CommentLike, **kwargs) -> None:
    # Unliking takes the notification with it. When the comment itself was
    # deleted the notification is already gone by cascade and this matches no rows.
    NotificationService().withdraw(
        kind=Notification.Kind.COMMENT_LIKE,
        actor_id=instance.user_id,
        comment_id=instance.comment_id,
    )


@receiver(post_save, sender=Post, dispatch_uid="notifications.notify_share")
def notify_share(sender, instance: Post, created: bool, **kwargs) -> None:
    if created and instance.shared_from_id:
        NotificationService().record(
            recipient_id=instance.shared_from.author_id,
            actor_id=instance.author_id,
            kind=Notification.Kind.SHARE,
            # The reshare, not the original: opening it shows what the sharer
            # said with the original quoted inside. Deleting the reshare also
            # takes this notification with it, by cascade.
            post_id=instance.id,
        )
