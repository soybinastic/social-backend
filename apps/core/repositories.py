"""Generic persistence helpers.

Repositories are the only layer allowed to build querysets. Services depend on
them rather than on managers directly, so swapping the storage engine or adding
caching stays contained to this layer.
"""

from typing import Any, Generic, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F

from apps.core.exceptions import ResourceNotFound

TModel = TypeVar("TModel", bound=models.Model)


class BaseRepository(Generic[TModel]):
    model: type[TModel]

    def get_queryset(self) -> models.QuerySet:
        return self.model._default_manager.all()

    def get_by_id(self, pk: Any) -> TModel | None:
        try:
            return self.get_queryset().filter(pk=pk).first()
        except (ValidationError, ValueError, TypeError):
            # Filtering an integer primary key on a non-numeric value raises
            # ValueError. A junk value in a URL is a missing resource, so it
            # becomes a 404 rather than an unhandled 500.
            return None

    def require_by_id(self, pk: Any) -> TModel:
        instance = self.get_by_id(pk)
        if instance is None:
            raise ResourceNotFound(f"{self.model._meta.verbose_name.capitalize()} not found.")
        return instance

    def create(self, **fields: Any) -> TModel:
        return self.model._default_manager.create(**fields)

    def exists(self, **filters: Any) -> bool:
        return self.get_queryset().filter(**filters).exists()

    def delete(self, instance: TModel) -> None:
        instance.delete()

    def counters(self, pk: Any, *fields: str) -> dict:
        """Re-read denormalized counts, which an `F()` update does not refresh
        on the in-memory instance."""
        row = self.model._default_manager.filter(pk=pk).values(*fields).first()
        return row or dict.fromkeys(fields, 0)

    def increment_counter(self, pk: Any, field: str, by: int = 1) -> None:
        """Apply a counter delta as arithmetic in the database.

        Read-modify-write in Python would lose updates when two requests touch
        the same row at once; `F()` makes it a single atomic UPDATE.
        """
        self.model._default_manager.filter(pk=pk).update(**{field: F(field) + by})

    def decrement_counter(self, pk: Any, field: str, by: int = 1) -> None:
        """Mirror of `increment_counter` that refuses to go below zero.

        The `__gte` filter is the clamp: these are PositiveIntegerFields, and
        Postgres would reject a negative value outright.
        """
        self.model._default_manager.filter(pk=pk, **{f"{field}__gte": by}).update(
            **{field: F(field) - by}
        )
