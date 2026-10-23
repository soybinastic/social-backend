from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.comments.models import Comment
from apps.comments.services import MAX_COMMENT_LENGTH


class CommentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    post = serializers.CharField(source="post_id", read_only=True)
    parent = serializers.CharField(source="parent_id", read_only=True)
    author = UserSerializer(read_only=True)
    liked = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = (
            "id",
            "post",
            "parent",
            "author",
            "body",
            "like_count",
            "reply_count",
            "liked",
            "can_delete",
            "created_at",
        )
        read_only_fields = fields

    def get_liked(self, comment: Comment) -> bool:
        # Populated once per page by the view; see CommentStateMixin.
        return comment.id in self.context.get("liked_comment_ids", set())

    def get_can_delete(self, comment: Comment) -> bool:
        """Whether this viewer may remove it: its writer, or the post's author.

        Sent rather than inferred client-side because the moderation half of the
        rule is not something a client can work out from the comment alone.
        """
        request = self.context.get("request")
        if not (request and request.user.is_authenticated):
            return False
        return request.user.id in (comment.author_id, comment.post.author_id)


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, max_length=MAX_COMMENT_LENGTH)


class CommentStateSerializer(serializers.Serializer):
    liked = serializers.BooleanField(read_only=True)
    like_count = serializers.IntegerField(read_only=True)
