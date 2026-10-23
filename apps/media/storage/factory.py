"""Resolves the configured `MediaStorage` implementation.

This is the single place that turns configuration into a concrete provider, so
call sites can depend on the abstraction and stay ignorant of the choice.
"""

from functools import cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.media.storage.base import MediaStorage


@cache
def get_media_storage() -> MediaStorage:
    """Instantiate `settings.MEDIA_STORAGE_BACKEND` once per process."""
    path = settings.MEDIA_STORAGE_BACKEND
    try:
        backend_class = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"MEDIA_STORAGE_BACKEND '{path}' could not be imported."
        ) from exc

    if not issubclass(backend_class, MediaStorage):
        raise ImproperlyConfigured(
            f"MEDIA_STORAGE_BACKEND '{path}' must subclass "
            f"{MediaStorage.__module__}.{MediaStorage.__qualname__}."
        )
    return backend_class()
