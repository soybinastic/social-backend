"""Filesystem implementation of `MediaStorage`, used for local development.

Lets the whole app run end to end without Cloudinary credentials. It is the
proof that the storage seam is real: switching providers is an env var change.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import UploadedFile

from apps.core.exceptions import StorageFailure
from apps.media.kinds import MediaKind
from apps.media.storage.base import MediaStorage, StoredMedia


class LocalFileSystemStorage(MediaStorage):
    provider_name = "local"

    def __init__(self, location: str | None = None, base_url: str | None = None):
        # Passing location=None lets FileSystemStorage resolve MEDIA_ROOT lazily,
        # so tests can redirect writes with override_settings.
        self._storage = FileSystemStorage(location=location)
        self._base_url = (base_url or settings.SITE_BASE_URL).rstrip("/")

    def upload(self, file: UploadedFile, *, kind: str, folder: str) -> StoredMedia:
        extension = Path(file.name or "").suffix.lower()
        relative_path = f"{folder}/{kind}/{uuid.uuid4().hex}{extension}"

        try:
            stored_path = self._storage.save(relative_path, file)
        except OSError as exc:
            raise StorageFailure(f"Could not write the file to disk: {exc}") from exc

        width, height = self._image_dimensions(file) if kind == MediaKind.IMAGE else (None, None)
        url = f"{self._base_url}{settings.MEDIA_URL.rstrip('/')}/{stored_path}"

        return StoredMedia(
            provider=self.provider_name,
            public_id=stored_path,
            url=url,
            kind=kind,
            thumbnail_url=url if kind == MediaKind.IMAGE else "",
            mime_type=file.content_type or "",
            byte_size=file.size or 0,
            width=width,
            height=height,
            # Probing duration would need ffmpeg; the client reports it instead.
            duration_seconds=None,
            original_filename=file.name or "",
        )

    def delete(self, *, public_id: str, kind: str) -> None:
        if self._storage.exists(public_id):
            self._storage.delete(public_id)

    def _image_dimensions(self, file: UploadedFile) -> tuple[int | None, int | None]:
        from PIL import Image, UnidentifiedImageError

        try:
            file.seek(0)
            with Image.open(file) as image:
                return image.width, image.height
        except (UnidentifiedImageError, OSError, ValueError):
            return None, None
        finally:
            file.seek(0)
