from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.chat.broadcast import ChatBroadcaster, user_group
from apps.chat.middleware import JWTAuthMiddleware
from apps.chat.models import Conversation, Message, Participant
from apps.chat.routing import websocket_urlpatterns
from apps.chat.services import ChatService
from apps.core.exceptions import InvalidInput, ResourceNotFound
from apps.core.testing import MediaRootTestCase, audio_upload, make_user, png_upload, video_upload
from apps.media.kinds import MediaKind
from apps.media.models import MediaAsset
from apps.media.testing import ExplodingStorage, InMemoryStorage

# Redis is the real transport, but a test process is one process and one loop.
IN_MEMORY_LAYER = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


class ConversationServiceTests(APITestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.service = ChatService(storage=InMemoryStorage())

    def test_starting_a_conversation_creates_it_with_both_participants(self):
        conversation, created = self.service.start_direct(user=self.alice, username="bob")

        self.assertTrue(created)
        self.assertEqual(
            set(conversation.participants.values_list("user_id", flat=True)),
            {self.alice.id, self.bob.id},
        )

    def test_starting_the_same_conversation_again_reuses_it(self):
        first, _ = self.service.start_direct(user=self.alice, username="bob")
        # From the other side, which is the same thread by definition.
        second, created = self.service.start_direct(user=self.bob, username="alice")

        self.assertEqual(first.id, second.id)
        self.assertFalse(created)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_the_pair_key_does_not_depend_on_who_started_it(self):
        self.assertEqual(
            Conversation.key_for(self.alice.id, self.bob.id),
            Conversation.key_for(self.bob.id, self.alice.id),
        )

    def test_a_new_thread_sorts_by_its_creation_time(self):
        conversation, _ = self.service.start_direct(user=self.alice, username="bob")

        # Not null, because cursor pagination cannot compare nulls.
        self.assertIsNotNone(conversation.last_message_at)
        self.assertIsNone(conversation.last_message)

    def test_you_cannot_start_a_conversation_with_yourself(self):
        with self.assertRaises(InvalidInput):
            self.service.start_direct(user=self.alice, username="alice")

    def test_starting_one_with_an_unknown_account_is_not_found(self):
        with self.assertRaises(ResourceNotFound):
            self.service.start_direct(user=self.alice, username="nobody")

    def test_the_inbox_only_contains_your_own_threads(self):
        mine, _ = self.service.start_direct(user=self.alice, username="bob")
        carol = make_user("carol")
        self.service.start_direct(user=self.bob, username="carol")

        self.assertEqual([row.id for row in self.service.inbox(user=self.alice)], [mine.id])
        self.assertEqual(self.service.inbox(user=carol).count(), 1)

    def test_reading_a_thread_you_are_not_in_is_not_found(self):
        conversation, _ = self.service.start_direct(user=self.alice, username="bob")
        intruder = make_user("intruder")

        with self.assertRaises(ResourceNotFound):
            self.service.get_for(user=intruder, conversation_id=conversation.id)


class MessageServiceTests(APITestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.storage = InMemoryStorage()
        self.service = ChatService(storage=self.storage)
        self.conversation, _ = self.service.start_direct(user=self.alice, username="bob")

    def _send(self, sender=None, **kwargs):
        return self.service.send(
            sender=sender or self.alice,
            conversation_id=self.conversation.id,
            **kwargs,
        )

    def test_sends_a_text_message(self):
        message = self._send(body="  hello bob  ")

        self.assertEqual(message.body, "hello bob")
        self.assertEqual(message.sender_id, self.alice.id)
        self.assertEqual(message.media.count(), 0)

    def test_sends_an_image_and_an_audio_attachment(self):
        message = self._send(body="", files=[png_upload(), audio_upload()])

        self.assertEqual(
            [asset.kind for asset in message.media.all()],
            [MediaKind.IMAGE, MediaKind.AUDIO],
        )
        self.assertEqual(len(self.storage.files), 2)

    def test_video_is_not_a_chat_attachment(self):
        with self.assertRaises(InvalidInput):
            self._send(files=[video_upload()])

        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(self.storage.files, {})

    def test_a_message_needs_text_or_an_attachment(self):
        with self.assertRaises(InvalidInput):
            self._send(body="   ")

    def test_too_many_attachments_is_rejected_before_uploading(self):
        with self.assertRaises(InvalidInput):
            self._send(files=[png_upload(f"{index}.png") for index in range(5)])

        self.assertEqual(self.storage.files, {})

    def test_a_failed_upload_leaves_no_message_and_no_files(self):
        service = ChatService(storage=ExplodingStorage(fail_on_call=2))

        with self.assertRaises(RuntimeError):
            service.send(
                sender=self.alice,
                conversation_id=self.conversation.id,
                files=[png_upload("first.png"), png_upload("second.png")],
            )

        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(MediaAsset.objects.count(), 0)

    def test_deleting_a_message_deletes_its_attachments(self):
        message = self._send(files=[png_upload()])

        message.delete()

        self.assertEqual(MediaAsset.objects.count(), 0)

    def test_replying_quotes_a_message_from_the_same_thread(self):
        original = self._send(body="what time?")

        reply = self._send(sender=self.bob, body="eight", reply_to_id=original.id)

        self.assertEqual(reply.reply_to_id, original.id)
        self.assertEqual(list(original.replies.all()), [reply])

    def test_replying_to_a_message_in_another_thread_is_rejected(self):
        carol = make_user("carol")
        elsewhere, _ = self.service.start_direct(user=self.alice, username="carol")
        theirs = self.service.send(
            sender=carol,
            conversation_id=elsewhere.id,
            body="private",
        )

        with self.assertRaises(InvalidInput):
            self._send(body="quoting", reply_to_id=theirs.id)

    def test_deleting_a_quoted_message_keeps_the_reply(self):
        original = self._send(body="what time?")
        reply = self._send(sender=self.bob, body="eight", reply_to_id=original.id)

        original.delete()

        reply.refresh_from_db()
        self.assertIsNone(reply.reply_to_id)

    def test_sending_moves_the_thread_to_the_top_of_the_inbox(self):
        message = self._send(body="hello")

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.last_message_id, message.id)
        self.assertEqual(self.conversation.last_message_at, message.created_at)

    def test_sending_raises_the_recipients_unread_count_only(self):
        self._send(body="one")
        self._send(body="two")

        self.assertEqual(self._participant(self.bob).unread_count, 2)
        self.assertEqual(self._participant(self.alice).unread_count, 0)

    def test_reading_a_thread_clears_its_unread_count(self):
        self._send(body="one")

        self.service.mark_read(user=self.bob, conversation_id=self.conversation.id)

        participant = self._participant(self.bob)
        self.assertEqual(participant.unread_count, 0)
        self.assertIsNotNone(participant.last_read_at)

    def test_replying_counts_as_reading(self):
        self._send(body="one")

        self._send(sender=self.bob, body="answer")

        self.assertEqual(self._participant(self.bob).unread_count, 0)
        self.assertEqual(self._participant(self.alice).unread_count, 1)

    def test_the_unread_total_spans_every_thread(self):
        make_user("carol")
        other, _ = self.service.start_direct(user=self.alice, username="carol")
        self._send(body="one")
        self._send(body="two")
        self.service.send(sender=self.alice, conversation_id=other.id, body="hi carol")

        self.assertEqual(self.service.unread_total(user=self.bob), 2)
        self.assertEqual(self.service.unread_total(user=self.alice), 0)

    def test_someone_outside_the_thread_cannot_send_to_it(self):
        intruder = make_user("intruder")

        with self.assertRaises(ResourceNotFound):
            self.service.send(
                sender=intruder,
                conversation_id=self.conversation.id,
                body="let me in",
            )

    def test_history_is_newest_first(self):
        first = self._send(body="one")
        second = self._send(body="two")

        history = self.service.history(user=self.bob, conversation_id=self.conversation.id)
        self.assertEqual([row.id for row in history], [second.id, first.id])

    def _participant(self, user) -> Participant:
        return Participant.objects.get(conversation=self.conversation, user=user)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class ChatApiTests(MediaRootTestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.client.force_authenticate(self.alice)

    def _start(self):
        response = self.client.post(reverse("conversation-list"), {"username": "bob"})
        return response.data["id"]

    def test_starting_a_conversation_returns_it_created_once(self):
        first = self.client.post(reverse("conversation-list"), {"username": "bob"})
        second = self.client.post(reverse("conversation-list"), {"username": "bob"})

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["id"], second.data["id"])
        # A thread is named after the other person, whoever is looking.
        self.assertEqual(first.data["other"]["username"], "bob")
        self.assertIsNone(first.data["last_message"])
        self.assertEqual(first.data["unread_count"], 0)

    def test_sending_and_listing_messages(self):
        conversation_id = self._start()
        url = reverse("message-list", args=[conversation_id])

        created = self.client.post(url, {"body": "hello bob"})
        listed = self.client.get(url)

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["body"], "hello bob")
        self.assertEqual(created.data["sender"]["username"], "alice")
        self.assertEqual(created.data["conversation"], str(conversation_id))
        self.assertEqual([row["id"] for row in listed.data["results"]], [created.data["id"]])

    def test_sending_a_message_with_an_image_and_a_voice_note(self):
        conversation_id = self._start()

        response = self.client.post(
            reverse("message-list", args=[conversation_id]),
            {"body": "look and listen", "files": [png_upload(), audio_upload()]},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual([item["kind"] for item in response.data["media"]], ["image", "audio"])

    def test_video_attachments_are_refused(self):
        conversation_id = self._start()

        response = self.client.post(
            reverse("message-list", args=[conversation_id]),
            {"files": [video_upload()]},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_replying_carries_the_quoted_message(self):
        conversation_id = self._start()
        url = reverse("message-list", args=[conversation_id])
        original = self.client.post(url, {"body": "what time?"}).data

        reply = self.client.post(url, {"body": "eight", "reply_to": original["id"]})

        self.assertEqual(reply.data["reply_to"]["id"], original["id"])
        self.assertEqual(reply.data["reply_to"]["body"], "what time?")
        # One level deep: the quoted message does not carry its own quote.
        self.assertNotIn("reply_to", reply.data["reply_to"])

    def test_the_inbox_shows_the_newest_thread_first_with_a_preview(self):
        make_user("carol")
        with_bob = self._start()
        with_carol = self.client.post(reverse("conversation-list"), {"username": "carol"}).data["id"]
        self.client.post(reverse("message-list", args=[with_bob]), {"body": "latest"})

        rows = self.client.get(reverse("conversation-list")).data["results"]

        self.assertEqual([row["id"] for row in rows], [str(with_bob), str(with_carol)])
        self.assertEqual(rows[0]["last_message"]["body"], "latest")

    def test_the_recipient_sees_the_thread_as_unread_until_they_read_it(self):
        conversation_id = self._start()
        self.client.post(reverse("message-list", args=[conversation_id]), {"body": "hello"})

        self.client.force_authenticate(self.bob)
        unread = self.client.get(reverse("conversation-unread-count")).data
        inbox = self.client.get(reverse("conversation-list")).data["results"]
        read = self.client.post(reverse("conversation-read", args=[conversation_id]))

        self.assertEqual(unread, {"unread": 1})
        self.assertEqual(inbox[0]["unread_count"], 1)
        self.assertEqual(read.data, {"unread": 0})
        self.assertEqual(self.client.get(reverse("conversation-list")).data["results"][0][
            "unread_count"
        ], 0)

    def test_a_thread_reports_when_the_other_side_last_read_it(self):
        conversation_id = self._start()
        self.client.post(reverse("message-list", args=[conversation_id]), {"body": "hello"})
        url = reverse("conversation-detail", args=[conversation_id])

        before = self.client.get(url).data
        self.client.force_authenticate(self.bob)
        self.client.post(reverse("conversation-read", args=[conversation_id]))
        self.client.force_authenticate(self.alice)
        after = self.client.get(url).data

        # This is what turns alice's message from sent into seen.
        self.assertIsNone(before["other_read_at"])
        self.assertIsNotNone(after["other_read_at"])

    def test_the_sender_has_nothing_unread(self):
        conversation_id = self._start()
        self.client.post(reverse("message-list", args=[conversation_id]), {"body": "hello"})

        self.assertEqual(
            self.client.get(reverse("conversation-unread-count")).data, {"unread": 0}
        )

    def test_a_thread_you_are_not_in_is_not_found(self):
        conversation_id = self._start()
        self.client.force_authenticate(make_user("intruder"))

        detail = self.client.get(reverse("conversation-detail", args=[conversation_id]))
        history = self.client.get(reverse("message-list", args=[conversation_id]))
        send = self.client.post(
            reverse("message-list", args=[conversation_id]),
            {"body": "let me in"},
        )

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(history.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(send.status_code, status.HTTP_404_NOT_FOUND)

    def test_an_empty_message_is_rejected(self):
        conversation_id = self._start()

        response = self.client.post(
            reverse("message-list", args=[conversation_id]),
            {"body": "  "},
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_chat_requires_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get(reverse("conversation-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class ChatPublishingTests(APITestCase):
    """That an HTTP send hands the message to the channel layer."""

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.client.force_authenticate(self.alice)
        self.conversation, _ = ChatService().start_direct(user=self.alice, username="bob")

    def test_a_sent_message_is_published_to_every_participant(self):
        layer = get_channel_layer()
        # Stands in for a connected client: the consumer would join this group.
        async_to_sync(layer.group_add)(user_group(self.bob.id), "bob-socket")

        self.client.post(
            reverse("message-list", args=[self.conversation.id]),
            {"body": "hello bob"},
        )

        envelope = async_to_sync(layer.receive)("bob-socket")
        self.assertEqual(envelope["type"], "chat.event")
        self.assertEqual(envelope["payload"]["type"], "message.created")
        self.assertEqual(envelope["payload"]["message"]["body"], "hello bob")
        self.assertEqual(
            envelope["payload"]["message"]["conversation"], str(self.conversation.id)
        )

    def test_a_broken_channel_layer_does_not_fail_the_send(self):
        class BrokenLayer:
            async def group_send(self, group, message):
                raise ConnectionError("channel layer is down")

        # The message is already stored, so a delivery failure is logged rather
        # than raised: it is not the request's problem.
        with self.assertLogs("apps.chat.broadcast", level="ERROR"):
            ChatBroadcaster(layer=BrokenLayer()).message_created(
                recipient_ids=[self.bob.id],
                message={"id": "1"},
            )

    def test_reading_a_thread_is_published_to_everyone_in_it(self):
        layer = get_channel_layer()
        async_to_sync(layer.group_add)(user_group(self.alice.id), "alice-socket")
        async_to_sync(layer.group_add)(user_group(self.bob.id), "bob-socket")

        self.client.post(reverse("conversation-read", args=[self.conversation.id]))

        # The reader's own tabs drop the badge...
        own = async_to_sync(layer.receive)("alice-socket")["payload"]
        # ...and the other side learns its messages were seen.
        theirs = async_to_sync(layer.receive)("bob-socket")["payload"]

        self.assertEqual(own, theirs)
        self.assertEqual(own["type"], "conversation.read")
        self.assertEqual(own["conversation"], str(self.conversation.id))
        self.assertEqual(own["reader"], str(self.alice.id))
        self.assertIsNotNone(own["read_at"])


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class ChatConsumerTests(TransactionTestCase):
    """The socket end of delivery.

    `TransactionTestCase`, because the handshake authenticates in another thread
    and so cannot see data held inside an uncommitted test transaction.
    """

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.carol = make_user("carol")
        self.conversation, _ = ChatService().start_direct(user=self.alice, username="bob")

    def _communicator(self, user=None, *, token=None):
        if token is None:
            token = str(AccessToken.for_user(user)) if user else ""
        # The origin check is the concern of config/asgi.py; this is the
        # authentication and routing behind it.
        application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        return WebsocketCommunicator(application, f"/ws/chat/?token={token}")

    async def test_a_signed_in_client_is_accepted_and_told_it_is_ready(self):
        communicator = self._communicator(self.bob)

        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        self.assertEqual(await communicator.receive_json_from(), {"type": "ready"})
        await communicator.disconnect()

    async def test_a_socket_without_a_token_is_refused(self):
        communicator = self._communicator()

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_a_socket_with_a_junk_token_is_refused(self):
        communicator = self._communicator(token="not-a-jwt")

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_an_event_for_you_arrives(self):
        communicator = self._communicator(self.bob)
        await communicator.connect()
        await communicator.receive_json_from()

        await get_channel_layer().group_send(
            user_group(self.bob.id),
            {"type": "chat.event", "payload": {"type": "message.created", "message": {"id": "7"}}},
        )

        event = await communicator.receive_json_from()
        self.assertEqual(event, {"type": "message.created", "message": {"id": "7"}})
        await communicator.disconnect()

    async def test_an_event_for_somebody_else_does_not_arrive(self):
        communicator = self._communicator(self.bob)
        await communicator.connect()
        await communicator.receive_json_from()

        await get_channel_layer().group_send(
            user_group(self.alice.id),
            {"type": "chat.event", "payload": {"type": "message.created", "message": {"id": "7"}}},
        )

        self.assertTrue(await communicator.receive_nothing())
        await communicator.disconnect()

    async def test_a_keepalive_is_answered(self):
        communicator = self._communicator(self.bob)
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"type": "ping"})

        self.assertEqual(await communicator.receive_json_from(), {"type": "pong"})
        await communicator.disconnect()


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class TypingRelayTests(TransactionTestCase):
    """Typing is the one thing clients send, and it is never stored."""

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.carol = make_user("carol")
        self.conversation, _ = ChatService().start_direct(user=self.alice, username="bob")

    def _communicator(self, user):
        application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        token = str(AccessToken.for_user(user))
        return WebsocketCommunicator(application, f"/ws/chat/?token={token}")

    async def _connected(self, user):
        communicator = self._communicator(user)
        await communicator.connect()
        await communicator.receive_json_from()
        return communicator

    async def _type(self, communicator, **overrides):
        frame = {
            "type": "typing",
            "conversation": str(self.conversation.id),
            "state": "start",
        }
        frame.update(overrides)
        await communicator.send_json_to(frame)

    async def test_typing_reaches_the_other_participant(self):
        watcher = await self._connected(self.bob)
        typist = await self._connected(self.alice)

        await self._type(typist)

        self.assertEqual(
            await watcher.receive_json_from(),
            {
                "type": "typing",
                "conversation": str(self.conversation.id),
                "user": str(self.alice.id),
                "state": "start",
            },
        )
        # Nobody needs to be told they are typing.
        self.assertTrue(await typist.receive_nothing())
        await watcher.disconnect()
        await typist.disconnect()

    async def test_stopping_is_relayed_too(self):
        watcher = await self._connected(self.bob)
        typist = await self._connected(self.alice)

        await self._type(typist, state="stop")

        self.assertEqual((await watcher.receive_json_from())["state"], "stop")
        await watcher.disconnect()
        await typist.disconnect()

    async def test_typing_in_a_thread_you_are_not_in_reaches_nobody(self):
        watcher = await self._connected(self.bob)
        intruder = await self._connected(self.carol)

        await self._type(intruder)

        self.assertTrue(await watcher.receive_nothing())
        await watcher.disconnect()
        await intruder.disconnect()

    async def test_an_unknown_state_is_ignored(self):
        watcher = await self._connected(self.bob)
        typist = await self._connected(self.alice)

        await self._type(typist, state="dancing")

        self.assertTrue(await watcher.receive_nothing())
        await watcher.disconnect()
        await typist.disconnect()

    async def test_a_made_up_conversation_id_does_not_break_the_socket(self):
        watcher = await self._connected(self.bob)
        typist = await self._connected(self.alice)

        await self._type(typist, conversation="not-an-id")

        self.assertTrue(await watcher.receive_nothing())
        # The socket has to survive a frame it could not use.
        await typist.send_json_to({"type": "ping"})
        self.assertEqual(await typist.receive_json_from(), {"type": "pong"})
        await watcher.disconnect()
        await typist.disconnect()

    async def test_an_unknown_frame_is_ignored(self):
        typist = await self._connected(self.alice)

        await typist.send_json_to({"type": "delete-everything"})

        self.assertTrue(await typist.receive_nothing())
        await typist.disconnect()
