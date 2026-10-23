from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.chat.models import Conversation, Message
from apps.media.serializers import MediaAssetSerializer


class QuotedMessageSerializer(serializers.ModelSerializer):
    """The message a reply points at.

    Deliberately omits `reply_to`, which keeps quoting one level deep in the
    payload however long the chain of replies gets.
    """

    id = serializers.CharField(read_only=True)
    sender = UserSerializer(read_only=True)
    media = MediaAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = ("id", "sender", "body", "media", "created_at")
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    """A message as every participant sees it.

    There is no `is_mine` here, unlike `PostSerializer`: one serialized message
    is broadcast to the whole thread, so a viewer-dependent field would be wrong
    for everyone but the sender. Clients compare `sender.id` themselves.
    """

    id = serializers.CharField(read_only=True)
    conversation = serializers.CharField(source="conversation_id", read_only=True)
    sender = UserSerializer(read_only=True)
    media = MediaAssetSerializer(many=True, read_only=True)
    reply_to = QuotedMessageSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ("id", "conversation", "sender", "body", "media", "reply_to", "created_at")
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    """A thread from the viewer's side of it."""

    id = serializers.CharField(read_only=True)
    other = serializers.SerializerMethodField()
    other_read_at = serializers.SerializerMethodField()
    last_message = MessageSerializer(read_only=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "id",
            "other",
            "other_read_at",
            "last_message",
            "unread_count",
            "last_message_at",
            "created_at",
        )
        read_only_fields = fields

    def get_other(self, conversation: Conversation) -> dict | None:
        """The participant who is not the viewer: a thread is named after them."""
        participant = self._participant(conversation, is_viewer=False)
        return UserSerializer(participant.user).data if participant else None

    def get_other_read_at(self, conversation: Conversation):
        """When the other side last caught up.

        One timestamp per participant, rather than a flag per message: a message
        has been seen when it is older than this, which is the same answer at a
        fraction of the bookkeeping.
        """
        participant = self._participant(conversation, is_viewer=False)
        return participant.last_read_at if participant else None

    def get_unread_count(self, conversation: Conversation) -> int:
        participant = self._participant(conversation, is_viewer=True)
        return participant.unread_count if participant else 0

    def _participant(self, conversation: Conversation, *, is_viewer: bool):
        viewer_id = self._viewer_id()
        # Iterating the prefetched participants rather than filtering, which
        # would issue a query per row and undo the prefetch.
        for participant in conversation.participants.all():
            if (participant.user_id == viewer_id) is is_viewer:
                return participant
        return None

    def _viewer_id(self):
        request = self.context.get("request")
        return request.user.id if request and request.user.is_authenticated else None


class ConversationCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=30)


class MessageCreateSerializer(serializers.Serializer):
    """Validates the text part of a message.

    Attachments arrive as repeated `files` parts, which `request.FILES.getlist`
    handles directly; a ListField would silently keep only the last one.
    """

    body = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    reply_to = serializers.IntegerField(required=False, allow_null=True)


class ReadReceiptSerializer(serializers.Serializer):
    """What gets broadcast when somebody reads a thread.

    Built with a serializer rather than by hand so that `read_at` reaches the
    socket in the same shape the REST payloads use.
    """

    conversation = serializers.CharField()
    reader = serializers.CharField()
    read_at = serializers.DateTimeField()


class UnreadTotalSerializer(serializers.Serializer):
    unread = serializers.IntegerField(read_only=True)
