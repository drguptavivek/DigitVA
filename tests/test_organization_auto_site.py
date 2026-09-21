"""An organization project gets one automatic site, created and mapped by the app.

Policy: docs/policy/organization-model.md ("Project structure mode").
"""
import sqlalchemy as sa

from app import db
from app.models import VaForms, VaProjectMaster, VaProjectSites, VaSiteMaster, VaStatuses
from app.services import organization_service as org
from app.services.web_intake_readiness_service import assess_web_intake_readiness
from tests.base import BaseTestCase


class OrganizationAutoSiteTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        db.session.commit()

    def _create(self, project_id, **extra):
        response = self.client.post(
            "/admin/api/projects",
            json={
                "project_id": project_id,
                "project_name": project_id,
                "project_nickname": project_id,
                **extra,
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response

    def _update(self, project_id, payload):
        response = self.client.put(
            f"/admin/api/projects/{project_id}", json=payload, headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response

    def _auto_mappings(self, project_id):
        return db.session.execute(
            sa.select(VaProjectSites, VaSiteMaster)
            .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
            .where(
                VaProjectSites.project_id == project_id,
                VaSiteMaster.site_name == org.organization_site_name(project_id),
            )
        ).all()

    def _web_forms(self, project_id):
        return db.session.scalars(
            sa.select(VaForms).where(
                VaForms.project_id == project_id, VaForms.form_source == "web"
            )
        ).all()

    def setUp(self):
        super().setUp()
        self._login(str(self.base_admin_id))

    def test_create_organization_project_gets_one_site_and_web_form(self):
        self._create("AUTO01", project_structure_mode="organization", web_intake_mode="direct")

        rows = self._auto_mappings("AUTO01")
        self.assertEqual(len(rows), 1)
        mapping, site = rows[0]
        self.assertEqual(site.site_name, "Sites_in_project_AUTO01")
        self.assertEqual(site.site_abbr, "AUTO01")
        self.assertRegex(site.site_id, r"^O\d{3}$")
        self.assertEqual(mapping.project_site_status, VaStatuses.active)
        forms = self._web_forms("AUTO01")
        self.assertEqual([form.site_id for form in forms], [site.site_id])
        self.assertEqual(forms[0].form_id, f"AUTO01{site.site_id}01")

    def test_sites_project_gets_no_auto_site(self):
        self._create("AUTO02", web_intake_mode="direct")
        self.assertEqual(self._auto_mappings("AUTO02"), [])

    def test_codes_are_distinct_per_project(self):
        self._create("AUTO03", project_structure_mode="organization")
        self._create("AUTO04", project_structure_mode="organization")
        (_, first), = self._auto_mappings("AUTO03")
        (_, second), = self._auto_mappings("AUTO04")
        self.assertNotEqual(first.site_id, second.site_id)

    def test_switch_to_organization_is_idempotent_and_switch_back_keeps_site(self):
        self._create("AUTO05", web_intake_mode="direct")
        self.assertEqual(self._auto_mappings("AUTO05"), [])

        self._update("AUTO05", {"project_structure_mode": "organization"})
        (mapping, site), = self._auto_mappings("AUTO05")
        self.assertEqual(len(self._web_forms("AUTO05")), 1)

        self._update("AUTO05", {"project_structure_mode": "organization"})
        self._update("AUTO05", {"project_name": "Renamed"})
        self.assertEqual(len(self._auto_mappings("AUTO05")), 1)
        self.assertEqual(len(self._web_forms("AUTO05")), 1)

        self._update("AUTO05", {"project_structure_mode": "sites"})
        db.session.expire_all()
        (mapping, kept), = self._auto_mappings("AUTO05")
        self.assertEqual(kept.site_id, site.site_id)
        self.assertEqual(kept.site_status, VaStatuses.active)
        self.assertEqual(mapping.project_site_status, VaStatuses.active)

    def test_resave_reactivates_a_deactivated_auto_mapping(self):
        self._create("AUTO06", project_structure_mode="organization")
        (mapping, _), = self._auto_mappings("AUTO06")
        mapping.project_site_status = VaStatuses.deactive
        db.session.commit()

        self._update("AUTO06", {"project_name": "Again"})
        db.session.expire_all()
        (mapping, _), = self._auto_mappings("AUTO06")
        self.assertEqual(mapping.project_site_status, VaStatuses.active)

    def test_readiness_passes_sites_and_web_forms_for_organization_project(self):
        self._create("AUTO07", web_intake_mode="direct")
        before = {c["code"]: c for c in assess_web_intake_readiness("AUTO07")["checks"]}
        self.assertEqual(before["sites"]["status"], "fail")

        self._update("AUTO07", {"project_structure_mode": "organization"})
        after = {c["code"]: c for c in assess_web_intake_readiness("AUTO07")["checks"]}
        self.assertEqual(after["sites"]["status"], "ok")
        self.assertEqual(after["web_forms"]["status"], "ok")

    def test_readiness_hint_for_organization_project_without_site(self):
        self._create("AUTO08", project_structure_mode="organization")
        (mapping, _), = self._auto_mappings("AUTO08")
        mapping.project_site_status = VaStatuses.deactive
        db.session.commit()

        checks = {c["code"]: c for c in assess_web_intake_readiness("AUTO08")["checks"]}
        self.assertEqual(checks["sites"]["status"], "fail")
        self.assertIn("created automatically", checks["sites"]["fix_hint"])
        self.assertNotIn("Project Sites", checks["sites"]["fix_hint"])
        self.assertIn("ensure-site", checks["web_forms"]["fix_hint"])

    def test_ensure_site_command_is_idempotent(self):
        self._create("AUTO09", web_intake_mode="direct")
        project = db.session.get(VaProjectMaster, "AUTO09")
        project.project_structure_mode = "organization"
        db.session.commit()
        runner = self.app.test_cli_runner()

        first = runner.invoke(args=["org", "ensure-site", "--project", "AUTO09"])
        self.assertEqual(first.exit_code, 0, first.output)
        second = runner.invoke(args=["org", "ensure-site", "--project", "AUTO09"])
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(first.output, second.output)
        self.assertEqual(len(self._auto_mappings("AUTO09")), 1)
        self.assertEqual(len(self._web_forms("AUTO09")), 1)

        self._create("AUTO10")
        refused = runner.invoke(args=["org", "ensure-site", "--project", "AUTO10"])
        self.assertNotEqual(refused.exit_code, 0)
        self.assertEqual(self._auto_mappings("AUTO10"), [])
