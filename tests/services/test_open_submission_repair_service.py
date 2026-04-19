import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from app.models import VaForms, VaSubmissions
from app.services.open_submission_repair_service import repair_submission_for_coding_open


class TestOpenSubmissionRepairService(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.app.config["APP_DATA"] = self.tmp_dir.name
        self.submission = SimpleNamespace(va_sid="SID-1", va_form_id="FORM-1")
        self.form = SimpleNamespace(
            form_id="FORM-1",
            project_id="PROJ01",
            odk_form_id="ODK-FORM",
            odk_project_id="11",
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _db_get(self, model, key):
        if model is VaSubmissions and key == "SID-1":
            return self.submission
        if model is VaForms and key == "FORM-1":
            return self.form
        return None

    def test_returns_without_odk_calls_when_no_current_payload_gaps(self):
        with self.app.app_context(), \
            patch("app.services.open_submission_repair_service.db.session.get", side_effect=self._db_get), \
            patch("app.services.open_submission_repair_service._build_repair_map_for_form", return_value=({}, {"attachments_missing": 0})), \
            patch("app.services.open_submission_repair_service.va_odk_fetch_submissions_by_ids") as mock_fetch:
            result = repair_submission_for_coding_open("SID-1")

        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "no-gaps")
        mock_fetch.assert_not_called()

    def test_holds_submission_out_of_ordinary_repair_after_upstream_change_detection(self):
        initial_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": True,
                "needs_smartva": True,
            }
        }
        refreshed_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": False,
                "needs_smartva": False,
                "payload_revalidated": True,
            }
        }

        with self.app.app_context(), \
            patch("app.services.open_submission_repair_service.db.session.get", side_effect=self._db_get), \
            patch("app.services.open_submission_repair_service.db.session.commit"), \
            patch("app.services.open_submission_repair_service._build_repair_map_for_form", return_value=(initial_plan, {"attachments_missing": 1})), \
            patch("app.services.open_submission_repair_service._load_payload_rows", return_value=[("SID-1", {"KEY": "uuid:one"})]), \
            patch("app.services.open_submission_repair_service._get_single_form_odk_client", return_value=object()), \
            patch("app.services.open_submission_repair_service._release_read_transaction"), \
            patch("app.services.open_submission_repair_service.va_odk_fetch_submissions_by_ids", return_value=[{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._attach_all_odk_comments", side_effect=lambda *_args, **_kwargs: [{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._finalize_enriched_submissions_for_form", return_value=1), \
            patch(
                "app.services.open_submission_repair_service._refresh_batch_plan_after_enrichment",
                return_value=(refreshed_plan, {"attachments_missing": 0, "smartva_missing": 0}, 1),
            ), \
            patch("app.services.open_submission_repair_service.va_odk_sync_form_attachments") as mock_attachments, \
            patch("app.services.open_submission_repair_service.smartva_service.generate_for_submission") as mock_smartva:
            result = repair_submission_for_coding_open("SID-1")

        self.assertTrue(result["attempted"])
        self.assertTrue(result["upstream_changed_held"])
        mock_attachments.assert_not_called()
        mock_smartva.assert_not_called()

    def test_repairs_attachments_and_smartva_for_one_submission(self):
        initial_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": True,
                "needs_smartva": True,
            }
        }
        post_enrichment_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": True,
                "needs_smartva": True,
                "payload_revalidated": True,
            }
        }
        post_attachment_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": False,
                "needs_smartva": True,
                "payload_revalidated": True,
            }
        }

        with self.app.app_context(), \
            patch("app.services.open_submission_repair_service.db.session.get", side_effect=self._db_get), \
            patch("app.services.open_submission_repair_service.db.session.commit"), \
            patch("app.services.open_submission_repair_service._build_repair_map_for_form", return_value=(initial_plan, {"attachments_missing": 1, "smartva_missing": 1})), \
            patch("app.services.open_submission_repair_service._load_payload_rows", return_value=[("SID-1", {"KEY": "uuid:one"})]), \
            patch("app.services.open_submission_repair_service._get_single_form_odk_client", return_value=object()), \
            patch("app.services.open_submission_repair_service._release_read_transaction"), \
            patch("app.services.open_submission_repair_service.va_odk_fetch_submissions_by_ids", return_value=[{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._attach_all_odk_comments", side_effect=lambda *_args, **_kwargs: [{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._finalize_enriched_submissions_for_form", return_value=1), \
            patch(
                "app.services.open_submission_repair_service._refresh_batch_plan_after_enrichment",
                side_effect=[
                    (post_enrichment_plan, {"attachments_missing": 1, "smartva_missing": 1}, 0),
                    (post_attachment_plan, {"attachments_missing": 0, "smartva_missing": 1}, 0),
                ],
            ), \
            patch(
                "app.services.open_submission_repair_service.va_odk_sync_form_attachments",
                return_value={
                    "downloaded": 2,
                    "non_audit_downloaded": 1,
                    "audit_downloaded": 1,
                },
            ) as mock_attachments, \
            patch("app.services.open_submission_repair_service.get_submission_workflow_state", return_value="attachment_sync_pending"), \
            patch("app.services.open_submission_repair_service.mark_attachment_sync_completed") as mock_attachment_transition, \
            patch("app.services.open_submission_repair_service.smartva_service.generate_for_submission", return_value=1) as mock_smartva:
            result = repair_submission_for_coding_open("SID-1")

        self.assertTrue(result["attempted"])
        self.assertEqual(result["metadata_enriched"], 1)
        self.assertEqual(result["attachments_downloaded"], 2)
        self.assertEqual(result["non_audit_downloaded"], 1)
        self.assertEqual(result["audit_downloaded"], 1)
        self.assertEqual(result["smartva_generated"], 1)
        self.assertTrue(result["needs_smartva_after_repair"])
        mock_attachments.assert_called_once()
        mock_attachment_transition.assert_called_once()
        mock_smartva.assert_called_once_with("SID-1", trigger_source="coding_open_repair")

    def test_can_skip_inline_smartva_and_return_batch_candidate_signal(self):
        from app.services.open_submission_repair_service import repair_submission_current_payload

        initial_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": False,
                "needs_smartva": True,
            }
        }
        post_enrichment_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": False,
                "needs_smartva": True,
                "payload_revalidated": True,
            }
        }

        with self.app.app_context(), \
            patch("app.services.open_submission_repair_service.db.session.get", side_effect=self._db_get), \
            patch("app.services.open_submission_repair_service.db.session.commit"), \
            patch("app.services.open_submission_repair_service._build_repair_map_for_form", return_value=(initial_plan, {"attachments_missing": 0, "smartva_missing": 1})), \
            patch("app.services.open_submission_repair_service._load_payload_rows", return_value=[("SID-1", {"KEY": "uuid:one"})]), \
            patch("app.services.open_submission_repair_service._get_single_form_odk_client", return_value=object()), \
            patch("app.services.open_submission_repair_service._release_read_transaction"), \
            patch("app.services.open_submission_repair_service.va_odk_fetch_submissions_by_ids", return_value=[{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._attach_all_odk_comments", side_effect=lambda *_args, **_kwargs: [{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._finalize_enriched_submissions_for_form", return_value=1), \
            patch(
                "app.services.open_submission_repair_service._refresh_batch_plan_after_enrichment",
                return_value=(post_enrichment_plan, {"attachments_missing": 0, "smartva_missing": 1}, 0),
            ), \
            patch("app.services.open_submission_repair_service.get_submission_workflow_state", return_value="smartva_pending"), \
            patch("app.services.open_submission_repair_service.smartva_service.generate_for_submission") as mock_smartva:
            result = repair_submission_current_payload(
                "SID-1",
                trigger_source="test-batch",
                run_smartva=False,
            )

        self.assertTrue(result["attempted"])
        self.assertEqual(result["smartva_generated"], 0)
        self.assertTrue(result["needs_smartva_after_repair"])
        mock_smartva.assert_not_called()

    def test_advances_directly_to_ready_when_current_payload_smartva_already_exists(self):
        initial_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": True,
                "needs_smartva": False,
            }
        }
        post_enrichment_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": True,
                "needs_smartva": False,
                "payload_revalidated": True,
            }
        }
        post_attachment_plan = {
            "SID-1": {
                "instance_id": "uuid:one",
                "needs_metadata": False,
                "needs_attachments": False,
                "needs_smartva": False,
                "payload_revalidated": True,
            }
        }

        with self.app.app_context(), \
            patch("app.services.open_submission_repair_service.db.session.get", side_effect=self._db_get), \
            patch("app.services.open_submission_repair_service.db.session.commit"), \
            patch("app.services.open_submission_repair_service._build_repair_map_for_form", return_value=(initial_plan, {"attachments_missing": 1, "smartva_missing": 0})), \
            patch("app.services.open_submission_repair_service._load_payload_rows", return_value=[("SID-1", {"KEY": "uuid:one"})]), \
            patch("app.services.open_submission_repair_service._get_single_form_odk_client", return_value=object()), \
            patch("app.services.open_submission_repair_service._release_read_transaction"), \
            patch("app.services.open_submission_repair_service.va_odk_fetch_submissions_by_ids", return_value=[{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._attach_all_odk_comments", side_effect=lambda *_args, **_kwargs: [{"sid": "SID-1", "KEY": "uuid:one"}]), \
            patch("app.services.open_submission_repair_service._finalize_enriched_submissions_for_form", return_value=1), \
            patch(
                "app.services.open_submission_repair_service._refresh_batch_plan_after_enrichment",
                side_effect=[
                    (post_enrichment_plan, {"attachments_missing": 1, "smartva_missing": 0}, 0),
                    (post_attachment_plan, {"attachments_missing": 0, "smartva_missing": 0}, 0),
                ],
            ), \
            patch(
                "app.services.open_submission_repair_service.va_odk_sync_form_attachments",
                return_value={
                    "downloaded": 1,
                    "non_audit_downloaded": 1,
                    "audit_downloaded": 0,
                },
            ) as mock_attachments, \
            patch(
                "app.services.open_submission_repair_service.get_submission_workflow_state",
                side_effect=["attachment_sync_pending", "smartva_pending", "smartva_pending"],
            ), \
            patch("app.services.open_submission_repair_service.mark_attachment_sync_completed") as mock_attachment_transition, \
            patch("app.services.open_submission_repair_service.mark_smartva_completed") as mock_smartva_transition, \
            patch("app.services.open_submission_repair_service.smartva_service.generate_for_submission") as mock_smartva:
            result = repair_submission_for_coding_open("SID-1")

        self.assertTrue(result["attempted"])
        self.assertEqual(result["attachments_downloaded"], 1)
        mock_attachments.assert_called_once()
        mock_attachment_transition.assert_called_once()
        mock_smartva_transition.assert_called_once()
        mock_smartva.assert_not_called()
