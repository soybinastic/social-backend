from django.db.models import QuerySet
from django.utils import timezone

from apps.core.repositories import BaseRepository
from apps.notifications.models import Notification


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    def get_queryset(self) -> QuerySet:
        # Every row renders the actor with their avatar and previews whatever it
        # points at, so all of it is resolved up front rather than per row.
        return (
            super()
            .get_queryset()
            .select_related("actor", "actor__avatar", "post", "comment")
        )

    def for_recipient(self, recipient_id) -> QuerySet:
        return self.get_queryset().filter(recipient_id=recipient_id)

    def owned_by(self, *, recipient_id, notification_id) -> Notification | None:
        """Scoped to the recipient, so one account can never read another's."""
        return (
            self.get_queryset()
            .filter(pk=notification_id, recipient_id=recipient_id)
            .first()
        )

    def unread_count(self, recipient_id) -> int:
        return self.get_queryset().filter(recipient_id=recipient_id, read_at__isnull=True).count()

    def mark_all_read(self, recipient_id) -> int:
        return (
            self.get_queryset()
            .filter(recipient_id=recipient_id, read_at__isnull=True)
            .update(read_at=timezone.now())
        )

    def delete_where(self, **filters) -> None:
        self.get_queryset().filter(**filters).delete()
