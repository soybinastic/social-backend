from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, username: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("Users must have an email address.")
        if not username:
            raise ValueError("Users must have a username.")

        user = self.model(
            email=self.normalize_email(email).lower(),
            username=username.lower(),
            **extra,
        )
        user.set_password(password)
        # Field-level validation only. Uniqueness is left to the database's
        # indexes, which avoids a redundant SELECT and means a duplicate always
        # surfaces as IntegrityError rather than sometimes as ValidationError.
        user.full_clean(exclude=["password"], validate_unique=False)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, username: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superusers must have is_staff and is_superuser set.")
        return self.create_user(email, username, password, **extra)
