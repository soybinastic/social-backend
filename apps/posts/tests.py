from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.exceptions import InvalidInput, PermissionDenied, ResourceNotFound
from apps.core.testing import (
    MediaRootTestCase,
    audio_upload,
    make_user,
    png_upload,
    video_upload,
)
from apps.interactions.models import Like
from apps.media.kinds import MediaKind
from apps.media.models import MediaAsset
from apps.media.services import MediaUploadService
from apps.media.testing import ExplodingStorage, InMemoryStorage
from apps.posts.models import Post
from apps.posts.services import PostService


class PostServiceTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.storage = InMemoryStorage()
        self.service = PostService(uploads=MediaUploadService(storage=self.storage))

    def test_creates_a_text_only_post(self):
        post = self.service.create(author=self.author, caption="  Hello world  ")
        self.assertEqual(post.caption, "Hello world")
        self.assertEqual(post.media.count(), 0)

    def test_creates_a_post_with_mixed_media(self):
        post = self.service.create(
            author=self.author,
            caption="A little of everything",
            files=[png_upload(), video_upload(), audio_upload()],
        )

        self.assertEqual(
            [asset.kind for asset in post.media.all()],
            [MediaKind.IMAGE, MediaKind.VIDEO, MediaKind.AUDIO],
        )
        self.assertEqual(len(self.storage.files), 3)

    def test_attachment_order_is_preserved(self):
        # Rows are ordered by an explicit position, not by insertion order.
        post = self.service.create(
            author=self.author,
            files=[png_upload("a.png"), png_upload("b.png"), png_upload("c.png")],
        )

        stored = Post.objects.get(pk=post.id)
        self.assertEqual(
            [asset.original_filename for asset in stored.media.all()],
            ["a.png", "b.png", "c.png"],
        )
        self.assertEqual([asset.position for asset in stored.media.all()], [0, 1, 2])

    def test_media_survives_a_round_trip_through_the_database(self):
        post = self.service.create(author=self.author, files=[png_upload("cat.png")])

        asset = Post.objects.get(pk=post.id).media.get()
        self.assertEqual(asset.original_filename, "cat.png")
        self.assertEqual(asset.kind, MediaKind.IMAGE)
        self.assertEqual(asset.provider, "memory")

    def test_rejects_a_post_with_neither_caption_nor_media(self):
        with self.assertRaises(InvalidInput):
            self.service.create(author=self.author, caption="   ")

    def test_failed_upload_leaves_no_post_and_no_orphaned_files(self):
        service = PostService(uploads=MediaUploadService(storage=ExplodingStorage(fail_on_call=2)))

        with self.assertRaises(RuntimeError):
            service.create(author=self.author, caption="nope", files=[png_upload(), png_upload()])

        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(MediaAsset.objects.count(), 0)

    def test_only_the_author_may_edit(self):
        post = self.service.create(author=self.author, caption="mine")
        with self.assertRaises(PermissionDenied):
            self.service.update_caption(post_id=post.id, actor=make_user("intruder"), caption="hi")

    def test_only_the_author_may_delete(self):
        post = self.service.create(author=self.author, caption="mine")
        with self.assertRaises(PermissionDenied):
            self.service.delete(post_id=post.id, actor=make_user("intruder"))

    def test_deleting_a_post_cascades_to_its_media_and_likes(self):
        post = self.service.create(author=self.author, caption="bye", files=[png_upload()])
        public_id = post.media.get().public_id
        Like.objects.create(user=self.author, post=post)

        # Stored files are removed by an on_commit hook, which only runs for
        # real inside this block.
        with self.captureOnCommitCallbacks(execute=True):
            self.service.delete(post_id=post.id, actor=self.author)

        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(Like.objects.count(), 0)
        self.assertEqual(MediaAsset.objects.count(), 0)
        self.assertIn(public_id, self.storage.deleted)

    def test_stored_files_are_kept_until_the_delete_commits(self):
        post = self.service.create(author=self.author, caption="bye", files=[png_upload()])

        # Without executing the callbacks the transaction never "commits", so
        # the provider must still hold the file.
        with self.captureOnCommitCallbacks(execute=False):
            self.service.delete(post_id=post.id, actor=self.author)

        self.assertEqual(self.storage.deleted, [])

    def test_editing_cannot_empty_a_text_only_post(self):
        post = self.service.create(author=self.author, caption="text only")
        with self.assertRaises(InvalidInput):
            self.service.update_caption(post_id=post.id, actor=self.author, caption="")

    def test_editing_may_empty_the_caption_of_a_post_with_media(self):
        post = self.service.create(author=self.author, caption="draft", files=[png_upload()])
        updated = self.service.update_caption(post_id=post.id, actor=self.author, caption="")
        self.assertEqual(updated.caption, "")

    def test_malformed_id_is_reported_as_not_found(self):
        # A junk path segment must not surface as a 500 from int parsing.
        with self.assertRaises(ResourceNotFound):
            self.service.get("not-a-number")


