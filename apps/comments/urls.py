from django.urls import path

from apps.comments.views import (
    CommentDetailView,
    CommentLikeView,
    CommentRepliesView,
    PostCommentsView,
)

urlpatterns = [
    path("posts/<str:post_id>/comments/", PostCommentsView.as_view(), name="post-comments"),
    path("comments/<str:comment_id>/", CommentDetailView.as_view(), name="comment-detail"),
    path(
        "comments/<str:comment_id>/replies/",
        CommentRepliesView.as_view(),
        name="comment-replies",
    ),
    path("comments/<str:comment_id>/like/", CommentLikeView.as_view(), name="comment-like"),
]
