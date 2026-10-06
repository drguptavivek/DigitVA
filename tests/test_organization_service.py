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
        self.assertEqual(first, {"levels": 6, "cadres": 11, "level_cadres": 15})
        self.assertEqual(second, {"levels": 0, "cadres": 0, "level_cadres": 0})
        self.assertEqual([lv.depth for lv in org.list_levels(self.PROJECT)], [1, 2, 3, 4, 5, 6])
        self.assertEqual(self._levels()["phc"].odk_field_name, "org_phc_code")
        grid = {
            (row["level_code"], row["cadre_code"]): (
                row["can_fill_va_form"], row["can_code_va_form"], row["can_supervise_interviews"],
                row["can_report_deaths"],
            )
            for row in org.list_level_cadres(self.PROJECT)
        }
        self.assertEqual(grid, org.DEFAULT_LEVEL_CADRE_TEMPLATE)
        self.assertEqual(grid[("district", "CS")], (False, False, True, False))
        self.assertEqual(grid[("chc", "SMO")], (False, True, True, False))
        self.assertEqual(grid[("phc", "MO")], (False, True, True, False))
        self.assertEqual(grid[("chc", "MO")], (False, True, False, False))
        # Owner 2026-10-06: ANM and MPW at the sub-centre and ASHA at the village report deaths.
        reporters = {key for key, flags in grid.items() if flags[3]}
        self.assertEqual(
            reporters, {("subcentre", "ANM"), ("subcentre", "MPW"), ("village", "ASHA")}
        )

    def test_seed_template_never_overwrites_an_existing_row(self):
        org.seed_default_organization(self.PROJECT)
        lv = self._levels()
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        org.update_level(self.PROJECT, lv["district"].org_level_id, level_name="Zila")
        org.upsert_level_cadre(
            self.PROJECT, org_level_id=lv["district"].org_level_id, cadre_id=cadres["CS"].cadre_id,
            can_fill_va_form=True, can_code_va_form=True, can_supervise_interviews=False,
        )
        self.assertEqual(
            org.seed_default_organization(self.PROJECT), {"levels": 0, "cadres": 0, "level_cadres": 0}
        )
        row = org.get_level_cadre_permission(lv["district"].org_level_id, cadres["CS"].cadre_id)
        self.assertIsNotNone(row)
        self.assertEqual(
            (row.can_fill_va_form, row.can_code_va_form, row.can_supervise_interviews), (True, True, False)
        )
        self.assertEqual(self._levels()["district"].level_name, "Zila")

    def test_seed_template_without_cadres_adds_levels_only(self):
        self.assertEqual(
            org.seed_default_organization(self.PROJECT, include_cadres=False),
            {"levels": 6, "cadres": 0, "level_cadres": 0},
        )
        self.assertEqual(org.list_level_cadres(self.PROJECT), [])

    def test_district_reference_model_matches_the_template(self):
        model = org.district_reference_model()
        self.assertEqual([lv["level_code"] for lv in model["levels"]],
                         ["district", "taluka", "chc", "phc", "subcentre", "village"])
        rows = {(r["level_code"], r["cadre_code"]): r for r in model["grid"]}
        self.assertEqual(set(rows), set(org.DEFAULT_LEVEL_CADRE_TEMPLATE))
        # A typical-roles key the grid does not have would never be shown.
        self.assertTrue(set(org.DEFAULT_TYPICAL_ROLES) <= set(org.DEFAULT_LEVEL_CADRE_TEMPLATE))
        # The In-charge is site_pi held at the unit (district, block, PHC).
        self.assertEqual(rows[("district", "CS")]["typical_roles"], ["site_pi"])
        self.assertEqual(rows[("chc", "SMO")]["typical_roles"], ["site_pi", "reviewer"])
        self.assertEqual(rows[("phc", "MO")]["typical_roles"], ["site_pi", "coder"])
        self.assertTrue(rows[("district", "CS")]["can_supervise_interviews"])
        for key in (("subcentre", "ANM"), ("subcentre", "MPW"), ("village", "ASHA")):
            self.assertEqual(rows[key]["typical_roles"], ["death_reporter"])
            self.assertTrue(rows[key]["can_report_deaths"])
        self.assertFalse(rows[("subcentre", "CHO")]["can_report_deaths"])

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
        self.assertCountEqual(org.subtree_unit_ids(d), [d.org_unit_id, c.org_unit_id])

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

    def test_level_cadre_cannot_be_removed_while_active_workers_hold_it(self):
        d, c, p, s = self._seed_tree()
        cadres = {cd.cadre_code: cd for cd in org.list_cadres(self.PROJECT)}
        worker = org.create_worker(self.PROJECT, org_unit_id=s.org_unit_id, cadre_id=cadres["CHO"].cadre_id, worker_code="W01", worker_name="A CHO")
        perm = org.get_level_cadre_permission(s.org_level_id, cadres["CHO"].cadre_id)
        self.assertIsNotNone(perm)
        with self.assertRaises(org.OrganizationError) as ctx:
            org.upsert_level_cadre(
                self.PROJECT, org_level_id=s.org_level_id, cadre_id=cadres["CHO"].cadre_id,
                can_fill_va_form=perm.can_fill_va_form, can_code_va_form=perm.can_code_va_form, is_active=False,
            )
        self.assertIn("first", str(ctx.exception))
        org.update_worker(self.PROJECT, worker.worker_id, is_active=False)
        org.upsert_level_cadre(
            self.PROJECT, org_level_id=s.org_level_id, cadre_id=cadres["CHO"].cadre_id,
            can_fill_va_form=perm.can_fill_va_form, can_code_va_form=perm.can_code_va_form, is_active=False,
        )
        self.assertIsNone(org.get_level_cadre_permission(s.org_level_id, cadres["CHO"].cadre_id))

    def test_worker_cannot_be_created_or_moved_onto_inactive_cadre(self):
        d, c, p, s = self._seed_tree()
        cadres = {cd.cadre_code: cd for cd in org.list_cadres(self.PROJECT)}
        w1 = org.create_worker(self.PROJECT, org_unit_id=s.org_unit_id, cadre_id=cadres["CHO"].cadre_id, worker_code="W01", worker_name="A CHO")
        w2 = org.create_worker(self.PROJECT, org_unit_id=s.org_unit_id, cadre_id=cadres["MPW"].cadre_id, worker_code="W02", worker_name="An MPW")
        org.update_cadre(self.PROJECT, cadres["CHO"].cadre_id, is_active=False)
        with self.assertRaises(org.OrganizationError) as ctx:
            org.create_worker(self.PROJECT, org_unit_id=s.org_unit_id, cadre_id=cadres["CHO"].cadre_id, worker_code="W03", worker_name="Another CHO")
        self.assertIn("inactive", str(ctx.exception))
        with self.assertRaises(org.OrganizationError) as ctx:
            org.update_worker(self.PROJECT, w2.worker_id, cadre_id=cadres["CHO"].cadre_id)
        self.assertIn("inactive", str(ctx.exception))
        org.update_worker(self.PROJECT, w1.worker_id, worker_name="Renamed")
        listed = {w["worker_id"]: w for w in org.list_workers(self.PROJECT)}
        self.assertEqual(listed[str(w1.worker_id)]["worker_name"], "Renamed")
        self.assertEqual(listed[str(w1.worker_id)]["cadre_code"], "CHO")

    def test_import_retires_level_cadre_and_its_workers_in_one_file(self):
        # Level-cadre deactivations are applied after workers, so one file
        # can retire a level-cadre and deactivate the workers holding it.
        d, c, p, s = self._seed_tree()
        cadres = {cd.cadre_code: cd for cd in org.list_cadres(self.PROJECT)}
        worker = org.create_worker(self.PROJECT, org_unit_id=s.org_unit_id, cadre_id=cadres["CHO"].cadre_id, worker_code="W01", worker_name="A CHO")
        sheets = org.export_organization_rows(self.PROJECT)
        self.assertIn(("subcentre", "CHO"), {(r["level_code"], r["cadre_code"]) for r in sheets["level_cadres"]})
        sheets["level_cadres"] = [r for r in sheets["level_cadres"] if (r["level_code"], r["cadre_code"]) != ("subcentre", "CHO")]

        # The worker still active: the guard refuses the whole import.
        plan = org.import_organization(self.PROJECT, sheets, dry_run=False, deactivate_missing=True)
        self.assertTrue(any("first" in e for e in plan.errors), plan.errors)
        self.assertFalse(plan.applied)
        self.assertIsNotNone(org.get_level_cadre_permission(s.org_level_id, cadres["CHO"].cadre_id))

        for row in sheets["workers"]:
            if row["worker_code"] == "W01":
                row["is_active"] = False
        plan = org.import_organization(self.PROJECT, sheets, dry_run=False, deactivate_missing=True)
        self.assertEqual(plan.errors, [])
        self.assertTrue(plan.applied)
        self.assertIn("subcentre/CHO", plan.deactivates["level_cadres"])
        self.assertIsNone(org.get_level_cadre_permission(s.org_level_id, cadres["CHO"].cadre_id))
        self.assertFalse(db.session.get(type(worker), worker.worker_id).is_active)

    # -- the Report deaths flag (digitva-t6q) ---------------------------------

    def _report_flags(self):
        return {
            (r["level_code"], r["cadre_code"]): r["can_report_deaths"]
            for r in org.list_level_cadres(self.PROJECT)
        }

    def test_upsert_with_no_report_deaths_value_keeps_the_stored_one(self):
        org.seed_default_organization(self.PROJECT)
        lv = self._levels()
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        args = dict(org_level_id=lv["subcentre"].org_level_id, cadre_id=cadres["ANM"].cadre_id,
                    can_fill_va_form=False, can_code_va_form=False)
        self.assertTrue(self._report_flags()[("subcentre", "ANM")])  # present first
        self.assertTrue(org.upsert_level_cadre(self.PROJECT, **args, can_report_deaths=None).can_report_deaths)
        self.assertFalse(org.upsert_level_cadre(self.PROJECT, **args, can_report_deaths=False).can_report_deaths)
        self.assertFalse(org.upsert_level_cadre(self.PROJECT, **args).can_report_deaths)

    def test_the_report_deaths_flag_goes_through_csv_and_xlsx_export_and_import(self):
        import csv

        org.seed_default_organization(self.PROJECT)
        # Export: the header and the row (CSV), the sheet (XLSX).
        text = org.export_organization_csv(self.PROJECT, "level_cadres")
        reader = csv.DictReader(io.StringIO(text))
        self.assertIn("can_report_deaths", reader.fieldnames)
        rows = {(r["level_code"], r["cadre_code"]): r for r in reader}
        self.assertEqual(rows[("subcentre", "ANM")]["can_report_deaths"], "True")
        self.assertEqual(rows[("subcentre", "CHO")]["can_report_deaths"], "False")
        workbook = org.parse_organization_workbook(io.BytesIO(org.export_organization_xlsx(self.PROJECT)))
        sheet = {(r["level_code"], r["cadre_code"]): r for r in workbook["level_cadres"]}
        self.assertTrue(sheet[("subcentre", "ANM")]["can_report_deaths"])
        self.assertFalse(sheet[("subcentre", "CHO")]["can_report_deaths"])

        # Import (CSV): the CHO gains the flag, the ANM loses it.
        edited = text.replace("subcentre,CHO,True,False,False,False", "subcentre,CHO,True,False,False,True")
        # The ANM's blank default_roles keeps the stored one, which the cleared flag then drops.
        edited = edited.replace("subcentre,ANM,False,False,False,True,death_reporter", "subcentre,ANM,False,False,False,False,")
        self.assertNotEqual(edited, text)
        plan = org.import_organization(
            self.PROJECT, org.parse_organization_csv(io.BytesIO(edited.encode()), "level_cadres"), dry_run=False)
        self.assertEqual(plan.errors, [])
        flags = self._report_flags()
        self.assertEqual((flags[("subcentre", "CHO")], flags[("subcentre", "ANM")]), (True, False))
        # Import (XLSX rows): an empty cell keeps the stored value.
        sheet[("subcentre", "ANM")]["can_report_deaths"] = None
        sheet[("subcentre", "ANM")]["default_roles"] = None
        plan = org.import_organization(self.PROJECT, {"level_cadres": list(sheet.values())}, dry_run=False)
        self.assertEqual(plan.errors, [])
        self.assertFalse(self._report_flags()[("subcentre", "ANM")])
        self.assertTrue(self._report_flags()[("village", "ASHA")])

    def test_deactivating_a_level_cadre_by_import_keeps_its_report_deaths_flag(self):
        from app.models import MapOrgLevelCadre

        org.seed_default_organization(self.PROJECT)
        rows = [r for r in org.export_organization_rows(self.PROJECT)["level_cadres"]
                if (r["level_code"], r["cadre_code"]) != ("village", "ASHA")]
        plan = org.import_organization(self.PROJECT, {"level_cadres": rows}, dry_run=False, deactivate_missing=True)
        self.assertEqual(plan.errors, [])
        self.assertIn("village/ASHA", plan.deactivates["level_cadres"])
        village = self._levels()["village"]
        asha = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}["ASHA"]
        row = db.session.scalar(sa.select(MapOrgLevelCadre).where(
            MapOrgLevelCadre.org_level_id == village.org_level_id, MapOrgLevelCadre.cadre_id == asha.cadre_id))
        self.assertEqual((row.is_active, row.can_report_deaths), (False, True))

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
