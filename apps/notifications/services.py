"""Notification use cases."""

from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions import ResourceNotFound
from apps.notifications.models import Notification
from apps.notifications.repositories import NotificationRepository


class NotificationService:
    def __init__(self, notifications: NotificationRepository | None = None):
        self._notifications = notifications or NotificationRepository()

    def record(
        self,
        *,
        recipient_id,
        actor_id,
        kind: str,
        post_id=None,
        comment_id=None,
    ) -> Notification | None:
        """Write one notification, or nothing when there is no one to tell.

        Called from the receivers in signals.py, which run inside the same
        transaction as the interaction, so an interaction can never commit
        without its notification or the other way round.
        """
        if recipient_id == actor_id:
            return None
        return self._notifications.create(
            recipient_id=recipient_id,
            actor_id=actor_id,
            kind=kind,
            post_id=post_id,
            comment_id=comment_id,
        )

    def withdraw(self, **filters) -> None:
        """Drop notifications for an interaction that no longer exists."""
        self._notifications.delete_where(**filters)

    def inbox(self, *, recipient: User) -> QuerySet:
        return self._notifications.for_recipient(recipient.id)

    def unread_count(self, *, recipient: User) -> int:
        return self._notifications.unread_count(recipient.id)

    def mark_read(self, *, recipient: User, notification_id) -> Notification:
        notification = self._notifications.owned_by(
            recipient_id=recipient.id,
            notification_id=notification_id,
        )
        if notification is None:
            # Someone else's notification is indistinguishable from one that
            # does not exist, so reading it cannot be used to probe for others.
            raise ResourceNotFound("Notification not found.")

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "updated_at"])
        return notification

    def mark_all_read(self, *, recipient: User) -> int:
        return self._notifications.mark_all_read(recipient.id)
