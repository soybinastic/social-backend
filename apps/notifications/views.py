"""HTTP layer for notifications."""

from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.serializers import NotificationSerializer, UnreadCountSerializer
from apps.notifications.services import NotificationService


class NotificationListView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get(self, request):
        page = self.paginate_queryset(NotificationService().inbox(recipient=request.user))
        return self.get_paginated_response(NotificationSerializer(page, many=True).data)


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unread = NotificationService().unread_count(recipient=request.user)
        return Response(UnreadCountSerializer({"unread": unread}).data)


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id: int):
        notification = NotificationService().mark_read(
            recipient=request.user,
            notification_id=notification_id,
        )
        return Response(NotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        NotificationService().mark_all_read(recipient=request.user)
        return Response(UnreadCountSerializer({"unread": 0}).data)
