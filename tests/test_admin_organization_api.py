"""HTTP contract of app/routes/admin_organization.py: authorization and thin dispatch."""
import io
from datetime import UTC, datetime

from app import db
from app.models import VaProjectMaster, VaStatuses
from app.services import organization_service as org
from tests.base import BaseTestCase


class AdminOrganizationApiTests(BaseTestCase):
    PROJECT = "ORGA01"
    SITES_PROJECT = "ORGS01"

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
                project_structure_mode="organization",
            )
        )
        db.session.add(
            VaProjectMaster(
                project_id=cls.SITES_PROJECT,
                project_code=cls.SITES_PROJECT,
                project_name="Sites Project",
                project_nickname="Sites",
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

    def _import_csv(self, headers, sheet, text, dry_run):
        return self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(text.encode("utf-8-sig")), f"{sheet}.csv"), "sheet": sheet, "dry_run": "1" if dry_run else "0"},
            content_type="multipart/form-data",
            headers=headers,
        )

    def test_csv_import_adds_cadres_placements_and_workers(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id, unit_code="D01", unit_name="District One")
        org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id, parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One")
        db.session.commit()

        cadres = "cadre_code,cadre_name\nLT,Lab Technician\n"
        dry = self._import_csv(headers, "cadres", cadres, dry_run=True)
        self.assertEqual(dry.status_code, 200, dry.get_json())
        self.assertEqual(dry.get_json()["plan"]["counts"]["cadres"]["create"], 1)
        self.assertNotIn("LT", {c.cadre_code for c in org.list_cadres(self.PROJECT)})
        self.assertEqual(self._import_csv(headers, "cadres", cadres, dry_run=False).status_code, 200)
        self.assertIn("LT", {c.cadre_code for c in org.list_cadres(self.PROJECT)})

        placements = "level_code,cadre_code,can_fill_va_form,can_code_va_form\nchc,LT,true,false\n"
        self.assertEqual(self._import_csv(headers, "level_cadres", placements, dry_run=False).status_code, 200)

        workers = "worker_code,worker_name,unit_code,cadre_code,phone,user_email,remarks,is_active\nW01,Lab Person,C01,LT,,,,\n"
        applied = self._import_csv(headers, "workers", workers, dry_run=False)
        self.assertEqual(applied.status_code, 200, applied.get_json())
        worker = {w["worker_code"]: w for w in org.list_workers(self.PROJECT, include_inactive=True)}["W01"]
        self.assertTrue(worker["is_active"])
        self.assertIsNone(worker["phone"])

        # A re-upload with a blank is_active keeps the worker active: blank
        # CSV cells mean "no value", as empty workbook cells do.
        again = self._import_csv(headers, "workers", workers.replace("Lab Person", "Lab Person Two"), dry_run=False)
        self.assertEqual(again.status_code, 200, again.get_json())
        worker = {w["worker_code"]: w for w in org.list_workers(self.PROJECT, include_inactive=True)}["W01"]
        self.assertEqual(worker["worker_name"], "Lab Person Two")
        self.assertTrue(worker["is_active"])

        # A worker whose cadre is not placed at the unit's level is refused.
        bad = self._import_csv(headers, "workers", "worker_code,worker_name,unit_code,cadre_code\nW02,Nobody,D01,LT\n", dry_run=True)
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(bad.get_json()["plan"]["errors"])

        unknown_sheet = self._import_csv(headers, "bogus", cadres, dry_run=True)
        self.assertEqual(unknown_sheet.status_code, 400)

    def test_worker_code_is_optional(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id, unit_code="D01", unit_name="District One")
        chc = org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id, parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One")
        mo = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}["MO"]
        db.session.commit()

        created = self.client.post(
            self._url("/workers"),
            json={"org_unit_id": str(chc.org_unit_id), "cadre_id": str(mo.cadre_id), "worker_name": "Dr Kaur"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertEqual(created.get_json()["worker"]["worker_code"], "W00001")

        # Code-less rows match by unit and name: Dr Kaur is updated, Dr Rao is new,
        # and re-uploading the same file creates nothing more.
        rows = "worker_name,unit_code,cadre_code,phone\ndr kaur,C01,MO,111\nDr Rao,C01,MO,\n"
        for _ in range(2):
            self.assertEqual(self._import_csv(headers, "workers", rows, dry_run=False).status_code, 200)
        workers = {w["worker_code"]: w for w in org.list_workers(self.PROJECT, include_inactive=True)}
        self.assertEqual(set(workers), {"W00001", "W00002"})
        self.assertEqual(workers["W00001"]["phone"], "111")
        self.assertEqual(workers["W00002"]["worker_name"], "Dr Rao")

    # -- project structure mode (docs/policy/organization-model.md) ----------

    def test_writes_refused_for_sites_project_reads_allowed(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        base = f"/admin/api/organization/{self.SITES_PROJECT}"

        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.get(f"{base}/levels").status_code, 200)

        refused = [
            self.client.post(f"{base}/seed-template", json={}, headers=headers),
            self.client.post(
                f"{base}/levels",
                json={"level_code": "district", "level_name": "District", "depth": 1},
                headers=headers,
            ),
            self.client.post(f"{base}/cadres", json={"cadre_code": "MO", "cadre_name": "MO"}, headers=headers),
            self.client.put(f"{base}/level-cadres", json={}, headers=headers),
            self.client.post(
                f"{base}/import",
                data={"file": (io.BytesIO(b"x"), "org.xlsx"), "dry_run": "1"},
                content_type="multipart/form-data",
                headers=headers,
            ),
        ]
        for response in refused:
            self.assertEqual(response.status_code, 409, response.get_json())
            self.assertIn("Organization", response.get_json()["error"])
        self.assertEqual(org.list_levels(self.SITES_PROJECT, include_inactive=True), [])
        self.assertEqual(org.list_cadres(self.SITES_PROJECT, include_inactive=True), [])

    def test_create_project_accepts_and_rejects_structure_mode(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        payload = {"project_name": "Mode", "project_nickname": "Mode"}

        default = self.client.post("/admin/api/projects", json={**payload, "project_id": "MODE01"}, headers=headers)
        self.assertEqual(default.status_code, 201, default.get_json())
        self.assertEqual(default.get_json()["project"]["project_structure_mode"], "sites")

        explicit = self.client.post(
            "/admin/api/projects",
            json={**payload, "project_id": "MODE02", "project_structure_mode": "organization"},
            headers=headers,
        )
        self.assertEqual(explicit.status_code, 201, explicit.get_json())
        self.assertEqual(explicit.get_json()["project"]["project_structure_mode"], "organization")

        bogus = self.client.post(
            "/admin/api/projects",
            json={**payload, "project_id": "MODE03", "project_structure_mode": "tree"},
            headers=headers,
        )
        self.assertEqual(bogus.status_code, 400)
        self.assertIsNone(db.session.get(VaProjectMaster, "MODE03"))

        bad_update = self.client.put(
            "/admin/api/projects/MODE01", json={"project_structure_mode": ["sites"]}, headers=headers
        )
        self.assertEqual(bad_update.status_code, 400)

    def test_switch_back_to_sites_refused_while_units_active(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        url = f"/admin/api/projects/{self.SITES_PROJECT}"

        to_org = self.client.put(url, json={"project_structure_mode": "organization"}, headers=headers)
        self.assertEqual(to_org.status_code, 200, to_org.get_json())
        self.assertEqual(to_org.get_json()["project"]["project_structure_mode"], "organization")

        org.seed_default_organization(self.SITES_PROJECT, include_cadres=False)
        level = org.list_levels(self.SITES_PROJECT)[0]
        unit = org.create_unit(self.SITES_PROJECT, org_level_id=level.org_level_id, unit_code="D01", unit_name="District One")
        db.session.commit()

        refused = self.client.put(url, json={"project_structure_mode": "sites"}, headers=headers)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("active organization units", refused.get_json()["error"])
        db.session.expire_all()
        self.assertEqual(db.session.get(VaProjectMaster, self.SITES_PROJECT).project_structure_mode, "organization")
        self.assertIsNotNone(org.find_unit_by_code(self.SITES_PROJECT, "D01"))

        org.set_unit_active(self.SITES_PROJECT, unit.org_unit_id, False)
        db.session.commit()
        allowed = self.client.put(url, json={"project_structure_mode": "sites"}, headers=headers)
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual(allowed.get_json()["project"]["project_structure_mode"], "sites")
