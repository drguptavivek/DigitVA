"""VA cause definitions: coder API, admin panel/API, help page (digitva-oyq)."""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import MasVaCauseDefinition, VaForms, VaResearchProjects, VaSites, VaStatuses
from tests.base import BaseTestCase
from tests.services.test_va_cause_definition_service import seed_icd_lookup_fixtures

API = "/api/v1/va-definitions"
ADMIN_API = "/admin/api/va-definitions"


class VaDefinitionsRoutesTests(BaseTestCase):
    FORM_ID = "BASE01BS0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # is_coder() needs a form on the coder's site (as in test_icd10_coding_api.py).
        now = datetime.now(UTC)
        if db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID, project_code=cls.BASE_PROJECT_ID,
                project_name="Base Test Project", project_nickname="BaseTest",
                project_status=VaStatuses.active, project_registered_at=now, project_updated_at=now,
            ))
            db.session.flush()
        if db.session.get(VaSites, cls.BASE_SITE_ID) is None:
            db.session.add(VaSites(
                site_id=cls.BASE_SITE_ID, project_id=cls.BASE_PROJECT_ID, site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
            db.session.flush()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
                odk_form_id="VADEF_FORM", odk_project_id="1", form_type="WHO 2022 VA",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
            db.session.flush()
        seed_icd_lookup_fixtures()

    def _id(self, code):
        return str(db.session.scalar(
            sa.select(MasVaCauseDefinition.id).where(MasVaCauseDefinition.va_code == code)
        ))

    # ── coder API ────────────────────────────────────────────────────────
    def test_api_rejects_anonymous(self):
        self.assertEqual(self.client.get(API).status_code, 401)

    def test_api_rejects_a_user_without_a_coding_role(self):
        self._login(str(self.base_project_pi_id))
        self.assertEqual(self.client.get(API).status_code, 403)

    def test_api_lists_definitions_for_a_coder(self):
        self._login(str(self.base_coder_id))
        payload = self.client.get(API).get_json()
        self.assertEqual(payload["total"], 63)
        sepsis = payload["definitions"][0]
        self.assertEqual(sepsis["va_code"], "VAs-01.01")
        self.assertIn("<ul><li>", sepsis["definition_html"])
        self.assertIn("Inability to stand up", sepsis["definition_text"])
        self.assertNotIn("<", sepsis["definition_text"])

    def test_api_filters_on_q(self):
        self._login(str(self.base_coder_id))
        payload = self.client.get(API, query_string={"q": "malaria"}).get_json()
        codes = [d["va_code"] for d in payload["definitions"]]
        self.assertIn("VAs-01.05", codes)
        self.assertNotIn("VAs-01.01", codes)

    # ── help page ────────────────────────────────────────────────────────
    def test_help_page_renders_the_viewer_for_a_coder(self):
        self._login(str(self.base_coder_id))
        response = self.client.get("/help/va-definitions")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("VA Cause Definitions", body)
        self.assertIn('class="va-def-root"', body)
        self.assertIn("js/va_definitions.js", body)

    def test_help_page_is_forbidden_without_a_coding_role(self):
        self._login(str(self.base_project_pi_id))
        self.assertEqual(self.client.get("/help/va-definitions").status_code, 403)

    # ── admin panel and API ──────────────────────────────────────────────
    def test_shell_links_the_panel_and_panel_renders_for_admin(self):
        self._login(str(self.base_admin_id))
        self.assertIn('data-panel="/admin/panels/va-definitions"', self.client.get("/admin/").get_data(as_text=True))
        response = self.client.get("/admin/panels/va-definitions")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="panel-va-definitions"', body)
        self.assertIn("js/rich_text_editor.js", body)

    def test_admin_endpoints_refuse_non_admins(self):
        self._login(str(self.base_coder_id))
        self.assertIn(self.client.get("/admin/panels/va-definitions").status_code, (302, 403))
        self.assertEqual(self.client.get(ADMIN_API).status_code, 403)
        response = self.client.patch(
            f"{ADMIN_API}/{self._id('VAs-01.01')}", json={"title": "x"}, headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_write_requires_csrf(self):
        self._login(str(self.base_admin_id))
        response = self.client.patch(f"{ADMIN_API}/{self._id('VAs-01.01')}", json={"title": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.get_json()["error"])

    def test_admin_edit_is_sanitized_and_served_escaped_to_coders(self):
        self._login(str(self.base_admin_id))
        response = self.client.patch(
            f"{ADMIN_API}/{self._id('VAs-01.02')}",
            json={"title": "ARI", "definition_html": '<p>ok<img src=x onerror="alert(1)"></p><script>alert(2)</script>'},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        stored = response.get_json()["definition"]
        self.assertEqual(stored["definition_html"], "<p>ok</p>")
        self.assertTrue(stored["edited"])

        self._login(str(self.base_coder_id))
        payload = self.client.get(API, query_string={"q": "VAs-01.02"}).get_json()
        cause = payload["definitions"][0]
        self.assertEqual(cause["definition_html"], "<p>ok</p>")
        self.assertNotIn("alert", self.client.get(API).get_data(as_text=True))

    def test_admin_lists_creates_and_deactivates(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        listed = self.client.get(ADMIN_API).get_json()["definitions"]
        self.assertEqual(len(listed), 63)

        created = self.client.post(
            ADMIN_API,
            json={"va_code": "VAs-01.14", "title": "New cause", "definition_html": "<ul><li>a</li></ul>"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        row = created.get_json()["definition"]
        self.assertEqual(row["va_code"], "VAs-01.14")

        duplicate = self.client.post(ADMIN_API, json={"va_code": "VAs-01.14", "title": "x"}, headers=headers)
        self.assertEqual(duplicate.status_code, 400)
        bad_code = self.client.post(ADMIN_API, json={"va_code": "<b>", "title": "x"}, headers=headers)
        self.assertEqual(bad_code.status_code, 400)

        off = self.client.patch(f"{ADMIN_API}/{row['id']}", json={"is_active": False}, headers=headers)
        self.assertFalse(off.get_json()["definition"]["is_active"])
        self.assertEqual(self.client.patch(f"{ADMIN_API}/not-a-uuid", json={"title": "x"}, headers=headers).status_code, 404)

        self._login(str(self.base_coder_id))
        codes = [d["va_code"] for d in self.client.get(API).get_json()["definitions"]]
        self.assertIn("VAs-01.13", codes)
        self.assertNotIn("VAs-01.14", codes)

    # ── ICD code -> VA definition (floating panel) ───────────────────────
    def test_for_icd_rejects_anonymous_and_non_coders(self):
        self.assertEqual(self.client.get(f"{API}/for-icd?code=A04").status_code, 401)
        self._login(str(self.base_project_pi_id))
        self.assertEqual(self.client.get(f"{API}/for-icd?code=A04").status_code, 403)

    def test_for_icd_returns_the_mapped_definition(self):
        self._login(str(self.base_coder_id))
        response = self.client.get(f"{API}/for-icd", query_string={"code": "A04.0-Other bacterial intestinal infections"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["va_code"], "VAs-01.04")
        self.assertEqual(payload["title"], "Diarrhoeal diseases")
        self.assertIn("<ul>", payload["definition_html"])

        icd11 = self.client.get(f"{API}/for-icd", query_string={"code": "1A00.1", "classification": "icd11"})
        self.assertEqual(icd11.get_json()["va_code"], "VAs-01.04")

    def test_for_icd_404_and_bad_classification(self):
        self._login(str(self.base_coder_id))
        self.assertEqual(self.client.get(f"{API}/for-icd?code=Z99").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/for-icd").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/for-icd?code=A04&classification=icd9").status_code, 400)

    def test_modal_partial_loads_the_floating_panel_once(self):
        from flask import render_template

        with self.app.test_request_context("/"):
            html = render_template("va_form_partials/_va_definitions_modal.html", modal_id="vaDefinitionsModal")
        self.assertEqual(html.count("js/va_definition_panel.js"), 1)
        self.assertIn("js/va_definitions.js", html)

    def test_every_coding_screen_includes_the_definitions_partial(self):
        for template in (
            "va_form_partials/vainitialasses.html",
            "va_form_partials/vafinalasses.html",
            "va_formcategory_partials/_va_cod_assessment_panel.html",
        ):
            source = self.app.jinja_env.loader.get_source(self.app.jinja_env, template)[0]
            self.assertIn('include "va_form_partials/_va_definitions_modal.html"', source, template)
