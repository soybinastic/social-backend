from django.apps import AppConfig


class CommentsConfig(AppConfig):
    name = "apps.comments"
    label = "comments"

    def ready(self) -> None:
        from apps.comments import signals  # noqa: F401
