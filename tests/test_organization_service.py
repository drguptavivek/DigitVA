"""Rules of app/services/organization_service.py (tree, codes, permissions, transfer)."""
import io
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import MasOrgUnit, VaProjectMaster, VaStatuses
from app.services import organization_service as org
from tests.base import BaseTestCase


def _make_project(project_id, name):
    now = datetime.now(UTC)
    if db.session.get(VaProjectMaster, project_id) is None:
        db.session.add(
            VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name=name,
                project_nickname=name,
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()


class OrganizationServiceTests(BaseTestCase):
    PROJECT = "ORGS01"
    OTHER = "ORGS02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _make_project(cls.PROJECT, "Org Service Project")
        _make_project(cls.OTHER, "Org Service Other")
        db.session.commit()

    # -- helpers -----------------------------------------------------------

    def _levels(self):
        return {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}

    def _seed_tree(self):
        org.seed_default_organization(self.PROJECT)
        lv = self._levels()
        d = org.create_unit(self.PROJECT, org_level_id=lv["district"].org_level_id, unit_code="D01", unit_name="District One")
        c = org.create_unit(self.PROJECT, org_level_id=lv["chc"].org_level_id, parent_org_unit_id=d.org_unit_id, unit_code="C01", unit_name="CHC One")
        p = org.create_unit(self.PROJECT, org_level_id=lv["phc"].org_level_id, parent_org_unit_id=c.org_unit_id, unit_code="P01", unit_name="PHC One", latitude="12.5", longitude="77.25", google_maps_url="https://maps.app.goo.gl/x")
        s = org.create_unit(self.PROJECT, org_level_id=lv["subcentre"].org_level_id, parent_org_unit_id=p.org_unit_id, unit_code="S01", unit_name="Sub-centre One")
        return d, c, p, s

    # -- template ------------------------------------------------------------

    def test_seed_template_is_idempotent(self):
        first = org.seed_default_organization(self.PROJECT)
        second = org.seed_default_organization(self.PROJECT)
        self.assertEqual(first, {"levels": 6, "cadres": 6, "level_cadres": 8})
        self.assertEqual(second, {"levels": 0, "cadres": 0, "level_cadres": 0})
        self.assertEqual([lv.depth for lv in org.list_levels(self.PROJECT)], [1, 2, 3, 4, 5, 6])
        self.assertEqual(self._levels()["phc"].odk_field_name, "org_phc_code")

    # -- tree rules ----------------------------------------------------------

    def test_optional_level_may_be_skipped_but_required_level_may_not(self):
        d, c, p, s = self._seed_tree()
        self.assertEqual(str(c.path), "D01.C01")  # taluka (optional) skipped
        self.assertEqual(str(s.path), "D01.C01.P01.S01")
        lv = self._levels()
        with self.assertRaises(org.OrganizationError) as ctx:
            org.create_unit(self.PROJECT, org_level_id=lv["phc"].org_level_id, parent_org_unit_id=d.org_unit_id, unit_code="P99", unit_name="Skips CHC")
        self.assertIn("'chc'", str(ctx.exception))
        with self.assertRaises(org.OrganizationError):
            org.create_unit(self.PROJECT, org_level_id=lv["phc"].org_level_id, unit_code="P98", unit_name="No parent")
        with self.assertRaises(org.OrganizationError):
            org.create_unit(self.PROJECT, org_level_id=lv["district"].org_level_id, unit_code="d01", unit_name="Duplicate after upper-casing")

    def test_code_is_project_scoped_and_normalized(self):
        self._seed_tree()
        org.seed_default_organization(self.OTHER)
        other_level = {lv.level_code: lv for lv in org.list_levels(self.OTHER)}["district"]
        unit = org.create_unit(self.OTHER, org_level_id=other_level.org_level_id, unit_code=" d01 ", unit_name="Same code, other project")
        self.assertEqual(unit.unit_code, "D01")
        with self.assertRaises(org.OrganizationError):
            org.normalize_code("bad code!")

    def test_rename_and_move_rewrite_subtree_paths(self):
        d, c, p, s = self._seed_tree()
        org.update_unit(self.PROJECT, c.org_unit_id, unit_code="C02")
        paths = {u.unit_code: str(u.path) for u in db.session.scalars(sa.select(MasOrgUnit).where(MasOrgUnit.project_id == self.PROJECT))}
        self.assertEqual(paths["S01"], "D01.C02.P01.S01")
        lv = self._levels()
        d2 = org.create_unit(self.PROJECT, org_level_id=lv["district"].org_level_id, unit_code="D02", unit_name="District Two")
        org.update_unit(self.PROJECT, c.org_unit_id, parent_org_unit_id=d2.org_unit_id)
        moved = db.session.get(MasOrgUnit, s.org_unit_id)
        self.assertEqual(str(moved.path), "D02.C02.P01.S01")
        with self.assertRaises(org.OrganizationError):
            org.update_unit(self.PROJECT, c.org_unit_id, parent_org_unit_id=s.org_unit_id)

    def test_deactivate_cascades_and_reactivate_needs_active_parent(self):
        d, c, p, s = self._seed_tree()
        self.assertEqual(org.set_unit_active(self.PROJECT, c.org_unit_id, False), 3)
        self.assertFalse(db.session.get(MasOrgUnit, s.org_unit_id).is_active)
        with self.assertRaises(org.OrganizationError):
            org.set_unit_active(self.PROJECT, s.org_unit_id, True)
        self.assertEqual(org.set_unit_active(self.PROJECT, c.org_unit_id, True), 1)
        self.assertEqual(len(org.get_unit_tree(self.PROJECT)), 1)
        self.assertEqual([u["unit_code"] for u in org.list_units(self.PROJECT, include_inactive=True)], ["D01", "C01", "P01", "S01"])
        self.assertEqual(org.subtree_unit_ids(d), [d.org_unit_id, c.org_unit_id])

    # -- cadres, permissions, workers ----------------------------------------

    def test_worker_requires_cadre_defined_at_unit_level(self):
        d, c, p, s = self._seed_tree()
        cadres = {cd.cadre_code: cd for cd in org.list_cadres(self.PROJECT)}
        worker = org.create_worker(self.PROJECT, org_unit_id=s.org_unit_id, cadre_id=cadres["CHO"].cadre_id, worker_code="W01", worker_name="A CHO", user=self.base_coder_user.email)
        self.assertEqual(worker.user_id, self.base_coder_user.user_id)
        with self.assertRaises(org.OrganizationError) as ctx:
            org.create_worker(self.PROJECT, org_unit_id=d.org_unit_id, cadre_id=cadres["ASHA"].cadre_id, worker_code="W02", worker_name="ASHA at district")
        self.assertIn("not defined at level", str(ctx.exception))
        listed = org.list_workers(self.PROJECT)
        self.assertEqual(listed[0]["user_email"], self.base_coder_user.email)
        perm = org.get_level_cadre_permission(s.org_level_id, cadres["CHO"].cadre_id)
        self.assertTrue(perm.can_fill_va_form)
        self.assertFalse(perm.can_code_va_form)

    def test_level_cannot_deactivate_while_units_exist(self):
        self._seed_tree()
        lv = self._levels()
        with self.assertRaises(org.OrganizationError):
            org.update_level(self.PROJECT, lv["phc"].org_level_id, is_active=False)
        with self.assertRaises(org.OrganizationError):
            org.update_level(self.PROJECT, lv["phc"].org_level_id, depth=9)
        org.update_level(self.PROJECT, lv["village"].org_level_id, is_active=False)

    # -- export / import -----------------------------------------------------

    def test_export_import_round_trip(self):
        d, c, p, s = self._seed_tree()
        cadres = {cd.cadre_code: cd for cd in org.list_cadres(self.PROJECT)}
        org.create_worker(self.PROJECT, org_unit_id=p.org_unit_id, cadre_id=cadres["MO"].cadre_id, worker_code="MO01", worker_name="Dr One", phone="9999")
        workbook = org.export_organization_xlsx(self.PROJECT)
        sheets = org.parse_organization_workbook(io.BytesIO(workbook))
        self.assertEqual(sorted(sheets), sorted(org.EXPORT_SHEETS))
        self.assertEqual(len(sheets["units"]), 4)

        # Same project: everything is an update, nothing applied on dry run.
        plan = org.import_organization(self.PROJECT, sheets, dry_run=True)
        self.assertEqual(plan.errors, [])
        self.assertFalse(plan.applied)
        self.assertEqual(plan.creates["units"], [])
        self.assertEqual(sorted(plan.updates["units"]), ["C01", "D01", "P01", "S01"])

        # Fresh project: everything is created, then a rerun is all updates.
        plan2 = org.import_organization(self.OTHER, sheets, dry_run=False)
        self.assertEqual(plan2.errors, [])
        self.assertTrue(plan2.applied)
        self.assertEqual(sorted(plan2.creates["units"]), ["C01", "D01", "P01", "S01"])
        self.assertEqual(plan2.creates["workers"], ["MO01"])
        copied = org.list_units(self.OTHER)
        self.assertEqual([u["path"] for u in copied], ["D01", "D01.C01", "D01.C01.P01", "D01.C01.P01.S01"])
        self.assertEqual(copied[2]["latitude"], "12.500000")
        plan3 = org.import_organization(self.OTHER, sheets, dry_run=False)
        self.assertEqual(plan3.creates["units"], [])

        # deactivate_missing only acts with the flag; a bad row aborts everything.
        trimmed = {**sheets, "units": [row for row in sheets["units"] if row["unit_code"] != "S01"], "workers": []}
        plan4 = org.import_organization(self.OTHER, trimmed, dry_run=False, deactivate_missing=True)
        self.assertEqual(plan4.deactivates["units"], ["S01"])
        self.assertEqual(plan4.deactivates["workers"], ["MO01"])
        broken = {**sheets, "units": sheets["units"] + [{"unit_code": "X!", "level_code": "phc", "unit_name": "bad"}]}
        plan5 = org.import_organization(self.OTHER, broken, dry_run=False)
        self.assertFalse(plan5.applied)
        self.assertTrue(plan5.errors and "units row" in plan5.errors[0])

    def test_odk_choices_and_csv_exports(self):
        self._seed_tree()
        rows = org.export_odk_choices_rows(self.PROJECT)
        self.assertEqual(rows[0], {"list_name": "org_district", "name": "D01", "label": "District One", "parent_code": ""})
        self.assertEqual(rows[1], {"list_name": "org_chc", "name": "C01", "label": "CHC One", "parent_code": "D01"})
        self.assertIn("list_name,name,label,parent_code", org.export_odk_choices_csv(self.PROJECT))
        self.assertIn("unit_code,unit_name,level_code,parent_code,path", org.export_organization_csv(self.PROJECT, "units"))
        with self.assertRaises(org.OrganizationError):
            org.export_organization_csv(self.PROJECT, "nope")
