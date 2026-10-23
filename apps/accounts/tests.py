from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.accounts.repositories import UserRepository
from apps.accounts.services import AuthService, InvalidCredentials, ProfileService
from apps.core.exceptions import Conflict
from apps.core.testing import make_user, png_upload
from apps.media.models import MediaAsset
from apps.media.services import MediaUploadService
from apps.media.testing import InMemoryStorage


class RegistrationTests(APITestCase):
    url = reverse("register")

    def test_registers_and_returns_a_usable_session(self):
        response = self.client.post(
            self.url,
            {
                "email": "Alice@Example.com",
                "username": "Alice",
                "password": "sup3r-secret-passphrase",
                "display_name": "Alice A.",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["username"], "alice")
        self.assertTrue(response.data["access_token"])
        self.assertTrue(response.data["refresh_token"])
        # Email and username are normalized so sign-in is case-insensitive.
        self.assertTrue(User.objects.filter(email="alice@example.com").exists())

    def test_rejects_duplicate_email(self):
        make_user("bob")
        response = self.client.post(
            self.url,
            {"email": "bob@example.com", "username": "bobby", "password": "sup3r-secret-pass"},
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "conflict")

    def test_rejects_duplicate_username(self):
        make_user("carol")
        response = self.client.post(
            self.url,
            {"email": "other@example.com", "username": "carol", "password": "sup3r-secret-pass"},
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_rejects_weak_password(self):
        response = self.client.post(
            self.url,
            {"email": "dan@example.com", "username": "dan", "password": "password"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data["error"]["details"])

    def test_rejects_malformed_username(self):
        response = self.client.post(
            self.url,
            {"email": "eve@example.com", "username": "Eve!!", "password": "sup3r-secret-pass"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(APITestCase):
    def setUp(self):
        self.user = make_user("frank")

    def test_logs_in_with_correct_credentials(self):
        response = self.client.post(
            reverse("login"),
            {"email": "frank@example.com", "password": "sup3r-secret-passphrase"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "frank")

    def test_rejects_wrong_password(self):
        response = self.client.post(
            reverse("login"),
            {"email": "frank@example.com", "password": "not-the-password"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_email_is_indistinguishable_from_wrong_password(self):
        unknown = self.client.post(
            reverse("login"), {"email": "nobody@example.com", "password": "whatever-long-pass"}
        )
        wrong = self.client.post(
            reverse("login"), {"email": "frank@example.com", "password": "whatever-long-pass"}
        )
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(unknown.data["error"]["message"], wrong.data["error"]["message"])

    def test_deactivated_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(InvalidCredentials):
            AuthService().login(email="frank@example.com", password="sup3r-secret-passphrase")


class AuthenticatedAccessTests(APITestCase):
    def setUp(self):
        self.session = AuthService().register(
            email="grace@example.com",
            username="grace",
            password="sup3r-secret-passphrase",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.session.access_token}")

    def test_jwt_round_trips_the_primary_key(self):
        # The id is serialized as a string while the column is an integer, so
        # this proves the claim survives the round trip and still resolves to
        # the right user.
        response = self.client.get(reverse("current-user"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "grace")
        self.assertEqual(response.data["id"], str(self.session.user.id))

    def test_rejects_request_without_a_token(self):
        self.client.credentials()
        response = self.client.get(reverse("current-user"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token_issues_a_new_access_token(self):
        response = self.client.post(
            reverse("token-refresh"), {"refresh": self.session.refresh_token}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["access"])

    def test_updates_editable_profile_fields(self):
        response = self.client.patch(
            reverse("current-user"),
            {"display_name": "Grace H.", "bio": "Compiler enthusiast."},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["display_name"], "Grace H.")
        self.assertEqual(response.data["bio"], "Compiler enthusiast.")

    def test_fetches_another_users_public_profile(self):
        make_user("heidi")
        response = self.client.get(reverse("user-detail", args=["heidi"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "heidi")

    def test_unknown_username_returns_not_found(self):
        response = self.client.get(reverse("user-detail", args=["nobody"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AvatarTests(APITestCase):
    def setUp(self):
        self.user = make_user("ivan")
        self.storage = InMemoryStorage()
        self.service = ProfileService(uploads=MediaUploadService(storage=self.storage))

    def test_setting_a_new_avatar_replaces_the_old_row_and_file(self):
        self.service.set_avatar(self.user, png_upload("first.png"))
        first_public_id = self.user.avatar.public_id

        # Files are removed by an on_commit hook, which needs this block to run.
        with self.captureOnCommitCallbacks(execute=True):
            self.service.set_avatar(self.user, png_upload("second.png"))

        self.assertEqual(self.user.avatar.original_filename, "second.png")
        self.assertIn(first_public_id, self.storage.deleted)
        # Exactly one row survives, so replacing an avatar cannot accumulate rows.
        self.assertEqual(MediaAsset.objects.count(), 1)

    def test_clearing_an_avatar_removes_the_row_and_the_file(self):
        self.service.set_avatar(self.user, png_upload())
        public_id = self.user.avatar.public_id

        with self.captureOnCommitCallbacks(execute=True):
            self.service.clear_avatar(self.user)

        self.user.refresh_from_db()
        self.assertIsNone(self.user.avatar)
        self.assertEqual(MediaAsset.objects.count(), 0)
        self.assertIn(public_id, self.storage.deleted)

    def test_clearing_when_there_is_no_avatar_is_a_no_op(self):
        self.service.clear_avatar(self.user)
        self.assertEqual(self.storage.deleted, [])

    def test_deleting_an_avatar_row_does_not_delete_the_account(self):
        # The relation is SET_NULL, so losing an image must not lose the user.
        self.service.set_avatar(self.user, png_upload())
        self.user.avatar.delete()

        self.user.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertIsNone(self.user.avatar)


class RegistrationRaceTests(APITestCase):
    """The unique indexes, not the pre-checks, are the real guarantee."""

    def test_losing_a_concurrent_signup_reports_a_conflict(self):
        make_user("jules", email="jules@example.com")

        users = UserRepository()
        # Simulates the window where both requests see the email as free.
        users.email_taken = lambda email: False
        users.username_taken = lambda username: False

        with self.assertRaises(Conflict):
            AuthService(users=users).register(
                email="jules@example.com",
                username="jules2",
                password="sup3r-secret-passphrase",
            )
