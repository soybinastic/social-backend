"""Rebuild denormalized comment counters from the tables they summarize.

`like_count` and `reply_count` are caches maintained by signal receivers inside
the same transaction as the write that triggered them, so normal traffic cannot
push them out of step. They can still drift from writes that bypass signals --
`bulk_create`, `QuerySet.update`, a raw SQL fix, a restored backup -- and this
rebuilds them from the source tables. Safe to run repeatedly and while the app
is serving traffic.
"""

from django.core.management.base import BaseCommand

from apps.comments.models import Comment, CommentLike


class Command(BaseCommand):
    help = "Recompute Comment.like_count and Comment.reply_count from their source tables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report drift without writing corrections.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        checked = repaired = 0

        for comment in Comment.objects.all().iterator():
            checked += 1
            actual_likes = CommentLike.objects.filter(comment_id=comment.id).count()
            actual_replies = Comment.objects.filter(parent_id=comment.id).count()

            if actual_likes == comment.like_count and actual_replies == comment.reply_count:
                continue

            repaired += 1
            self.stdout.write(
                f"{comment.id}: likes {comment.like_count} -> {actual_likes}, "
                f"replies {comment.reply_count} -> {actual_replies}"
            )
            if not dry_run:
                Comment.objects.filter(pk=comment.id).update(
                    like_count=actual_likes,
                    reply_count=actual_replies,
                )

        verb = "would repair" if dry_run else "repaired"
        self.stdout.write(
            self.style.SUCCESS(f"Checked {checked} comment(s); {verb} {repaired}.")
        )
