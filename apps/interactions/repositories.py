from django.db.models import QuerySet

from apps.core.repositories import BaseRepository
from apps.interactions.models import Follow, Like


class LikeRepository(BaseRepository[Like]):
    model = Like

    def get_for(self, *, user_id, post_id) -> Like | None:
        return self.get_queryset().filter(user_id=user_id, post_id=post_id).first()

    def liked_post_ids(self, *, user_id, post_ids: list) -> set:
        """Resolve the viewer's like state for a whole feed page in one query.

        Checking each post individually would be a query per row, which is the
        classic N+1 that makes feeds slow.
        """
        if not post_ids:
            return set()
        rows = self.get_queryset().filter(user_id=user_id, post_id__in=post_ids)
        return set(rows.values_list("post_id", flat=True))

    def likers_of(self, post_id) -> QuerySet:
        return self.get_queryset().filter(post_id=post_id).select_related("user")


class FollowRepository(BaseRepository[Follow]):
    model = Follow

    def get_for(self, *, follower_id, followee_id) -> Follow | None:
        return (
            self.get_queryset()
            .filter(follower_id=follower_id, followee_id=followee_id)
            .first()
        )

    def following_ids(self, *, follower_id, user_ids: list) -> set:
        """Which of `user_ids` the follower follows, in one query.

        Asking per row is the N+1 that makes a page of accounts slow.
        """
        if not user_ids:
            return set()
        rows = self.get_queryset().filter(follower_id=follower_id, followee_id__in=user_ids)
        return set(rows.values_list("followee_id", flat=True))

    def follower_ids(self, *, followee_id, user_ids: list) -> set:
        """Mirror of `following_ids` for the other direction, which is what
        tells a client to offer "Follow back" instead of "Follow"."""
        if not user_ids:
            return set()
        rows = self.get_queryset().filter(followee_id=followee_id, follower_id__in=user_ids)
        return set(rows.values_list("follower_id", flat=True))

    def followers_of(self, user_id) -> QuerySet:
        return (
            self.get_queryset()
            .filter(followee_id=user_id)
            .select_related("follower", "follower__avatar")
        )

    def following_of(self, user_id) -> QuerySet:
        return (
            self.get_queryset()
            .filter(follower_id=user_id)
            .select_related("followee", "followee__avatar")
        )
