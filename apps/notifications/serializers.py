from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.comments.models import Comment
from apps.notifications.models import Notification
from apps.posts.models import Post


class NotificationPostSerializer(serializers.ModelSerializer):
    """Just enough of a post to preview it in a row and open it on click."""

    id = serializers.CharField(read_only=True)

    class Meta:
        model = Post
        fields = ("id", "caption")
        read_only_fields = fields


class NotificationCommentSerializer(serializers.ModelSerializer):
    """The comment a row is about, so it can be quoted rather than referred to."""

    id = serializers.CharField(read_only=True)

    class Meta:
        model = Comment
        fields = ("id", "body")
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    actor = UserSerializer(read_only=True)
    post = NotificationPostSerializer(read_only=True)
    comment = NotificationCommentSerializer(read_only=True)
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = ("id", "kind", "actor", "post", "comment", "is_read", "created_at")
        read_only_fields = fields


class UnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField(read_only=True)
