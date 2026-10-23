"""Test doubles for the storage seam.

`InMemoryStorage` is the payoff of depending on the `MediaStorage` abstraction:
the whole post pipeline can be exercised without Cloudinary credentials, network
access, or temporary directories.
"""

from django.core.files.uploadedfile import UploadedFile

from apps.media.kinds import MediaKind
from apps.media.storage.base import MediaStorage, StoredMedia


class InMemoryStorage(MediaStorage):
    provider_name = "memory"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def upload(self, file: UploadedFile, *, kind: str, folder: str) -> StoredMedia:
        public_id = f"{folder}/{kind}/{len(self.files)}-{file.name}"
        file.seek(0)
        self.files[public_id] = file.read()
        return StoredMedia(
            provider=self.provider_name,
            public_id=public_id,
            url=f"memory://{public_id}",
            kind=kind,
            thumbnail_url=f"memory://{public_id}" if kind == MediaKind.IMAGE else "",
            mime_type=getattr(file, "content_type", "") or "",
            byte_size=file.size or 0,
            original_filename=file.name or "",
        )

    def delete(self, *, public_id: str, kind: str) -> None:
        self.files.pop(public_id, None)
        self.deleted.append(public_id)


class ExplodingStorage(MediaStorage):
    """Fails on the Nth upload, to exercise partial-failure cleanup."""

    provider_name = "memory"

    def __init__(self, fail_on_call: int = 1) -> None:
        self.inner = InMemoryStorage()
        self.fail_on_call = fail_on_call
        self.calls = 0

    def upload(self, file: UploadedFile, *, kind: str, folder: str) -> StoredMedia:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("storage provider is down")
        return self.inner.upload(file, kind=kind, folder=folder)

    def delete(self, *, public_id: str, kind: str) -> None:
        self.inner.delete(public_id=public_id, kind=kind)

    @property
    def deleted(self) -> list[str]:
        return self.inner.deleted
