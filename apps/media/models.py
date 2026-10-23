from django.db import models

from apps.core.models import TimeStampedModel
from apps.media.kinds import MediaKind


class MediaAsset(TimeStampedModel):
    """A file held by the configured storage provider.

    One table serves post attachments, chat attachments and profile avatars so
    that a single upload service can produce every kind of asset. Each owner is
    therefore a nullable foreign key: exactly one of them is set per row, and an
    avatar has neither because it is reached through `User.avatar` instead.

    The `provider`/`public_id` pair is what lets the remote file be deleted
    later without knowing which backend produced it.
    """

    post = models.ForeignKey(
        "posts.Post",
        related_name="media",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    message = models.ForeignKey(
        "chat.Message",
        related_name="media",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    # Preserves the order the author chose, which insertion order alone
    # would not guarantee.
    position = models.PositiveSmallIntegerField(default=0)

    kind = models.CharField(max_length=16, choices=MediaKind)
    provider = models.CharField(max_length=32)
    public_id = models.CharField(max_length=255)
    url = models.URLField(max_length=1000)
    thumbnail_url = models.URLField(max_length=1000, blank=True)
    mime_type = models.CharField(max_length=127, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "media_assets"
        ordering = ("position", "id")
        indexes = [
            models.Index(fields=("post", "position"), name="media_post_position_idx"),
            models.Index(fields=("message", "position"), name="media_message_position_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.public_id}"
