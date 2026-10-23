"""Server-to-client delivery over the channel layer."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def user_group(user_id) -> str:
    """The group a signed-in client's socket joins.

    Groups are named per user rather than per conversation so one socket serves
    every thread: the client does not reconnect when it switches threads, and
    the inbox badge still hears about threads that are not open. Channel layer
    group names are limited to letters, digits, hyphens, underscores and dots.
    """
    return f"chat.user.{user_id}"


class ChatBroadcaster:
    """Pushes chat events to the sockets of the people involved.

    The fan-out exists once, in `apublish`, and is reached two ways: the HTTP
    views are sync, while a typing relay starts inside the consumer and is
    already async. Neither side owns a second copy of it.

    Delivery is best effort on purpose. A message is already committed by the
    time this runs, so a channel layer outage must not fail the request that
    stored it; a client that misses a frame sees the message as soon as it loads
    the thread again.
    """

    def __init__(self, layer=None):
        self._layer = layer or get_channel_layer()

    def message_created(self, *, recipient_ids: list[int], message: dict) -> None:
        self.publish(recipient_ids, {"type": "message.created", "message": message})

    def conversation_read(self, *, recipient_ids: list[int], receipt: dict) -> None:
        """Announces that somebody caught up with a thread.

        The reader's other tabs use it to drop the unread badge, and everyone
        else in the thread uses it to mark their own messages as seen.
        """
        self.publish(recipient_ids, {"type": "conversation.read", **receipt})

    async def typing(
        self,
        *,
        recipient_ids: list[int],
        conversation_id,
        user_id,
        state: str,
    ) -> None:
        """Relayed from one socket to the others, so this end stays async."""
        await self.apublish(
            recipient_ids,
            {
                "type": "typing",
                "conversation": str(conversation_id),
                "user": str(user_id),
                "state": state,
            },
        )

    def publish(self, recipient_ids: list[int], payload: dict) -> None:
        async_to_sync(self.apublish)(recipient_ids, payload)

    async def apublish(self, recipient_ids: list[int], payload: dict) -> None:
        if self._layer is None:
            return
        for user_id in recipient_ids:
            try:
                await self._layer.group_send(
                    user_group(user_id),
                    # "type" routes to the consumer method of the same name
                    # with dots replaced by underscores.
                    {"type": "chat.event", "payload": payload},
                )
            except Exception:
                logger.exception("Could not deliver a chat event to user %s", user_id)
