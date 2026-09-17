"""Tests for the attachment object store (app/services/attachment_store.py).

The S3 backend runs entirely against moto: no AWS credentials exist in this
project and no test may reach a real bucket.

Policy baseline: docs/policy/attachment-storage.md.
"""

import os
import tempfile
from unittest import TestCase
from urllib.parse import parse_qs, urlparse

from moto import mock_aws

from app import create_app
from app.services import attachment_store as store_mod
from config import TestConfig, validate_attachment_store_config


class S3TestConfig(TestConfig):
    """TestConfig with the S3 store selected. Only ever used under moto."""

    ATTACHMENT_STORE = "s3"


def make_s3_app():
    """An app on the S3 store with its bucket created inside the active mock."""
    store_mod.reset_s3_clients()
    app = create_app(S3TestConfig)
    with app.app_context():
        store = store_mod.get_attachment_store()
        store.client.create_bucket(
            Bucket=store.bucket,
            CreateBucketConfiguration={"LocationConstraint": app.config["S3_REGION"]},
        )
    return app


class ConfigValidationTests(TestCase):
    """The app refuses to start on an S3 store it cannot use."""

    def _config(self, **overrides):
        base = {
            "ATTACHMENT_STORE": "s3",
            "S3_SERVER": "https://s3.ap-south-1.amazonaws.com",
            "S3_BUCKET": "b",
            "S3_REGION": "ap-south-1",
            "S3_ACCESS_KEY_ID": "k",
            "S3_SECRET_ACCESS_KEY": "s",
            "ATTACHMENT_PRESIGN_EXPIRY_SECONDS": 300,
        }
        base.update(overrides)
        return base

    def test_local_store_needs_no_s3_keys(self):
        validate_attachment_store_config(
            {"ATTACHMENT_STORE": "local", "ATTACHMENT_PRESIGN_EXPIRY_SECONDS": 300}
        )

    def test_unknown_store_is_refused(self):
        with self.assertRaises(RuntimeError):
            validate_attachment_store_config(self._config(ATTACHMENT_STORE="gcs"))

    def test_missing_key_fails_closed_and_names_only_the_key(self):
        for key in store_mod_required_keys():
            with self.subTest(key=key):
                with self.assertRaises(RuntimeError) as ctx:
                    validate_attachment_store_config(self._config(**{key: ""}))
                message = str(ctx.exception)
                self.assertIn(key, message)
                # The message may name keys; it must never echo a secret value.
                self.assertNotIn("s3-secret", message)

    def test_expiry_must_be_a_sane_integer(self):
        with self.assertRaises(RuntimeError):
            validate_attachment_store_config(
                self._config(ATTACHMENT_PRESIGN_EXPIRY_SECONDS=0)
            )
        with self.assertRaises(RuntimeError):
            validate_attachment_store_config(
                self._config(ATTACHMENT_PRESIGN_EXPIRY_SECONDS="300")
            )

    def test_region_is_derived_from_an_aws_endpoint_host(self):
        from config import _region_from_s3_server

        self.assertEqual(
            _region_from_s3_server("https://s3.ap-south-1.amazonaws.com"), "ap-south-1"
        )
        self.assertEqual(_region_from_s3_server("https://minio.internal:9000"), "")
        self.assertEqual(_region_from_s3_server(""), "")


def store_mod_required_keys():
    from config import REQUIRED_S3_CONFIG_KEYS

    return REQUIRED_S3_CONFIG_KEYS


class LocalStoreInterfaceTests(TestCase):
    FORM_ID = "STOREFORM"

    def setUp(self):
        self.app = create_app(TestConfig)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app.config["APP_DATA"] = self._tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.store = store_mod.get_attachment_store()

    def _target(self, storage_name="abc.jpg", local_path=None):
        return store_mod.StoreTarget(
            va_form_id=self.FORM_ID, storage_name=storage_name, local_path=local_path
        )

    def test_key_for(self):
        self.assertEqual(self.store.key_for(self._target()), f"{self.FORM_ID}/media/abc.jpg")
        self.assertIsNone(self.store.key_for(self._target(storage_name=None)))

    def test_put_exists_open_and_delete_round_trip(self):
        target = self._target()
        self.assertFalse(self.store.exists(target))
        path = self.store.put(target, iter([b"one", b"two"]), content_type="image/jpeg")
        self.assertTrue(self.store.exists(target))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"onetwo")
        self.assertEqual(self.store.open_local_path(target), path)
        self.assertTrue(self.store.delete(target))
        self.assertFalse(self.store.exists(target))
        self.assertFalse(self.store.delete(target))

    def test_put_from_a_path_leaves_no_temp_file(self):
        source = os.path.join(self._tmp.name, "source.bin")
        with open(source, "wb") as handle:
            handle.write(b"payload")
        target = self._target()
        self.store.put(target, source, content_type=None)
        media = os.path.join(self._tmp.name, self.FORM_ID, "media")
        self.assertEqual(sorted(os.listdir(media)), ["abc.jpg"])

    def test_local_store_never_presigns(self):
        self.assertIsNone(
            self.store.presigned_url(self._target(), content_type="image/jpeg", filename="a.jpg")
        )

    def test_put_without_a_storage_name_is_refused(self):
        with self.assertRaises(store_mod.AttachmentStoreError):
            self.store.put(self._target(storage_name=None), iter([b"x"]), content_type=None)


