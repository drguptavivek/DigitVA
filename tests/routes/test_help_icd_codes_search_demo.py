"""/help/icd-codes/search-demo (digitva-zm1): live coding-search demo page."""

from datetime import UTC, datetime

from app import db
from app.models import VaForms, VaResearchProjects, VaSites, VaStatuses
from tests.base import BaseTestCase


class HelpIcdCodesSearchDemoRouteTests(BaseTestCase):
    URL = "/help/icd-codes/search-demo"
    FORM_ID = "BASE01BS01HD"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # is_coder() only resolves through a VaForms row under the granted
        # project/site (app/models/va_users.py::_get_granted_va_forms).
        now = datetime.now(UTC)
        if db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID) is None:
            db.session.add(
                VaResearchProjects(
                    project_id=cls.BASE_PROJECT_ID,
                    project_code=cls.BASE_PROJECT_ID,
                    project_name="Base Test Project",
                    project_nickname="BaseTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaSites, cls.BASE_SITE_ID) is None:
            db.session.add(
                VaSites(
                    site_id=cls.BASE_SITE_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_name="Base Test Site",
                    site_abbr=cls.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_id=cls.BASE_SITE_ID,
                    odk_form_id="HELP_DEMO_FORM",
                    odk_project_id="1",
                    form_type="WHO 2022 VA",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.commit()

    def test_anonymous_gets_403(self):
        # _user_has_role treats an unauthenticated visitor as holding no
        # roles, so this role-gated page 403s rather than redirecting —
        # same behaviour as help.page (tests/test_route_auth_coverage.py).
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 403)

    def test_coder_can_view_the_demo_page(self):
        self._login(self.base_coder_id)

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("coding-demo-query", body)
        self.assertIn("vendor/icd11ect/1.8/icd11ect-1.8.js", body)
        self.assertIn("who-ect-query", body)
        self.assertIn(
            "connect-src 'self' http://127.0.0.1:8382",
            response.headers["Content-Security-Policy"],
        )

    def test_role_without_access_gets_403(self):
        self._login(self.base_project_pi_id)

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 403)

    def test_icd_codes_page_links_to_the_demo(self):
        self._login(self.base_coder_id)

        response = self.client.get("/help/icd-codes")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.URL, response.get_data(as_text=True))
        self.assertNotIn(
            "http://127.0.0.1:8382", response.headers["Content-Security-Policy"]
        )
