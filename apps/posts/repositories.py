from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.repositories import BaseRepository
from apps.media.models import MediaAsset
from apps.posts.models import Post


class PostRepository(BaseRepository[Post]):
    model = Post

    def get_queryset(self) -> QuerySet:
        # Every row renders an author header with an avatar and may render the
        # reshared post, so all of it is resolved up front. Without this a feed
        # page costs a query per post; with it the page is a fixed few queries.
        return (
            super()
            .get_queryset()
            .select_related(
                "author",
                "author__avatar",
                "shared_from",
                "shared_from__author",
                "shared_from__author__avatar",
            )
            .prefetch_related("media", "shared_from__media")
        )

    def feed(self) -> QuerySet:
        return self.get_queryset()

    def by_author(self, author_id) -> QuerySet:
        return self.get_queryset().filter(author_id=author_id)

    def create_with_media(
        self,
        *,
        author: User,
        caption: str,
        media: list[MediaAsset],
        shared_from: Post | None = None,
    ) -> Post:
        """Insert a post and its attachments.

        Callers must wrap this in a transaction so a post is never left with a
        partial set of attachments.
        """
        post = self.model._default_manager.create(
            author=author,
            caption=caption,
            shared_from=shared_from,
        )
        if media:
            for position, asset in enumerate(media):
                asset.post = post
                asset.position = position
            # One statement for every attachment rather than one apiece.
            MediaAsset.objects.bulk_create(media)
        return post

    def counters(self, post_id) -> dict:
        return super().counters(post_id, "like_count", "share_count", "comment_count")
