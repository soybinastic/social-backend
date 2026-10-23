"""HTTP layer for comments. Views compose services and serializers; no rules here."""

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.comments.serializers import (
    CommentCreateSerializer,
    CommentSerializer,
    CommentStateSerializer,
)
from apps.comments.services import CommentService


class CommentStateMixin:
    """Resolves the viewer's like state for a batch of comments in one query."""

    def comment_context(self, comments) -> dict:
        liked_ids = CommentService().liked_ids(user=self.request.user, comments=list(comments))
        return {"request": self.request, "liked_comment_ids": liked_ids}

    def created(self, comment) -> Response:
        serializer = CommentSerializer(comment, context=self.comment_context([comment]))
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def page_of(self, queryset) -> Response:
        page = self.paginate_queryset(queryset)
        serializer = CommentSerializer(page, many=True, context=self.comment_context(page))
        return self.get_paginated_response(serializer.data)

    def body_from(self, request) -> str:
        form = CommentCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        return form.validated_data.get("body", "")


class PostCommentsView(CommentStateMixin, GenericAPIView):
    """The conversation under a post: top-level comments only.

    Replies are fetched per comment rather than nested here, so one very busy
    sub-thread cannot push every other comment off the page.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def get(self, request, post_id):
        return self.page_of(CommentService().on_post(post_id))

    def post(self, request, post_id):
        comment = CommentService().add(
            author=request.user,
            post_id=post_id,
            body=self.body_from(request),
        )
        return self.created(comment)


class CommentRepliesView(CommentStateMixin, GenericAPIView):
    """Replies live under the comment, not under the post.

    The post is derived from the parent, which is what makes a reply that lands
    on somebody else's post impossible to ask for.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def get(self, request, comment_id):
        return self.page_of(CommentService().replies_to(comment_id))

    def post(self, request, comment_id):
        comment = CommentService().reply(
            author=request.user,
            comment_id=comment_id,
            body=self.body_from(request),
        )
        return self.created(comment)


class CommentDetailView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def delete(self, request, comment_id):
        CommentService().delete(comment_id=comment_id, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentLikeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentStateSerializer

    def post(self, request, comment_id):
        state = CommentService().like(user=request.user, comment_id=comment_id)
        return Response(CommentStateSerializer(state).data)

    def delete(self, request, comment_id):
        state = CommentService().unlike(user=request.user, comment_id=comment_id)
        return Response(CommentStateSerializer(state).data)
