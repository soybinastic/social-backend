"""WebSocket endpoints."""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.chat.broadcast import ChatBroadcaster, user_group
from apps.chat.services import ChatService

# Application close codes, which a browser hands to the client untouched so it
# can tell "your token is no good" apart from a network drop and decide whether
# reconnecting is worth trying.
UNAUTHENTICATED = 4401

TYPING_STATES = frozenset({"start", "stop"})


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """One socket per signed-in client, carrying all of their conversations.

    Messages are sent over HTTP (see `apps.chat.views`) because attachments need
    a multipart body, and a single write path is easier to keep correct than two;
    this end forwards what the broadcaster fans out.

    Typing is the exception, and travels the other way down this socket. It is
    the one thing here with nothing worth storing — it is stale within seconds
    and means nothing after the fact — so it is relayed between sockets and
    never written down.

    Authorization for delivery is settled by the group name: a client only ever
    joins the group for its own user id, and the broadcaster sends to one group
    per participant, so no per-message access check is needed here.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=UNAUTHENTICATED)
            return

        self.user = user
        self.group_name = user_group(user.id)
        self._participants: dict[str, list[int]] = {}
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        # Lets the client distinguish "connected" from "connected and joined",
        # which is when it is safe to stop polling.
        await self.send_json({"type": "ready"})

    async def disconnect(self, code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "ping":
            # An idle WebSocket is liable to be dropped by proxies.
            await self.send_json({"type": "pong"})
        elif kind == "typing":
            await self._relay_typing(content)
        # Anything else is ignored rather than answered, because writes are HTTP.

    async def chat_event(self, event):
        """Channel layer handler for `{"type": "chat.event"}` envelopes."""
        await self.send_json(event["payload"])

    async def _relay_typing(self, content: dict) -> None:
        state = content.get("state")
        conversation_id = content.get("conversation")
        if state not in TYPING_STATES or conversation_id is None:
            return

        participants = await self._participants_of(conversation_id)
        if self.user.id not in participants:
            # Not a thread this client is in, or not a thread at all. Without
            # this check a made-up conversation id would be a way to send
            # anything to anybody.
            return

        recipients = [user_id for user_id in participants if user_id != self.user.id]
        if not recipients:
            return

        await ChatBroadcaster().typing(
            recipient_ids=recipients,
            conversation_id=conversation_id,
            user_id=self.user.id,
            state=state,
        )

    async def _participants_of(self, conversation_id) -> list[int]:
        """Cached for the life of the socket.

        Typing arrives every few seconds per thread, and who is in a direct
        conversation does not change, so this is one query per thread per
        connection rather than one per keystroke.
        """
        key = str(conversation_id)
        if key not in self._participants:
            self._participants[key] = await self._load_participants(key)
        return self._participants[key]

    @database_sync_to_async
    def _load_participants(self, conversation_id: str) -> list[int]:
        try:
            return ChatService().participant_ids(int(conversation_id))
        except (TypeError, ValueError):
            # A junk id is not a thread, so it has no participants.
            return []
