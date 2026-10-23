"""Authentication and profile use cases."""

from dataclasses import dataclass

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.repositories import UserRepository
from apps.core.exceptions import Conflict, DomainError, InvalidInput
from apps.media.services import MediaUploadService


class InvalidCredentials(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"
    message = "Incorrect email or password."


@dataclass(frozen=True)
class AuthenticatedSession:
    """What a caller needs after a successful sign-in or sign-up."""

    user: User
    access_token: str
    refresh_token: str


class TokenIssuer:
    """Isolates the JWT library so services don't depend on it directly."""

    def issue(self, user: User) -> tuple[str, str]:
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token), str(refresh)


class AuthService:
    def __init__(self, users: UserRepository | None = None, tokens: TokenIssuer | None = None):
        self._users = users or UserRepository()
        self._tokens = tokens or TokenIssuer()

    def register(
        self,
        *,
        email: str,
        username: str,
        password: str,
        display_name: str = "",
    ) -> AuthenticatedSession:
        # Checked up front so the caller gets a message naming the field that
        # clashed. The unique indexes below are what actually guarantee it.
        if self._users.email_taken(email):
            raise Conflict("An account with that email already exists.")
        if self._users.username_taken(username):
            raise Conflict("That username is already taken.")

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    username=username,
                    password=password,
                    display_name=display_name,
                )
        except IntegrityError as exc:
            # Two simultaneous sign-ups can both pass the checks above; the
            # database settles it and the loser lands here.
            raise Conflict("That email or username was just taken.") from exc
        except DjangoValidationError as exc:
            raise InvalidInput(" ".join(exc.messages)) from exc

        return self._session_for(user)

    def login(self, *, email: str, password: str) -> AuthenticatedSession:
        user = authenticate(username=email.strip().lower(), password=password)
        if user is None:
            # Same message for unknown email and wrong password so the endpoint
            # can't be used to enumerate registered accounts.
            raise InvalidCredentials
        if not user.is_active:
            raise InvalidCredentials("This account has been deactivated.")
        return self._session_for(user)

    def _session_for(self, user: User) -> AuthenticatedSession:
        access, refresh = self._tokens.issue(user)
        return AuthenticatedSession(user=user, access_token=access, refresh_token=refresh)


class ProfileService:
    EDITABLE_FIELDS = ("display_name", "bio")

    def __init__(
        self,
        users: UserRepository | None = None,
        uploads: MediaUploadService | None = None,
    ):
        self._users = users or UserRepository()
        self._uploads = uploads or MediaUploadService()

    def update(self, user: User, **changes) -> User:
        updated = [field for field in self.EDITABLE_FIELDS if field in changes]
        for field in updated:
            setattr(user, field, changes[field])
        if updated:
            user.save(update_fields=updated)
        return user

    def set_avatar(self, user: User, file: UploadedFile) -> User:
        previous = user.avatar
        asset = self._uploads.upload(file)

        with transaction.atomic():
            asset.save()
            user.avatar = asset
            # Repointing the account before dropping the old row means the
            # SET_NULL on this relation never has anything to null out.
            user.save(update_fields=["avatar"])
            if previous is not None:
                previous.delete()
                transaction.on_commit(lambda: self._uploads.discard(previous))

        return user

    def clear_avatar(self, user: User) -> User:
        previous = user.avatar
        if previous is None:
            return user

        with transaction.atomic():
            user.avatar = None
            user.save(update_fields=["avatar"])
            previous.delete()
            # Deleted from storage only once the change is durable.
            transaction.on_commit(lambda: self._uploads.discard(previous))

        return user
