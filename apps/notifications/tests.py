from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comments.services import CommentService
from apps.core.exceptions import ResourceNotFound
from apps.core.testing import make_user
from apps.interactions.services import FollowService, LikeService, ShareService
from apps.media.services import MediaUploadService
from apps.media.testing import InMemoryStorage
from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from apps.posts.services import PostService


def _post_service() -> PostService:
    return PostService(uploads=MediaUploadService(storage=InMemoryStorage()))


class NotificationRecordingTests(APITestCase):
    """What the receivers write for each kind of interaction."""

    def setUp(self):
        self.author = make_user("author")
        self.actor = make_user("actor")
        self.post = _post_service().create(author=self.author, caption="notify me")

    def test_liking_notifies_the_post_author(self):
        LikeService().like(user=self.actor, post_id=self.post.id)

        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.LIKE)
        self.assertEqual(notification.recipient_id, self.author.id)
        self.assertEqual(notification.actor_id, self.actor.id)
        # Clicking it opens the post that was liked.
        self.assertEqual(notification.post_id, self.post.id)
        self.assertFalse(notification.is_read)

    def test_unliking_withdraws_the_notification(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        LikeService().unlike(user=self.actor, post_id=self.post.id)

        self.assertEqual(Notification.objects.count(), 0)

    def test_liking_twice_notifies_once(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        LikeService().like(user=self.actor, post_id=self.post.id)

        # The like is idempotent, so no second row and no second notification.
        self.assertEqual(Notification.objects.count(), 1)

    def test_liking_your_own_post_notifies_nobody(self):
        LikeService().like(user=self.author, post_id=self.post.id)

        self.assertEqual(Notification.objects.count(), 0)

    def test_following_notifies_the_followed_account(self):
        FollowService().follow(user=self.actor, username="author")

        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.FOLLOW)
        self.assertEqual(notification.recipient_id, self.author.id)
        self.assertEqual(notification.actor_id, self.actor.id)
        # A follow has no post; the client opens the actor's profile instead.
        self.assertIsNone(notification.post_id)

    def test_following_back_notifies_the_other_side_too(self):
        FollowService().follow(user=self.actor, username="author")
        FollowService().follow(user=self.author, username="actor")

        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(
            set(Notification.objects.values_list("recipient_id", flat=True)),
            {self.author.id, self.actor.id},
        )

    def test_unfollowing_withdraws_the_notification(self):
        FollowService().follow(user=self.actor, username="author")
        FollowService().unfollow(user=self.actor, username="author")

        self.assertEqual(Notification.objects.count(), 0)

    def test_sharing_notifies_the_original_author_and_points_at_the_reshare(self):
        share = ShareService().share(user=self.actor, post_id=self.post.id, caption="look")

        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.SHARE)
        self.assertEqual(notification.recipient_id, self.author.id)
        self.assertEqual(notification.post_id, share.id)

    def test_sharing_your_own_post_notifies_nobody(self):
        ShareService().share(user=self.author, post_id=self.post.id)

        self.assertEqual(Notification.objects.count(), 0)

    def test_deleting_the_reshare_removes_its_notification(self):
        share = ShareService().share(user=self.actor, post_id=self.post.id)
        _post_service().delete(post_id=share.id, actor=self.actor)

        self.assertEqual(Notification.objects.count(), 0)

    def test_deleting_the_liked_post_removes_its_notification(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        _post_service().delete(post_id=self.post.id, actor=self.author)

        self.assertEqual(Notification.objects.count(), 0)

    def test_deleting_the_actor_removes_their_notifications(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        self.actor.delete()

        self.assertEqual(Notification.objects.count(), 0)

    def test_the_interaction_and_its_notification_commit_together(self):
        from django.db import transaction

        with self.assertRaises(RuntimeError), transaction.atomic():
            LikeService().like(user=self.actor, post_id=self.post.id)
            raise RuntimeError("caller failed after liking")

        self.assertEqual(Notification.objects.count(), 0)


class CommentNotificationTests(APITestCase):
    """Who hears about a comment, a reply, and a like on one."""

    def setUp(self):
        self.author = make_user("author")
        self.actor = make_user("actor")
        self.third = make_user("third")
        self.post = _post_service().create(author=self.author, caption="notify me")
        self.comments = CommentService()

    def test_commenting_notifies_the_post_author_and_quotes_the_comment(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="well said")

        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.COMMENT)
        self.assertEqual(notification.recipient_id, self.author.id)
        self.assertEqual(notification.actor_id, self.actor.id)
        # The post is what opens on click; the comment is what the row quotes.
        self.assertEqual(notification.post_id, self.post.id)
        self.assertEqual(notification.comment_id, comment.id)

    def test_commenting_on_your_own_post_notifies_nobody(self):
        self.comments.add(author=self.author, post_id=self.post.id, body="first")

        self.assertEqual(Notification.objects.count(), 0)

    def test_deleting_a_comment_withdraws_its_notification(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="oops")

        self.comments.delete(comment_id=comment.id, actor=self.actor)

        self.assertEqual(Notification.objects.count(), 0)

    def test_replying_notifies_the_comments_author(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="question")
        Notification.objects.all().delete()

        reply = self.comments.reply(author=self.third, comment_id=comment.id, body="answer")

        replied = Notification.objects.get(kind=Notification.Kind.REPLY)
        self.assertEqual(replied.recipient_id, self.actor.id)
        self.assertEqual(replied.comment_id, reply.id)
        self.assertEqual(replied.post_id, self.post.id)

    def test_replying_also_tells_the_post_author(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="question")
        Notification.objects.all().delete()

        self.comments.reply(author=self.third, comment_id=comment.id, body="answer")

        # Two people are owed the news: the one answered and the one whose post
        # the conversation is happening under.
        self.assertEqual(
            set(Notification.objects.values_list("recipient_id", flat=True)),
            {self.actor.id, self.author.id},
        )

    def test_the_post_author_answering_their_own_thread_hears_once(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="question")
        Notification.objects.all().delete()

        self.comments.reply(author=self.author, comment_id=comment.id, body="answer")

        # The author is the actor here, so only the person answered is told.
        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.REPLY)
        self.assertEqual(notification.recipient_id, self.actor.id)

    def test_replying_to_the_post_authors_own_comment_notifies_them_once(self):
        comment = self.comments.add(author=self.author, post_id=self.post.id, body="my thoughts")

        self.comments.reply(author=self.actor, comment_id=comment.id, body="answer")

        # They wrote the parent and own the post; that is one piece of news.
        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.REPLY)
        self.assertEqual(notification.recipient_id, self.author.id)

    def test_liking_a_comment_notifies_its_author(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="like me")
        Notification.objects.all().delete()

        self.comments.like(user=self.third, comment_id=comment.id)

        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.COMMENT_LIKE)
        self.assertEqual(notification.recipient_id, self.actor.id)
        self.assertEqual(notification.comment_id, comment.id)
        self.assertEqual(notification.post_id, self.post.id)

    def test_unliking_a_comment_withdraws_the_notification(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="like me")
        self.comments.like(user=self.third, comment_id=comment.id)

        self.comments.unlike(user=self.third, comment_id=comment.id)

        self.assertEqual(
            Notification.objects.filter(kind=Notification.Kind.COMMENT_LIKE).count(), 0
        )

    def test_liking_your_own_comment_notifies_nobody(self):
        comment = self.comments.add(author=self.actor, post_id=self.post.id, body="like me")
        Notification.objects.all().delete()

        self.comments.like(user=self.actor, comment_id=comment.id)

        self.assertEqual(Notification.objects.count(), 0)

    def test_the_comment_and_its_notification_commit_together(self):
        from django.db import transaction

        with self.assertRaises(RuntimeError), transaction.atomic():
            self.comments.add(author=self.actor, post_id=self.post.id, body="doomed")
            raise RuntimeError("caller failed after commenting")

        self.assertEqual(Notification.objects.count(), 0)


