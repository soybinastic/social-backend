from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.media.serializers import MediaAssetSerializer
from apps.posts.models import Post


class SharedPostSerializer(serializers.ModelSerializer):
    """The quoted original inside a reshare.

    Deliberately omits `shared_from`, which both prevents unbounded nesting and
    matches the service rule that reshare chains are flattened to one level.
    """

    id = serializers.CharField(read_only=True)
    author = UserSerializer(read_only=True)
    media = MediaAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = (
            "id",
            "author",
            "caption",
            "media",
            "like_count",
            "share_count",
            "comment_count",
            "created_at",
        )
        read_only_fields = fields


class PostSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    author = UserSerializer(read_only=True)
    media = MediaAssetSerializer(many=True, read_only=True)
    shared_from = SharedPostSerializer(read_only=True)
    liked = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = (
            "id",
            "author",
            "caption",
            "media",
            "shared_from",
            "like_count",
            "share_count",
            "comment_count",
            "liked",
            "is_mine",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_liked(self, post: Post) -> bool:
        # Populated once per page by the view; see LikeStateMixin.
        return post.id in self.context.get("liked_post_ids", set())

    def get_is_mine(self, post: Post) -> bool:
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and post.author_id == request.user.id)


class PostCreateSerializer(serializers.Serializer):
    """Validates the text part of a post.

    Attachments arrive as repeated `files` parts, which `request.FILES.getlist`
    handles directly; a ListField would silently keep only the last one.
    """

    caption = serializers.CharField(required=False, allow_blank=True, max_length=2200)


class PostUpdateSerializer(serializers.Serializer):
    caption = serializers.CharField(required=False, allow_blank=True, max_length=2200)


class ShareSerializer(serializers.Serializer):
    caption = serializers.CharField(required=False, allow_blank=True, max_length=2200)


class InteractionStateSerializer(serializers.Serializer):
    liked = serializers.BooleanField(read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    share_count = serializers.IntegerField(read_only=True)
