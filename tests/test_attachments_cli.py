"""Tests for the ``flask attachments`` commands.

Each command is a thin wrapper over ``app/services/attachment_service.py``;
these tests assert the wrapper reaches the service and prints what an operator
needs, not that the service is correct — that lives in
``tests/services/test_attachment_lifecycle.py``.
"""

from app import db
from app.models import VaProjectMaster, VaStatuses
from tests.base import BaseTestCase


class AttachmentsCliTests(BaseTestCase):
    PROJECT_ID = "ATCL01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = cls.app.test_cli_runner()
        if not db.session.get(VaProjectMaster, cls.PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment CLI Project",
                project_nickname="AttCli",
                project_status=VaStatuses.active,
            ))
        db.session.commit()

    def tearDown(self):
        project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        if project is not None:
            project.attachment_central_fetch_enabled = False
            db.session.commit()
        super().tearDown()

    def _run(self, *args):
        return self.runner.invoke(args=["attachments", "central-fetch", *args])

    def test_status_is_the_default_and_reports_the_stored_value(self):
        result = self._run(self.PROJECT_ID)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("attachment_central_fetch_enabled=False", result.output)
        self.assertFalse(
            db.session.get(
                VaProjectMaster, self.PROJECT_ID
            ).attachment_central_fetch_enabled
        )

    def test_enable_then_disable_round_trips(self):
        result = self._run(self.PROJECT_ID, "--enable")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("attachment_central_fetch_enabled=True", result.output)
        self.assertTrue(
            db.session.get(
                VaProjectMaster, self.PROJECT_ID
            ).attachment_central_fetch_enabled
        )

        result = self._run(self.PROJECT_ID, "--disable")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("attachment_central_fetch_enabled=False", result.output)
        self.assertFalse(
            db.session.get(
                VaProjectMaster, self.PROJECT_ID
            ).attachment_central_fetch_enabled
        )

    def test_unknown_project_fails(self):
        result = self._run("NOPE99", "--enable")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not found", result.output)


class AttachmentsOverviewCliTests(AttachmentsCliTests):
    """``flask attachments overview`` prints the panel's own figures."""

    def test_overview_reports_the_store_and_the_scope(self):
        result = self.runner.invoke(args=["attachments", "overview"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Attachment store:", result.output)
        self.assertIn("Scope: ALL", result.output)
        self.assertIn("Delivery counters", result.output)

    def test_overview_scopes_to_one_project(self):
        from unittest.mock import patch

        with patch(
            "app.services.attachment_service.attachment_management_overview",
            return_value={
                "store": "local",
                "project_ids": [self.PROJECT_ID],
                "projects": [],
                "forms": [],
                "delivery_counters": {},
                "source_error_categories": [],
            },
        ) as overview:
            result = self.runner.invoke(
                args=["attachments", "overview", "--project-id", self.PROJECT_ID.lower()]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        overview.assert_called_once_with([self.PROJECT_ID])
        self.assertIn(f"Scope: {self.PROJECT_ID}", result.output)
