"""HTTP layer for chat. Views compose services and serializers; no rules here."""

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.broadcast import ChatBroadcaster
from apps.chat.pagination import InboxCursorPagination
from apps.chat.serializers import (
    ConversationCreateSerializer,
    ConversationSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    ReadReceiptSerializer,
    UnreadTotalSerializer,
)
from apps.chat.services import ChatService


class ConversationListCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer
    pagination_class = InboxCursorPagination

    def get(self, request):
        page = self.paginate_queryset(ChatService().inbox(user=request.user))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def post(self, request):
        form = ConversationCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        conversation, created = ChatService().start_direct(
            user=request.user,
            username=form.validated_data["username"],
        )
        return Response(
            self.get_serializer(conversation).data,
            # Opening a chat twice is the same request twice, so the second one
            # is not a creation.
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ConversationDetailView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer

    def get(self, request, conversation_id: int):
        conversation = ChatService().get_for(user=request.user, conversation_id=conversation_id)
        return Response(self.get_serializer(conversation).data)


class MessageListCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, conversation_id: int):
        page = self.paginate_queryset(
            ChatService().history(user=request.user, conversation_id=conversation_id)
        )
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def post(self, request, conversation_id: int):
        form = MessageCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        service = ChatService()
        message = service.send(
            sender=request.user,
            conversation_id=conversation_id,
            body=form.validated_data.get("body", ""),
            files=request.FILES.getlist("files"),
            reply_to_id=form.validated_data.get("reply_to"),
        )

        payload = self.get_serializer(message).data
        # The sender is included: their other tabs need it too, and clients
        # already ignore a message they hold by id.
        ChatBroadcaster().message_created(
            recipient_ids=service.participant_ids(conversation_id),
            message=payload,
        )
        return Response(payload, status=status.HTTP_201_CREATED)


class ConversationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        service = ChatService()
        participant = service.mark_read(user=request.user, conversation_id=conversation_id)

        receipt = ReadReceiptSerializer(
            {
                "conversation": str(conversation_id),
                "reader": str(request.user.id),
                "read_at": participant.last_read_at,
            }
        ).data
        # The whole thread hears it: the reader's other tabs drop the badge, and
        # the other side learns that its messages have been seen.
        ChatBroadcaster().conversation_read(
            recipient_ids=service.participant_ids(conversation_id),
            receipt=receipt,
        )
        return Response(
            UnreadTotalSerializer({"unread": service.unread_total(user=request.user)}).data
        )


class UnreadTotalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unread = ChatService().unread_total(user=request.user)
        return Response(UnreadTotalSerializer({"unread": unread}).data)
