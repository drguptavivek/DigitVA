"""Daily purge of web intake uploads (digitva-i9lb): files of a draft untouched
for 30 days, and files no answer of their draft references any more once 30
days old, are deleted (rows and stored objects) with an audit row per draft; a
file a submission holds, and the draft itself, are never touched.
"""
import io
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from app import db
from app.models import (
    MapCaseTransition,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import web_intake_attachment_service as svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.tasks import web_intake_upload_tasks as tasks
from tests.base import BaseTestCase

PDF = b"%PDF-1.4\n" + b"0" * 60
NOW = datetime.now(timezone.utc)


def _days_ago(days):
    return NOW - timedelta(days=days)


class UploadPurgeTests(BaseTestCase):
    PROJECT_ID = "WPU02"
    SITE_ID = "WP02"
    ODK_FORM_ID = "WPU02WP0201"
    death_seq = 9_100_000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Upload Purge Project",
            project_nickname="UploadPurge", project_status=VaStatuses.active, project_registered_at=NOW,
            project_updated_at=NOW, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Upload Purge Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=NOW, site_updated_at=NOW,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=NOW, project_site_updated_at=NOW,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id=cls.ODK_FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, odk_form_id="ODK_PURGE",
            odk_project_id="9", form_type="WHO VA 2022", form_source="odk", form_status=VaStatuses.active,
            form_registered_at=NOW, form_updated_at=NOW,
        ))
        db.session.flush()
        cls.user_id = cls._get_or_make_user("purge.interviewer@test.local", "PurgeTest123").user_id
        db.session.commit()

    def setUp(self):
        super().setUp()
        data_dir = tempfile.mkdtemp(prefix="digitva-purge-")
        previous = self.app.config["APP_DATA"]
        self.app.config["APP_DATA"] = data_dir
        self.addCleanup(lambda: self.app.config.__setitem__("APP_DATA", previous))
        self.addCleanup(shutil.rmtree, data_dir, True)
        self.data_dir = data_dir

    # -- helpers -------------------------------------------------------------

    def _stored_files(self):
        found = []
        for root, _dirs, files in os.walk(self.data_dir):
            found.extend(os.path.join(root, name) for name in files if not name.startswith(".tmp_"))
        return found

    def _draft(self, *, idle_days):
        """An open draft on its own case, last answer-saved *idle_days* ago."""
        UploadPurgeTests.death_seq += 1
        unique_id = f"PURGE{self.death_seq}"
        death = VaDeathRegister(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_number=self.death_seq, unique_id=unique_id,
            deceased_name="Purge Test", deceased_sex="female", date_of_death=date.today(), status="in_progress",
            registered_by=self.user_id, source="direct",
        )
        db.session.add(death)
        db.session.flush()
        draft = VaWebIntakeDraft(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id, form_id=self.ODK_FORM_ID,
            user_id=self.user_id, unique_id=unique_id, status="draft", meta={}, prefill={},
        )
        db.session.add(draft)
        db.session.flush()
        draft.updated_at = _days_ago(idle_days)
        db.session.flush()
        return draft

    def _upload(self, draft, *, age_days, referenced):
        """One stored file of *draft*, uploaded *age_days* ago; *referenced* puts
        its reference in a section the way the page saves it."""
        cid = uuid.uuid4()
        row, _created = svc.store_upload(draft, cid, io.BytesIO(PDF), len(PDF))
        row.created_at = _days_ago(age_days)
        if referenced:
            db.session.add(VaWebIntakeDraftSection(
                draft_id=draft.draft_id, section_name=f"s{cid.hex[:6]}",
                data={"md_im1": {"id": str(cid), "uri": f"who-va-attachment:{cid}", "mimeType": "application/pdf"}},
            ))
        db.session.commit()
        return cid

    def _held(self, draft, cid):
        db.session.expire_all()
        return db.session.get(VaWebIntakeAttachment, (draft.draft_id, cid)) is not None

    def _audits(self, draft):
        return db.session.scalars(
            sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == draft.death_id, MapCaseTransition.action == svc.PURGE_ACTION
            )
        ).all()

    # -- tests ---------------------------------------------------------------

    def test_a_draft_untouched_for_30_days_loses_its_uploads_and_it_is_audited(self):
        draft = self._draft(idle_days=31)
        first = self._upload(draft, age_days=40, referenced=True)  # still named by an answer
        self._upload(draft, age_days=40, referenced=True)
        self.assertEqual(len(self._stored_files()), 2)

        result = svc.purge_expired_uploads()
        svc.delete_committed_blobs()

        self.assertEqual(result, {"files": 2, "batches": 1})
        self.assertFalse(self._held(draft, first))
        self.assertEqual(self._stored_files(), [])
        self.assertEqual(db.session.get(VaWebIntakeDraft, draft.draft_id).status, "draft")  # the draft stays
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraftSection)
                              .where(VaWebIntakeDraftSection.draft_id == draft.draft_id)), 2)  # and its answers
        (audit,) = self._audits(draft)
        self.assertEqual(audit.reason, "idle_30d: 2 file(s)")
        self.assertEqual((audit.from_state, audit.to_state), ("in_progress", "in_progress"))
        self.assertEqual(audit.actor_user_id, self.user_id)
        self.assertIsNone(audit.changes)
        self.assertIsNone(audit.authorizing_grant_id)

    def test_a_draft_saved_29_days_ago_keeps_its_referenced_uploads(self):
        draft = self._draft(idle_days=29)
        cid = self._upload(draft, age_days=45, referenced=True)
        self.assertEqual(svc.purge_expired_uploads(), {"files": 0, "batches": 0})
        self.assertTrue(self._held(draft, cid))
        self.assertEqual(len(self._stored_files()), 1)
        self.assertEqual(self._audits(draft), [])

    def test_an_unreferenced_file_older_than_30_days_goes_a_referenced_or_newer_one_stays(self):
        draft = self._draft(idle_days=1)  # an active draft
        gone = self._upload(draft, age_days=31, referenced=False)
        referenced = self._upload(draft, age_days=60, referenced=True)
        recent = self._upload(draft, age_days=29, referenced=False)

        self.assertEqual(svc.purge_expired_uploads(), {"files": 1, "batches": 1})

        self.assertFalse(self._held(draft, gone))
        self.assertTrue(self._held(draft, referenced))
        self.assertTrue(self._held(draft, recent))
        self.assertEqual(len(self._stored_files()), 2)
        (audit,) = self._audits(draft)
        self.assertEqual(audit.reason, "unreferenced_30d: 1 file(s)")

    def test_a_file_a_submission_holds_is_never_touched_even_on_an_old_draft(self):
        draft = self._draft(idle_days=90)
        cid = self._upload(draft, age_days=90, referenced=True)
        sid = f"purge-{uuid.uuid4().hex[:12]}"
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=self.ODK_FORM_ID, va_submission_date=NOW, va_odk_updatedat=NOW,
            va_data_collector="Collector", va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English", va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        row = db.session.get(VaWebIntakeAttachment, (draft.draft_id, cid))
        svc.link_to_submission(sid, draft.draft_id, {"md_im1": row.filename})
        db.session.commit()
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionAttachments)
                              .where(VaSubmissionAttachments.storage_name == row.storage_name)), 1)

        self.assertEqual(svc.purge_expired_uploads(), {"files": 0, "batches": 0})

        self.assertTrue(self._held(draft, cid))
        self.assertEqual(len(self._stored_files()), 1)

    def test_submitted_and_discarded_drafts_are_not_this_purges(self):
        for status in ("submitted", "discarded"):
            draft = self._draft(idle_days=90)
            cid = self._upload(draft, age_days=90, referenced=False)
            draft.status = status
            db.session.commit()
            self.assertEqual(svc.purge_expired_uploads(), {"files": 0, "batches": 0})
            self.assertTrue(self._held(draft, cid))

    def test_the_run_is_bounded_by_the_batch_size_and_the_batch_cap(self):
        draft = self._draft(idle_days=40)
        for _ in range(5):
            self._upload(draft, age_days=40, referenced=False)
        with mock.patch.object(svc, "PURGE_BATCH", 2), mock.patch.object(svc, "PURGE_MAX_BATCHES", 2):
            self.assertEqual(svc.purge_expired_uploads(), {"files": 4, "batches": 2})
        self.assertEqual(len(self._stored_files()), 1)
        # Tomorrow's run takes the rest.
        self.assertEqual(svc.purge_expired_uploads(), {"files": 1, "batches": 1})
        self.assertEqual(self._stored_files(), [])
        self.assertEqual(len(self._audits(draft)), 3)  # an audit row per batch the draft appears in

    def test_a_failed_commit_leaves_the_rows_and_the_next_run_deletes_them(self):
        draft = self._draft(idle_days=40)
        cid = self._upload(draft, age_days=40, referenced=False)
        with mock.patch.object(db.session, "commit", side_effect=OperationalError("COMMIT", {}, Exception("boom"))):
            with self.assertRaises(OperationalError):
                svc.purge_expired_uploads()
        # The object went first (under the case lock); the rows came back with the rollback.
        self.assertTrue(self._held(draft, cid))
        self.assertEqual(self._stored_files(), [])
        self.assertEqual(self._audits(draft), [])

        # The next run finds the rows again; the missing object is tolerated.
        self.assertEqual(svc.purge_expired_uploads(), {"files": 1, "batches": 1})
        self.assertFalse(self._held(draft, cid))
        self.assertEqual(len(self._audits(draft)), 1)

    def test_objects_go_before_the_commit_while_the_locks_are_held(self):
        draft = self._draft(idle_days=40)
        self._upload(draft, age_days=40, referenced=False)
        seen = []
        real_commit = db.session.commit

        def commit():
            seen.append(len(self._stored_files()))  # at commit time the object is already gone
            real_commit()

        with mock.patch.object(db.session, "commit", commit):
            svc.purge_expired_uploads()
        self.assertEqual(seen, [0])
        self.assertEqual(self._stored_files(), [])

    def test_a_submission_linking_the_file_after_selection_keeps_the_object(self):
        draft = self._draft(idle_days=40)
        cid = self._upload(draft, age_days=40, referenced=False)
        row = db.session.get(VaWebIntakeAttachment, (draft.draft_id, cid))
        filename, storage_name = row.filename, row.storage_name
        sid = f"purge-{uuid.uuid4().hex[:12]}"
        real = svc._discard_blob

        def link_then_discard(local_path, form_id, name):
            # A submission links the file after the purge selected it, before the object goes.
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=self.ODK_FORM_ID, va_submission_date=NOW, va_odk_updatedat=NOW,
                va_data_collector="Collector", va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English", va_deceased_age=42, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
            ))
            db.session.flush()
            svc.link_to_submission(sid, draft.draft_id, {"md_im1": filename})
            real(local_path, form_id, name)

        with mock.patch.object(svc, "_discard_blob", link_then_discard):
            svc.purge_expired_uploads()

        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionAttachments)
                              .where(VaSubmissionAttachments.storage_name == storage_name)), 1)
        self.assertEqual(len(self._stored_files()), 1)

    def test_locks_are_taken_cases_first_then_drafts_and_never_waited_for(self):
        from tests.authz.test_grants import count_queries

        draft = self._draft(idle_days=40)
        self._upload(draft, age_days=40, referenced=False)
        with count_queries() as statements:
            svc.purge_expired_uploads()
        locks = [s for s in statements if "FOR UPDATE" in s]
        self.assertEqual(len(locks), 2, locks)
        self.assertIn("FROM va_death_register", locks[0])
        self.assertIn("FROM va_web_intake_drafts", locks[1])
        self.assertTrue(all("SKIP LOCKED" in s for s in locks))

    def test_a_draft_whose_case_is_locked_elsewhere_is_left_for_the_next_run(self):
        draft = self._draft(idle_days=40)
        cid = self._upload(draft, age_days=40, referenced=False)
        with mock.patch.object(svc, "_lock_cases", return_value={}):  # SKIP LOCKED skipped it
            self.assertEqual(svc.purge_expired_uploads(), {"files": 0, "batches": 0})
        self.assertTrue(self._held(draft, cid))
        self.assertEqual(len(self._stored_files()), 1)
        self.assertEqual(svc.purge_expired_uploads(), {"files": 1, "batches": 1})

    def test_a_draft_without_a_case_is_purged_and_logged_with_its_id(self):
        draft = self._draft(idle_days=40)
        cid = self._upload(draft, age_days=40, referenced=False)
        draft.death_id = None
        db.session.commit()
        with self.assertLogs(svc.log, level="INFO") as logs:
            self.assertEqual(svc.purge_expired_uploads(), {"files": 1, "batches": 1})
        self.assertFalse(self._held(draft, cid))
        self.assertIn(f"draft={draft.draft_id} | files=1", "\n".join(logs.output))

    def test_discard_queues_objects_for_after_the_commit(self):
        draft = self._draft(idle_days=0)
        cid = self._upload(draft, age_days=0, referenced=False)
        self.assertEqual(svc.delete_draft_uploads(draft), 1)
        self.assertEqual(len(self._stored_files()), 1)  # not before the commit
        db.session.rollback()
        svc.delete_committed_blobs()
        self.assertEqual(len(self._stored_files()), 1)  # a rollback dropped the queue
        self.assertTrue(self._held(draft, cid))

        self.assertEqual(svc.delete_draft_uploads(draft), 1)
        db.session.commit()
        svc.delete_committed_blobs()
        self.assertEqual(self._stored_files(), [])

    def test_task_returns_counts_and_never_raises(self):
        draft = self._draft(idle_days=40)
        self._upload(draft, age_days=40, referenced=False)
        with self.assertLogs(tasks.log, level="INFO") as logs:
            result = tasks.purge_web_intake_uploads_task.run()
        self.assertEqual(result, {"files": 1, "batches": 1, "status": "ok"})
        self.assertIn("1 file(s) in 1 batch(es)", "\n".join(logs.output))

        with mock.patch.object(svc, "purge_expired_uploads", side_effect=RuntimeError("boom")):
            self.assertEqual(
                tasks.purge_web_intake_uploads_task.run(), {"files": 0, "batches": 0, "status": "unexpected"}
            )


