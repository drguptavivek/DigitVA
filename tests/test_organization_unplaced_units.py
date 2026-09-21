"""Unplaced units: import a facility list first, map parents afterwards.

Rule: docs/policy/organization-model.md ("Unplaced units"). Service in
app/services/organization_service.py (``_import_units``, ``place_units``),
endpoint ``POST /admin/api/organization/<project_id>/units/place``.
"""
import io
from datetime import UTC, datetime

from app import db
from app.models import VaProjectMaster, VaStatuses
from app.services import organization_service as org
from app.services.web_intake_readiness_service import assess_web_intake_readiness
from tests.base import BaseTestCase

FACILITIES_CSV = (
    "unit_code,unit_name,level_code,parent_code\n"
    "P01,PHC One,phc,\n"
    "P02,PHC Two,phc,\n"
    "S01,Sub-centre One,subcentre,\n"
)


class UnplacedUnitTests(BaseTestCase):
    PROJECT = "ORGU01"
    SITES_PROJECT = "ORGUS1"
    OTHER_PROJECT = "ORGU02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, mode in ((cls.PROJECT, "organization"), (cls.SITES_PROJECT, "sites"), (cls.OTHER_PROJECT, "organization")):
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Unplaced {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                    project_structure_mode=mode,
                )
            )
        db.session.commit()

    def setUp(self):
        super().setUp()
        org.seed_default_organization(self.PROJECT)
        self.levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        self.district = org.create_unit(
            self.PROJECT, org_level_id=self.levels["district"].org_level_id, unit_code="D01", unit_name="District One"
        )
        self.chc = org.create_unit(
            self.PROJECT,
            org_level_id=self.levels["chc"].org_level_id,
            parent_org_unit_id=self.district.org_unit_id,
            unit_code="C01",
            unit_name="CHC One",
        )
        db.session.commit()
        self._login(str(self.base_admin_id))
        self.headers = self._csrf_headers()

    # -- helpers -------------------------------------------------------------

    def _url(self, suffix="", project=None):
        return f"/admin/api/organization/{project or self.PROJECT}{suffix}"

    def _import_units_csv(self, text, dry_run=False):
        return self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(text.encode("utf-8-sig")), "units.csv"), "sheet": "units", "dry_run": "1" if dry_run else "0"},
            content_type="multipart/form-data",
            headers=self.headers,
        )

    def _units(self):
        return {u["unit_code"]: u for u in org.list_units(self.PROJECT, include_inactive=True)}

    def _place(self, placements, project=None):
        return self.client.post(
            self._url("/units/place", project), json={"placements": placements}, headers=self.headers
        )

    # -- import --------------------------------------------------------------

    def test_import_without_parents_creates_unplaced_units_and_reports_them(self):
        dry = self._import_units_csv(FACILITIES_CSV, dry_run=True)
        self.assertEqual(dry.status_code, 200, dry.get_json())
        self.assertEqual(dry.get_json()["plan"]["unplaced"], ["P01", "P02", "S01"])
        self.assertNotIn("P01", self._units())

        applied = self._import_units_csv(FACILITIES_CSV)
        self.assertEqual(applied.status_code, 200, applied.get_json())
        plan = applied.get_json()["plan"]
        self.assertEqual(plan["counts"]["units"]["create"], 3)
        self.assertEqual(plan["unplaced"], ["P01", "P02", "S01"])

        units = self._units()
        self.assertIn("P01", units)
        self.assertTrue(units["P01"]["is_unplaced"])
        self.assertIsNone(units["P01"]["parent_org_unit_id"])
        self.assertEqual(units["P01"]["path"], "P01")
        self.assertFalse(units["D01"]["is_unplaced"])
        self.assertFalse(units["C01"]["is_unplaced"])

        tree = self.client.get(self._url("/units?tree=1")).get_json()["units"]
        roots = {node["unit_code"]: node for node in tree}
        self.assertIn("P01", roots)
        self.assertTrue(roots["P01"]["is_unplaced"])
        self.assertFalse(roots["D01"]["is_unplaced"])

    def test_import_with_unknown_parent_code_still_errors(self):
        response = self._import_units_csv("unit_code,unit_name,level_code,parent_code\nP09,PHC Nine,phc,NOPE\n")
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown parent unit 'NOPE'", response.get_json()["plan"]["errors"][0])
        self.assertNotIn("P09", self._units())

    def test_reimport_with_blank_parent_keeps_a_placed_units_parent(self):
        phc = org.create_unit(
            self.PROJECT,
            org_level_id=self.levels["phc"].org_level_id,
            parent_org_unit_id=self.chc.org_unit_id,
            unit_code="P01",
            unit_name="PHC One",
        )
        db.session.commit()
        self.assertEqual(self._units()["P01"]["parent_org_unit_id"], str(self.chc.org_unit_id))

        response = self._import_units_csv("unit_code,unit_name,level_code,parent_code\nP01,PHC One Renamed,phc,\n")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["plan"]["unplaced"], [])

        unit = self._units()["P01"]
        self.assertEqual(unit["unit_name"], "PHC One Renamed")
        self.assertEqual(unit["parent_org_unit_id"], str(phc.parent_org_unit_id))
        self.assertEqual(unit["path"], "D01.C01.P01")
        self.assertFalse(unit["is_unplaced"])

    def test_admin_form_still_requires_a_parent_below_the_top_level(self):
        response = self.client.post(
            self._url("/units"),
            json={"org_level_id": str(self.levels["phc"].org_level_id), "unit_code": "P07", "unit_name": "No Parent"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("need a parent", response.get_json()["error"])
        self.assertNotIn("P07", self._units())

    def test_editing_an_unplaced_unit_can_set_its_parent(self):
        self._import_units_csv(FACILITIES_CSV)
        p01 = self._units()["P01"]
        response = self.client.patch(
            self._url(f"/units/{p01['org_unit_id']}"),
            json={"parent_org_unit_id": str(self.chc.org_unit_id), "unit_name": "PHC One"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()["unit"]["is_unplaced"])
        self.assertEqual(response.get_json()["unit"]["path"], "D01.C01.P01")

    # -- placing -------------------------------------------------------------

    def test_bulk_place_validates_levels_and_rewrites_child_paths(self):
        self._import_units_csv(FACILITIES_CSV)
        units = self._units()
        # Place S01 under the still-unplaced P01 first, then P01 under the CHC:
        # the second move must carry S01's path along.
        response = self._place([
            {"org_unit_id": units["S01"]["org_unit_id"], "parent_org_unit_id": units["P01"]["org_unit_id"]},
            {"org_unit_id": units["P01"]["org_unit_id"], "parent_org_unit_id": str(self.chc.org_unit_id)},
        ])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["placed"], 2)

        units = self._units()
        self.assertEqual(units["P01"]["path"], "D01.C01.P01")
        self.assertEqual(units["S01"]["path"], "D01.C01.P01.S01")
        self.assertFalse(units["P01"]["is_unplaced"])
        self.assertFalse(units["S01"]["is_unplaced"])
        self.assertTrue(units["P02"]["is_unplaced"])
        self.assertEqual(org.unplaced_unit_codes(self.PROJECT), ["P02"])

    def test_bulk_place_is_all_or_nothing(self):
        self._import_units_csv(FACILITIES_CSV)
        units = self._units()
        response = self._place([
            {"org_unit_id": units["P01"]["org_unit_id"], "parent_org_unit_id": str(self.chc.org_unit_id)},
            # A PHC straight under the district skips the mandatory CHC level.
            {"org_unit_id": units["P02"]["org_unit_id"], "parent_org_unit_id": str(self.district.org_unit_id)},
        ])
        self.assertEqual(response.status_code, 400)
        self.assertIn("P02", response.get_json()["error"])
        self.assertIn("'chc'", response.get_json()["error"])

        units = self._units()
        self.assertTrue(units["P01"]["is_unplaced"], "the valid first placement was not rolled back")
        self.assertEqual(units["P01"]["path"], "P01")

    def test_bulk_place_skips_an_optional_level(self):
        taluka_level = self.levels["taluka"]
        self._import_units_csv("unit_code,unit_name,level_code,parent_code\nC09,CHC Nine,chc,\n")
        c09 = self._units()["C09"]
        self.assertTrue(c09["is_unplaced"])
        self.assertTrue(taluka_level.is_optional)
        response = self._place([{"org_unit_id": c09["org_unit_id"], "parent_org_unit_id": str(self.district.org_unit_id)}])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._units()["C09"]["path"], "D01.C09")

    def test_bulk_place_refuses_blank_parent_and_own_subtree(self):
        self._import_units_csv(FACILITIES_CSV)
        units = self._units()
        blank = self._place([{"org_unit_id": units["P01"]["org_unit_id"], "parent_org_unit_id": None}])
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(self._place([]).status_code, 400)

        under_self = self._place([{"org_unit_id": str(self.chc.org_unit_id), "parent_org_unit_id": str(self.chc.org_unit_id)}])
        self.assertEqual(under_self.status_code, 400)
        self.assertEqual(self._units()["C01"]["path"], "D01.C01")

    def test_moving_a_placed_unit_rewrites_its_subtree(self):
        """The Units tree's drag-and-drop goes through the same endpoint."""
        chc2 = org.create_unit(
            self.PROJECT,
            org_level_id=self.levels["chc"].org_level_id,
            parent_org_unit_id=self.district.org_unit_id,
            unit_code="C02",
            unit_name="CHC Two",
        )
        phc = org.create_unit(
            self.PROJECT,
            org_level_id=self.levels["phc"].org_level_id,
            parent_org_unit_id=self.chc.org_unit_id,
            unit_code="P05",
            unit_name="PHC Five",
        )
        org.create_unit(
            self.PROJECT,
            org_level_id=self.levels["subcentre"].org_level_id,
            parent_org_unit_id=phc.org_unit_id,
            unit_code="S05",
            unit_name="Sub-centre Five",
        )
        db.session.commit()
        self.assertEqual(self._units()["S05"]["path"], "D01.C01.P05.S05")

        response = self._place([{"org_unit_id": str(phc.org_unit_id), "parent_org_unit_id": str(chc2.org_unit_id)}])
        self.assertEqual(response.status_code, 200, response.get_json())
        units = self._units()
        self.assertEqual(units["P05"]["path"], "D01.C02.P05")
        self.assertEqual(units["S05"]["path"], "D01.C02.P05.S05")
        self.assertEqual(units["P05"]["parent_org_unit_id"], str(chc2.org_unit_id))

    def test_place_refused_for_sites_mode_project(self):
        response = self._place(
            [{"org_unit_id": str(self.chc.org_unit_id), "parent_org_unit_id": str(self.district.org_unit_id)}],
            project=self.SITES_PROJECT,
        )
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertIn("Organization", response.get_json()["error"])

    def test_place_cannot_reach_into_another_project(self):
        org.seed_default_organization(self.OTHER_PROJECT)
        other_level = org.list_levels(self.OTHER_PROJECT)[0]
        other_district = org.create_unit(
            self.OTHER_PROJECT, org_level_id=other_level.org_level_id, unit_code="D01", unit_name="Other District"
        )
        db.session.commit()
        response = self._place([{"org_unit_id": str(self.chc.org_unit_id), "parent_org_unit_id": str(other_district.org_unit_id)}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("not found in this project", response.get_json()["error"])
        self.assertEqual(self._units()["C01"]["path"], "D01.C01")

    # -- exclusions ----------------------------------------------------------

    def test_intake_picker_leaves_out_unplaced_units_and_their_subtree(self):
        self._import_units_csv(FACILITIES_CSV)
        units = self._units()
        self._place([{"org_unit_id": units["S01"]["org_unit_id"], "parent_org_unit_id": units["P01"]["org_unit_id"]}])
        self.assertEqual(self._units()["S01"]["path"], "P01.S01")

        response = self.client.get(f"/api/v1/organization/{self.PROJECT}/units")
        self.assertEqual(response.status_code, 200, response.get_json())
        codes = {u["unit_code"] for u in response.get_json()["units"]}
        self.assertIn("C01", codes)
        self.assertNotIn("P01", codes)
        self.assertNotIn("P02", codes)
        self.assertNotIn("S01", codes)

    def test_readiness_warns_while_units_are_unplaced(self):
        check = {c["code"]: c for c in assess_web_intake_readiness(self.PROJECT)["checks"]}["org_unplaced"]
        self.assertEqual(check["status"], "ok")

        self._import_units_csv(FACILITIES_CSV)
        check = {c["code"]: c for c in assess_web_intake_readiness(self.PROJECT)["checks"]}["org_unplaced"]
        self.assertEqual(check["status"], "warn")
        self.assertIn("3 unit(s) are not yet placed", check["message"])
        self.assertIn("Map parents", check["fix_hint"])

    def test_panel_script_is_served(self):
        response = self.client.get(f"/admin/panels/organization?project_id={self.PROJECT}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="org-place-modal"', response.data)
