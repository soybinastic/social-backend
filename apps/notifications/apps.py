from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    label = "notifications"

    def ready(self) -> None:
        from apps.notifications import signals  # noqa: F401
