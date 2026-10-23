from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comments.models import Comment, CommentLike
from apps.comments.services import CommentService
from apps.core.exceptions import InvalidInput, PermissionDenied, ResourceNotFound
from apps.core.testing import make_user
from apps.media.services import MediaUploadService
from apps.media.testing import InMemoryStorage
from apps.posts.models import Post
from apps.posts.services import PostService


def _post_service() -> PostService:
    return PostService(uploads=MediaUploadService(storage=InMemoryStorage()))


class CommentServiceTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.reader = make_user("reader")
        self.post = _post_service().create(author=self.author, caption="say something")
        self.service = CommentService()

    def test_commenting_stores_the_body_against_the_post(self):
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="  nice one  ")

        self.assertEqual(comment.body, "nice one")
        self.assertEqual(comment.post_id, self.post.id)
        self.assertIsNone(comment.parent_id)

    def test_an_empty_comment_is_rejected(self):
        with self.assertRaises(InvalidInput):
            self.service.add(author=self.reader, post_id=self.post.id, body="   ")

    def test_an_overlong_comment_is_rejected(self):
        with self.assertRaises(InvalidInput):
            self.service.add(author=self.reader, post_id=self.post.id, body="x" * 1001)

    def test_commenting_on_a_missing_post_is_not_found(self):
        with self.assertRaises(ResourceNotFound):
            self.service.add(author=self.reader, post_id=999, body="hello?")

    def test_commenting_raises_the_posts_comment_count(self):
        self.service.add(author=self.reader, post_id=self.post.id, body="one")
        self.service.add(author=self.reader, post_id=self.post.id, body="two")

        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 2)

    def test_a_reply_belongs_to_the_same_post_as_its_parent(self):
        parent = self.service.add(author=self.reader, post_id=self.post.id, body="question")

        reply = self.service.reply(author=self.author, comment_id=parent.id, body="answer")

        self.assertEqual(reply.parent_id, parent.id)
        self.assertEqual(reply.post_id, self.post.id)

    def test_replying_to_a_reply_joins_the_same_thread(self):
        parent = self.service.add(author=self.reader, post_id=self.post.id, body="question")
        reply = self.service.reply(author=self.author, comment_id=parent.id, body="answer")

        deeper = self.service.reply(author=self.reader, comment_id=reply.id, body="thanks")

        # Flattened onto the top-level comment rather than nested under a reply,
        # so a thread is always two levels deep.
        self.assertEqual(deeper.parent_id, parent.id)

    def test_replying_raises_the_parents_reply_count_and_the_posts_total(self):
        parent = self.service.add(author=self.reader, post_id=self.post.id, body="question")
        self.service.reply(author=self.author, comment_id=parent.id, body="answer")

        parent.refresh_from_db()
        self.post.refresh_from_db()
        self.assertEqual(parent.reply_count, 1)
        # Replies count towards the conversation as a whole.
        self.assertEqual(self.post.comment_count, 2)

    def test_the_thread_of_a_post_excludes_replies(self):
        first = self.service.add(author=self.reader, post_id=self.post.id, body="one")
        second = self.service.add(author=self.reader, post_id=self.post.id, body="two")
        self.service.reply(author=self.author, comment_id=first.id, body="answer")

        thread = self.service.on_post(self.post.id)

        # Newest first, and the reply is reached through its parent instead.
        self.assertEqual([row.id for row in thread], [second.id, first.id])

    def test_liking_a_comment_is_idempotent(self):
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="like me")

        self.service.like(user=self.author, comment_id=comment.id)
        state = self.service.like(user=self.author, comment_id=comment.id)

        self.assertTrue(state.liked)
        self.assertEqual(state.like_count, 1)
        self.assertEqual(CommentLike.objects.count(), 1)

    def test_unliking_a_comment_that_was_not_liked_is_a_no_op(self):
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="like me")

        state = self.service.unlike(user=self.author, comment_id=comment.id)

        self.assertFalse(state.liked)
        self.assertEqual(state.like_count, 0)

    def test_unliking_lowers_the_count(self):
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="like me")
        self.service.like(user=self.author, comment_id=comment.id)

        state = self.service.unlike(user=self.author, comment_id=comment.id)

        self.assertFalse(state.liked)
        self.assertEqual(state.like_count, 0)

    def test_the_writer_can_delete_their_comment(self):
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="oops")

        self.service.delete(comment_id=comment.id, actor=self.reader)

        self.assertEqual(Comment.objects.count(), 0)
        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 0)

    def test_the_post_author_can_delete_somebody_elses_comment(self):
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="spam")

        # Moderating your own thread is the whole reason this is allowed.
        self.service.delete(comment_id=comment.id, actor=self.author)

        self.assertEqual(Comment.objects.count(), 0)

    def test_a_bystander_cannot_delete_a_comment(self):
        bystander = make_user("bystander")
        comment = self.service.add(author=self.reader, post_id=self.post.id, body="mine")

        with self.assertRaises(PermissionDenied):
            self.service.delete(comment_id=comment.id, actor=bystander)

        self.assertEqual(Comment.objects.count(), 1)

    def test_deleting_a_comment_takes_its_replies_and_their_counts(self):
        parent = self.service.add(author=self.reader, post_id=self.post.id, body="question")
        self.service.reply(author=self.author, comment_id=parent.id, body="answer")

        self.service.delete(comment_id=parent.id, actor=self.reader)

        self.assertEqual(Comment.objects.count(), 0)
        self.post.refresh_from_db()
        # Both rows came off the post's total, not just the one deleted directly.
        self.assertEqual(self.post.comment_count, 0)

    def test_deleting_a_reply_lowers_its_parents_reply_count(self):
        parent = self.service.add(author=self.reader, post_id=self.post.id, body="question")
        reply = self.service.reply(author=self.author, comment_id=parent.id, body="answer")

        self.service.delete(comment_id=reply.id, actor=self.author)

        parent.refresh_from_db()
        self.assertEqual(parent.reply_count, 0)

    def test_deleting_the_post_takes_the_whole_conversation(self):
        parent = self.service.add(author=self.reader, post_id=self.post.id, body="question")
        self.service.reply(author=self.author, comment_id=parent.id, body="answer")

        _post_service().delete(post_id=self.post.id, actor=self.author)

        self.assertEqual(Comment.objects.count(), 0)

    def test_a_deleted_account_takes_its_comments(self):
        self.service.add(author=self.reader, post_id=self.post.id, body="mine")

        self.reader.delete()

        self.assertEqual(Comment.objects.count(), 0)
        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 0)


class CommentApiTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.reader = make_user("reader")
        self.post = _post_service().create(author=self.author, caption="say something")
        self.client.force_authenticate(self.reader)

    def _comment(self, body: str = "hello", author=None) -> Comment:
        return CommentService().add(
            author=author or self.reader,
            post_id=self.post.id,
            body=body,
        )

    def test_posting_a_comment_returns_it(self):
        response = self.client.post(
            reverse("post-comments", args=[self.post.id]),
            {"body": "well said"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["body"], "well said")
        self.assertEqual(response.data["author"]["username"], "reader")
        self.assertEqual(response.data["post"], str(self.post.id))
        self.assertIsNone(response.data["parent"])
        self.assertFalse(response.data["liked"])
        self.assertTrue(response.data["can_delete"])

    def test_posting_an_empty_comment_is_rejected(self):
        response = self.client.post(
            reverse("post-comments", args=[self.post.id]),
            {"body": "  "},
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["error"]["code"], "invalid_input")

    def test_listing_returns_the_newest_comment_first(self):
        self._comment("first")
        self._comment("second")

        response = self.client.get(reverse("post-comments", args=[self.post.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["body"] for row in response.data["results"]], ["second", "first"])

    def test_listing_reports_the_viewers_own_likes(self):
        comment = self._comment()
        self.client.post(reverse("comment-like", args=[comment.id]))

        rows = self.client.get(reverse("post-comments", args=[self.post.id])).data["results"]

        self.assertTrue(rows[0]["liked"])
        self.assertEqual(rows[0]["like_count"], 1)

    def test_replying_through_the_api_nests_one_level(self):
        parent = self._comment("question")

        response = self.client.post(
            reverse("comment-replies", args=[parent.id]),
            {"body": "answer"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["parent"], str(parent.id))
        self.assertEqual(response.data["post"], str(self.post.id))

    def test_listing_replies_of_a_comment(self):
        parent = self._comment("question")
        self.client.post(reverse("comment-replies", args=[parent.id]), {"body": "answer"})

        response = self.client.get(reverse("comment-replies", args=[parent.id]))

        self.assertEqual([row["body"] for row in response.data["results"]], ["answer"])

    def test_like_and_unlike_endpoints_report_the_count(self):
        comment = self._comment()

        liked = self.client.post(reverse("comment-like", args=[comment.id]))
        self.assertEqual(liked.data, {"liked": True, "like_count": 1})

        unliked = self.client.delete(reverse("comment-like", args=[comment.id]))
        self.assertEqual(unliked.data, {"liked": False, "like_count": 0})

    def test_deleting_your_own_comment(self):
        comment = self._comment()

        response = self.client.delete(reverse("comment-detail", args=[comment.id]))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Comment.objects.count(), 0)

    def test_deleting_somebody_elses_comment_is_forbidden(self):
        comment = self._comment(author=self.author)

        response = self.client.delete(reverse("comment-detail", args=[comment.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_the_post_author_is_told_they_may_delete_a_comment(self):
        comment = self._comment()
        self.client.force_authenticate(self.author)

        rows = self.client.get(reverse("post-comments", args=[self.post.id])).data["results"]

        self.assertTrue(rows[0]["can_delete"])
        self.assertEqual(rows[0]["id"], str(comment.id))

    def test_a_bystander_is_told_they_may_not_delete_a_comment(self):
        self._comment()
        self.client.force_authenticate(make_user("bystander"))

        rows = self.client.get(reverse("post-comments", args=[self.post.id])).data["results"]

        self.assertFalse(rows[0]["can_delete"])

    def test_a_comment_on_a_missing_post_is_not_found(self):
        response = self.client.get(reverse("post-comments", args=[999]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_junk_comment_id_is_not_found(self):
        response = self.client.get(reverse("comment-replies", args=["not-an-id"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_the_post_payload_carries_the_conversation_size(self):
        self._comment()

        response = self.client.get(reverse("post-detail", args=[self.post.id]))

        self.assertEqual(response.data["comment_count"], 1)

    def test_comments_require_authentication(self):
        self.client.force_authenticate(None)

        response = self.client.get(reverse("post-comments", args=[self.post.id]))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class CommentCounterReconciliationTests(APITestCase):
    """The recount commands, which exist for writes that bypass the receivers."""

    def setUp(self):
        self.author = make_user("author")
        self.reader = make_user("reader")
        self.post = _post_service().create(author=self.author, caption="say something")
        self.comment = CommentService().add(
            author=self.reader,
            post_id=self.post.id,
            body="hello",
        )

    def test_recount_repairs_a_drifted_post_comment_count(self):
        Post.objects.filter(pk=self.post.id).update(comment_count=99)

        call_command("recount_post_stats", stdout=StringIO())

        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 1)

    def test_recount_repairs_drifted_comment_counters(self):
        CommentService().reply(author=self.author, comment_id=self.comment.id, body="answer")
        Comment.objects.filter(pk=self.comment.id).update(like_count=7, reply_count=0)

        call_command("recount_comment_stats", stdout=StringIO())

        self.comment.refresh_from_db()
        self.assertEqual(self.comment.like_count, 0)
        self.assertEqual(self.comment.reply_count, 1)
