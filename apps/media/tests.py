import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from apps.core.exceptions import InvalidInput
from apps.core.testing import audio_upload, png_upload, video_upload
from apps.media.kinds import MB, MediaKind, registry
from apps.media.services import MediaUploadService
from apps.media.storage.local import LocalFileSystemStorage
from apps.media.testing import ExplodingStorage, InMemoryStorage


class MediaKindDetectionTests(SimpleTestCase):
    def test_detects_each_supported_kind(self):
        cases = [
            (png_upload(), MediaKind.IMAGE),
            (video_upload(), MediaKind.VIDEO),
            (audio_upload(), MediaKind.AUDIO),
        ]
        for upload, expected in cases:
            with self.subTest(kind=expected):
                spec = registry.detect(filename=upload.name, content_type=upload.content_type)
                self.assertEqual(spec.kind, expected)

    def test_falls_back_to_extension_when_mime_type_is_generic(self):
        # Browsers often send application/octet-stream for audio picked from disk.
        spec = registry.detect(filename="track.flac", content_type="application/octet-stream")
        self.assertEqual(spec.kind, MediaKind.AUDIO)

    def test_rejects_unsupported_type(self):
        with self.assertRaises(InvalidInput):
            registry.detect(filename="resume.pdf", content_type="application/pdf")

    def test_rejects_file_above_the_kind_limit(self):
        spec = registry.get(MediaKind.IMAGE)
        with self.assertRaises(InvalidInput):
            registry.validate_size(spec, spec.max_bytes + 1)

    def test_rejects_empty_file(self):
        with self.assertRaises(InvalidInput):
            registry.validate_size(registry.get(MediaKind.IMAGE), 0)

    def test_image_limit_is_ten_megabytes(self):
        self.assertEqual(registry.get(MediaKind.IMAGE).max_bytes, 10 * MB)


class MediaUploadServiceTests(SimpleTestCase):
    def test_upload_returns_asset_describing_stored_file(self):
        storage = InMemoryStorage()
        service = MediaUploadService(storage=storage, folder="tests")

        asset = service.upload(png_upload("avatar.png"))

        self.assertEqual(asset.kind, MediaKind.IMAGE)
        self.assertEqual(asset.provider, "memory")
        self.assertEqual(asset.original_filename, "avatar.png")
        self.assertGreater(asset.byte_size, 0)
        self.assertIn(asset.public_id, storage.files)

    def test_rejects_unsupported_file_before_touching_storage(self):
        storage = InMemoryStorage()
        service = MediaUploadService(storage=storage)

        with self.assertRaises(InvalidInput):
            service.upload(SimpleUploadedFile("a.pdf", b"%PDF-", content_type="application/pdf"))

        self.assertEqual(storage.files, {})

    def test_partial_failure_removes_already_uploaded_files(self):
        # Without compensation the first two files would be orphaned in the
        # provider, since no database rollback can reach them.
        storage = ExplodingStorage(fail_on_call=3)
        service = MediaUploadService(storage=storage, folder="tests")

        with self.assertRaises(RuntimeError):
            service.upload_many([png_upload("a.png"), png_upload("b.png"), png_upload("c.png")])

        self.assertEqual(len(storage.deleted), 2)
        self.assertEqual(storage.inner.files, {})

    def test_rejects_more_attachments_than_the_cap(self):
        service = MediaUploadService(storage=InMemoryStorage())
        with self.assertRaises(InvalidInput):
            service.upload_many([png_upload(f"{i}.png") for i in range(11)])

    def test_discard_skips_assets_from_another_provider(self):
        storage = InMemoryStorage()
        service = MediaUploadService(storage=storage, folder="tests")
        asset = service.upload(png_upload())
        asset.provider = "cloudinary"

        service.discard(asset)

        self.assertEqual(storage.deleted, [])


class LocalFileSystemStorageTests(SimpleTestCase):
    """Covers the concrete backend the app uses when Cloudinary is unconfigured."""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="social-media-storage-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.service = MediaUploadService(storage=LocalFileSystemStorage(), folder="tests")

    def test_reads_dimensions_from_an_image(self):
        asset = self.service.upload(png_upload(size=(48, 32)))

        self.assertEqual((asset.width, asset.height), (48, 32))
        self.assertTrue(asset.url.endswith(asset.public_id))

    def test_leaves_dimensions_unset_for_audio(self):
        asset = self.service.upload(audio_upload())

        self.assertIsNone(asset.width)
        self.assertEqual(asset.thumbnail_url, "")

    def test_files_with_the_same_name_do_not_collide(self):
        first = self.service.upload(png_upload("same.png"))
        second = self.service.upload(png_upload("same.png"))

        self.assertNotEqual(first.public_id, second.public_id)

    def test_delete_removes_the_file_and_is_safe_to_repeat(self):
        asset = self.service.upload(png_upload())

        self.service.discard(asset)
        self.service.discard(asset)  # must not raise

        storage = LocalFileSystemStorage()
        self.assertFalse(storage._storage.exists(asset.public_id))
