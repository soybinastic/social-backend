"""HTTP layer for likes, shares and follows."""

from collections.abc import Callable

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.serializers import (
    FollowStateSerializer,
    ProfileSerializer,
    UserSerializer,
)
from apps.interactions.models import Follow
from apps.interactions.services import FollowService, LikeService, ShareService
from apps.posts.serializers import (
    InteractionStateSerializer,
    PostSerializer,
    ShareSerializer,
)


class PostLikeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InteractionStateSerializer

    def post(self, request, post_id):
        state = LikeService().like(user=request.user, post_id=post_id)
        return Response(InteractionStateSerializer(state).data)

    def delete(self, request, post_id):
        state = LikeService().unlike(user=request.user, post_id=post_id)
        return Response(InteractionStateSerializer(state).data)


class PostLikersView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request, post_id):
        page = self.paginate_queryset(LikeService().likers_of(post_id))
        serializer = UserSerializer([like.user for like in page], many=True)
        return self.get_paginated_response(serializer.data)


class PostShareView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ShareSerializer

    def post(self, request, post_id):
        form = self.get_serializer(data=request.data)
        form.is_valid(raise_exception=True)
        share = ShareService().share(
            user=request.user,
            post_id=post_id,
            caption=form.validated_data.get("caption", ""),
        )
        serializer = PostSerializer(share, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UserFollowView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FollowStateSerializer

    def post(self, request, username):
        state = FollowService().follow(user=request.user, username=username)
        return Response(FollowStateSerializer(state).data)

    def delete(self, request, username):
        state = FollowService().unfollow(user=request.user, username=username)
        return Response(FollowStateSerializer(state).data)


class FollowListView(GenericAPIView):
    """Paging and serialization shared by both sides of the follow graph."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def respond_with(self, follows: QuerySet, pick: Callable[[Follow], User]) -> Response:
        # Edges are paged, not accounts, so the cursor orders by when the
        # follow happened and the newest followers come first.
        page = self.paginate_queryset(follows)
        users = [pick(follow) for follow in page]
        context = {
            "request": self.request,
            **FollowService().relationship_context(viewer=self.request.user, users=users),
        }
        serializer = ProfileSerializer(users, many=True, context=context)
        return self.get_paginated_response(serializer.data)


class UserFollowersView(FollowListView):
    def get(self, request, username):
        return self.respond_with(FollowService().followers_of(username), lambda row: row.follower)


class UserFollowingView(FollowListView):
    def get(self, request, username):
        return self.respond_with(FollowService().following_of(username), lambda row: row.followee)
