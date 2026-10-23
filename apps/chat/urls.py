from django.urls import path

from apps.chat.views import (
    ConversationDetailView,
    ConversationListCreateView,
    ConversationReadView,
    MessageListCreateView,
    UnreadTotalView,
)

urlpatterns = [
    path("conversations/", ConversationListCreateView.as_view(), name="conversation-list"),
    # Before the detail route, so "unread-count" is not read as an id.
    path(
        "conversations/unread-count/",
        UnreadTotalView.as_view(),
        name="conversation-unread-count",
    ),
    path(
        "conversations/<int:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<int:conversation_id>/messages/",
        MessageListCreateView.as_view(),
        name="message-list",
    ),
    path(
        "conversations/<int:conversation_id>/read/",
        ConversationReadView.as_view(),
        name="conversation-read",
    ),
]
