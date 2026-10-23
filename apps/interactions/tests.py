from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.exceptions import InvalidInput, ResourceNotFound
from apps.core.testing import make_user, png_upload
from apps.interactions.models import Follow, Like
from apps.interactions.services import FollowService, LikeService, ShareService
from apps.media.services import MediaUploadService
from apps.media.testing import InMemoryStorage
from apps.posts.models import Post
from apps.posts.services import PostService


def _post_service() -> PostService:
    return PostService(uploads=MediaUploadService(storage=InMemoryStorage()))


class LikeServiceTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.liker = make_user("liker")
        self.post = _post_service().create(author=self.author, caption="like me")
        self.service = LikeService()

    def test_liking_records_the_like_and_bumps_the_counter(self):
        state = self.service.like(user=self.liker, post_id=self.post.id)

        self.assertTrue(state.liked)
        self.assertEqual(state.like_count, 1)
        self.assertEqual(Like.objects.count(), 1)

    def test_liking_twice_is_idempotent(self):
        self.service.like(user=self.liker, post_id=self.post.id)
        state = self.service.like(user=self.liker, post_id=self.post.id)

        # The unique constraint absorbs the duplicate instead of double counting.
        self.assertEqual(state.like_count, 1)
        self.assertEqual(Like.objects.count(), 1)

    def test_unliking_removes_the_like_and_decrements(self):
        self.service.like(user=self.liker, post_id=self.post.id)
        state = self.service.unlike(user=self.liker, post_id=self.post.id)

        self.assertFalse(state.liked)
        self.assertEqual(state.like_count, 0)
        self.assertEqual(Like.objects.count(), 0)

    def test_unliking_a_post_that_was_never_liked_is_a_no_op(self):
        state = self.service.unlike(user=self.liker, post_id=self.post.id)
        self.assertEqual(state.like_count, 0)

    def test_counter_never_goes_negative(self):
        # Two unlikes against a zero counter must not persist -1 into a
        # PositiveIntegerField.
        self.service.unlike(user=self.liker, post_id=self.post.id)
        self.service.unlike(user=self.liker, post_id=self.post.id)

        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 0)

    def test_counts_likes_from_several_users(self):
        for name in ("one", "two", "three"):
            self.service.like(user=make_user(name), post_id=self.post.id)

        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 3)

    def test_unique_constraint_is_enforced_by_the_database(self):
        from django.db import IntegrityError, transaction

        Like.objects.create(user=self.liker, post=self.post)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Like.objects.create(user=self.liker, post=self.post)

    def test_the_like_and_its_counter_commit_together(self):
        """The row and the denormalized count are one atomic unit.

        If the surrounding work fails, neither the Like nor the incremented
        counter may survive, which is what keeps the cache truthful.
        """
        from django.db import transaction

        with self.assertRaises(RuntimeError), transaction.atomic():
            self.service.like(user=self.liker, post_id=self.post.id)
            raise RuntimeError("caller failed after liking")

        self.post.refresh_from_db()
        self.assertEqual(Like.objects.count(), 0)
        self.assertEqual(self.post.like_count, 0)

    def test_liking_an_unknown_post_is_not_found(self):
        with self.assertRaises(ResourceNotFound):
            self.service.like(user=self.liker, post_id="64b7f9c2e1a2b3c4d5e6f7a8")


class ShareServiceTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.sharer = make_user("sharer")
        self.post = _post_service().create(author=self.author, caption="original")
        self.service = ShareService()

    def test_sharing_creates_a_post_pointing_at_the_original(self):
        share = self.service.share(user=self.sharer, post_id=self.post.id, caption="worth a read")

        self.assertEqual(share.shared_from_id, self.post.id)
        self.assertEqual(share.caption, "worth a read")
        self.assertTrue(share.is_share)

        self.post.refresh_from_db()
        self.assertEqual(self.post.share_count, 1)

    def test_sharing_a_share_attributes_it_to_the_original(self):
        first = self.service.share(user=self.sharer, post_id=self.post.id)
        second = self.service.share(user=make_user("third"), post_id=first.id)

        # Chains stay one level deep so share_count reflects real reach.
        self.assertEqual(second.shared_from_id, self.post.id)
        self.post.refresh_from_db()
        self.assertEqual(self.post.share_count, 2)

    def test_deleting_a_share_decrements_the_original(self):
        share = self.service.share(user=self.sharer, post_id=self.post.id)
        _post_service().delete(post_id=share.id, actor=self.sharer)

        self.post.refresh_from_db()
        self.assertEqual(self.post.share_count, 0)

    def test_deleting_the_original_detaches_its_shares(self):
        share = self.service.share(user=self.sharer, post_id=self.post.id)
        _post_service().delete(post_id=self.post.id, actor=self.author)

        share.refresh_from_db()
        self.assertIsNone(share.shared_from_id)


