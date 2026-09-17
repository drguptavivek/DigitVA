"""Data-manager CSV exports in the object store.

The S3 half runs entirely inside moto: no AWS credentials exist in this project
and no test may reach a real bucket. ``TestConfig`` keeps the suite on the local
store, so the S3 classes flip ``ATTACHMENT_STORE`` themselves exactly as the
attachment, SmartVA archive and backup tests do.

Baseline: docs/current-state/data-manager-dashboard.md, *Exports*.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from urllib.parse import parse_qs, urlparse

from moto import mock_aws

from app.services import attachment_store as store_mod
from app.services import export_store_service as svc
from config import TestConfig
from tests.base import create_app_without_celery_takeover
from tests.services.test_attachment_store import make_s3_app


class _ExportStoreBase(TestCase):
    """One app, one temp APP_DATA, and a per-test user id."""

    CSV = "sid,result\nuuid:abc,ok\n"

    def setUp(self):
        self.user_id = uuid.uuid4()
        self.filters = {"project": "P1", "site": "S1", "search": ""}

    def _store_ref(self, *, export_kind="smartva_input", csv_text=None, filters=None):
        return svc.write_export(
            export_kind=export_kind,
            user_id=self.user_id,
            filters=self.filters if filters is None else filters,
            csv_text=self.CSV if csv_text is None else csv_text,
        )


class LocalExportStoreTests(_ExportStoreBase):
    """The local store keeps today's behaviour: files under APP_DATA/exports/."""

    def setUp(self):
        super().setUp()
        self.app = create_app_without_celery_takeover(TestConfig)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app.config["APP_DATA"] = self._tmp.name
        self.app.config["DB_BACKUP_TMP_DIR"] = self._tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)

    def _path(self, key):
        return os.path.join(self._tmp.name, key)

    def _backdate(self, key, hours):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
            svc.EXPORT_TS_FORMAT
        )
        directory, name = key.rsplit("/", 1)
        new_key = f"{directory}/{stamp}_{name.split('_', 1)[1]}"
        os.replace(self._path(key), self._path(new_key))
        return new_key

    def test_write_lands_under_app_data_exports_with_a_bom(self):
        ref = self._store_ref()

        self.assertTrue(ref.key.startswith("exports/smartva_input/"))
        self.assertTrue(ref.key.endswith(".csv"))
        with open(self._path(ref.key), encoding="utf-8") as handle:
            body = handle.read()
        self.assertEqual(body, svc.UTF8_BOM + self.CSV)
        self.assertEqual(ref.size_bytes, len(body.encode("utf-8")))
        self.assertEqual(len(ref.sha256), 64)
        self.assertEqual(
            ref.expires_at - ref.created_at,
            timedelta(hours=svc.export_retention_hours()),
        )

    def test_the_key_carries_the_user_so_one_user_cannot_reach_another(self):
        mine = self._store_ref()
        self.user_id = uuid.uuid4()
        theirs = self._store_ref()

        self.assertNotEqual(mine.key, theirs.key)
        self.assertNotIn(str(self.user_id), mine.key)
        # A lookup is scoped to the prefix, so the other user's object is unseen.
        found = svc.export_cache_lookup(
            export_kind="smartva_input",
            user_id=self.user_id,
            filters=self.filters,
            ttl_seconds=300,
        )
        self.assertEqual(found.key, theirs.key)

    def test_cache_lookup_matches_the_same_filters_and_misses_on_a_change(self):
        ref = self._store_ref()

        hit = svc.export_cache_lookup(
            export_kind="smartva_input",
            user_id=self.user_id,
            filters=self.filters,
            ttl_seconds=300,
        )
        self.assertEqual(hit.key, ref.key)

        miss = svc.export_cache_lookup(
            export_kind="smartva_input",
            user_id=self.user_id,
            filters={**self.filters, "site": "OTHER"},
            ttl_seconds=300,
        )
        self.assertIsNone(miss)

    def test_cache_lookup_respects_the_ttl_and_a_disabled_cache(self):
        ref = self._store_ref()
        stale_key = self._backdate(ref.key, hours=2)
        self.assertTrue(os.path.isfile(self._path(stale_key)))

        self.assertIsNone(
            svc.export_cache_lookup(
                export_kind="smartva_input",
                user_id=self.user_id,
                filters=self.filters,
                ttl_seconds=300,
            )
        )
        self.assertIsNone(
            svc.export_cache_lookup(
                export_kind="smartva_input",
                user_id=self.user_id,
                filters=self.filters,
                ttl_seconds=0,
            )
        )

    def test_prune_removes_expired_exports_and_keeps_fresh_ones(self):
        fresh = self._store_ref()
        expired = self._backdate(self._store_ref(export_kind="data").key, hours=30)
        stray = os.path.join(self._tmp.name, "exports", "not-an-export.csv")
        with open(stray, "w", encoding="utf-8") as handle:
            handle.write("x")

        outcome = svc.prune_exports()

        self.assertEqual(outcome.pruned, 1)
        self.assertEqual(outcome.kept, 1)
        self.assertFalse(os.path.exists(self._path(expired)))
        self.assertTrue(os.path.isfile(self._path(fresh.key)))
        # A name the service did not write is never guessed at, never deleted.
        self.assertTrue(os.path.isfile(stray))

    def test_presign_is_none_on_the_local_store_and_the_file_is_served(self):
        ref = self._store_ref()

        self.assertIsNone(svc.presigned_download_url(ref, "export.csv"))
        self.assertEqual(svc.export_local_path(ref), self._path(ref.key))

    def test_a_missing_local_export_is_a_miss_not_an_arbitrary_file_read(self):
        ref = self._store_ref()
        os.remove(self._path(ref.key))
        self.assertIsNone(svc.export_local_path(ref))

        escaping = svc.ExportRef(
            key="exports/../../etc/passwd",
            size_bytes=0,
            sha256="",
            created_at=ref.created_at,
            expires_at=ref.expires_at,
        )
        self.assertIsNone(svc.export_local_path(escaping))

    def test_retention_hours_is_clamped_to_at_least_one(self):
        self.app.config["EXPORT_RETENTION_HOURS"] = 0
        self.assertEqual(svc.export_retention_hours(), 1)
        self.app.config["EXPORT_RETENTION_HOURS"] = "not a number"
        self.assertEqual(svc.export_retention_hours(), svc.DEFAULT_RETENTION_HOURS)

    def test_a_download_filename_cannot_carry_header_syntax(self):
        self.assertEqual(
            svc.safe_filename('a"; attachment; filename="b.csv'),
            "a-attachment-filename-b.csv",
        )
        self.assertEqual(svc.safe_filename("   "), "export.csv")


