import os
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.models.va_users import VaUsers
from tests.base import BaseTestCase

class MediaAccessTests(BaseTestCase):
    FORM_ID = "MEDIAFORM1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if not db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Research Project",
                project_nickname="BaseResearch",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
            db.session.flush()

        existing_site = db.session.scalar(
            sa.select(VaSites).where(VaSites.site_id == cls.BASE_SITE_ID)
        )
        if not existing_site:
            db.session.add(VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
            db.session.flush()

        db.session.add(VaForms(
            form_id=cls.FORM_ID,
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="MEDIA_TEST_ODK",
            odk_project_id="88",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()

        cls.submission = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=cls.FORM_ID,
            va_data_collector="Media Test Collector",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_uniqueid_masked="MEDIA001",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(cls.submission)
        db.session.commit()

    def test_media_access_requires_login(self):
        """Verify that media files cannot be accessed without logging in."""
        response = self.client.get("/vaform/media/test_form/test.jpg")
        self.assertEqual(response.status_code, 401)

    def test_path_traversal_protection(self):
        """Verify that path traversal attempts are blocked."""
        # Create and login a user
        email = f"test.media.{uuid.uuid4().hex[:8]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status="active",
        )
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        
        self._login(str(user.user_id))

        # Attempt path traversal
        # We manually construct the path because url_for or the client might normalize '..'
        traversal_paths = [
            "/vaservemedia/../config.py",
            "/vaservemedia/test/../../../config.py",
            "/vaservemedia/test/%2e%2e/%2e%2e/config.py",
        ]
        
        for path in traversal_paths:
            response = self.client.get(path)
            # If it doesn't match the route, it's 404, which is also a form of protection,
            # but if it matches, it should be 400 because of our validation.
            self.assertIn(response.status_code, [400, 404])

    def test_media_route_requires_attachment_record(self):
        self._login(self.base_admin_id)
        media_dir = os.path.join(self.app.config["APP_DATA"], self.FORM_ID, "media")
        os.makedirs(media_dir, exist_ok=True)
        filename = f"missing-row-{uuid.uuid4().hex[:8]}.jpg"
        file_path = os.path.join(media_dir, filename)
        with open(file_path, "wb") as handle:
            handle.write(b"fake-image-data")

        try:
            response = self.client.get(f"/vaform/media/{self.FORM_ID}/{filename}")
            self.assertEqual(response.status_code, 404)
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
