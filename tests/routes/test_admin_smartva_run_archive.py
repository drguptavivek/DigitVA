"""Admin SmartVA run archive endpoints.

The block lives in the Attachment Management panel because it shares the
bucket. These tests cover the shape the block depends on, that the action
enqueues the real Celery task with a bound limit, and that both are admin-only
and CSRF-protected.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaSmartvaFormRun,
    VaStatuses,
)
from tests.base import BaseTestCase


class AdminSmartvaRunArchiveTests(BaseTestCase):
    PROJECT_ID = "SVAP01"
    SITE_ID = "SP01"
    FORM_ID = "SVAP01SP0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if not db.session.get(VaProjectMaster, cls.PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="SmartVA Archive Panel Project",
                project_nickname="SvaPanel",
                project_status=VaStatuses.active,
            ))
        if not db.session.get(VaResearchProjects, cls.PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="SmartVA Archive Panel Project",
                project_nickname="SvaPanel",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()
        if not db.session.get(VaSites, cls.SITE_ID):
            db.session.add(VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="SmartVA Archive Panel Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
            db.session.flush()
        if not db.session.get(VaForms, cls.FORM_ID):
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="SVAP_ODK",
                odk_project_id="92",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        now = datetime.now(timezone.utc)
        db.session.add(VaSmartvaFormRun(
            form_run_id=uuid.uuid4(),
            form_id=self.FORM_ID,
            project_id=self.PROJECT_ID,
            trigger_source="test",
            pending_sid_count=1,
            outcome=VaSmartvaFormRun.OUTCOME_SUCCESS,
            run_started_at=now,
            run_completed_at=now,
        ))
        db.session.flush()

    # -- overview ----------------------------------------------------------

    def test_overview_returns_the_block_shape(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/admin/api/smartva/run-archive/overview")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["key_prefix"], "smartva_runs/")
        self.assertEqual(payload["keep_local_days"], 0)
        self.assertIn("store", payload)
        self.assertIn("local_bytes", payload)
        self.assertIn("local_run_dirs", payload)
        self.assertIn("last_failure", payload)
        for state in VaSmartvaFormRun.ARCHIVE_STATES:
            self.assertIn(state, payload["counts"])

    def test_overview_scopes_to_one_form(self):
        self._login(str(self.base_admin_id))
        response = self.client.get(
            "/admin/api/smartva/run-archive/overview?form_id=" + self.FORM_ID
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["form_id"], self.FORM_ID)
        self.assertEqual(
            payload["counts"][VaSmartvaFormRun.ARCHIVE_STATE_LOCAL], 1
        )

    def test_overview_is_admin_only(self):
        self._login(str(self.base_coder_id))
        self.assertEqual(
            self.client.get(
                "/admin/api/smartva/run-archive/overview"
            ).status_code,
            403,
        )

    # -- action ------------------------------------------------------------

    def test_archive_action_queues_the_bounded_task(self):
        from app.tasks.sync_tasks import SMARTVA_ARCHIVE_TASK_LIMIT

        self._login(str(self.base_admin_id))
        with patch("app.tasks.sync_tasks.run_smartva_run_archive.delay") as delay:
            delay.return_value = type("T", (), {"id": "task-sva"})()
            response = self.client.post(
                "/admin/api/smartva/run-archive/archive-pending",
                json={"form_id": self.FORM_ID},
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["form_id"], self.FORM_ID)
        self.assertEqual(payload["limit"], SMARTVA_ARCHIVE_TASK_LIMIT)
        delay.assert_called_once()
        self.assertEqual(delay.call_args.kwargs["limit"], SMARTVA_ARCHIVE_TASK_LIMIT)
        self.assertTrue(delay.call_args.kwargs["delete_local"])

    def test_archive_action_is_admin_only(self):
        self._login(str(self.base_coder_id))
        response = self.client.post(
            "/admin/api/smartva/run-archive/archive-pending",
            json={},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_archive_action_requires_csrf(self):
        self._login(str(self.base_admin_id))
        response = self.client.post(
            "/admin/api/smartva/run-archive/archive-pending", json={}
        )
        self.assertEqual(response.status_code, 400)

    def test_panel_carries_the_run_archive_block(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/admin/panels/attachments")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"sva-archive-wrap", response.data)
        self.assertIn(b"/admin/api/smartva/run-archive/overview", response.data)
