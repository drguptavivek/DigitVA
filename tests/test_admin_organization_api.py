"""HTTP contract of app/routes/admin_organization.py: authorization and thin dispatch."""
import io
from datetime import UTC, datetime

from app import db
from app.models import VaProjectMaster, VaStatuses
from app.services import organization_service as org
from tests.base import BaseTestCase


class AdminOrganizationApiTests(BaseTestCase):
    PROJECT = "ORGA01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Org API Project",
                project_nickname="OrgApi",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.commit()

    def _url(self, suffix=""):
        return f"/admin/api/organization/{self.PROJECT}{suffix}"

    def test_panel_renders_for_admin(self):
        self._login(str(self.base_admin_id))
        response = self.client.get(f"/admin/panels/organization?project_id={self.PROJECT}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="panel-organization"', response.data)

    def test_coder_is_forbidden(self):
        self._login(str(self.base_coder_id))
        response = self.client.get(self._url())
        self.assertIn(response.status_code, (302, 403))

    def test_project_pi_of_other_project_is_forbidden(self):
        self._login(str(self.base_project_pi_id))
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "You do not have access to that project.")

    def test_project_pi_manages_own_project(self):
        from app.models import VaAccessRoles, VaAccessScopeTypes, VaUserAccessGrants

        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_project_pi_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(self.base_project_pi_id))
        headers = self._csrf_headers()
        self.assertEqual(self.client.post(self._url("/seed-template"), json={}, headers=headers).status_code, 200)
        level = self.client.get(self._url("/levels")).get_json()["levels"][0]
        created = self.client.post(
            self._url("/units"),
            json={"org_level_id": level["org_level_id"], "unit_code": "D01", "unit_name": "District One"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        missing_flag = self.client.post(self._url(f"/units/{created.get_json()['unit']['org_unit_id']}/toggle"), json={}, headers=headers)
        self.assertEqual(missing_flag.status_code, 400)

    def test_admin_builds_tree_through_api(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()

        seeded = self.client.post(self._url("/seed-template"), json={}, headers=headers)
        self.assertEqual(seeded.status_code, 200)
        self.assertEqual(seeded.get_json()["seeded"]["levels"], 6)

        levels = {lv["level_code"]: lv for lv in self.client.get(self._url("/levels")).get_json()["levels"]}
        created = self.client.post(
            self._url("/units"),
            json={"org_level_id": levels["district"]["org_level_id"], "unit_code": "d01", "unit_name": "District One", "google_maps_url": "https://maps.app.goo.gl/abc"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        district = created.get_json()["unit"]
        self.assertEqual(district["unit_code"], "D01")

        bad = self.client.post(
            self._url("/units"),
            json={"org_level_id": levels["phc"]["org_level_id"], "parent_org_unit_id": district["org_unit_id"], "unit_code": "P01", "unit_name": "Skips CHC"},
            headers=headers,
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("'chc'", bad.get_json()["error"])

        chc = self.client.post(
            self._url("/units"),
            json={"org_level_id": levels["chc"]["org_level_id"], "parent_org_unit_id": district["org_unit_id"], "unit_code": "C01", "unit_name": "CHC One"},
            headers=headers,
        ).get_json()["unit"]
        self.assertEqual(chc["path"], "D01.C01")
        self.assertEqual(chc["parent_code"], "D01")

        summary = self.client.get(self._url()).get_json()
        self.assertEqual(summary["units"][0]["children"][0]["unit_code"], "C01")
        self.assertEqual(len(summary["level_cadres"]), 8)

        toggled = self.client.post(self._url(f"/units/{district['org_unit_id']}/toggle"), json={"is_active": False}, headers=headers)
        self.assertEqual(toggled.get_json()["changed"], 2)
        self.assertEqual(self.client.get(self._url("/units")).get_json()["units"], [])
        self.assertEqual(len(self.client.get(self._url("/units?include_inactive=1")).get_json()["units"]), 2)

        perm = self.client.put(
            self._url("/level-cadres"),
            json={"org_level_id": levels["district"]["org_level_id"], "cadre_id": summary["cadres"][0]["cadre_id"], "can_fill_va_form": False, "can_code_va_form": True},
            headers=headers,
        )
        self.assertEqual(perm.status_code, 200)
        self.assertTrue(perm.get_json()["level_cadre"]["can_code_va_form"])

    def test_export_and_import_endpoints(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        level = org.list_levels(self.PROJECT)[0]
        org.create_unit(self.PROJECT, org_level_id=level.org_level_id, unit_code="D01", unit_name="District One")
        db.session.commit()

        xlsx = self.client.get(self._url("/export.xlsx"))
        self.assertEqual(xlsx.status_code, 200)
        self.assertIn("spreadsheetml", xlsx.mimetype)
        csv_resp = self.client.get(self._url("/export/units.csv"))
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("D01,District One,district", csv_resp.get_data(as_text=True))
        choices = self.client.get(self._url("/odk-choices.csv"))
        self.assertIn("org_district,D01,District One,", choices.get_data(as_text=True))
        self.assertEqual(self.client.get(self._url("/export/bogus.csv")).status_code, 400)

        dry = self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(xlsx.data), "org.xlsx"), "dry_run": "1"},
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(dry.status_code, 200, dry.get_json())
        body = dry.get_json()
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["plan"]["applied"])
        self.assertEqual(body["plan"]["counts"]["units"]["update"], 1)

        rejected = self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(b"not a workbook"), "org.xlsx"), "dry_run": "1"},
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(rejected.status_code, 400)
