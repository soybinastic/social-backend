"""WebSocket authentication."""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError


class JWTAuthMiddleware:
    """Resolves `scope["user"]` from an access token in the handshake query string.

    A browser cannot set an Authorization header on a WebSocket handshake, so the
    token travels as `?token=`. What makes that acceptable here is that access
    tokens are short-lived and the socket is delivery-only, so a leaked URL grants
    a few minutes of reading what the user would have received anyway.

    An unusable token produces an anonymous scope rather than an error: refusing
    the connection is the consumer's decision, and it can say why.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = await self._authenticate(scope)
        return await self.inner(scope, receive, send)

    async def _authenticate(self, scope):
        query = parse_qs(scope.get("query_string", b"").decode())
        raw_token = next(iter(query.get("token", [])), "")
        if not raw_token:
            return AnonymousUser()
        try:
            return await self._user_for(raw_token)
        except (TokenError, AuthenticationFailed):
            return AnonymousUser()

    @database_sync_to_async
    def _user_for(self, raw_token: str):
        backend = JWTAuthentication()
        return backend.get_user(backend.get_validated_token(raw_token))
