from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User, username_validator
from apps.media.serializers import MediaAssetSerializer


class UserSerializer(serializers.ModelSerializer):
    """Public profile projection."""

    id = serializers.CharField(read_only=True)
    avatar = MediaAssetSerializer(read_only=True)
    name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "display_name",
            "name",
            "bio",
            "avatar",
            "follower_count",
            "following_count",
            "date_joined",
        )
        read_only_fields = fields


class ProfileSerializer(UserSerializer):
    """`UserSerializer` plus how the viewer relates to the account.

    Both flags read from sets the caller resolves once for the whole page, so a
    list of accounts costs two extra queries rather than two per row. See
    `FollowService.relationship_context`.
    """

    is_following = serializers.SerializerMethodField()
    follows_you = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ("is_following", "follows_you")
        read_only_fields = fields

    def get_is_following(self, user: User) -> bool:
        return user.id in self.context.get("following_ids", set())

    def get_follows_you(self, user: User) -> bool:
        return user.id in self.context.get("follower_ids", set())


class FollowStateSerializer(serializers.Serializer):
    """Envelope returned by follow and unfollow."""

    is_following = serializers.BooleanField(read_only=True)
    follows_you = serializers.BooleanField(read_only=True)
    follower_count = serializers.IntegerField(read_only=True)
    following_count = serializers.IntegerField(read_only=True)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(max_length=30)
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=80)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate_username(self, value: str) -> str:
        # Normalize before validating: usernames are case-insensitive, so
        # "Alice" should become "alice" rather than fail the lowercase pattern.
        value = value.strip().lower()
        username_validator(value)
        return value

    def validate(self, attrs: dict) -> dict:
        # Run Django's configured password policy, reported against the field.
        try:
            validate_password(attrs["password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class ProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=80)
    bio = serializers.CharField(required=False, allow_blank=True, max_length=280)


class SessionSerializer(serializers.Serializer):
    """Envelope returned by register and login."""

    user = UserSerializer(read_only=True)
    access_token = serializers.CharField(read_only=True)
    refresh_token = serializers.CharField(read_only=True)


class AvatarUploadSerializer(serializers.Serializer):
    file = serializers.FileField(write_only=True)
