"""WHO_2022_VA_SOCIAL is kept for the projects already on it and not offered to
any other; the Projects panel shows the questionnaire a project actually
resolves to, served by the project API (digitva-l2dg,
docs/policy/va-form-project-configuration.md, "One field mapping for every
layer").
"""
from datetime import UTC, datetime

from app import db
from app.models import VaProjectMaster, VaProjectSites, VaSiteMaster, VaStatuses
from tests.base import BaseTestCase


class RetiredWebFormTypeTests(BaseTestCase):
    ON_SOCIAL = "FOPT09"
    FRESH = "FOPT10"
    SITE = "FT09"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.services.runtime_form_sync_service import ensure_web_runtime_form

        now = datetime.now(UTC)
        for project_id in (cls.ON_SOCIAL, cls.FRESH):
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Retired Form Type {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                    web_intake_mode="direct",
                )
            )
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE,
                site_name="Retired Form Type Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.ON_SOCIAL,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.flush()
        cls.base_type = cls._ensure_form_type("WHO_2022_VA", "WHO 2022 VA Form")
        cls.social_type = cls._ensure_form_type(
            "WHO_2022_VA_SOCIAL", "WHO 2022 VA with social autopsy"
        )
        # ON_SOCIAL's web form was made while the project named SOCIAL; the
        # project then went back to a NULL setting, which resolves through
        # that web form rather than to the default.
        on_social = db.session.get(VaProjectMaster, cls.ON_SOCIAL)
        on_social.web_intake_form_type_id = cls.social_type.form_type_id
        db.session.flush()
        ensure_web_runtime_form(cls.ON_SOCIAL, cls.SITE)
        on_social.web_intake_form_type_id = None
        db.session.commit()

    def setUp(self):
        super().setUp()
        self._login(str(self.base_admin_user.user_id))

    def _listed(self, project_id):
        response = self.client.get("/admin/api/projects")
        self.assertEqual(response.status_code, 200)
        return next(p for p in response.get_json()["projects"] if p["project_id"] == project_id)

    def _put(self, project_id, form_type):
        return self.client.put(
            f"/admin/api/projects/{project_id}",
            json={"web_intake_form_type_id": str(form_type.form_type_id)},
            headers=self._csrf_headers(),
        )

    def test_the_project_list_serves_the_questionnaire_each_project_resolves_to(self):
        on_social = self._listed(self.ON_SOCIAL)
        self.assertIsNone(on_social["web_intake_form_type_id"])
        self.assertEqual(on_social["web_intake_resolved_form_type_code"], "WHO_2022_VA_SOCIAL")
        self.assertEqual(
            on_social["web_intake_resolved_form_type_id"], str(self.social_type.form_type_id)
        )
        fresh = self._listed(self.FRESH)
        self.assertIsNone(fresh["web_intake_form_type_id"])
        self.assertEqual(fresh["web_intake_resolved_form_type_code"], "WHO_2022_VA")

    def test_web_form_types_marks_social_as_not_offered_for_new_choices(self):
        payload = self.client.get("/admin/api/web-form-types").get_json()
        self.assertEqual(payload["default_form_type_code"], "WHO_2022_VA")
        by_code = {ft["form_type_code"]: ft for ft in payload["form_types"]}
        self.assertIn("WHO_2022_VA", by_code)
        self.assertTrue(by_code["WHO_2022_VA"]["offered_for_new"])
        self.assertIn("WHO_2022_VA_SOCIAL", by_code)
        self.assertFalse(by_code["WHO_2022_VA_SOCIAL"]["offered_for_new"])

    def test_social_is_refused_to_a_project_that_does_not_use_it(self):
        # Positive control: the default type is accepted for the same project.
        self.assertEqual(self._put(self.FRESH, self.base_type).status_code, 200)
        response = self._put(self.FRESH, self.social_type)
        self.assertEqual(response.status_code, 400)
        self.assertIn("kept only for projects already using it", response.get_json()["error"])
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaProjectMaster, self.FRESH).web_intake_form_type_id,
            self.base_type.form_type_id,
        )

    def test_social_is_kept_for_a_project_whose_web_form_carries_it(self):
        response = self._put(self.ON_SOCIAL, self.social_type)
        self.assertEqual(response.status_code, 200, response.get_json())
        project = response.get_json()["project"]
        self.assertEqual(project["web_intake_form_type_code"], "WHO_2022_VA_SOCIAL")
        self.assertEqual(project["web_intake_resolved_form_type_code"], "WHO_2022_VA_SOCIAL")

    def test_a_new_project_may_not_choose_social(self):
        response = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": "FOPT11",
                "project_name": "New On Social",
                "project_nickname": "NewSocial",
                "web_intake_mode": "direct",
                "web_intake_form_type_id": str(self.social_type.form_type_id),
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("kept only for projects already using it", response.get_json()["error"])
        self.assertIsNone(db.session.get(VaProjectMaster, "FOPT11"))
