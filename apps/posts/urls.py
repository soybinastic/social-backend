from django.urls import path

from apps.interactions.views import PostLikersView, PostLikeView, PostShareView
from apps.posts.views import PostDetailView, PostListCreateView, UserPostsView

urlpatterns = [
    path("posts/", PostListCreateView.as_view(), name="post-list-create"),
    path("posts/<str:post_id>/", PostDetailView.as_view(), name="post-detail"),
    path("posts/<str:post_id>/like/", PostLikeView.as_view(), name="post-like"),
    path("posts/<str:post_id>/likers/", PostLikersView.as_view(), name="post-likers"),
    path("posts/<str:post_id>/share/", PostShareView.as_view(), name="post-share"),
    path("users/<str:username>/posts/", UserPostsView.as_view(), name="user-posts"),
]