class S3ExportStoreTests(_ExportStoreBase):
    """The S3 store: the object is the export, and nothing stays on the VM."""

    def setUp(self):
        super().setUp()
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(store_mod.reset_s3_clients)
        self.app = make_s3_app()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app.config["APP_DATA"] = self._tmp.name
        self.app.config["DB_BACKUP_TMP_DIR"] = self._tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.store = store_mod.get_attachment_store()

    def _head(self, key):
        return self.store.head_key(key)

    def _backdate(self, key, hours):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
            svc.EXPORT_TS_FORMAT
        )
        directory, name = key.rsplit("/", 1)
        new_key = f"{directory}/{stamp}_{name.split('_', 1)[1]}"
        self.store.client.copy_object(
            Bucket=self.store.bucket,
            CopySource={"Bucket": self.store.bucket, "Key": self.store.absolute_key(key)},
            Key=self.store.absolute_key(new_key),
        )
        self.store.delete_key(key)
        return new_key

    def test_write_puts_a_no_store_encrypted_csv_and_leaves_nothing_on_disk(self):
        ref = self._store_ref()

        head = self._head(ref.key)
        self.assertIsNotNone(head)
        self.assertEqual(head["ContentType"], svc.EXPORT_CONTENT_TYPE)
        self.assertEqual(head["CacheControl"], "private, no-store")
        self.assertEqual(head["ServerSideEncryption"], "AES256")
        self.assertEqual(head["ContentLength"], ref.size_bytes)
        # No export file, and no temp file, is left behind on the app server.
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_cache_lookup_finds_the_object_for_the_same_filters(self):
        ref = self._store_ref()

        hit = svc.export_cache_lookup(
            export_kind="smartva_input",
            user_id=self.user_id,
            filters=self.filters,
            ttl_seconds=300,
        )
        self.assertEqual(hit.key, ref.key)
        self.assertEqual(hit.size_bytes, ref.size_bytes)

        self.assertIsNone(
            svc.export_cache_lookup(
                export_kind="smartva_input",
                user_id=uuid.uuid4(),
                filters=self.filters,
                ttl_seconds=300,
            )
        )

    def test_presigned_url_fixes_the_attachment_disposition_in_the_signature(self):
        ref = self._store_ref()

        url = svc.presigned_download_url(ref, "data-management-submissions.csv")

        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertIn(self.store.absolute_key(ref.key), parsed.path)
        self.assertEqual(
            query["response-content-disposition"][0],
            'attachment; filename="data-management-submissions.csv"',
        )
        self.assertEqual(query["response-content-type"][0], svc.EXPORT_CONTENT_TYPE)
        self.assertEqual(query["response-cache-control"][0], "private, no-store")
        self.assertEqual(
            int(query["X-Amz-Expires"][0]),
            self.app.config["ATTACHMENT_PRESIGN_EXPIRY_SECONDS"],
        )
        self.assertIn("X-Amz-Signature", query)

    def test_prune_deletes_only_expired_objects(self):
        fresh = self._store_ref()
        expired = self._backdate(self._store_ref(export_kind="data").key, hours=48)

        outcome = svc.prune_exports()

        self.assertEqual(outcome.store, "s3")
        self.assertEqual(outcome.pruned, 1)
        self.assertEqual(outcome.kept, 1)
        self.assertIsNone(self._head(expired))
        self.assertIsNotNone(self._head(fresh.key))

    def test_prune_honours_an_explicit_max_age(self):
        recent = self._backdate(self._store_ref().key, hours=3)

        self.assertEqual(svc.prune_exports(max_age_hours=6).pruned, 0)
        self.assertEqual(svc.prune_exports(max_age_hours=1).pruned, 1)
        self.assertIsNone(self._head(recent))

    def test_a_failed_listing_prunes_nothing(self):
        ref = self._store_ref()

        def explode(*_args, **_kwargs):
            raise store_mod.AttachmentStoreError("listing down")

        original = type(self.store).iter_keys
        type(self.store).iter_keys = explode
        try:
            outcome = svc.prune_exports()
        finally:
            type(self.store).iter_keys = original

        self.assertEqual(outcome.skipped_reason, "listing_failed")
        self.assertEqual(outcome.pruned, 0)
        self.assertIsNotNone(self._head(ref.key))