class PostApiTests(MediaRootTestCase):
    def setUp(self):
        self.user = make_user("poster")
        self.client.force_authenticate(self.user)

    def test_creates_a_post_with_an_upload_over_multipart(self):
        response = self.client.post(
            reverse("post-list-create"),
            {"caption": "my first post", "files": [png_upload()]},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["caption"], "my first post")
        self.assertEqual(len(response.data["media"]), 1)
        self.assertEqual(response.data["media"][0]["kind"], MediaKind.IMAGE)
        self.assertTrue(response.data["is_mine"])
        self.assertFalse(response.data["liked"])
        # Internal storage handles are not exposed to clients.
        self.assertNotIn("public_id", response.data["media"][0])

    def test_post_id_is_serialized_as_a_string(self):
        # Keeps the client contract stable and avoids handing JavaScript a
        # bigint it cannot represent exactly.
        response = self.client.post(reverse("post-list-create"), {"caption": "hello"})
        self.assertIsInstance(response.data["id"], str)

    def test_rejects_an_unsupported_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("post-list-create"),
            {"files": [SimpleUploadedFile("cv.pdf", b"%PDF-1.4", content_type="application/pdf")]},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["error"]["code"], "invalid_input")

    def test_feed_is_newest_first_and_paginated(self):
        for index in range(3):
            self.client.post(reverse("post-list-create"), {"caption": f"post {index}"})

        response = self.client.get(reverse("post-list-create"), {"limit": 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["caption"], "post 2")
        self.assertIsNotNone(response.data["next"])

    def test_feed_second_page_returns_the_remainder(self):
        for index in range(3):
            self.client.post(reverse("post-list-create"), {"caption": f"post {index}"})

        first = self.client.get(reverse("post-list-create"), {"limit": 2})
        second = self.client.get(first.data["next"])

        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual([row["caption"] for row in second.data["results"]], ["post 0"])

    def test_feed_costs_the_same_number_of_queries_regardless_of_page_size(self):
        """Guards against N+1 regressions in the feed queryset.

        Authors, avatars, reshared posts, and attachments are all resolved
        eagerly, so query count must not grow with the number of rows returned.
        """
        for index in range(2):
            PostService().create(author=make_user(f"early{index}"), caption=f"p{index}")
        small = self._feed_query_count()

        for index in range(8):
            author = make_user(f"later{index}")
            PostService().create(author=author, caption=f"q{index}", files=[png_upload()])
        large = self._feed_query_count()

        self.assertEqual(small, large)

    def _feed_query_count(self) -> int:
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("post-list-create"), {"limit": 50})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        return len(captured.captured_queries)

    def test_profile_feed_only_returns_that_authors_posts(self):
        other = make_user("someone_else")
        PostService().create(author=other, caption="theirs")
        self.client.post(reverse("post-list-create"), {"caption": "mine"})

        response = self.client.get(reverse("user-posts", args=["someone_else"]))

        self.assertEqual([row["caption"] for row in response.data["results"]], ["theirs"])

    def test_deleting_someone_elses_post_is_forbidden(self):
        victim_post = PostService().create(author=make_user("victim"), caption="hands off")
        response = self.client.delete(reverse("post-detail", args=[str(victim_post.id)]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_post_id_returns_not_found(self):
        response = self.client.get(reverse("post-detail", args=["987654"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_post_id_returns_not_found_rather_than_a_server_error(self):
        response = self.client.get(reverse("post-detail", args=["garbage"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_feed_requires_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get(reverse("post-list-create"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
