"""Media kind definitions and the registry that validates uploads against them.

Supporting a new kind of attachment (documents, GIF-only, 3D models…) means
registering another spec here. No existing branch has to be edited, and neither
the storage backends nor the post services need to change.
"""

from dataclasses import dataclass
from pathlib import Path

from django.db import models

from apps.core.exceptions import InvalidInput

MB = 1024 * 1024


class MediaKind(models.TextChoices):
    IMAGE = "image", "Image"
    VIDEO = "video", "Video"
    AUDIO = "audio", "Audio"


@dataclass(frozen=True)
class MediaKindSpec:
    """The rules that decide whether a file is an acceptable instance of a kind."""

    kind: str
    mime_prefixes: tuple[str, ...]
    extensions: frozenset[str]
    max_bytes: int

    def accepts(self, *, content_type: str, extension: str) -> bool:
        if content_type and content_type.lower().startswith(self.mime_prefixes):
            return True
        return extension in self.extensions


class MediaKindRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, MediaKindSpec] = {}

    def register(self, spec: MediaKindSpec) -> None:
        self._specs[spec.kind] = spec

    def get(self, kind: str) -> MediaKindSpec:
        try:
            return self._specs[kind]
        except KeyError:
            raise InvalidInput(f"Unsupported media kind '{kind}'.") from None

    def subset(self, *kinds: str) -> "MediaKindRegistry":
        """A narrower registry for callers that accept fewer kinds.

        Chat attachments are photos and voice notes but not video. Expressing
        that as a registry keeps the rule where every other media rule lives,
        and the rejection message below adapts to it on its own.
        """
        narrowed = MediaKindRegistry()
        for kind in kinds:
            narrowed.register(self.get(kind))
        return narrowed

    def detect(self, *, filename: str, content_type: str) -> MediaKindSpec:
        """Resolve the spec for an upload, preferring MIME type over extension."""
        extension = Path(filename or "").suffix.lower().lstrip(".")
        for spec in self._specs.values():
            if spec.accepts(content_type=content_type or "", extension=extension):
                return spec
        raise InvalidInput(
            f"Unsupported file type. Upload {self._accepted_phrase()} file.",
            details={"filename": filename, "content_type": content_type},
        )

    def _accepted_phrase(self) -> str:
        """"an image, video, or audio" for the message above."""
        kinds = list(self._specs)
        if len(kinds) == 1:
            listed = kinds[0]
        elif len(kinds) == 2:
            listed = f"{kinds[0]} or {kinds[1]}"
        else:
            listed = f"{', '.join(kinds[:-1])}, or {kinds[-1]}"
        return f"an {listed}" if listed[0] in "aeiou" else f"a {listed}"

    def validate_size(self, spec: MediaKindSpec, byte_size: int) -> None:
        if byte_size <= 0:
            raise InvalidInput("The uploaded file is empty.")
        if byte_size > spec.max_bytes:
            limit_mb = spec.max_bytes // MB
            raise InvalidInput(
                f"{spec.kind.capitalize()} files must be {limit_mb}MB or smaller.",
                details={"max_bytes": spec.max_bytes, "byte_size": byte_size},
            )


registry = MediaKindRegistry()

registry.register(
    MediaKindSpec(
        kind=MediaKind.IMAGE,
        mime_prefixes=("image/",),
        extensions=frozenset({"jpg", "jpeg", "png", "gif", "webp", "avif", "heic"}),
        max_bytes=10 * MB,
    )
)
registry.register(
    MediaKindSpec(
        kind=MediaKind.VIDEO,
        mime_prefixes=("video/",),
        extensions=frozenset({"mp4", "mov", "webm", "m4v", "avi", "mkv"}),
        max_bytes=200 * MB,
    )
)
registry.register(
    MediaKindSpec(
        kind=MediaKind.AUDIO,
        mime_prefixes=("audio/",),
        extensions=frozenset({"mp3", "wav", "ogg", "m4a", "aac", "flac"}),
        max_bytes=50 * MB,
    )
)
