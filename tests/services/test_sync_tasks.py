from unittest import TestCase
from unittest.mock import MagicMock, patch

from app import db
from app.models import VaForms


class SyncTaskBatchingTests(TestCase):
    def test_run_enrichment_sync_batch_releases_read_transaction_before_odk_calls(self):
        from app.tasks.sync_tasks import run_enrichment_sync_batch

        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM04"
        fake_form.project_id = "PROJ04"

        fake_rows = MagicMock()
        fake_rows.all.return_value = [("sid-1", {"KEY": "key-1"})]
        events: list[str] = []

        def fake_get(model, key):
            if model is VaForms and key == "FORM04":
                return fake_form
            return None

        with patch.object(db.session, "rollback", side_effect=lambda: events.append("rollback")):
            with patch.object(db.session, "get", side_effect=fake_get):
                with patch.object(db.session, "execute", return_value=fake_rows):
                    with patch.object(db.session, "expunge", side_effect=lambda entity: events.append(f"expunge:{getattr(entity, 'form_id', 'unknown')}")):
                        with patch.object(db.session, "commit", side_effect=lambda: events.append("commit")):
                            with patch("app.tasks.sync_tasks._log_progress", MagicMock()):
                                with patch("app.tasks.sync_tasks._get_single_form_odk_client", return_value=MagicMock()):
                                    with patch(
                                        "app.services.va_data_sync.va_data_sync_01_odkcentral._attach_all_odk_comments",
                                        side_effect=lambda *args, **kwargs: events.append("attach") or args[1],
                                    ):
                                        with patch(
                                            "app.services.va_data_sync.va_data_sync_01_odkcentral._finalize_enriched_submissions_for_form",
                                            side_effect=lambda *args, **kwargs: events.append("finalize") or 1,
                                        ):
                                            with patch("app.tasks.sync_tasks._finalize_repair_batch", MagicMock()):
                                                result = run_enrichment_sync_batch.run(
                                                    form_id="FORM04",
                                                    batch_map={"sid-1": {"instance_id": "key-1", "needs_metadata": True, "needs_attachments": False, "needs_smartva": False}},
                                                    remaining_batches=[],
                                                    run_id="run-111",
                                                    batch_index=1,
                                                    batch_total=1,
                                                )

        self.assertEqual(result["enriched"], 1)
        self.assertLess(events.index("rollback"), events.index("attach"))
        self.assertIn("expunge:FORM04", events)

    def test_dispatch_repair_batch_skips_enrich_for_attachment_only_batch(self):
        from app.tasks.sync_tasks import _dispatch_repair_batch

        batch_plan = {
            "sid-1": {
                "instance_id": "key-1",
                "needs_metadata": False,
                "needs_attachments": True,
                "needs_smartva": False,
            }
        }

        with patch("app.tasks.sync_tasks.run_enrichment_sync_batch.delay") as enrich_delay:
            with patch("app.tasks.sync_tasks.run_attachment_sync_batch.delay") as attachment_delay:
                with patch("app.tasks.sync_tasks.run_smartva_sync_batch.delay") as smartva_delay:
                    stage = _dispatch_repair_batch(
                        form_id="FORM01",
                        batch_map=batch_plan,
                        remaining_batches=[],
                        run_id="run-1",
                        batch_index=1,
                        batch_total=5,
                    )

        self.assertEqual(stage, "attachments")
        enrich_delay.assert_not_called()
        smartva_delay.assert_not_called()
        attachment_delay.assert_called_once()

    def test_dispatch_repair_batch_skips_to_smartva_for_smartva_only_batch(self):
        from app.tasks.sync_tasks import _dispatch_repair_batch

        batch_plan = {
            "sid-1": {
                "instance_id": "key-1",
                "needs_metadata": False,
                "needs_attachments": False,
                "needs_smartva": True,
            }
        }

        with patch("app.tasks.sync_tasks.run_enrichment_sync_batch.delay") as enrich_delay:
            with patch("app.tasks.sync_tasks.run_attachment_sync_batch.delay") as attachment_delay:
                with patch("app.tasks.sync_tasks.run_smartva_sync_batch.delay") as smartva_delay:
                    stage = _dispatch_repair_batch(
                        form_id="FORM01",
                        batch_map=batch_plan,
                        remaining_batches=[],
                        run_id="run-1",
                        batch_index=1,
                        batch_total=5,
                    )

        self.assertEqual(stage, "smartva")
        enrich_delay.assert_not_called()
        attachment_delay.assert_not_called()
        smartva_delay.assert_called_once()

    def test_schedule_enrichment_sync_splits_submissions_into_bounded_batches(self):
        from app.tasks.sync_tasks import (
            ENRICHMENT_SYNC_BATCH_SIZE,
            _schedule_enrichment_sync_for_form,
        )

        upserted_map = {f"sid-{index}": f"key-{index}" for index in range(101)}
        log_progress = MagicMock()

        fake_run = MagicMock()
        fake_execute = MagicMock()
        fake_execute.scalar_one.return_value = fake_run

        with patch.object(db.session, "execute", return_value=fake_execute):
            with patch.object(db.session, "commit", MagicMock()):
                with patch(
                    "app.tasks.sync_tasks.run_enrichment_sync_batch.delay",
                    side_effect=lambda **kwargs: kwargs,
                ) as batch_delay:
                    batch_count = _schedule_enrichment_sync_for_form(
                        "run-123",
                        "FORM01",
                        upserted_map,
                        log_progress,
                    )

        self.assertEqual(batch_count, 11)
        batch_delay.assert_called_once()
        batch_kwargs = batch_delay.call_args.kwargs
        self.assertEqual(batch_kwargs["form_id"], "FORM01")
        self.assertEqual(batch_kwargs["run_id"], "run-123")
        self.assertEqual(batch_kwargs["batch_index"], 1)
        self.assertEqual(batch_kwargs["batch_total"], 11)
        self.assertEqual(len(batch_kwargs["batch_map"]), ENRICHMENT_SYNC_BATCH_SIZE)
        self.assertEqual(len(batch_kwargs["remaining_batches"]), 10)
        self.assertEqual(len(batch_kwargs["remaining_batches"][0]), ENRICHMENT_SYNC_BATCH_SIZE)
        self.assertEqual(len(batch_kwargs["remaining_batches"][-1]), 1)
        log_progress.assert_called_once()
        self.assertIn("queued 11 batch(es)", log_progress.call_args.args[0])

    def test_schedule_attachment_sync_splits_submissions_into_bounded_batches(self):
        from app.tasks.sync_tasks import (
            ATTACHMENT_SYNC_BATCH_SIZE,
            _schedule_attachment_sync_for_form,
        )

        upserted_map = {f"sid-{index}": f"key-{index}" for index in range(24)}
        log_progress = MagicMock()

        fake_run = MagicMock()
        fake_execute = MagicMock()
        fake_execute.scalar_one.return_value = fake_run

        with patch.object(db.session, "execute", return_value=fake_execute):
            with patch.object(db.session, "commit", MagicMock()):
                with patch(
                    "app.tasks.sync_tasks.run_attachment_sync_batch.delay",
                    side_effect=lambda **kwargs: kwargs,
                ) as batch_delay:
                    batch_count = _schedule_attachment_sync_for_form(
                        "run-456",
                        "FORM02",
                        upserted_map,
                        log_progress,
                    )

        self.assertEqual(batch_count, 3)
        batch_delay.assert_called_once()
        batch_kwargs = batch_delay.call_args.kwargs
        self.assertEqual(batch_kwargs["form_id"], "FORM02")
        self.assertEqual(batch_kwargs["run_id"], "run-456")
        self.assertEqual(batch_kwargs["batch_index"], 1)
        self.assertEqual(batch_kwargs["batch_total"], 3)
        self.assertEqual(len(batch_kwargs["batch_map"]), ATTACHMENT_SYNC_BATCH_SIZE)
        self.assertEqual(len(batch_kwargs["remaining_batches"]), 2)
        self.assertEqual(len(batch_kwargs["remaining_batches"][-1]), 4)
        log_progress.assert_called_once()
        self.assertIn("queued 3 download batch(es)", log_progress.call_args.args[0])

    def test_run_attachment_sync_batch_uses_internal_finalize_helper(self):
        from app.tasks.sync_tasks import run_attachment_sync_batch

        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM03"

        def fake_get(model, key):
            if model is VaForms and key == "FORM03":
                return fake_form
            return None

        with patch.object(db.session, "rollback", MagicMock()):
            with patch.object(db.session, "get", side_effect=fake_get):
                with patch.object(db.session, "commit", MagicMock()):
                    with patch("app.tasks.sync_tasks._log_progress", MagicMock()):
                        with patch(
                            "app.utils.va_odk_sync_form_attachments",
                        ) as mocked_sync:
                            mocked_sync.return_value = {
                                "downloaded": 7,
                                "skipped": 1,
                                "errors": 0,
                            }
                            with patch(
                                "app.tasks.sync_tasks._finalize_repair_batch"
                            ) as mocked_finalize:
                                with patch(
                                    "app.services.workflow.state_store.get_submission_workflow_state",
                                    return_value="ready_for_coding",
                                ):
                                    result = run_attachment_sync_batch.run(
                                        form_id="FORM03",
                                        batch_map={
                                            "sid-1": {
                                                "instance_id": "key-1",
                                                "needs_metadata": False,
                                                "needs_attachments": True,
                                                "needs_smartva": False,
                                            },
                                            "sid-2": {
                                                "instance_id": "key-2",
                                                "needs_metadata": False,
                                                "needs_attachments": True,
                                                "needs_smartva": False,
                                            },
                                        },
                                        remaining_batches=[{"sid-3": "key-3"}],
                                        run_id="run-789",
                                        batch_index=2,
                                        batch_total=3,
                                    )

        self.assertEqual(result["downloaded"], 7)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["errors"], 0)
        mocked_finalize.assert_called_once_with(
            form_id="FORM03",
            run_id="run-789",
            batch_plan={
                "sid-1": {
                    "instance_id": "key-1",
                    "needs_metadata": False,
                    "needs_attachments": False,
                    "needs_smartva": False,
                },
                "sid-2": {
                    "instance_id": "key-2",
                    "needs_metadata": False,
                    "needs_attachments": False,
                    "needs_smartva": False,
                },
            },
            remaining_batches=[{"sid-3": "key-3"}],
            batch_index=2,
            batch_total=3,
            downloaded=7,
            skipped=1,
            errors=0,
            smartva_updated=0,
            error_messages=[],
        )

    def test_run_attachment_sync_batch_releases_read_transaction_before_download(self):
        from app.tasks.sync_tasks import run_attachment_sync_batch

        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM05"
        fake_form.project_id = "PROJ05"
        events: list[str] = []

        def fake_get(model, key):
            if model is VaForms and key == "FORM05":
                return fake_form
            return None

        with patch.object(db.session, "rollback", side_effect=lambda: events.append("rollback")):
            with patch.object(db.session, "get", side_effect=fake_get):
                with patch.object(db.session, "expunge", side_effect=lambda entity: events.append(f"expunge:{getattr(entity, 'form_id', 'unknown')}")):
                    with patch.object(db.session, "commit", MagicMock()):
                        with patch("app.tasks.sync_tasks._log_progress", MagicMock()):
                            with patch(
                                "app.utils.va_odk_sync_form_attachments",
                                side_effect=lambda *args, **kwargs: events.append("download") or {"downloaded": 1, "skipped": 0, "errors": 0},
                            ):
                                with patch("app.tasks.sync_tasks._finalize_repair_batch", MagicMock()):
                                    with patch(
                                        "app.services.workflow.state_store.get_submission_workflow_state",
                                        return_value="ready_for_coding",
                                    ):
                                        run_attachment_sync_batch.run(
                                            form_id="FORM05",
                                            batch_map={"sid-1": {"instance_id": "key-1", "needs_metadata": False, "needs_attachments": True, "needs_smartva": False}},
                                            remaining_batches=[],
                                            run_id="run-222",
                                            batch_index=1,
                                            batch_total=1,
                                        )

        self.assertLess(events.index("rollback"), events.index("download"))
        self.assertIn("expunge:FORM05", events)

    def test_run_smartva_sync_batch_releases_read_transaction_before_generation(self):
        from app.tasks.sync_tasks import run_smartva_sync_batch

        fake_form = MagicMock(spec=VaForms)
        fake_form.form_id = "FORM06"
        fake_form.project_id = "PROJ06"
        events: list[str] = []

        def fake_get(model, key):
            if model is VaForms and key == "FORM06":
                return fake_form
            return None

        with patch.object(db.session, "rollback", side_effect=lambda: events.append("rollback")):
            with patch.object(db.session, "get", side_effect=fake_get):
                with patch.object(db.session, "expunge", side_effect=lambda entity: events.append(f"expunge:{getattr(entity, 'form_id', 'unknown')}")):
                    with patch("app.tasks.sync_tasks._log_progress", MagicMock()):
                        with patch(
                            "app.services.smartva_service.generate_for_form",
                            side_effect=lambda *args, **kwargs: events.append("generate") or 2,
                        ):
                            with patch("app.tasks.sync_tasks._finalize_repair_batch", MagicMock()):
                                result = run_smartva_sync_batch.run(
                                    form_id="FORM06",
                                    batch_map={"sid-1": {"instance_id": "key-1", "needs_metadata": False, "needs_attachments": False, "needs_smartva": True}},
                                    remaining_batches=[],
                                    run_id="run-333",
                                    batch_index=1,
                                    batch_total=1,
                                )

        self.assertEqual(result["smartva_updated"], 2)
        self.assertLess(events.index("rollback"), events.index("generate"))
        self.assertIn("expunge:FORM06", events)
