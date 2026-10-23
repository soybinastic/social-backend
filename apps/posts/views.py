"""HTTP layer for posts. Views compose services and serializers; no rules here."""

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.repositories import UserRepository
from apps.core.exceptions import ResourceNotFound
from apps.interactions.repositories import LikeRepository
from apps.posts.serializers import (
    PostCreateSerializer,
    PostSerializer,
    PostUpdateSerializer,
)
from apps.posts.services import PostService


class LikeStateMixin:
    """Resolves the viewer's like state for a batch of posts in one query."""

    def post_context(self, posts) -> dict:
        post_ids = [post.id for post in posts]
        liked_ids = LikeRepository().liked_post_ids(
            user_id=self.request.user.id,
            post_ids=post_ids,
        )
        return {"request": self.request, "liked_post_ids": liked_ids}


class PostListCreateView(LikeStateMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PostSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return PostService().feed()

    def get(self, request):
        page = self.paginate_queryset(self.get_queryset())
        serializer = PostSerializer(page, many=True, context=self.post_context(page))
        return self.get_paginated_response(serializer.data)

    def post(self, request):
        form = PostCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        post = PostService().create(
            author=request.user,
            caption=form.validated_data.get("caption", ""),
            files=request.FILES.getlist("files"),
        )
        serializer = PostSerializer(post, context=self.post_context([post]))
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PostDetailView(LikeStateMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PostSerializer

    def get(self, request, post_id):
        post = PostService().get(post_id)
        return Response(PostSerializer(post, context=self.post_context([post])).data)

    def patch(self, request, post_id):
        form = PostUpdateSerializer(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        post = PostService().update_caption(
            post_id=post_id,
            actor=request.user,
            caption=form.validated_data.get("caption", ""),
        )
        return Response(PostSerializer(post, context=self.post_context([post])).data)

    def delete(self, request, post_id):
        PostService().delete(post_id=post_id, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserPostsView(LikeStateMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PostSerializer

    def get(self, request, username):
        author = UserRepository().get_by_username(username)
        if author is None:
            raise ResourceNotFound("No user with that username.")

        page = self.paginate_queryset(PostService().by_author(author.id))
        serializer = PostSerializer(page, many=True, context=self.post_context(page))
        return self.get_paginated_response(serializer.data)
