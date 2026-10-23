from django.db.models import QuerySet

from apps.comments.models import Comment, CommentLike
from apps.core.repositories import BaseRepository


class CommentRepository(BaseRepository[Comment]):
    model = Comment

    def get_queryset(self) -> QuerySet:
        # Every row renders its author with an avatar, and `can_delete` needs the
        # post's author, so both are resolved up front. Without this a thread
        # page costs a query per comment.
        return (
            super()
            .get_queryset()
            .select_related("author", "author__avatar", "post")
        )

    def top_level_of(self, post_id) -> QuerySet:
        return self.get_queryset().filter(post_id=post_id, parent__isnull=True)

    def replies_to(self, comment_id) -> QuerySet:
        return self.get_queryset().filter(parent_id=comment_id)

    def counters(self, comment_id) -> dict:
        return super().counters(comment_id, "like_count", "reply_count")


class CommentLikeRepository(BaseRepository[CommentLike]):
    model = CommentLike

    def get_for(self, *, user_id, comment_id) -> CommentLike | None:
        return self.get_queryset().filter(user_id=user_id, comment_id=comment_id).first()

    def liked_comment_ids(self, *, user_id, comment_ids: list) -> set:
        """Resolve the viewer's like state for a whole page in one query.

        Checking each comment individually would be a query per row, which is the
        classic N+1 that makes a thread slow.
        """
        if not comment_ids:
            return set()
        rows = self.get_queryset().filter(user_id=user_id, comment_id__in=comment_ids)
        return set(rows.values_list("comment_id", flat=True))
