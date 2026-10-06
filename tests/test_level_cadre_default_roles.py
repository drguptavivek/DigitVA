"""Default roles per level x cadre (digitva-vjt, owner decision 2026-10-06).

The stored column, its validation against the row's flags, the grid API and
CSV/XLSX round trip, and the one place a default acts on the server: a project
user import row that names no role. Defaults never grant by themselves and
editing one never touches an existing grant.

Policy: docs/policy/district-reference-model.md, "Default roles by cadre".
"""
import csv
import io
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.models.mas_languages import MasLanguages
from app.services import organization_service as org
from tests.base import BaseTestCase

USER_HEADER = "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"


class LevelCadreDefaultRolesTests(BaseTestCase):
    PROJECT = "ORGD01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT, project_code=cls.PROJECT, project_name="Default Roles Project",
            project_nickname="DefRoles", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
        ))
        if db.session.get(MasLanguages, "en") is None:
            db.session.add(MasLanguages(language_code="en", language_name="English", is_active=True))
        db.session.commit()

    # -- helpers -----------------------------------------------------------

    def _url(self, suffix=""):
        return f"/admin/api/organization/{self.PROJECT}{suffix}"

    def _grid(self):
        return {(r["level_code"], r["cadre_code"]): r for r in org.list_level_cadres(self.PROJECT)}

    def _row(self, level_code, cadre_code):
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        return levels[level_code], cadres[cadre_code]

    def _upsert(self, level_code, cadre_code, **kwargs):
        level, cadre = self._row(level_code, cadre_code)
        current = self._grid()[(level_code, cadre_code)]
        args = dict(
            can_fill_va_form=current["can_fill_va_form"], can_code_va_form=current["can_code_va_form"],
            can_supervise_interviews=current["can_supervise_interviews"],
            can_report_deaths=current["can_report_deaths"],
        )
        args.update(kwargs)
        return org.upsert_level_cadre(
            self.PROJECT, org_level_id=level.org_level_id, cadre_id=cadre.cadre_id, **args)

    def _put(self, level_code, cadre_code, **body):
        level, cadre = self._row(level_code, cadre_code)
        return self.client.put(
            self._url("/level-cadres"), headers=self._csrf_headers(),
            json={"org_level_id": str(level.org_level_id), "cadre_id": str(cadre.cadre_id),
                  "can_fill_va_form": False, "can_code_va_form": False, **body})

    def _import_users(self, text):
        return self.client.post(
            self._url("/project-users/import"),
            data={"file": (io.BytesIO(text.encode("utf-8")), "users.csv"), "dry_run": "0"},
            content_type="multipart/form-data", headers=self._csrf_headers())

    def _phc_unit(self):
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id,
                                   unit_code="DD1", unit_name="District")
        chc = org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id,
                              unit_code="DC1", unit_name="CHC", parent_org_unit_id=district.org_unit_id)
        return org.create_unit(self.PROJECT, org_level_id=levels["phc"].org_level_id,
                               unit_code="DP1", unit_name="PHC", parent_org_unit_id=chc.org_unit_id)

    def _grant_roles(self, unit):
        return sorted(
            grant.role.value for grant in db.session.scalars(
                sa.select(VaUserAccessGrants).where(
                    VaUserAccessGrants.org_unit_id == unit.org_unit_id,
                    VaUserAccessGrants.user_id == self.base_coder_id,
                    VaUserAccessGrants.grant_status == VaStatuses.active,
                )
            )
        )

    # -- seed and validation ---------------------------------------------------

    def test_a_new_grid_takes_the_template_defaults_and_unlisted_rows_start_empty(self):
        org.seed_default_organization(self.PROJECT)
        grid = self._grid()
        self.assertEqual(grid[("district", "CS")]["default_roles"], ["site_pi"])
        self.assertEqual(grid[("phc", "MO")]["default_roles"], ["site_pi", "coder"])
        self.assertEqual(grid[("village", "ASHA")]["default_roles"], ["death_reporter"])
        self.assertEqual(grid[("subcentre", "ANM")]["default_roles"], ["death_reporter"])
        for key, roles in org.DEFAULT_TYPICAL_ROLES.items():
            self.assertEqual(set(grid[key]["default_roles"]), set(roles), key)

    def test_a_default_the_flags_do_not_allow_is_refused_and_nothing_changes(self):
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        # (subcentre, CHO): fill only. Each flag-bound role is refused, interviewer is not.
        for role in ("coder", "interview_supervisor", "death_reporter"):
            with self.subTest(role=role):
                with self.assertRaises(org.OrganizationError) as raised:
                    self._upsert("subcentre", "CHO", default_roles=[role])
                self.assertIn(role, str(raised.exception))
        db.session.rollback()
        self.assertEqual(self._grid()[("subcentre", "CHO")]["default_roles"], ["interviewer"])
        saved = self._upsert("subcentre", "CHO", default_roles=["interviewer", "reviewer", "collaborator_pii"])
        self.assertEqual(saved.default_roles, ["collaborator_pii", "reviewer", "interviewer"])

    def test_roles_that_cannot_be_held_at_a_unit_or_do_not_exist_are_refused(self):
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        for role in ("admin", "project_pi", "not_a_role"):
            with self.subTest(role=role), self.assertRaises(org.OrganizationError):
                self._upsert("district", "MO", default_roles=[role])
            db.session.rollback()

    def test_the_flag_rule_is_the_grant_writes(self):
        # One rule: every role the grant write ties to a flag is checked here.
        from app.services.org_grant_service import CADRE_FLAG_BY_ROLE

        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        for role, (flag, _permits) in CADRE_FLAG_BY_ROLE.items():
            # (village, ASHA) carries only Fill VA and Report deaths.
            flagged = flag == "can_report_deaths"
            with self.subTest(role=role.value):
                if flagged:
                    self.assertEqual(
                        self._upsert("village", "ASHA", default_roles=[role.value]).default_roles, [role.value])
                else:
                    with self.assertRaises(org.OrganizationError):
                        self._upsert("village", "ASHA", default_roles=[role.value])
                    db.session.rollback()

    def test_clearing_a_flag_drops_the_stored_defaults_that_relied_on_it(self):
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        # Supplied defaults are checked against the new flags: refused.
        with self.assertRaises(org.OrganizationError):
            self._upsert("phc", "MO", can_code_va_form=False, default_roles=["site_pi", "coder"])
        db.session.rollback()
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["site_pi", "coder"])
        # A caller that never mentions defaults (an older workbook) can still clear the flag.
        row = self._upsert("phc", "MO", can_code_va_form=False)
        self.assertEqual((row.can_code_va_form, row.default_roles), (False, ["site_pi"]))

    def test_none_keeps_the_stored_defaults_and_an_empty_list_clears_them(self):
        org.seed_default_organization(self.PROJECT)
        self.assertEqual(self._upsert("phc", "MO").default_roles, ["site_pi", "coder"])
        self.assertEqual(self._upsert("phc", "MO", default_roles=[]).default_roles, [])
        self.assertEqual(self._upsert("phc", "MO").default_roles, [])

    # -- API -------------------------------------------------------------------

    def test_api_round_trips_the_column_with_none_keeps(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        listed = {(r["level_code"], r["cadre_code"]): r
                  for r in self.client.get(self._url("/level-cadres")).get_json()["level_cadres"]}
        self.assertEqual(listed[("phc", "MO")]["default_roles"], ["site_pi", "coder"])

        body = {"can_code_va_form": True, "can_supervise_interviews": True}
        kept = self._put("phc", "MO", **body)  # key absent keeps
        self.assertEqual(kept.status_code, 200, kept.get_json())
        self.assertEqual(kept.get_json()["level_cadre"]["default_roles"], ["site_pi", "coder"])
        changed = self._put("phc", "MO", **body, default_roles=["interview_supervisor", "coder"])
        self.assertEqual(changed.get_json()["level_cadre"]["default_roles"], ["coder", "interview_supervisor"])
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["coder", "interview_supervisor"])

    def test_api_refuses_a_default_the_flags_do_not_allow(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        before = self._grid()[("subcentre", "CHO")]["default_roles"]
        refused = self._put("subcentre", "CHO", can_fill_va_form=True, default_roles=["coder"])
        self.assertEqual(refused.status_code, 400)
        self.assertIn("coder", refused.get_json()["error"])
        for bad in ("coder", {"coder": True}):
            self.assertEqual(self._put("subcentre", "CHO", default_roles=bad).status_code, 400)
        self.assertEqual(self._grid()[("subcentre", "CHO")]["default_roles"], before)

    # -- CSV / XLSX --------------------------------------------------------------

    def test_csv_and_xlsx_carry_default_roles_pipe_separated(self):
        org.seed_default_organization(self.PROJECT)
        self._upsert("phc", "MO", default_roles=["coder", "site_pi"])
        text = org.export_organization_csv(self.PROJECT, "level_cadres")
        reader = csv.DictReader(io.StringIO(text))
        self.assertIn("default_roles", reader.fieldnames)
        rows = {(r["level_code"], r["cadre_code"]): r for r in reader}
        self.assertEqual(rows[("phc", "MO")]["default_roles"], "site_pi|coder")
        self.assertEqual(rows[("district", "DPM")]["default_roles"], "data_manager")
        sheet = {(r["level_code"], r["cadre_code"]): r for r in org.parse_organization_workbook(
            io.BytesIO(org.export_organization_xlsx(self.PROJECT)))["level_cadres"]}
        self.assertEqual(sheet[("phc", "MO")]["default_roles"], "site_pi|coder")

        # CSV import changes them; the unedited export re-imports unchanged.
        edited = text.replace("phc,MO,False,True,True,False,site_pi|coder", "phc,MO,False,True,True,False,reviewer| coder")
        self.assertNotEqual(edited, text)
        plan = org.import_organization(
            self.PROJECT, org.parse_organization_csv(io.BytesIO(edited.encode()), "level_cadres"), dry_run=False)
        self.assertEqual(plan.errors, [])
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["coder", "reviewer"])
        again = org.import_organization(
            self.PROJECT, org.parse_organization_csv(io.BytesIO(
                org.export_organization_csv(self.PROJECT, "level_cadres").encode()), "level_cadres"), dry_run=False)
        self.assertEqual(again.errors, [])
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["coder", "reviewer"])

        # XLSX rows: a blank cell keeps, a bad one is refused with nothing written.
        sheet[("phc", "MO")]["default_roles"] = None
        plan = org.import_organization(self.PROJECT, {"level_cadres": list(sheet.values())}, dry_run=False)
        self.assertEqual(plan.errors, [])
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["coder", "reviewer"])

    def test_import_refuses_a_default_the_row_flags_do_not_allow(self):
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        text = org.export_organization_csv(self.PROJECT, "level_cadres")
        bad = text.replace("subcentre,CHO,True,False,False,False,interviewer", "subcentre,CHO,True,False,False,False,interviewer|coder")
        self.assertNotEqual(bad, text)
        plan = org.import_organization(
            self.PROJECT, org.parse_organization_csv(io.BytesIO(bad.encode()), "level_cadres"), dry_run=False)
        self.assertTrue(any("coder" in e for e in plan.errors), plan.errors)
        self.assertFalse(plan.applied)
        db.session.rollback()
        self.assertEqual(self._grid()[("subcentre", "CHO")]["default_roles"], ["interviewer"])

    # -- the project user import ---------------------------------------------------

    def test_import_applies_defaults_only_to_a_row_that_names_no_role(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        phc = self._phc_unit()
        db.session.commit()

        # Names a role: that role only, defaults ignored.
        named = self._import_users(USER_HEADER + "base.coder@test.local,,reviewer,DP1,MO,,\n")
        self.assertEqual(named.status_code, 200, named.get_json())
        self.assertEqual(self._grant_roles(phc), ["reviewer"])

        # Names none: one grant per default role of (phc, MO) = site_pi, coder.
        blank = self._import_users(USER_HEADER + "base.coder@test.local,,,DP1,MO,,\n")
        self.assertEqual(blank.status_code, 200, blank.get_json())
        self.assertEqual(self._grant_roles(phc), ["coder", "reviewer", "site_pi"])
        grants = db.session.scalars(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.org_unit_id == phc.org_unit_id)).all()
        self.assertTrue(all(g.scope_type == VaAccessScopeTypes.org_unit and g.cadre_id for g in grants))

    def test_import_row_with_no_role_and_nothing_to_default_to_is_refused(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        phc = self._phc_unit()
        self._upsert("phc", "CHO", default_roles=[])
        db.session.commit()
        for row in ("base.coder@test.local,,,DP1,,,\n",      # no cadre
                    "base.coder@test.local,,,,MO,,\n",       # no unit
                    "base.coder@test.local,,,DP1,CHO,,\n"):  # cadre with no defaults
            with self.subTest(row=row):
                response = self._import_users(USER_HEADER + row)
                self.assertEqual(response.status_code, 400)
                self.assertIn("role must be one of", response.get_json()["error"])
        self.assertEqual(self._grant_roles(phc), [])

    def test_an_expanded_row_is_checked_like_an_explicit_one(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        phc = self._phc_unit()
        db.session.commit()
        # (phc, MO) defaults to site_pi and coder; an explicit coder row repeats one.
        response = self._import_users(
            USER_HEADER + "base.coder@test.local,,,DP1,MO,,\nbase.coder@test.local,,coder,DP1,MO,,\n")
        self.assertEqual(response.status_code, 400)
        self.assertIn("duplicate person, role and scope", response.get_json()["error"])
        self.assertEqual(self._grant_roles(phc), [])

    # -- later edits leave grants alone --------------------------------------------

    def test_editing_a_default_later_leaves_existing_grants_unchanged(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        phc = self._phc_unit()
        db.session.commit()
        self.assertEqual(self._import_users(USER_HEADER + "base.coder@test.local,,,DP1,MO,,\n").status_code, 200)
        self.assertEqual(self._grant_roles(phc), ["coder", "site_pi"])

        changed = self._put("phc", "MO", can_code_va_form=True, default_roles=["reviewer"])
        self.assertEqual(changed.status_code, 200, changed.get_json())
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["reviewer"])
        db.session.expire_all()
        self.assertEqual(self._grant_roles(phc), ["coder", "site_pi"])
        self.assertEqual(self._put("phc", "MO", can_code_va_form=True, default_roles=[]).status_code, 200)
        db.session.expire_all()
        self.assertEqual(self._grant_roles(phc), ["coder", "site_pi"])

    # -- one source for the unit-scope role set ---------------------------------

    def test_the_check_and_the_migration_name_the_roles_a_unit_grant_may_carry(self):
        import importlib.util
        import re
        from pathlib import Path

        from app.models import MapOrgLevelCadre
        from app.services.org_grant_service import ROLES_ALLOWING_ORG_UNIT

        check = next(c for c in MapOrgLevelCadre.__table__.constraints
                     if isinstance(c, sa.CheckConstraint) and "default_roles" in str(c.sqltext))
        in_model = set(re.findall(r"'(\w+)'", str(check.sqltext)))
        path = next(Path("migrations/versions").glob("g3k7o1s5w9a2_*.py"))
        spec = importlib.util.spec_from_file_location("default_roles_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        expected = {role.value for role in ROLES_ALLOWING_ORG_UNIT}
        self.assertEqual(in_model, expected)
        self.assertEqual(set(migration.UNIT_ROLES), expected)

    def test_a_database_refusal_is_a_400_on_put_and_a_row_error_on_import(self):
        from unittest.mock import patch

        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        db.session.commit()
        # A role the application checks let through but the CHECK refuses.
        with patch.object(org, "normalize_default_roles", return_value=["admin"]):
            response = self._put("phc", "MO", can_code_va_form=True, default_roles=["coder"])
            self.assertEqual(response.status_code, 400)
            self.assertIn("constraint", response.get_json()["error"])
            text = org.export_organization_csv(self.PROJECT, "level_cadres")
            plan = org.import_organization(
                self.PROJECT, org.parse_organization_csv(io.BytesIO(text.encode()), "level_cadres"), dry_run=False)
        self.assertTrue(plan.errors)
        self.assertFalse(plan.applied)
        db.session.rollback()
        self.assertEqual(self._grid()[("phc", "MO")]["default_roles"], ["site_pi", "coder"])

    def test_an_expanded_row_that_fails_reports_its_row_once(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        self._phc_unit()
        db.session.commit()
        # (phc, MO) defaults to two roles; a new account without a name fails
        # the row's check once per role, and the error names the row once.
        response = self._import_users(USER_HEADER + "nobody@example.org,,,DP1,MO,,\n")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"].count("Row 2"), 1)
        self.assertIn("needs a name", response.get_json()["error"])