class UploadPurgeBeatTests(BaseTestCase):
    def test_beat_seeding_is_idempotent(self):
        """The beat tables only exist in the migrated dev database, so the
        seeding runs against a stand-in connection that remembers its inserts."""
        inserted = []

        class Conn:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "INSERT INTO public.celery_periodictask\n" in sql:
                    inserted.append(params)
                result = mock.Mock()
                if "SELECT id FROM public.celery_intervalschedule" in sql:
                    result.scalar.return_value = 7
                elif "SELECT id FROM public.celery_periodictask" in sql:
                    result.scalar.return_value = 1 if inserted else None
                return result

        @contextmanager
        def begin():
            yield Conn()

        with mock.patch("app.db", mock.Mock(engine=mock.Mock(begin=begin))):
            tasks.ensure_web_intake_upload_purge_scheduled()
            tasks.ensure_web_intake_upload_purge_scheduled()
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0]["name"], tasks.UPLOAD_PURGE_SCHEDULE_NAME)
        self.assertEqual(inserted[0]["task"], "app.tasks.web_intake_upload_tasks.purge_web_intake_uploads_task")
        self.assertEqual(inserted[0]["schedule_id"], 7)

    def test_worker_startup_registers_and_seeds_it(self):
        source = (Path(__file__).resolve().parents[2] / "make_celery.py").read_text()
        self.assertIn("import app.tasks.web_intake_upload_tasks", source)
        self.assertIn("ensure_web_intake_upload_purge_scheduled()", source)
