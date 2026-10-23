from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.accounts.managers import UserManager

username_validator = RegexValidator(
    regex=r"^[a-z0-9_.]{3,30}$",
    message="Username must be 3-30 characters using lowercase letters, numbers, '_' or '.'.",
)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=30, unique=True, validators=[username_validator])
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.TextField(max_length=280, blank=True)
    # SET_NULL rather than CASCADE: deleting an image must never delete the
    # account that displays it.
    avatar = models.OneToOneField(
        "media.MediaAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # Denormalized so a profile header never counts rows. Maintained by the
    # receivers in apps/interactions/signals.py, inside the same transaction as
    # the Follow row that caused the change.
    follower_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.username

    @property
    def name(self) -> str:
        return self.display_name or self.username
