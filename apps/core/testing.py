"""Shared fixtures for the test suite."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User


class MediaRootTestCase(APITestCase):
    """Base class for tests that exercise endpoints performing real uploads.

    Requests made through the API use the storage backend named in settings, so
    writes are redirected to a scratch directory that is removed afterwards.
    """

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix="social-media-tests-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


def make_user(username: str = "alice", **overrides) -> User:
    defaults = {
        "email": f"{username}@example.com",
        "username": username,
        "password": "sup3r-secret-passphrase",
    }
    defaults.update(overrides)
    return User.objects.create_user(**defaults)


def png_upload(name: str = "picture.png", size: tuple[int, int] = (24, 16)) -> SimpleUploadedFile:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(120, 80, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def audio_upload(name: str = "sound.mp3") -> SimpleUploadedFile:
    # Content is irrelevant: detection keys off MIME type and extension.
    return SimpleUploadedFile(name, b"ID3\x03\x00\x00\x00fake-audio", content_type="audio/mpeg")


def video_upload(name: str = "clip.mp4") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"\x00\x00\x00\x18ftypmp42", content_type="video/mp4")
