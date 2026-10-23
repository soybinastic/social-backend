from apps.accounts.models import User
from apps.core.repositories import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        return self.get_queryset().filter(email=email.lower()).first()

    def get_by_username(self, username: str) -> User | None:
        return self.get_queryset().filter(username=username.lower()).first()

    def follow_counters(self, user_id) -> dict:
        return self.counters(user_id, "follower_count", "following_count")

    def email_taken(self, email: str) -> bool:
        return self.exists(email=email.lower())

    def username_taken(self, username: str) -> bool:
        return self.exists(username=username.lower())
