from django.apps import AppConfig


class PostsConfig(AppConfig):
    name = "apps.posts"
    label = "posts"

    def ready(self) -> None:
        from apps.posts import signals  # noqa: F401
