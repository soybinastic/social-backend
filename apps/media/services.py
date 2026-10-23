"""Upload orchestration: validate, store, and describe media files."""

import logging

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from apps.core.exceptions import InvalidInput
from apps.media.kinds import MediaKindRegistry
from apps.media.kinds import registry as default_registry
from apps.media.models import MediaAsset
from apps.media.storage.base import MediaStorage, StoredMedia
from apps.media.storage.factory import get_media_storage

logger = logging.getLogger(__name__)

MAX_ATTACHMENTS_PER_POST = 10


class MediaUploadService:
    """Turns raw uploads into `MediaAsset` instances.

    The instances are returned **unsaved**: this service owns the storage
    provider, while deciding when and how rows are written stays with the
    repositories, so a caller can persist them inside its own transaction.

    Collaborators are injected so tests can pass an in-memory storage double
    and never touch Cloudinary or the filesystem.
    """

    def __init__(
        self,
        storage: MediaStorage | None = None,
        registry: MediaKindRegistry | None = None,
        folder: str | None = None,
    ):
        self._storage = storage or get_media_storage()
        self._registry = registry or default_registry
        self._folder = folder or settings.MEDIA_UPLOAD_FOLDER

    def upload(self, file: UploadedFile) -> MediaAsset:
        spec = self._registry.detect(
            filename=file.name or "",
            content_type=getattr(file, "content_type", "") or "",
        )
        self._registry.validate_size(spec, file.size or 0)
        stored = self._storage.upload(file, kind=spec.kind, folder=self._folder)
        return self._to_asset(stored)

    def upload_many(self, files: list[UploadedFile]) -> list[MediaAsset]:
        """Upload all files atomically from the caller's point of view.

        No database transaction can roll back a third-party HTTP upload, so a
        partial failure is compensated by deleting what already succeeded.
        """
        if len(files) > MAX_ATTACHMENTS_PER_POST:
            raise InvalidInput(
                f"A post may contain at most {MAX_ATTACHMENTS_PER_POST} attachments.",
                details={"received": len(files)},
            )

        uploaded: list[MediaAsset] = []
        try:
            for file in files:
                uploaded.append(self.upload(file))
        except Exception:
            for asset in uploaded:
                self.discard(asset)
            raise
        return uploaded

    def discard(self, asset: MediaAsset) -> None:
        """Best-effort delete of the stored file; the row is the caller's concern.

        Never raises, so cleanup cannot mask the error that triggered it.
        """
        if asset.provider != self._storage.provider_name:
            logger.warning(
                "Skipping delete of %s: it was stored by %r but %r is configured.",
                asset.public_id,
                asset.provider,
                self._storage.provider_name,
            )
            return
        try:
            self._storage.delete(public_id=asset.public_id, kind=asset.kind)
        except Exception:
            logger.exception("Failed to delete media asset %s", asset.public_id)

    def discard_many(self, assets: list[MediaAsset]) -> None:
        for asset in assets:
            self.discard(asset)

    @staticmethod
    def _to_asset(stored: StoredMedia) -> MediaAsset:
        """Build an unsaved row from the provider's response."""
        return MediaAsset(
            kind=stored.kind,
            provider=stored.provider,
            public_id=stored.public_id,
            url=stored.url,
            thumbnail_url=stored.thumbnail_url,
            mime_type=stored.mime_type,
            byte_size=stored.byte_size,
            width=stored.width,
            height=stored.height,
            duration_seconds=stored.duration_seconds,
            original_filename=stored.original_filename,
        )