class InteractionApiTests(APITestCase):
    def setUp(self):
        self.author = make_user("author")
        self.viewer = make_user("viewer")
        self.post = _post_service().create(
            author=self.author,
            caption="hello",
            files=[png_upload()],
        )
        self.client.force_authenticate(self.viewer)

    def test_like_endpoint_returns_fresh_counts(self):
        response = self.client.post(reverse("post-like", args=[str(self.post.id)]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"liked": True, "like_count": 1, "share_count": 0})

    def test_unlike_endpoint_returns_fresh_counts(self):
        self.client.post(reverse("post-like", args=[str(self.post.id)]))
        response = self.client.delete(reverse("post-like", args=[str(self.post.id)]))

        self.assertEqual(response.data, {"liked": False, "like_count": 0, "share_count": 0})

    def test_feed_reports_the_viewers_own_like_state(self):
        self.client.post(reverse("post-like", args=[str(self.post.id)]))

        response = self.client.get(reverse("post-list-create"))
        row = response.data["results"][0]

        self.assertTrue(row["liked"])
        self.assertFalse(row["is_mine"])

    def test_feed_does_not_leak_another_users_like_state(self):
        LikeService().like(user=self.author, post_id=self.post.id)

        response = self.client.get(reverse("post-list-create"))
        row = response.data["results"][0]

        self.assertEqual(row["like_count"], 1)
        self.assertFalse(row["liked"])

    def test_likers_endpoint_lists_the_users_who_liked(self):
        self.client.post(reverse("post-like", args=[str(self.post.id)]))

        response = self.client.get(reverse("post-likers", args=[str(self.post.id)]))

        self.assertEqual([row["username"] for row in response.data["results"]], ["viewer"])

    def test_share_endpoint_returns_the_new_post_with_the_original_embedded(self):
        response = self.client.post(
            reverse("post-share", args=[str(self.post.id)]),
            {"caption": "look at this"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["caption"], "look at this")
        self.assertEqual(response.data["shared_from"]["id"], str(self.post.id))
        self.assertEqual(response.data["shared_from"]["author"]["username"], "author")
        self.assertEqual(len(response.data["shared_from"]["media"]), 1)

    def test_shared_post_appears_in_the_feed(self):
        self.client.post(reverse("post-share", args=[str(self.post.id)]))

        response = self.client.get(reverse("post-list-create"))

        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["shared_from"]["id"], str(self.post.id))
        self.assertEqual(Post.objects.count(), 2)


class FollowServiceTests(APITestCase):
    def setUp(self):
        self.viewer = make_user("viewer")
        self.target = make_user("target")
        self.service = FollowService()

    def test_following_records_the_edge_and_bumps_both_counters(self):
        state = self.service.follow(user=self.viewer, username="target")

        self.assertTrue(state.is_following)
        self.assertFalse(state.follows_you)
        self.assertEqual(state.follower_count, 1)
        self.assertEqual(Follow.objects.count(), 1)

        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.following_count, 1)

    def test_following_twice_is_idempotent(self):
        self.service.follow(user=self.viewer, username="target")
        state = self.service.follow(user=self.viewer, username="target")

        # The unique constraint absorbs the duplicate instead of double counting.
        self.assertEqual(state.follower_count, 1)
        self.assertEqual(Follow.objects.count(), 1)

    def test_unfollowing_removes_the_edge_and_decrements(self):
        self.service.follow(user=self.viewer, username="target")
        state = self.service.unfollow(user=self.viewer, username="target")

        self.assertFalse(state.is_following)
        self.assertEqual(state.follower_count, 0)
        self.assertEqual(Follow.objects.count(), 0)

        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.following_count, 0)

    def test_unfollowing_someone_never_followed_is_a_no_op(self):
        state = self.service.unfollow(user=self.viewer, username="target")
        self.assertFalse(state.is_following)
        self.assertEqual(state.follower_count, 0)

    def test_counters_never_go_negative(self):
        self.service.unfollow(user=self.viewer, username="target")
        self.service.unfollow(user=self.viewer, username="target")

        self.target.refresh_from_db()
        self.assertEqual(self.target.follower_count, 0)

    def test_following_back_makes_the_pair_mutual(self):
        self.service.follow(user=self.target, username="viewer")
        state = self.service.follow(user=self.viewer, username="target")

        # Both directions exist, and each is its own row.
        self.assertTrue(state.is_following)
        self.assertTrue(state.follows_you)
        self.assertEqual(Follow.objects.count(), 2)

    def test_a_one_sided_follow_is_reported_as_follows_you(self):
        self.service.follow(user=self.target, username="viewer")
        state = self.service.state_for(viewer=self.viewer, target=self.target)

        # What the client turns into a "Follow back" button.
        self.assertFalse(state.is_following)
        self.assertTrue(state.follows_you)

    def test_following_yourself_is_rejected(self):
        with self.assertRaises(InvalidInput):
            self.service.follow(user=self.viewer, username="viewer")
        self.assertEqual(Follow.objects.count(), 0)

    def test_self_follow_is_refused_by_the_database(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=self.viewer, followee=self.viewer)

    def test_unique_constraint_is_enforced_by_the_database(self):
        from django.db import IntegrityError, transaction

        Follow.objects.create(follower=self.viewer, followee=self.target)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=self.viewer, followee=self.target)

    def test_the_edge_and_its_counters_commit_together(self):
        from django.db import transaction

        with self.assertRaises(RuntimeError), transaction.atomic():
            self.service.follow(user=self.viewer, username="target")
            raise RuntimeError("caller failed after following")

        self.target.refresh_from_db()
        self.assertEqual(Follow.objects.count(), 0)
        self.assertEqual(self.target.follower_count, 0)

    def test_deleting_an_account_takes_its_edges_and_counters_with_it(self):
        self.service.follow(user=self.viewer, username="target")
        self.viewer.delete()

        self.target.refresh_from_db()
        self.assertEqual(Follow.objects.count(), 0)
        self.assertEqual(self.target.follower_count, 0)

    def test_following_an_unknown_account_is_not_found(self):
        with self.assertRaises(ResourceNotFound):
            self.service.follow(user=self.viewer, username="nobody")


