"""Characterization: the repair helpers and task enqueues services share with
app.tasks.sync_tasks (digitva-r8nh.13 wave 6).

Pins the helpers' behaviour and that sync_tasks and
open_submission_repair_service see the same function objects, so a patch on
either module name keeps reaching the code it reached before the move.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import open_submission_repair_service
from app.tasks import sync_tasks

HELPERS = (
    "_build_repair_map_for_form",
    "_get_single_form_odk_client",
    "_normalize_batch_plan",
    "_refresh_batch_plan_after_enrichment",
    "_release_read_transaction",
)


class TestSharedRepairHelpers(unittest.TestCase):
    def test_service_and_tasks_share_the_same_helper_objects(self):
        for name in HELPERS:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(open_submission_repair_service, name),
                    getattr(sync_tasks, name),
                )

    def test_normalize_batch_plan_shapes(self):
        plan = sync_tasks._normalize_batch_plan({
            "sid-dict": {"KEY": "uuid:k", "needs_attachments": 1, "legacy_attachment_rows": "3"},
            "sid-legacy": "uuid:legacy",
            "sid-none": None,
        })
        self.assertEqual(plan["sid-dict"], {
            "instance_id": "uuid:k",
            "needs_metadata": False,
            "needs_attachments": True,
            "needs_smartva": False,
            "payload_revalidated": False,
            "legacy_attachment_rows": 3,
        })
        self.assertEqual(plan["sid-legacy"], {
            "instance_id": "uuid:legacy",
            "needs_metadata": True,
            "needs_attachments": True,
            "needs_smartva": True,
            "payload_revalidated": False,
            "legacy_attachment_rows": 0,
        })
        self.assertEqual(plan["sid-none"]["instance_id"], "")
        self.assertEqual(sync_tasks._normalize_batch_plan(None), {})

    def test_release_read_transaction_expunges_rows_then_rolls_back(self):
        session = MagicMock()
        session.expunge.side_effect = [RuntimeError("detached"), None]
        first, second = object(), object()
        with patch("app.db.session", session):
            sync_tasks._release_read_transaction(first, None, second)
        self.assertEqual(
            [c.args[0] for c in session.expunge.call_args_list], [first, second]
        )
        session.rollback.assert_called_once_with()

    def test_single_form_client_refuses_a_form_without_active_mapping(self):
        form = SimpleNamespace(form_id="FORM01", project_id="PROJ01")
        with patch(
            "app.services.runtime_form_sync_service.get_active_mapping_for_form",
            return_value=None,
        ), patch("app.utils.va_odk_clientsetup") as setup:
            with self.assertRaisesRegex(
                ValueError, r"^Active runtime mapping not found for form 'FORM01'\.$"
            ):
                sync_tasks._get_single_form_odk_client(form)
        setup.assert_not_called()

    def test_single_form_client_uses_the_form_project(self):
        form = SimpleNamespace(form_id="FORM01", project_id="PROJ01")
        with patch(
            "app.services.runtime_form_sync_service.get_active_mapping_for_form",
            return_value=object(),
        ), patch("app.utils.va_odk_clientsetup", return_value="client") as setup:
            self.assertEqual(sync_tasks._get_single_form_odk_client(form), "client")
        setup.assert_called_once_with(project_id="PROJ01")


if __name__ == "__main__":
    unittest.main()
