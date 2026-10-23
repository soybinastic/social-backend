from rest_framework import serializers


class MediaAssetSerializer(serializers.Serializer):
    """Read-only projection of an embedded `MediaAsset`.

    `provider` and `public_id` stay server-side; clients only need playback data.
    """

    kind = serializers.CharField(read_only=True)
    url = serializers.CharField(read_only=True)
    thumbnail_url = serializers.CharField(read_only=True)
    mime_type = serializers.CharField(read_only=True)
    byte_size = serializers.IntegerField(read_only=True)
    width = serializers.IntegerField(read_only=True, allow_null=True)
    height = serializers.IntegerField(read_only=True, allow_null=True)
    duration_seconds = serializers.FloatField(read_only=True, allow_null=True)
    original_filename = serializers.CharField(read_only=True)