class FollowApiTests(APITestCase):
    def setUp(self):
        self.viewer = make_user("viewer")
        self.target = make_user("target")
        self.client.force_authenticate(self.viewer)

    def test_follow_endpoint_returns_fresh_state(self):
        response = self.client.post(reverse("user-follow", args=["target"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "is_following": True,
                "follows_you": False,
                "follower_count": 1,
                "following_count": 0,
            },
        )

    def test_unfollow_endpoint_returns_fresh_state(self):
        self.client.post(reverse("user-follow", args=["target"]))
        response = self.client.delete(reverse("user-follow", args=["target"]))

        self.assertFalse(response.data["is_following"])
        self.assertEqual(response.data["follower_count"], 0)

    def test_following_yourself_is_unprocessable(self):
        response = self.client.post(reverse("user-follow", args=["viewer"]))

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["error"]["code"], "invalid_input")

    def test_profile_reports_the_viewers_side_of_the_relationship(self):
        FollowService().follow(user=self.target, username="viewer")

        response = self.client.get(reverse("user-detail", args=["target"]))

        self.assertFalse(response.data["is_following"])
        self.assertTrue(response.data["follows_you"])
        self.assertEqual(response.data["following_count"], 1)

    def test_followers_endpoint_lists_accounts_that_follow_the_user(self):
        FollowService().follow(user=self.viewer, username="target")
        FollowService().follow(user=make_user("other"), username="target")

        response = self.client.get(reverse("user-followers", args=["target"]))
        rows = response.data["results"]

        # Newest follower first, which is the cursor's ordering on the edge.
        self.assertEqual([row["username"] for row in rows], ["other", "viewer"])

    def test_following_endpoint_lists_accounts_the_user_follows(self):
        FollowService().follow(user=self.viewer, username="target")

        response = self.client.get(reverse("user-following", args=["viewer"]))

        self.assertEqual([row["username"] for row in response.data["results"]], ["target"])

    def test_list_rows_carry_the_viewers_relationship_with_each_account(self):
        FollowService().follow(user=self.viewer, username="target")
        mutual = make_user("mutual")
        FollowService().follow(user=mutual, username="target")
        FollowService().follow(user=mutual, username="viewer")

        response = self.client.get(reverse("user-followers", args=["target"]))
        rows = {row["username"]: row for row in response.data["results"]}

        # `mutual` follows the viewer but is not followed back: a follow back.
        self.assertFalse(rows["mutual"]["is_following"])
        self.assertTrue(rows["mutual"]["follows_you"])
        # The viewer's own row needs no relationship flags set.
        self.assertFalse(rows["viewer"]["is_following"])
        self.assertFalse(rows["viewer"]["follows_you"])

    def test_followers_of_an_unknown_account_is_not_found(self):
        response = self.client.get(reverse("user-followers", args=["nobody"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_follow_requires_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.post(reverse("user-follow", args=["target"]))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
