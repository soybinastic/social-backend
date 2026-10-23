"""Rebuild denormalized follow counters from the `follows` table.

`follower_count` and `following_count` are caches maintained by signal
receivers inside the same transaction as the Follow row that triggered them, so
normal traffic cannot push them out of step. They can still drift from writes
that bypass signals -- `bulk_create`, `QuerySet.update`, a raw SQL fix, a
restored backup -- and this rebuilds them from the edges. Safe to run
repeatedly and while the app is serving traffic.
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.interactions.models import Follow


class Command(BaseCommand):
    help = "Recompute User.follower_count and User.following_count from Follows."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report drift without writing corrections.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        checked = repaired = 0

        for user in User.objects.all().iterator():
            checked += 1
            actual_followers = Follow.objects.filter(followee_id=user.id).count()
            actual_following = Follow.objects.filter(follower_id=user.id).count()

            if (
                actual_followers == user.follower_count
                and actual_following == user.following_count
            ):
                continue

            repaired += 1
            self.stdout.write(
                f"{user.username}: followers {user.follower_count} -> {actual_followers}, "
                f"following {user.following_count} -> {actual_following}"
            )
            if not dry_run:
                User.objects.filter(pk=user.id).update(
                    follower_count=actual_followers,
                    following_count=actual_following,
                )

        verb = "would repair" if dry_run else "repaired"
        self.stdout.write(
            self.style.SUCCESS(f"Checked {checked} account(s); {verb} {repaired}.")
        )
