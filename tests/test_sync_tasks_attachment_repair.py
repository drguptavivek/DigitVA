import os
import tempfile
import uuid
from itertools import count
from datetime import datetime, timezone
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    VaForms,
    VaResearchProjects,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissions,
    VaSubmissionPayloadVersion,
    VaSyncRun,
    VaSites,
)
from app.tasks.sync_tasks import (
    _build_repair_map_for_form,
    _run_canonical_repair_batches,
    _refresh_batch_plan_after_enrichment,
    run_legacy_attachment_repair,
    run_single_form_backfill,
)
from app.models.va_submission_payload_versions import PAYLOAD_VERSION_STATUS_ACTIVE
from tests.base import BaseTestCase


class SyncTaskAttachmentRepairTests(BaseTestCase):
    _id_counter = count(1)

    def setUp(self):
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._old_app_data = self.app.config.get("APP_DATA")
        self.app.config["APP_DATA"] = self._tmp_dir.name
        seq = next(self._id_counter)
        self.project_id = f"P{seq:05d}"
        self.site_id = f"S{seq % 1000:03d}"
        self.form_id = f"BS01{uuid.uuid4().hex[:8].upper()}"[:12]
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaResearchProjects(
                    project_id=self.project_id,
                    project_code=self.project_id,
                    project_name="Sync Task Test Project",
                    project_nickname="SyncTaskTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSites(
                    site_id=self.site_id,
                    project_id=self.project_id,
                    site_name="Sync Task Test Site",
                    site_abbr=self.site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add(
            VaForms(
                form_id=self.form_id,
                project_id=self.project_id,
                site_id=self.site_id,
                odk_form_id=f"ODK-{self.form_id}",
                odk_project_id="1",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    def tearDown(self):
        self.app.config["APP_DATA"] = self._old_app_data
        self._tmp_dir.cleanup()
        super().tearDown()

    def _create_submission_with_attachment(
        self,
        *,
        filename: str,
        storage_name: str | None,
        local_path: str | None,
        attachments_expected: int = 1,
    ) -> str:
        now = datetime.now(timezone.utc)
        instance_id = uuid.uuid4().hex
        va_sid = f"{instance_id}-{self.form_id.lower()}"
        submission = VaSubmissions(
            va_sid=va_sid,
            va_form_id=self.form_id,
            active_payload_version_id=None,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="collector",
            va_odk_reviewstate=None,
            va_odk_reviewcomments=None,
            va_sync_issue_code=None,
            va_sync_issue_detail=None,
            va_sync_issue_updated_at=None,
            va_instance_name=instance_id,
            va_uniqueid_real=None,
            va_uniqueid_masked=instance_id,
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_age_normalized_days=None,
            va_deceased_age_normalized_years=None,
            va_deceased_age_source=None,
            va_deceased_gender="male",
            va_summary=["summary"],
            va_catcount={},
            va_category_list=["category"],
            va_created_at=now,
            va_updated_at=now,
        )
        db.session.add(submission)
        db.session.flush()

        payload = VaSubmissionPayloadVersion(
            va_sid=va_sid,
            source_updated_at=now,
            payload_fingerprint=uuid.uuid4().hex,
            payload_data={
                "KEY": instance_id,
                "instanceID": instance_id,
                "FormVersion": "1",
                "DeviceID": "device-1",
                "SubmitterID": "submitter-1",
                "AttachmentsExpected": attachments_expected,
                "AttachmentsPresent": attachments_expected,
            },
            version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
            created_by_role="vasystem",
            created_by=None,
            version_created_at=now,
            version_activated_at=now,
            has_required_metadata=True,
            attachments_expected=attachments_expected,
        )
        db.session.add(payload)
        db.session.flush()

        submission.active_payload_version_id = payload.payload_version_id
        db.session.add(
            VaSubmissionAttachments(
                va_sid=va_sid,
                filename=filename,
                local_path=local_path,
                mime_type="image/jpeg",
                etag="etag-1",
                exists_on_odk=True,
                last_downloaded_at=now,
                storage_name=storage_name,
            )
        )
        db.session.add(
            VaSmartvaResults(
                va_sid=va_sid,
                payload_version_id=payload.payload_version_id,
                smartva_run_id=None,
                va_smartva_cause1="Some cause",
                va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
                va_smartva_status=VaStatuses.active,
                va_smartva_addedat=now,
                va_smartva_updatedat=now,
            )
        )
        db.session.commit()
        return va_sid

    def test_build_repair_map_marks_missing_local_attachment_files(self):
        va_sid = self._create_submission_with_attachment(
            filename="photo.jpg",
            storage_name="photo-storage.jpg",
            local_path=os.path.join(self._tmp_dir.name, self.form_id, "media", "photo.jpg"),
        )

        repair_map, summary = _build_repair_map_for_form(self.form_id, [], {})

        self.assertEqual(summary["metadata_missing"], 0)
        self.assertEqual(summary["attachments_missing"], 1)
        self.assertEqual(summary["smartva_missing"], 0)
        self.assertIn(va_sid, repair_map)
        self.assertTrue(repair_map[va_sid]["needs_attachments"])
        self.assertFalse(repair_map[va_sid]["needs_metadata"])
        self.assertFalse(repair_map[va_sid]["needs_smartva"])

    def test_build_repair_map_excludes_audit_csv_from_present_files(self):
        media_dir = os.path.join(self._tmp_dir.name, self.form_id, "media")
        os.makedirs(media_dir, exist_ok=True)
        audit_path = os.path.join(media_dir, "audit.csv")
        with open(audit_path, "w", encoding="utf-8") as handle:
            handle.write("audit")

        va_sid = self._create_submission_with_attachment(
            filename="audit.csv",
            storage_name=None,
            local_path=audit_path,
        )

        repair_map, summary = _build_repair_map_for_form(self.form_id, [], {})

        self.assertEqual(summary["attachments_missing"], 1)
        self.assertIn(va_sid, repair_map)
        self.assertTrue(repair_map[va_sid]["needs_attachments"])

    def test_build_repair_map_marks_legacy_attachment_rows_for_migration(self):
        media_dir = os.path.join(self._tmp_dir.name, self.form_id, "media")
        os.makedirs(media_dir, exist_ok=True)
        legacy_local_path = os.path.join(media_dir, "legacy-photo.jpg")
        with open(legacy_local_path, "wb") as handle:
            handle.write(b"legacy")

        va_sid = self._create_submission_with_attachment(
            filename="legacy-photo.jpg",
            storage_name=None,
            local_path=legacy_local_path,
        )

        repair_map, summary = _build_repair_map_for_form(self.form_id, [], {})

        self.assertEqual(summary["attachments_missing"], 1)
        self.assertIn(va_sid, repair_map)
        self.assertTrue(repair_map[va_sid]["needs_attachments"])

    def test_refresh_batch_plan_after_enrichment_rediscovered_attachment_need(self):
        now = datetime.now(timezone.utc)
        instance_id = uuid.uuid4().hex
        va_sid = f"{instance_id}-{self.form_id.lower()}"
        submission = VaSubmissions(
            va_sid=va_sid,
            va_form_id=self.form_id,
            active_payload_version_id=None,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="collector",
            va_odk_reviewstate=None,
            va_odk_reviewcomments=None,
            va_sync_issue_code=None,
            va_sync_issue_detail=None,
            va_sync_issue_updated_at=None,
            va_instance_name=instance_id,
            va_uniqueid_real=None,
            va_uniqueid_masked=instance_id,
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_age_normalized_days=None,
            va_deceased_age_normalized_years=None,
            va_deceased_age_source=None,
            va_deceased_gender="male",
            va_summary=["summary"],
            va_catcount={},
            va_category_list=["category"],
            va_created_at=now,
            va_updated_at=now,
        )
        db.session.add(submission)
        db.session.flush()
        payload = VaSubmissionPayloadVersion(
            va_sid=va_sid,
            source_updated_at=now,
            payload_fingerprint=uuid.uuid4().hex,
            payload_data={
                "KEY": instance_id,
                "instanceID": instance_id,
                "FormVersion": "1",
                "DeviceID": "device-1",
                "SubmitterID": "submitter-1",
                "AttachmentsExpected": 2,
                "AttachmentsPresent": 2,
            },
            version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
            created_by_role="vasystem",
            created_by=None,
            version_created_at=now,
            version_activated_at=now,
            has_required_metadata=True,
            attachments_expected=2,
        )
        db.session.add(payload)
        db.session.flush()
        submission.active_payload_version_id = payload.payload_version_id
        db.session.add(
            VaSmartvaResults(
                va_sid=va_sid,
                payload_version_id=payload.payload_version_id,
                smartva_run_id=None,
                va_smartva_cause1="Some cause",
                va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
                va_smartva_status=VaStatuses.active,
                va_smartva_addedat=now,
                va_smartva_updatedat=now,
            )
        )
        db.session.commit()

        batch_plan = {
            va_sid: {
                "instance_id": instance_id,
                "needs_metadata": True,
                "needs_attachments": False,
                "needs_smartva": False,
            }
        }

        refreshed_plan, summary, upstream_changed = _refresh_batch_plan_after_enrichment(
            form_id=self.form_id,
            batch_plan=batch_plan,
            raw_submissions=[{"sid": va_sid, "KEY": instance_id}],
            upserted_map={va_sid: instance_id},
        )

        self.assertEqual(upstream_changed, 0)
        self.assertEqual(summary["metadata_missing"], 0)
        self.assertEqual(summary["attachments_missing"], 1)
        self.assertEqual(summary["smartva_missing"], 0)
        self.assertFalse(refreshed_plan[va_sid]["needs_metadata"])
        self.assertTrue(refreshed_plan[va_sid]["needs_attachments"])
        self.assertFalse(refreshed_plan[va_sid]["needs_smartva"])

    def test_run_canonical_repair_batches_aggregates_shared_engine_results(self):
        now = datetime.now(timezone.utc)
        run = VaSyncRun(
            triggered_by="test-repair",
            started_at=now,
            status="running",
        )
        db.session.add(run)
        db.session.commit()

        candidate_sids = [f"sid-{i}" for i in range(6)]
        result_rows = [
            {
                "attempted": True,
                "initial_summary": {"attachments_missing": 1},
                "attachments_downloaded": 1,
                "non_audit_downloaded": 1,
                "audit_downloaded": 0,
                "smartva_generated": 0,
                "needs_smartva_after_repair": True,
                "upstream_changed_held": False,
                "form_id": self.form_id,
            }
            for _ in candidate_sids
        ]

        with patch(
            "app.services.open_submission_repair_service.repair_submission_current_payload",
            side_effect=result_rows,
        ), patch(
            "app.services.smartva_service.generate_for_form",
            side_effect=[5, 1],
        ) as mock_smartva:
            totals = _run_canonical_repair_batches(
                run_id=run.sync_run_id,
                label=self.form_id,
                candidate_sids=candidate_sids,
                trigger_source="backfill",
                force_attachment_redownload=False,
                log_progress=lambda _msg: None,
            )

        refreshed_run = db.session.get(VaSyncRun, run.sync_run_id)
        self.assertEqual(totals["downloaded"], 6)
        self.assertEqual(totals["smartva_generated"], 6)
        self.assertEqual(refreshed_run.attachment_forms_total, 2)
        self.assertEqual(refreshed_run.attachment_forms_completed, 2)
        self.assertEqual(refreshed_run.attachment_downloaded, 6)
        self.assertEqual(refreshed_run.attachment_errors, 0)
        self.assertEqual(refreshed_run.smartva_records_generated, 6)
        self.assertEqual(refreshed_run.status, "success")
        self.assertEqual(mock_smartva.call_count, 2)

    def test_run_single_form_backfill_delegates_repairs_to_canonical_engine_batches(self):
        with patch("app.tasks.sync_tasks._authorize_data_manager_form_sync"), \
            patch("app.tasks.sync_tasks._get_single_form_odk_client", return_value=object()), \
            patch("app.utils.va_odk_fetch_instance_ids", return_value=[]), \
            patch(
                "app.tasks.sync_tasks._build_repair_map_for_form",
                return_value=(
                    {
                        "sid-1": {
                            "instance_id": "uuid:one",
                            "needs_metadata": False,
                            "needs_attachments": True,
                            "needs_smartva": False,
                        }
                    },
                    {
                        "metadata_missing": 0,
                        "attachments_missing": 1,
                        "legacy_attachment_rows": 1,
                        "smartva_missing": 0,
                    },
                ),
            ), \
            patch("app.tasks.sync_tasks._prepare_run_for_canonical_repair") as mock_prepare, \
            patch("app.tasks.sync_tasks.run_canonical_repair_batches_task.delay") as mock_repair, \
            patch("app.tasks.sync_tasks.finalize_canonical_repair_run_task.delay") as mock_finalize:
            run_single_form_backfill.run(form_id=self.form_id, triggered_by="backfill", user_id=None)

        mock_repair.assert_called_once()
        mock_prepare.assert_called_once()
        self.assertEqual(mock_repair.call_args.kwargs["form_id"], self.form_id)
        self.assertEqual(mock_repair.call_args.kwargs["candidate_sids"], ["sid-1"])
        self.assertEqual(mock_repair.call_args.kwargs["trigger_source"], "backfill")
        mock_finalize.assert_called_once()

    def test_run_single_form_backfill_pipelines_gap_batches_into_immediate_repair(self):
        missing_ids = [f"uuid:{i}" for i in range(60)]

        def _fake_fetch(_va_form, batch_ids, **_kwargs):
            return [{"sid": f"{instance_id}-{self.form_id.lower()}", "KEY": instance_id} for instance_id in batch_ids]

        def _fake_upsert(_va_form, batch_records, _discarded_ids, batch_upserted_map, **_kwargs):
            for record in batch_records:
                batch_upserted_map[record["sid"]] = record["KEY"]
            return len(batch_records), 0, 0, 0

        def _fake_build(_form_id, raw_submissions, upserted_map, **kwargs):
            target_sids = kwargs.get("target_sids")
            if target_sids:
                repair_map = {
                    va_sid: {
                        "instance_id": upserted_map[va_sid],
                        "needs_metadata": False,
                        "needs_attachments": True,
                        "needs_smartva": False,
                    }
                    for va_sid in target_sids
                }
                return repair_map, {
                    "metadata_missing": 0,
                    "attachments_missing": len(target_sids),
                    "legacy_attachment_rows": len(target_sids),
                    "smartva_missing": 0,
                }
            return {}, {
                "metadata_missing": 0,
                "attachments_missing": 0,
                "legacy_attachment_rows": 0,
                "smartva_missing": 0,
            }

        with patch("app.tasks.sync_tasks._authorize_data_manager_form_sync"), \
            patch("app.tasks.sync_tasks._get_single_form_odk_client", return_value=object()), \
            patch("app.utils.va_odk_fetch_instance_ids", return_value=missing_ids), \
            patch("app.utils.va_odk_fetch_submissions_by_ids", side_effect=_fake_fetch), \
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral._upsert_form_submissions",
                side_effect=_fake_upsert,
            ), \
            patch("app.tasks.sync_tasks._build_repair_map_for_form", side_effect=_fake_build), \
            patch("app.tasks.sync_tasks._prepare_run_for_canonical_repair") as mock_prepare, \
            patch("app.tasks.sync_tasks.run_canonical_repair_batches_task.delay") as mock_repair, \
            patch("app.tasks.sync_tasks.finalize_canonical_repair_run_task.delay") as mock_finalize:
            run_single_form_backfill.run(form_id=self.form_id, triggered_by="backfill", user_id=None)

        self.assertEqual(mock_repair.call_count, 2)
        first_call = mock_repair.call_args_list[0].kwargs
        second_call = mock_repair.call_args_list[1].kwargs
        self.assertEqual(len(first_call["candidate_sids"]), 50)
        self.assertEqual(len(second_call["candidate_sids"]), 10)
        self.assertEqual(mock_prepare.call_count, 2)
        mock_finalize.assert_called_once()

        latest_run = db.session.scalar(
            sa.select(VaSyncRun).order_by(VaSyncRun.started_at.desc()).limit(1)
        )
        self.assertEqual(latest_run.status, "running")
        self.assertIsNone(latest_run.finished_at)

    def test_run_legacy_attachment_repair_delegates_to_canonical_engine_batches(self):
        media_dir = os.path.join(self._tmp_dir.name, self.form_id, "media")
        os.makedirs(media_dir, exist_ok=True)
        legacy_local_path = os.path.join(media_dir, "legacy-audit.csv")
        with open(legacy_local_path, "w", encoding="utf-8") as handle:
            handle.write("audit")
        legacy_sid = self._create_submission_with_attachment(
            filename="audit.csv",
            storage_name=None,
            local_path=legacy_local_path,
        )

        def _complete_latest_run(**_kwargs):
            latest_run = db.session.scalar(
                sa.select(VaSyncRun).order_by(VaSyncRun.started_at.desc()).limit(1)
            )
            latest_run.status = "success"
            latest_run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
            return {"downloaded": 1}

        with patch(
            "app.tasks.sync_tasks._run_canonical_repair_batches",
            side_effect=_complete_latest_run,
        ) as mock_repair:
            run_legacy_attachment_repair.run(triggered_by="legacy-repair", user_id=None)

        mock_repair.assert_called_once()
        self.assertIn(legacy_sid, mock_repair.call_args.kwargs["candidate_sids"])
        self.assertEqual(
            mock_repair.call_args.kwargs["trigger_source"],
            "legacy_attachment_repair",
        )
