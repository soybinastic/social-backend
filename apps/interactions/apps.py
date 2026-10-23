from django.apps import AppConfig


class InteractionsConfig(AppConfig):
    name = "apps.interactions"
    label = "interactions"

    def ready(self) -> None:
        from apps.interactions import signals  # noqa: F401
