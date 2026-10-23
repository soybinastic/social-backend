"""Comment, reply and comment-like use cases."""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.comments.models import Comment
from apps.comments.repositories import CommentLikeRepository, CommentRepository
from apps.core.exceptions import InvalidInput, PermissionDenied
from apps.posts.repositories import PostRepository

MAX_COMMENT_LENGTH = 1000


@dataclass(frozen=True)
class CommentState:
    """What a client needs to re-render one comment's like button."""

    liked: bool
    like_count: int


class CommentService:
    """Comments, the replies under them, and the likes on both.

    A comment is written against a post, a reply against a comment; there is no
    single "create" taking an optional parent. Deriving the post from the parent
    is what makes a reply on somebody else's post impossible to ask for, rather
    than something every caller has to be checked for.
    """

    def __init__(
        self,
        comments: CommentRepository | None = None,
        likes: CommentLikeRepository | None = None,
        posts: PostRepository | None = None,
    ):
        self._comments = comments or CommentRepository()
        self._likes = likes or CommentLikeRepository()
        self._posts = posts or PostRepository()

    def on_post(self, post_id) -> QuerySet:
        """The top-level thread under a post, newest first."""
        post = self._posts.require_by_id(post_id)
        return self._comments.top_level_of(post.id)

    def replies_to(self, comment_id) -> QuerySet:
        comment = self._comments.require_by_id(comment_id)
        return self._comments.replies_to(comment.id)

    def get(self, comment_id) -> Comment:
        return self._comments.require_by_id(comment_id)

    def add(self, *, author: User, post_id, body: str) -> Comment:
        post = self._posts.require_by_id(post_id)
        with transaction.atomic():
            # The post_save receivers bump `Post.comment_count` and write the
            # notification in this same transaction.
            return self._comments.create(
                post=post,
                author=author,
                body=self._require_body(body),
            )

    def reply(self, *, author: User, comment_id, body: str) -> Comment:
        """Answer a comment, flattening a reply to a reply onto its parent.

        Threads stay two levels deep, so answering an answer joins the same
        conversation instead of starting a deeper one.
        """
        parent = self._comments.require_by_id(comment_id)
        with transaction.atomic():
            return self._comments.create(
                post_id=parent.post_id,
                author=author,
                body=self._require_body(body),
                parent_id=parent.parent_id or parent.id,
            )

    def like(self, *, user: User, comment_id) -> CommentState:
        comment = self._comments.require_by_id(comment_id)
        try:
            # The inner atomic block is required, not decorative: Postgres
            # aborts a transaction on a constraint violation, so the failing
            # INSERT needs its own savepoint for execution to continue here.
            with transaction.atomic():
                self._likes.create(user=user, comment=comment)
        except IntegrityError:
            # The unique constraint fired: already liked, so this is a no-op.
            pass
        return self._state(comment.id, liked=True)

    def unlike(self, *, user: User, comment_id) -> CommentState:
        comment = self._comments.require_by_id(comment_id)
        with transaction.atomic():
            existing = self._likes.get_for(user_id=user.id, comment_id=comment.id)
            if existing is not None:
                self._likes.delete(existing)
        return self._state(comment.id, liked=False)

    def delete(self, *, comment_id, actor: User) -> None:
        """Withdraw a comment, or remove one from under your own post.

        Both are the same operation: a post's author moderates their own thread,
        which is the only reason anyone but the writer may delete.
        """
        comment = self._comments.require_by_id(comment_id)
        if actor.id not in (comment.author_id, comment.post.author_id):
            raise PermissionDenied("You can only delete your own comments.")

        with transaction.atomic():
            # Cascades to this comment's replies and to every like on them. Each
            # deleted row fires its own receiver, so the counters it contributed
            # to come down with it.
            self._comments.delete(comment)

    def liked_ids(self, *, user: User, comments: list[Comment]) -> set:
        """The viewer's like state for a page of comments, in one query."""
        return self._likes.liked_comment_ids(
            user_id=user.id,
            comment_ids=[comment.id for comment in comments],
        )

    def _state(self, comment_id, *, liked: bool) -> CommentState:
        counters = self._comments.counters(comment_id)
        return CommentState(liked=liked, like_count=counters["like_count"])

    @staticmethod
    def _require_body(body: str) -> str:
        body = (body or "").strip()
        if not body:
            raise InvalidInput("A comment needs something to say.")
        if len(body) > MAX_COMMENT_LENGTH:
            raise InvalidInput(f"A comment is limited to {MAX_COMMENT_LENGTH} characters.")
        return body