class NotificationServiceTests(APITestCase):
    def setUp(self):
        self.recipient = make_user("recipient")
        self.actor = make_user("actor")
        self.service = NotificationService()
        self.notification = self.service.record(
            recipient_id=self.recipient.id,
            actor_id=self.actor.id,
            kind=Notification.Kind.FOLLOW,
        )

    def test_marking_read_stamps_the_time(self):
        marked = self.service.mark_read(
            recipient=self.recipient,
            notification_id=self.notification.id,
        )

        self.assertTrue(marked.is_read)
        self.assertEqual(self.service.unread_count(recipient=self.recipient), 0)

    def test_marking_read_twice_keeps_the_first_timestamp(self):
        first = self.service.mark_read(
            recipient=self.recipient,
            notification_id=self.notification.id,
        ).read_at
        second = self.service.mark_read(
            recipient=self.recipient,
            notification_id=self.notification.id,
        ).read_at

        self.assertEqual(first, second)

    def test_another_account_cannot_read_your_notification(self):
        with self.assertRaises(ResourceNotFound):
            self.service.mark_read(
                recipient=self.actor,
                notification_id=self.notification.id,
            )

    def test_marking_all_read_clears_the_count(self):
        self.service.record(
            recipient_id=self.recipient.id,
            actor_id=self.actor.id,
            kind=Notification.Kind.LIKE,
        )

        self.assertEqual(self.service.unread_count(recipient=self.recipient), 2)
        self.assertEqual(self.service.mark_all_read(recipient=self.recipient), 2)
        self.assertEqual(self.service.unread_count(recipient=self.recipient), 0)

    def test_inbox_only_contains_your_own_notifications(self):
        self.service.record(
            recipient_id=self.actor.id,
            actor_id=self.recipient.id,
            kind=Notification.Kind.FOLLOW,
        )

        inbox = self.service.inbox(recipient=self.recipient)
        self.assertEqual([row.id for row in inbox], [self.notification.id])


class NotificationApiTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.actor = make_user("actor")
        self.post = _post_service().create(author=self.author, caption="notify me")
        self.client.force_authenticate(self.author)

    def test_list_returns_the_newest_notification_first(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        FollowService().follow(user=self.actor, username="author")

        response = self.client.get(reverse("notification-list"))
        rows = response.data["results"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["kind"] for row in rows], ["follow", "like"])
        self.assertEqual(rows[0]["actor"]["username"], "actor")
        self.assertIsNone(rows[0]["post"])
        self.assertEqual(rows[1]["post"]["id"], str(self.post.id))
        self.assertFalse(rows[1]["is_read"])

    def test_unread_count_endpoint(self):
        LikeService().like(user=self.actor, post_id=self.post.id)

        response = self.client.get(reverse("notification-unread-count"))
        self.assertEqual(response.data, {"unread": 1})

    def test_read_endpoint_marks_one_notification(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        notification = Notification.objects.get()

        response = self.client.post(reverse("notification-read", args=[notification.id]))

        self.assertTrue(response.data["is_read"])
        self.assertEqual(
            self.client.get(reverse("notification-unread-count")).data["unread"], 0
        )

    def test_reading_someone_elses_notification_is_not_found(self):
        FollowService().follow(user=self.author, username="actor")
        theirs = Notification.objects.get(recipient=self.actor)

        response = self.client.post(reverse("notification-read", args=[theirs.id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_read_all_endpoint_clears_the_badge(self):
        LikeService().like(user=self.actor, post_id=self.post.id)
        FollowService().follow(user=self.actor, username="author")

        response = self.client.post(reverse("notification-read-all"))

        self.assertEqual(response.data, {"unread": 0})
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 0)

    def test_notifications_require_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get(reverse("notification-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
