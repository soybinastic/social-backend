"""Post use cases."""

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.exceptions import InvalidInput, PermissionDenied
from apps.media.services import MediaUploadService
from apps.posts.models import Post
from apps.posts.repositories import PostRepository


class PostService:
    def __init__(
        self,
        posts: PostRepository | None = None,
        uploads: MediaUploadService | None = None,
    ):
        self._posts = posts or PostRepository()
        self._uploads = uploads or MediaUploadService()

    def feed(self) -> QuerySet:
        return self._posts.feed()

    def by_author(self, author_id) -> QuerySet:
        return self._posts.by_author(author_id)

    def get(self, post_id) -> Post:
        return self._posts.require_by_id(post_id)

    def create(
        self,
        *,
        author: User,
        caption: str = "",
        files: list[UploadedFile] | None = None,
    ) -> Post:
        files = files or []
        caption = (caption or "").strip()
        if not caption and not files:
            raise InvalidInput("A post needs a caption or at least one attachment.")

        # Uploading has to happen before the transaction, because the rows
        # record the URLs the provider hands back.
        assets = self._uploads.upload_many(files) if files else []
        try:
            with transaction.atomic():
                return self._posts.create_with_media(
                    author=author,
                    caption=caption,
                    media=assets,
                )
        except Exception:
            # The files already reached the storage provider, which no database
            # rollback can undo, so they are removed explicitly.
            self._uploads.discard_many(assets)
            raise

    def update_caption(self, *, post_id, actor: User, caption: str) -> Post:
        post = self._posts.require_by_id(post_id)
        self._assert_author(post, actor)

        caption = (caption or "").strip()
        if not caption and not post.media.exists():
            raise InvalidInput("A post needs a caption or at least one attachment.")

        post.caption = caption
        post.save(update_fields=["caption", "updated_at"])
        return post

    def delete(self, *, post_id, actor: User) -> None:
        post = self._posts.require_by_id(post_id)
        self._assert_author(post, actor)
        assets = list(post.media.all())

        with transaction.atomic():
            # Cascades to this post's attachments and likes and detaches any
            # reshares of it. The post_delete receiver corrects `share_count`
            # on the original in the same transaction.
            self._posts.delete(post)
            # Remote files are dropped only once the delete is durable, so a
            # rollback can never leave rows pointing at deleted files.
            transaction.on_commit(lambda: self._uploads.discard_many(assets))

    @staticmethod
    def _assert_author(post: Post, actor: User) -> None:
        if post.author_id != actor.id:
            raise PermissionDenied("You can only modify your own posts.")
