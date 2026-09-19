"""GET /admin/api/projects/<project_id>/web-intake-readiness.

WP2 of docs/planning/web-capture-project-configuration-plan.md. The
assessment itself is covered by
tests/services/test_web_intake_readiness_service.py; what is under test here
is who may read it and for which project — a project PI reads only the
projects they manage, the same ownership rule the project-sites endpoints
apply.
"""
from datetime import UTC, datetime

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase


class AdminWebIntakeReadinessApiTests(BaseTestCase):
    OWNED_PROJECT = "WRA001"
    OTHER_PROJECT = "WRA002"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        for project_id, name in (
            (cls.OWNED_PROJECT, "Readiness Owned"),
            (cls.OTHER_PROJECT, "Readiness Other"),
        ):
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=name,
                    project_nickname=name,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                    web_intake_mode="direct",
                )
            )
        db.session.flush()

        cls.pi_user = cls._get_or_make_user("readiness.pi@test.local", "Readiness123")
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.pi_user.user_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.OWNED_PROJECT,
                notes="readiness api pi grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def _url(self, project_id):
        return f"/admin/api/projects/{project_id}/web-intake-readiness"

    def test_admin_reads_any_project(self):
        self._login(self.base_admin_id)

        response = self.client.get(self._url(self.OTHER_PROJECT))

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["project_id"], self.OTHER_PROJECT)
        self.assertIn("ready", body)
        self.assertTrue(body["checks"])

    def test_project_pi_reads_a_project_they_manage(self):
        self._login(str(self.pi_user.user_id))

        response = self.client.get(self._url(self.OWNED_PROJECT))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["project_id"], self.OWNED_PROJECT)

    def test_project_pi_is_refused_a_project_they_do_not_manage(self):
        """The PI can read their own project, and only their own.

        The positive case is asserted in the same test: without it a broken
        session or a dead route would make the 403 pass for the wrong reason.
        """
        self._login(str(self.pi_user.user_id))
        self.assertEqual(
            self.client.get(self._url(self.OWNED_PROJECT)).status_code, 200
        )

        response = self.client.get(self._url(self.OTHER_PROJECT))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_gets_json_401(self):
        response = self.client.get(self._url(self.OWNED_PROJECT))

        self.assertEqual(response.status_code, 401)
        self.assertIn("application/json", response.content_type)

    def test_unknown_project_is_404_for_an_admin(self):
        self._login(self.base_admin_id)

        response = self.client.get(self._url("NOSUCH"))

        self.assertEqual(response.status_code, 404)