class S3StoreInterfaceTests(TestCase):
    FORM_ID = "STOREFORM"

    def setUp(self):
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(store_mod.reset_s3_clients)
        self.app = make_s3_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.store = store_mod.get_attachment_store()

    def _target(self, storage_name="abc.jpg"):
        return store_mod.StoreTarget(va_form_id=self.FORM_ID, storage_name=storage_name)

    def _source(self, payload=b"payload"):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(payload)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def test_key_for_includes_the_prefix(self):
        self.assertEqual(self.store.key_for(self._target()), f"{self.FORM_ID}/media/abc.jpg")
        self.store.key_prefix = "digitva/"
        self.assertEqual(
            self.store.key_for(self._target()), f"digitva/{self.FORM_ID}/media/abc.jpg"
        )

    def test_legacy_row_without_a_storage_name_has_no_key_and_no_presign(self):
        legacy = self._target(storage_name=None)
        self.assertIsNone(self.store.key_for(legacy))
        self.assertFalse(self.store.exists(legacy))
        self.assertIsNone(
            self.store.presigned_url(legacy, content_type="image/jpeg", filename="x.jpg")
        )

    def test_put_writes_the_required_object_metadata(self):
        target = self._target()
        self.assertFalse(self.store.exists(target))
        self.store.put(target, self._source(), content_type="image/jpeg")
        self.assertTrue(self.store.exists(target))

        head = self.store.client.head_object(
            Bucket=self.store.bucket, Key=self.store.key_for(target)
        )
        self.assertEqual(head["ContentType"], "image/jpeg")
        self.assertEqual(head["CacheControl"], "private, no-store")
        self.assertEqual(head["ContentDisposition"], "inline")
        self.assertEqual(head["ServerSideEncryption"], "AES256")

    def test_put_defaults_the_content_type_rather_than_storing_nothing(self):
        target = self._target()
        self.store.put(target, self._source(), content_type=None)
        head = self.store.head(self.store.key_for(target))
        self.assertEqual(head["ContentType"], "application/octet-stream")

    def test_presigned_url_fixes_the_response_headers_and_expiry(self):
        target = self._target()
        self.store.put(target, self._source(), content_type="image/jpeg")
        url = self.store.presigned_url(
            target, content_type="image/jpeg", filename="abc.jpg"
        )
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params["response-content-type"], ["image/jpeg"])
        self.assertEqual(
            params["response-content-disposition"], ['inline; filename="abc.jpg"']
        )
        self.assertEqual(params["response-cache-control"], ["private, no-store"])
        self.assertEqual(params["X-Amz-Expires"], ["300"])
        self.assertIn("X-Amz-Signature", params)

    def test_delete_and_iter_keys(self):
        first = self._target("one.jpg")
        second = self._target("two.jpg")
        self.store.put(first, self._source(b"a"), content_type="image/jpeg")
        self.store.put(second, self._source(b"bb"), content_type="image/jpeg")

        keys = {key for key, _size, _etag in self.store.iter_keys()}
        self.assertEqual(
            keys, {self.store.key_for(first), self.store.key_for(second)}
        )

        self.assertTrue(self.store.delete(first))
        self.assertFalse(self.store.exists(first))
        self.assertTrue(self.store.exists(second))

    def test_head_reports_absent_rather_than_raising(self):
        self.assertIsNone(self.store.head(f"{self.FORM_ID}/media/nothing.jpg"))

    def test_s3_store_has_no_local_path(self):
        self.assertIsNone(self.store.open_local_path(self._target()))

    def test_public_origins_cover_both_addressing_styles(self):
        origins = store_mod.s3_public_origins(self.app.config)
        self.assertIn("https://s3.ap-south-1.amazonaws.com", origins)
        self.assertIn(
            "https://digitva-test-attachments.s3.ap-south-1.amazonaws.com", origins
        )
