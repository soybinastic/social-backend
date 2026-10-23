"""Cloudinary implementation of the `MediaStorage` contract."""

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import UploadedFile

from apps.core.exceptions import StorageFailure
from apps.media.kinds import MediaKind
from apps.media.storage.base import MediaStorage, StoredMedia


class CloudinaryStorage(MediaStorage):
    provider_name = "cloudinary"

    # Cloudinary has no dedicated audio resource type; audio is handled by the
    # video pipeline. Containing that quirk here keeps it out of the domain.
    _RESOURCE_TYPES = {
        MediaKind.IMAGE: "image",
        MediaKind.VIDEO: "video",
        MediaKind.AUDIO: "video",
    }

    def __init__(self, config: dict | None = None):
        config = config if config is not None else settings.CLOUDINARY
        missing = [key for key in ("cloud_name", "api_key", "api_secret") if not config.get(key)]
        if missing:
            raise ImproperlyConfigured(
                "CloudinaryStorage is selected but these settings are empty: "
                f"{', '.join(missing)}. Set the matching CLOUDINARY_* env vars."
            )
        cloudinary.config(secure=True, **config)

    def upload(self, file: UploadedFile, *, kind: str, folder: str) -> StoredMedia:
        resource_type = self._RESOURCE_TYPES[kind]
        try:
            result = cloudinary.uploader.upload(
                file,
                folder=f"{folder}/{kind}",
                resource_type=resource_type,
                # Let Cloudinary sniff the real format rather than trusting the
                # client-supplied content type.
                unique_filename=True,
                overwrite=False,
            )
        except CloudinaryError as exc:
            raise StorageFailure(f"Cloudinary rejected the upload: {exc}") from exc

        return StoredMedia(
            provider=self.provider_name,
            public_id=result["public_id"],
            url=result["secure_url"],
            kind=kind,
            thumbnail_url=self._thumbnail_url(kind, result),
            mime_type=file.content_type or "",
            byte_size=result.get("bytes", 0),
            width=result.get("width"),
            height=result.get("height"),
            duration_seconds=result.get("duration"),
            original_filename=file.name or "",
            metadata={"resource_type": result.get("resource_type", resource_type)},
        )

    def delete(self, *, public_id: str, kind: str) -> None:
        try:
            cloudinary.uploader.destroy(
                public_id,
                resource_type=self._RESOURCE_TYPES[kind],
                invalidate=True,
            )
        except CloudinaryError as exc:
            raise StorageFailure(f"Cloudinary could not delete the file: {exc}") from exc

    def _thumbnail_url(self, kind: str, result: dict) -> str:
        """Derive a still frame for video; images are their own thumbnail."""
        if kind == MediaKind.IMAGE:
            url, _ = cloudinary.utils.cloudinary_url(
                result["public_id"],
                format="jpg",
                secure=True,
                transformation=[{"width": 600, "crop": "limit", "quality": "auto"}],
            )
            return url
        if kind == MediaKind.VIDEO:
            url, _ = cloudinary.utils.cloudinary_url(
                result["public_id"],
                resource_type="video",
                format="jpg",
                secure=True,
                transformation=[{"width": 600, "crop": "limit"}],
            )
            return url
        return ""
