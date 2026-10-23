"""The storage seam.

`MediaStorage` is the abstraction the domain depends on; Cloudinary, the local
filesystem, or an S3 backend are interchangeable implementations of it. Nothing
above this module imports a provider SDK.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.core.files.uploadedfile import UploadedFile


@dataclass(frozen=True)
class StoredMedia:
    """Provider-neutral description of a file that has been persisted."""

    provider: str
    public_id: str
    url: str
    kind: str
    thumbnail_url: str = ""
    mime_type: str = ""
    byte_size: int = 0
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    original_filename: str = ""
    metadata: dict = field(default_factory=dict)


class MediaStorage(ABC):
    """Contract every storage provider must satisfy."""

    provider_name: str

    @abstractmethod
    def upload(self, file: UploadedFile, *, kind: str, folder: str) -> StoredMedia:
        """Persist `file` and return a description of where it landed."""

    @abstractmethod
    def delete(self, *, public_id: str, kind: str) -> None:
        """Remove a previously uploaded file. Must be safe to call twice."""
