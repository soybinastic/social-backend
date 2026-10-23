"""Rebuild denormalized post counters from the tables they summarize.

`like_count`, `share_count` and `comment_count` are caches maintained by receivers inside
the same transaction as the write that triggered them, so normal traffic cannot
push them out of step. They can still drift from writes that bypass signals --
`bulk_create`, `QuerySet.update`, a raw SQL fix, a restored backup -- and this
rebuilds them from the source tables. Safe to run repeatedly and while the app
is serving traffic.
"""

from django.core.management.base import BaseCommand

from apps.comments.models import Comment
from apps.interactions.models import Like
from apps.posts.models import Post


class Command(BaseCommand):
    help = "Recompute Post.like_count, share_count and comment_count from their source tables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report drift without writing corrections.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        checked = repaired = 0

        for post in Post.objects.all().iterator():
            checked += 1
            actual_likes = Like.objects.filter(post_id=post.id).count()
            actual_shares = Post.objects.filter(shared_from_id=post.id).count()
            # Replies included, which is what `comment_count` means.
            actual_comments = Comment.objects.filter(post_id=post.id).count()

            if (
                actual_likes == post.like_count
                and actual_shares == post.share_count
                and actual_comments == post.comment_count
            ):
                continue

            repaired += 1
            self.stdout.write(
                f"{post.id}: likes {post.like_count} -> {actual_likes}, "
                f"shares {post.share_count} -> {actual_shares}, "
                f"comments {post.comment_count} -> {actual_comments}"
            )
            if not dry_run:
                Post.objects.filter(pk=post.id).update(
                    like_count=actual_likes,
                    share_count=actual_shares,
                    comment_count=actual_comments,
                )

        verb = "would repair" if dry_run else "repaired"
        self.stdout.write(
            self.style.SUCCESS(f"Checked {checked} post(s); {verb} {repaired}.")
        )
