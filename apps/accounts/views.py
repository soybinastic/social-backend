"""HTTP layer for accounts: parse, delegate, serialize.

Views deliberately contain no business rules; those live in `services.py`.
"""

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.repositories import UserRepository
from apps.accounts.serializers import (
    AvatarUploadSerializer,
    LoginSerializer,
    ProfileSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    SessionSerializer,
    UserSerializer,
)
from apps.accounts.services import AuthService, ProfileService
from apps.core.exceptions import ResourceNotFound
from apps.interactions.services import FollowService


class RegisterView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AuthService().register(**serializer.validated_data)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


class LoginView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AuthService().login(**serializer.validated_data)
        return Response(SessionSerializer(session).data)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = ProfileService().update(request.user, **serializer.validated_data)
        return Response(UserSerializer(user).data)


class AvatarView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = AvatarUploadSerializer

    def put(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = ProfileService().set_avatar(request.user, serializer.validated_data["file"])
        return Response(UserSerializer(user).data)

    def delete(self, request):
        user = ProfileService().clear_avatar(request.user)
        return Response(UserSerializer(user).data)


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, username: str):
        user = UserRepository().get_by_username(username)
        if user is None:
            raise ResourceNotFound("No user with that username.")

        # The viewer's side of the relationship is what decides whether the
        # client offers Follow, Follow back, or Following.
        context = FollowService().relationship_context(viewer=request.user, users=[user])
        return Response(ProfileSerializer(user, context=context).data)
