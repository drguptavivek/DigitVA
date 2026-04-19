import uuid
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app import db
from app.models import VaForms


class SyncTaskBatchingTests(TestCase):
    def test_fetch_submissions_by_ids_applies_request_timeout(self):
        from app.utils.va_odk.va_odk_06_fetchsubmissions import (
            va_odk_fetch_submissions_by_ids,
        )

        client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"value": [{"__id": "uuid:one"}]}
        client.session.get.return_value = response
        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM00"
        fake_form.project_id = "PROJ00"
        fake_form.odk_project_id = "1"
        fake_form.odk_form_id = "FORM00_ODK"

        records = va_odk_fetch_submissions_by_ids(
            fake_form,
            ["uuid:one"],
            client=client,
        )

        self.assertEqual(len(records), 1)
        _, kwargs = client.session.get.call_args
        self.assertEqual(kwargs["timeout"], (1.0, 5.0))

    def test_refresh_batch_plan_after_enrichment_suppresses_normal_repair_for_upstream_changed(self):
        from app.tasks.sync_tasks import _refresh_batch_plan_after_enrichment

        batch_plan = {
            "sid-1": {
                "instance_id": "key-1",
                "needs_metadata": True,
                "needs_attachments": True,
                "needs_smartva": True,
                "payload_revalidated": False,
                "legacy_attachment_rows": 0,
            }
        }

        with patch(
            "app.tasks.sync_tasks._build_repair_map_for_form",
            return_value=(
                {
                    "sid-1": {
                        "instance_id": "key-1",
                        "needs_metadata": False,
                        "needs_attachments": True,
                        "needs_smartva": True,
                        "legacy_attachment_rows": 0,
                    }
                },
                {
                    "metadata_missing": 0,
                    "attachments_missing": 1,
                    "smartva_missing": 1,
                    "legacy_attachment_rows": 0,
                },
            ),
        ):
            with patch(
                "app.services.workflow.state_store.get_submission_workflow_state",
                return_value="finalized_upstream_changed",
            ):
                refreshed_plan, summary, upstream_changed = _refresh_batch_plan_after_enrichment(
                    form_id="FORM01",
                    batch_plan=batch_plan,
                    raw_submissions=[{"sid": "sid-1", "KEY": "key-1"}],
                    upserted_map={"sid-1": "key-1"},
                )

        self.assertEqual(upstream_changed, 1)
        self.assertEqual(summary["attachments_missing"], 1)
        self.assertEqual(summary["smartva_missing"], 1)
        self.assertTrue(refreshed_plan["sid-1"]["payload_revalidated"])
        self.assertFalse(refreshed_plan["sid-1"]["needs_attachments"])
        self.assertFalse(refreshed_plan["sid-1"]["needs_smartva"])

    def test_run_canonical_repair_batches_task_delegates_to_helper(self):
        from app.tasks.sync_tasks import run_canonical_repair_batches_task

        with patch(
            "app.tasks.sync_tasks._run_canonical_repair_batches",
            return_value={"downloaded": 3},
        ) as mocked_helper:
            result = run_canonical_repair_batches_task.run(
                run_id="run-123",
                form_id="FORM01",
                candidate_sids=["sid-1", "sid-2"],
                trigger_source="odk_sync",
                force_attachment_redownload=False,
            )

        self.assertEqual(result, {"downloaded": 3})
        mocked_helper.assert_called_once()
        self.assertEqual(mocked_helper.call_args.kwargs["label"], "FORM01")
        self.assertEqual(mocked_helper.call_args.kwargs["candidate_sids"], ["sid-1", "sid-2"])
        self.assertEqual(mocked_helper.call_args.kwargs["trigger_source"], "odk_sync")

    def test_run_odk_sync_dispatcher_queues_canonical_repair_batches_task(self):
        from app.tasks.sync_tasks import run_odk_sync

        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM01"

        def fake_data_sync(*, log_progress, enrichment_sync_dispatcher):
            enrichment_sync_dispatcher(
                fake_form,
                {"sid-1": "key-1", "sid-2": "key-2"},
                log_progress,
            )
            return {
                "added": 4,
                "updated": 2,
                "smartva_updated": 0,
                "enrichment_sync_forms_enqueued": 1,
                "attachment_sync_forms_enqueued": 0,
                "failed_forms": [],
            }

        with patch(
            "app.services.va_data_sync.va_data_sync_01_odkcentral.va_data_sync_odkcentral",
            side_effect=fake_data_sync,
        ):
            with patch(
                "app.tasks.sync_tasks.run_canonical_repair_batches_task.delay"
            ) as mocked_delay:
                with patch("app.tasks.sync_tasks._prepare_run_for_canonical_repair") as mock_prepare:
                    with patch("app.tasks.sync_tasks.finalize_canonical_repair_run_task.delay") as mock_finalize:
                        with patch("app.tasks.sync_tasks.cleanup_stale_runs"):
                            run_odk_sync.run(triggered_by="manual", user_id=None)

        mocked_delay.assert_called_once()
        mock_prepare.assert_called_once()
        mock_finalize.assert_called_once()
        self.assertEqual(mocked_delay.call_args.kwargs["form_id"], "FORM01")
        self.assertEqual(mocked_delay.call_args.kwargs["candidate_sids"], ["sid-1", "sid-2"])
        self.assertEqual(mocked_delay.call_args.kwargs["trigger_source"], "odk_sync")

    def test_run_single_submission_sync_queues_canonical_repair_batches_task(self):
        from app.tasks.sync_tasks import run_single_submission_sync

        run_id = uuid.uuid4()
        fake_submission = MagicMock()
        fake_submission.va_form_id = "FORM01"
        fake_submission.va_sync_issue_code = None
        fake_submission.va_sync_issue_detail = None
        fake_submission.va_sync_issue_updated_at = None

        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM01"

        fake_run = MagicMock()
        fake_run.sync_run_id = run_id

        def fake_get(model, key):
            model_name = getattr(model, "__name__", "")
            if model_name == "VaSubmissions" and key == "sid-1":
                return fake_submission
            if model is VaForms and key == "FORM01":
                return fake_form
            if model_name == "VaSyncRun" and key == run_id:
                return fake_run
            return None

        def fake_add(obj):
            if obj.__class__.__name__ == "VaSyncRun":
                obj.sync_run_id = run_id

        def fake_upsert(_va_form, _records, amended_sids, upserted_map, **_kwargs):
            upserted_map["sid-1"] = "instance-1"
            return (0, 1, 0, 0)

        with patch.object(db.session, "get", side_effect=fake_get):
            with patch.object(db.session, "add", side_effect=fake_add):
                with patch.object(db.session, "commit", MagicMock()):
                    with patch("app.tasks.sync_tasks._log_progress", MagicMock()):
                        with patch("app.tasks.sync_tasks._authorize_data_manager_submission_sync"):
                            with patch("app.tasks.sync_tasks._get_single_form_odk_client", return_value=object()):
                                with patch(
                                    "app.services.odk_review_service.resolve_odk_instance_id",
                                    return_value="instance-1",
                                ):
                                    with patch(
                                        "app.utils.va_odk_fetch_submissions_by_ids",
                                        return_value=[{"sid": "sid-1", "KEY": "instance-1"}],
                                    ):
                                        with patch(
                                            "app.utils.va_odk_fetch_instance_ids",
                                            return_value=["instance-1"],
                                        ):
                                            with patch(
                                                "app.services.va_data_sync.va_data_sync_01_odkcentral._upsert_form_submissions",
                                                side_effect=fake_upsert,
                                            ):
                                                with patch(
                                                    "app.services.va_data_sync.va_data_sync_01_odkcentral._mark_form_sync_issues"
                                                ):
                                                    with patch(
                                                        "app.tasks.sync_tasks.run_canonical_repair_batches_task.delay"
                                                    ) as mocked_delay:
                                                        with patch("app.tasks.sync_tasks._prepare_run_for_canonical_repair") as mock_prepare:
                                                            with patch("app.tasks.sync_tasks.finalize_canonical_repair_run_task.delay") as mock_finalize:
                                                                run_single_submission_sync.run(
                                                                    va_sid="sid-1",
                                                                    triggered_by="manual",
                                                                    user_id=None,
                                                                )

        mocked_delay.assert_called_once()
        mock_prepare.assert_called_once()
        mock_finalize.assert_called_once()
        self.assertEqual(mocked_delay.call_args.kwargs["form_id"], "FORM01")
        self.assertEqual(mocked_delay.call_args.kwargs["candidate_sids"], ["sid-1"])
        self.assertEqual(
            mocked_delay.call_args.kwargs["trigger_source"],
            "single_submission_sync",
        )
