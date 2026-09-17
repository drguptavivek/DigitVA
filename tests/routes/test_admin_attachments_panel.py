"""Admin Attachment Management endpoints.

The panel is a view over ``app/services/attachment_service.py``: these tests
cover the contract the panel depends on (shape, scope), that the two actions
enqueue the real tasks, and that both are admin-only and CSRF-protected.
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
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service as svc
from tests.base import BaseTestCase


class AdminAttachmentsPanelTests(BaseTestCase):
    PROJECT_ID = "ATTP01"
    SITE_ID = "AP01"
    FORM_ID = "ATTP01AP0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if not db.session.get(VaProjectMaster, cls.PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment Panel Project",
                project_nickname="AttPanel",
                project_status=VaStatuses.active,
            ))
        if not db.session.get(VaResearchProjects, cls.PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment Panel Project",
                project_nickname="AttPanel",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()
        if not db.session.get(VaSites, cls.SITE_ID):
            db.session.add(VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Attachment Panel Site",
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
                odk_form_id="ATTP_ODK",
                odk_project_id="96",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        submission = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=self.FORM_ID,
            va_data_collector="c",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=1,
            va_deceased_gender="male",
            va_uniqueid_masked="X",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        db.session.add(VaSubmissionAttachments(
            va_sid=submission.va_sid,
            filename="photo.jpg",
            storage_name=uuid.uuid4().hex + ".jpg",
            mime_type="image/jpeg",
            exists_on_odk=True,
            source_state=svc.SOURCE_AVAILABLE,
        ))
        db.session.flush()

    # -- overview ----------------------------------------------------------

    def test_overview_returns_the_panel_shape(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/admin/api/attachments/overview")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("store", payload)
        self.assertIn("projects", payload)
        self.assertIn("delivery_counters", payload)
        self.assertIn("source_error_categories", payload)
        form = next(f for f in payload["forms"] if f["form_id"] == self.FORM_ID)
        self.assertEqual(form["source_state"][svc.SOURCE_AVAILABLE], 1)

    def test_overview_scopes_to_one_project(self):
        self._login(str(self.base_admin_id))
        response = self.client.get(
            "/admin/api/attachments/overview?project_id=" + self.PROJECT_ID
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["project_ids"], [self.PROJECT_ID])
        self.assertTrue(
            all(f["project_id"] == self.PROJECT_ID for f in payload["forms"])
        )

    def test_overview_is_admin_only(self):
        self._login(str(self.base_coder_id))
        self.assertEqual(
            self.client.get("/admin/api/attachments/overview").status_code, 403
        )

    # -- actions -----------------------------------------------------------

    def test_repair_action_queues_the_task_and_returns_a_run_id(self):
        self._login(str(self.base_admin_id))
        with patch(
            "app.tasks.sync_tasks.run_form_attachment_repair.delay"
        ) as delay:
            delay.return_value = type("T", (), {"id": "task-1"})()
            response = self.client.post(
                f"/admin/api/attachments/forms/{self.FORM_ID}/repair",
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["form_id"], self.FORM_ID)
        self.assertTrue(payload["run_id"])
        delay.assert_called_once()
        self.assertEqual(delay.call_args.kwargs["form_id"], self.FORM_ID)

    def test_repair_action_rejects_an_unknown_form(self):
        self._login(str(self.base_admin_id))
        response = self.client.post(
            "/admin/api/attachments/forms/NOSUCHFORM/repair",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_repair_action_requires_csrf(self):
        self._login(str(self.base_admin_id))
        response = self.client.post(
            f"/admin/api/attachments/forms/{self.FORM_ID}/repair"
        )
        self.assertEqual(response.status_code, 400)

    def test_integrity_action_queues_the_task(self):
        self._login(str(self.base_admin_id))
        with patch(
            "app.tasks.sync_tasks.run_attachment_integrity_check.delay"
        ) as delay:
            delay.return_value = type("T", (), {"id": "task-2"})()
            response = self.client.post(
                "/admin/api/attachments/integrity-check",
                json={"form_id": self.FORM_ID},
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["form_id"], self.FORM_ID)
        delay.assert_called_once()

    def test_integrity_action_is_admin_only(self):
        self._login(str(self.base_coder_id))
        response = self.client.post(
            "/admin/api/attachments/integrity-check",
            json={},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_integrity_action_requires_csrf(self):
        self._login(str(self.base_admin_id))
        response = self.client.post(
            "/admin/api/attachments/integrity-check", json={}
        )
        self.assertEqual(response.status_code, 400)

    def test_panel_renders_for_an_admin(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/admin/panels/attachments")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"panel-attachments", response.data)
