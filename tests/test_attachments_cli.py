"""Tests for ``flask attachments remote-delivery``.

The CLI is the primary rollout switch for Phase 4a of
docs/planning/s3-attachment-plan.md.
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
