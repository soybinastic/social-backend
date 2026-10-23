"""Like, share and follow use cases."""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.accounts.repositories import UserRepository
from apps.core.exceptions import InvalidInput, ResourceNotFound
from apps.interactions.repositories import FollowRepository, LikeRepository
from apps.posts.models import Post
from apps.posts.repositories import PostRepository


@dataclass(frozen=True)
class InteractionState:
    """The counts a client needs to re-render a post's action bar."""

    liked: bool
    like_count: int
    share_count: int


@dataclass(frozen=True)
class FollowState:
    """What a client needs to re-render a profile's follow button.

    `follows_you` is the other half of the pair: when it is true and
    `is_following` is false, the viewer is being offered a follow back.
    """

    is_following: bool
    follows_you: bool
    follower_count: int
    following_count: int


class LikeService:
    """Likes are set, not toggled.

    An explicit like/unlike pair is idempotent, so a double-tap or a retry
    after a dropped response converges instead of flipping the state.

    Writing the Like row and bumping `Post.like_count` happen in one
    transaction, so the counter cannot drift away from the Like table.
    """

    def __init__(self, likes: LikeRepository | None = None, posts: PostRepository | None = None):
        self._likes = likes or LikeRepository()
        self._posts = posts or PostRepository()

    def like(self, *, user: User, post_id) -> InteractionState:
        post = self._posts.require_by_id(post_id)
        try:
            # The inner atomic block is required, not decorative: Postgres
            # aborts a transaction on a constraint violation, so the failing
            # INSERT needs its own savepoint for execution to continue here.
            with transaction.atomic():
                self._likes.create(user=user, post=post)
        except IntegrityError:
            # The unique constraint fired: already liked, so this is a no-op.
            pass
        return self._state(post.id, liked=True)

    def unlike(self, *, user: User, post_id) -> InteractionState:
        post = self._posts.require_by_id(post_id)
        with transaction.atomic():
            existing = self._likes.get_for(user_id=user.id, post_id=post.id)
            if existing is not None:
                self._likes.delete(existing)
        return self._state(post.id, liked=False)

    def likers_of(self, post_id) -> QuerySet:
        post = self._posts.require_by_id(post_id)
        return self._likes.likers_of(post.id)

    def _state(self, post_id, *, liked: bool) -> InteractionState:
        counters = self._posts.counters(post_id)
        return InteractionState(
            liked=liked,
            like_count=counters["like_count"],
            share_count=counters["share_count"],
        )


class ShareService:
    def __init__(self, posts: PostRepository | None = None):
        self._posts = posts or PostRepository()

    def share(self, *, user: User, post_id, caption: str = "") -> Post:
        """Reshare a post, optionally quoting it with a caption.

        Sharing a share attributes the reshare to the original post so the
        chain stays one level deep and `share_count` reflects real reach.
        """
        post = self._posts.require_by_id(post_id)
        original = post.shared_from or post

        with transaction.atomic():
            # The post_save receiver bumps `share_count` on the original in
            # this same transaction.
            return self._posts.create_with_media(
                author=user,
                caption=(caption or "").strip(),
                media=[],
                shared_from=original,
            )


class FollowService:
    """Follows are set, not toggled.

    Like `LikeService`, an explicit follow/unfollow pair is idempotent, so a
    double-tap or a retry after a dropped response converges on the state the
    caller asked for instead of flipping it.

    Following is one-directional. Two people end up mutually followed only when
    both edges exist, which is why following back is an ordinary follow rather
    than a separate operation.
    """

    def __init__(
        self,
        follows: FollowRepository | None = None,
        users: UserRepository | None = None,
    ):
        self._follows = follows or FollowRepository()
        self._users = users or UserRepository()

    def follow(self, *, user: User, username: str) -> FollowState:
        target = self._require_user(username)
        if target.id == user.id:
            raise InvalidInput("You cannot follow yourself.")

        try:
            # The inner atomic block is required, not decorative: Postgres
            # aborts a transaction on a constraint violation, so the failing
            # INSERT needs its own savepoint for execution to continue here.
            with transaction.atomic():
                self._follows.create(follower=user, followee=target)
        except IntegrityError:
            # The unique constraint fired: already following, so this is a no-op.
            pass
        return self.state_for(viewer=user, target=target)

    def unfollow(self, *, user: User, username: str) -> FollowState:
        target = self._require_user(username)
        with transaction.atomic():
            existing = self._follows.get_for(follower_id=user.id, followee_id=target.id)
            if existing is not None:
                self._follows.delete(existing)
        return self.state_for(viewer=user, target=target)

    def state_for(self, *, viewer: User, target: User) -> FollowState:
        """The viewer's relationship with one account, plus that account's counts."""
        counters = self._users.follow_counters(target.id)
        return FollowState(
            is_following=self._follows.exists(follower_id=viewer.id, followee_id=target.id),
            follows_you=self._follows.exists(follower_id=target.id, followee_id=viewer.id),
            follower_count=counters["follower_count"],
            following_count=counters["following_count"],
        )

    def relationship_context(self, *, viewer: User, users: list[User]) -> dict:
        """Resolve both directions for a batch of accounts in two queries.

        Serializers read these sets instead of querying per row; see
        `apps.accounts.serializers.ProfileSerializer`.
        """
        user_ids = [user.id for user in users]
        return {
            "following_ids": self._follows.following_ids(
                follower_id=viewer.id,
                user_ids=user_ids,
            ),
            "follower_ids": self._follows.follower_ids(
                followee_id=viewer.id,
                user_ids=user_ids,
            ),
        }

    def followers_of(self, username: str) -> QuerySet:
        return self._follows.followers_of(self._require_user(username).id)

    def following_of(self, username: str) -> QuerySet:
        return self._follows.following_of(self._require_user(username).id)

    def _require_user(self, username: str) -> User:
        user = self._users.get_by_username(username)
        if user is None:
            raise ResourceNotFound("No user with that username.")
        return user
