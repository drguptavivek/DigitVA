"""People and roles page: service, routes and the bulk PII helper (digitva-nk1).

Policy: docs/policy/people-and-roles-page.md. Tree CSC001 (District D01 > CHC
C01 > PHC P01, P02) with the default level x cadre grid: at a PHC an MO may
code and supervise, a CHO may fill; at a CHC an SMO may code and supervise.
Every "absent" assertion first asserts that an in-scope sibling is present.
"""
import csv
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import organization_service as org
from app.services import people_roles_service as service
from app.services.authz import resolve_grants
from app.services.viewer_pii_service import pii_visible_user_ids, should_redact_pii
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

R = VaAccessRoles
ACTIVE = VaStatuses.active


class PeopleRolesBase(UnitScopeFixture, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.levels, self.d1, self.chc, self.p1, self.p2 = self._tree()
        self.cadre = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}

    # -- fixtures -------------------------------------------------------------

    def _user(self, key, name=None):
        user = self._get_or_make_user(f"pr.{key}@test.local", "PeopleRoles123")
        user.name = name or key.replace("_", " ").title()
        db.session.flush()
        return user

    def _grant(self, key, role, unit=None, cadre=None, *, name=None, status=ACTIVE, by=None,
               project_scope=False):
        user = self._user(key, name)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role,
            scope_type=VaAccessScopeTypes.project if project_scope else VaAccessScopeTypes.org_unit,
            project_id=self.PROJECT if project_scope else None,
            org_unit_id=None if project_scope else unit.org_unit_id,
            cadre_id=self.cadre[cadre].cadre_id if cadre else None,
            grant_status=status,
            created_by_user_id=by.user_id if by else None,
        ))
        db.session.commit()
        return user

    def _pair(self, site_id):
        """An active (project, site) pair of the tree project; returns it."""
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(
            site_id=site_id, site_abbr=site_id, site_name=f"Site {site_id}",
            site_status=ACTIVE, site_registered_at=now, site_updated_at=now))
        db.session.flush()
        db.session.add(VaSites(
            site_id=site_id, project_id=self.PROJECT, site_name=f"Site {site_id}",
            site_abbr=site_id, site_status=ACTIVE, site_registered_at=now, site_updated_at=now))
        pair = VaProjectSites(
            project_id=self.PROJECT, site_id=site_id, project_site_status=ACTIVE,
            project_site_registered_at=now, project_site_updated_at=now)
        db.session.add(pair)
        db.session.commit()
        return pair

    def _site_grant(self, key, pair, role=R.site_pi):
        user = self._user(key)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=pair.project_site_id, grant_status=ACTIVE))
        db.session.commit()
        return user

    def _call(self, viewer, **args):
        return service.people_roles(viewer, self.PROJECT, {k: str(v) for k, v in args.items()})

    @staticmethod
    def _rows(result, user):
        return [r for r in result["rows"] if r["person"]["user_id"] == str(user.user_id)]

    def _row(self, result, user):
        rows = self._rows(result, user)
        self.assertEqual(len(rows), 1, f"{user.name}: {len(rows)} rows")
        return rows[0]

    def _present(self, result, *users):
        for user in users:
            self.assertTrue(self._rows(result, user), f"{user.name} should be listed")

    def _absent(self, result, *users):
        for user in users:
            self.assertFalse(self._rows(result, user), f"{user.name} should not be listed")

    def _state(self, row, key):
        return row["cells"][key]["state"]

    def _team(self):
        """One person per level and kind, used by several tests."""
        self.pi = self._grant("pi", R.project_pi, project_scope=True)
        self.coder1 = self._grant("coder1", R.coder, self.p1, "MO")
        self.coder2 = self._grant("coder2", R.coder, self.p2, "MO")
        self.cho1 = self._grant("cho1", R.interviewer, self.p1, "CHO")
        self.smo = self._grant("smo", R.data_manager, self.chc, "SMO")
        self.cs = self._grant("cs", R.site_pi, self.d1, "CS")


class AudienceTests(PeopleRolesBase):
    def test_unit_viewer_sees_own_unit_ancestors_and_project_scope_only(self):
        self._team()
        result = self._call(self.coder1)
        # In scope: self, a P01 colleague, the CHC and district above, the PI.
        self._present(result, self.coder1, self.cho1, self.smo, self.cs, self.pi)
        # Out of scope: the sibling PHC.
        self._absent(result, self.coder2)
        codes = {u["unit_code"] for u in result["units"]["units"]}
        self.assertEqual(codes, {"D01", "C01", "P01"})

    def test_a_viewer_at_a_chc_sees_the_subtree_below_it(self):
        self._team()
        result = self._call(self.smo)
        self._present(result, self.smo, self.coder1, self.coder2, self.cs)

    def test_admin_and_pi_see_the_whole_project_and_admin_sees_global_admins(self):
        self._team()
        for viewer in (self.base_admin_user, self.pi):
            result = self._call(viewer)
            self._present(result, self.coder1, self.coder2, self.cs, self.pi, self.base_admin_user)
        platform = [r for r in self._call(self.pi)["rows"] if r["location"]["kind"] == "platform"]
        self.assertTrue(platform)
        # A plain coder never sees global admins.
        self._absent(self._call(self.coder1), self.base_admin_user)

    def test_no_grant_unknown_and_closed_projects_are_not_found(self):
        self._team()
        outsider = self._user("outsider")
        for viewer, project in ((outsider, self.PROJECT), (self.pi, "NOPE01")):
            with self.subTest(project=project), self.assertRaises(service.PeopleRolesError) as ctx:
                service.people_roles(viewer, project, {})
            self.assertEqual(ctx.exception.status, 404)
        self._present(self._call(self.pi), self.coder1)
        db.session.get(VaProjectMaster, self.PROJECT).project_status = VaStatuses.deactive
        db.session.commit()
        for viewer in (self.pi, self.base_admin_user, self.coder1):
            with self.subTest(closed=viewer.name), self.assertRaises(service.PeopleRolesError) as ctx:
                self._call(viewer)
            self.assertEqual(ctx.exception.status, 404)

    def test_bad_parameters_are_refused_after_the_gate(self):
        self._team()
        for args in ({"mode": "x"}, {"status": "x"}, {"capability": "x"}, {"unit": "nope"},
                     {"limit": "x"}, {"q": "a" * 65}):
            with self.subTest(args=args), self.assertRaises(service.PeopleRolesError) as ctx:
                self._call(self.pi, **args)
            self.assertEqual(ctx.exception.status, 400)
        # An unreachable parameter is 404 even for a viewer who may not use it.
        with self.assertRaises(service.PeopleRolesError) as ctx:
            self._call(self.coder1, unit=self.p2.org_unit_id)
        self.assertEqual(ctx.exception.status, 404)

    def test_site_rows_are_for_whole_project_viewers_and_the_same_site_only(self):
        self._team()
        pair_a = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE))
        pair_b = self._pair("CS08")
        site_a = self._site_grant("sitea", pair_a)
        site_b = self._site_grant("siteb", pair_b)

        # A whole-project viewer sees both, without grid cells, with a Site lead cell.
        for viewer in (self.pi, self.base_admin_user):
            result = self._call(viewer)
            self._present(result, site_a, site_b)
        row = self._row(self._call(self.pi), site_a)
        self.assertEqual(row["location"]["kind"], "site")
        self.assertEqual(row["location"]["site_id"], self.SITE)
        self.assertNotIn("hollow", {c["state"] for c in row["cells"].values()})
        self.assertIsNone(row["covered_below"])
        self.assertEqual(self._state(row, "site_lead"), "granted")
        self.assertEqual(self._state(self._row(self._call(self.pi), self.cs), "site_lead"), "blank")

        # A unit viewer sees the project-scope row but no site row.
        unit_view = self._call(self.coder1)
        self._present(unit_view, self.pi, self.coder1)
        self._absent(unit_view, site_a, site_b)

        # A site viewer sees its own site and not the other.
        site_view = self._call(site_a)
        self._present(site_view, site_a, self.pi)
        self._absent(site_view, site_b)


class ModeAndFilterTests(PeopleRolesBase):
    def test_granted_here_vs_can_act_here(self):
        self._team()
        here = self._call(self.base_admin_user, unit=self.p1.org_unit_id)
        self._present(here, self.coder1, self.cho1)
        self._absent(here, self.smo, self.cs, self.pi, self.coder2)

        act = self._call(self.base_admin_user, unit=self.p1.org_unit_id, mode="can_act_here")
        self._present(act, self.coder1, self.cho1, self.smo, self.cs, self.pi, self.base_admin_user)
        self._absent(act, self.coder2)

    def test_level_cadre_capability_and_text_filters(self):
        self._team()
        admin = self.base_admin_user
        self._present(self._call(admin, level="phc"), self.coder1, self.coder2)
        self._absent(self._call(admin, level="phc"), self.smo)
        only_cho = self._call(admin, cadre="cho")
        self._present(only_cho, self.cho1)
        self._absent(only_cho, self.coder1)
        can_code = self._call(admin, capability="code")
        self._present(can_code, self.coder1, self.coder2)
        self._absent(can_code, self.cho1)
        by_name = self._call(admin, q="CODER1")
        self._present(by_name, self.coder1)
        self._absent(by_name, self.coder2)
        by_email = self._call(admin, q="pr.cho1@")
        self._present(by_email, self.cho1)

    def test_text_search_cannot_reach_an_email_a_viewer_may_not_see(self):
        self._team()
        collab = self._grant("collab", R.collaborator, self.p1)
        # The collaborator's audience is not empty: cho1 is in it, as initials.
        self._present(self._call(collab), self.cho1)
        self._present(self._call(collab, q="c."), self.cho1)
        # Neither the email nor the full name is searchable.
        self.assertEqual(self._call(collab, q="pr.cho1@")["rows"], [])
        self.assertEqual(self._call(collab, q="cho1")["rows"], [])
        self._present(self._call(self.coder1, q="cho1"), self.cho1)
        self.assertEqual(self._call(self.coder1, q="pr.cho1@")["rows"], [])

    def test_column_counts_count_people_and_pagination_reports_total(self):
        self._team()
        result = self._call(self.base_admin_user, level="phc")
        counts = {c["key"]: c["people"] for c in result["columns"]}
        self.assertEqual(counts["code"], 2)
        self.assertEqual(counts["interview"], 1)
        page = self._call(self.base_admin_user, limit=1, offset=1)
        self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(page["total"], len(self._call(self.base_admin_user)["rows"]))
        self.assertEqual(page["limit"], 1)

    def test_status_filter_lists_deactivated_grants_only_to_the_identity_tier(self):
        self._team()
        gone = self._grant("gone", R.coder, self.p1, "MO", status=VaStatuses.deactive)
        self.assertEqual(self._rows(self._call(self.pi), gone), [])
        self._present(self._call(self.pi, status="deactivated"), gone)
        self._absent(self._call(self.pi, status="deactivated"), self.coder1)
        everyone = self._call(self.pi, status="all")
        self._present(everyone, gone, self.coder1)
        # A coder asking for everything still gets active people only.
        plain = self._call(self.coder1, status="all")
        self._present(plain, self.coder1)
        self._absent(plain, gone)


class CellTests(PeopleRolesBase):
    def test_green_red_and_blank_cells(self):
        self._team()
        result = self._call(self.base_admin_user)
        coder = self._row(result, self.coder1)
        self.assertEqual(self._state(coder, "code"), "granted")
        self.assertEqual(coder["cells"]["code"]["roles"], ["coder"])
        # An MO may supervise at a PHC but this coder does not.
        self.assertEqual(self._state(coder, "supervise"), "hollow")
        self.assertEqual(self._state(coder, "interview"), "blank")
        self.assertEqual(self._state(coder, "review"), "blank")
        cho = self._row(result, self.cho1)
        self.assertEqual(self._state(cho, "interview"), "granted")
        self.assertEqual(self._state(cho, "report_deaths"), "granted")
        self.assertEqual(self._state(cho, "code"), "blank")
        # A CHO may fill: a read-only grant leaves Interview red.
        viewer = self._grant("viewer", R.collaborator, self.p1, "CHO")
        row = self._row(self._call(self.base_admin_user), viewer)
        self.assertEqual(self._state(row, "interview"), "hollow")
        self.assertEqual(self._state(row, "read_only"), "granted")

    def test_report_deaths_is_given_by_interviewer_and_death_reporter_and_is_red_by_its_own_flag(self):
        sc1 = org.create_unit(
            self.PROJECT, org_level_id=self.levels["subcentre"].org_level_id,
            parent_org_unit_id=self.p1.org_unit_id, unit_code="S01", unit_name="SC One")
        db.session.commit()
        reporter = self._grant("anm_reporter", R.death_reporter, sc1, "ANM")
        cho = self._grant("cho_sc", R.interviewer, sc1, "CHO")
        # Read-only grants keep the person listed with a cadre but give no ability.
        anm_viewer = self._grant("anm_viewer", R.collaborator, sc1, "ANM")
        cho_viewer = self._grant("cho_viewer", R.collaborator, sc1, "CHO")
        result = self._call(self.base_admin_user)
        row = self._row(result, reporter)
        self.assertEqual(self._state(row, "report_deaths"), "granted")
        self.assertEqual(row["cells"]["report_deaths"]["roles"], ["death_reporter"])
        # A reporter does not interview: the Interview cell is never green.
        self.assertNotEqual(self._state(row, "interview"), "granted")
        self.assertEqual(self._state(self._row(result, cho), "report_deaths"), "granted")
        # Red by can_report_deaths: an ANM may report at a sub-centre, a CHO may not.
        self.assertEqual(self._state(self._row(result, anm_viewer), "report_deaths"), "hollow")
        self.assertEqual(self._state(self._row(result, cho_viewer), "report_deaths"), "blank")

    def test_derived_roles_in_charge_and_data_manager(self):
        self._team()
        result = self._call(self.base_admin_user)
        incharge = self._row(result, self.cs)
        for key in ("supervise", "manage_data", "manage_grants"):
            self.assertEqual(self._state(incharge, key), "granted", key)
        self.assertEqual(self._state(incharge, "code"), "blank")
        pi = self._row(result, self.pi)
        for key in ("supervise", "manage_data", "manage_grants"):
            self.assertEqual(self._state(pi, key), "granted", key)
        smo = self._row(result, self.smo)
        self.assertEqual(self._state(smo, "manage_data"), "granted")
        self.assertEqual(self._state(smo, "interview"), "blank")

    def test_view_pii_is_per_person_and_follows_should_redact_pii(self):
        self._team()
        collab = self._grant("collab", R.collaborator, self.p1)
        result = self._call(self.base_admin_user)
        self.assertEqual(self._state(self._row(result, self.coder1), "view_pii"), "granted")
        self.assertEqual(self._state(self._row(result, collab), "view_pii"), "blank")
        self.assertTrue(self._row(result, self.coder1)["person"]["sees_pii"])
        self.assertFalse(self._row(result, collab)["person"]["sees_pii"])

    def test_a_coder_above_the_coding_scope_level_is_view_only(self):
        self._team()
        coder_chc = self._grant("coderchc", R.coder, self.chc, "SMO")
        project = db.session.get(VaProjectMaster, self.PROJECT)
        project.coding_scope_level_id = self.levels["phc"].org_level_id
        project.above_scope_coding_mode = "view_only"
        db.session.commit()
        result = self._call(self.base_admin_user)
        self.assertEqual(self._state(self._row(result, coder_chc), "code"), "view_only")
        self.assertEqual(self._state(self._row(result, self.coder1), "code"), "granted")
        tester = self._grant("tester", R.coding_tester, self.chc)
        self.assertEqual(self._state(self._row(self._call(self.base_admin_user), tester), "test_code"),
                         "granted")

    def test_inactive_user_and_inactive_unit_cells_are_grey(self):
        self._team()
        self.coder1.user_status = VaStatuses.deactive
        self.p2.is_active = False
        db.session.commit()
        result = self._call(self.base_admin_user)
        self.assertEqual(self._state(self._row(result, self.coder1), "code"), "inactive")
        self.assertEqual(self._state(self._row(result, self.coder2), "code"), "inactive")
        self.assertEqual(self._state(self._row(result, self.cho1), "interview"), "granted")

    def test_row_key_is_person_location_and_cadre(self):
        self._team()
        # Two roles for one person at one unit and cadre: one row, two grants.
        db.session.add(VaUserAccessGrants(
            user_id=self.coder1.user_id, role=R.reviewer, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.p1.org_unit_id, cadre_id=self.cadre["MO"].cadre_id, grant_status=ACTIVE))
        # A second location: a second row.
        db.session.add(VaUserAccessGrants(
            user_id=self.coder1.user_id, role=R.coder, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.p2.org_unit_id, cadre_id=self.cadre["MO"].cadre_id, grant_status=ACTIVE))
        db.session.commit()
        rows = self._rows(self._call(self.base_admin_user), self.coder1)
        self.assertEqual(len(rows), 2)
        p1_row = next(r for r in rows if r["location"]["unit_code"] == "P01")
        self.assertEqual({g["role"] for g in p1_row["grants"]}, {"coder", "reviewer"})
        self.assertEqual(self._state(p1_row, "review"), "granted")

    def test_covered_below_counts_active_units_under_the_grant(self):
        self._team()
        result = self._call(self.base_admin_user)
        self.assertEqual(self._row(result, self.cs)["covered_below"], 3)    # C01, P01, P02
        self.assertEqual(self._row(result, self.smo)["covered_below"], 2)
        self.assertEqual(self._row(result, self.coder1)["covered_below"], 0)
        self.assertIsNone(self._row(result, self.pi)["covered_below"])
        # A PHC viewer sees the district row but counts only units it can see.
        scoped = self._call(self.coder1)
        self.assertEqual(self._row(scoped, self.cs)["covered_below"], 2)     # C01, P01
        self.assertEqual(self._row(scoped, self.smo)["covered_below"], 1)    # P01


class AuditTests(PeopleRolesBase):
    def _flags(self, user, viewer=None, **args):
        row = self._row(self._call(viewer or self.base_admin_user, **args), user)
        return row["audit"]["flags"]

    def test_flags(self):
        self._team()
        # Exceeds the grid: a CHO may not code at a PHC.
        exceeds = self._grant("exceeds", R.coder, self.p1, "CHO")
        self.assertIn("exceeds_grid", self._flags(exceeds))
        self.assertNotIn("exceeds_grid", self._flags(self.coder1))
        # A cadre removed from the grid after the grant.
        db.session.execute(sa.text(
            "UPDATE map_org_level_cadre SET can_code_va_form = false "
            "WHERE cadre_id = :c"), {"c": self.cadre["MO"].cadre_id})
        db.session.commit()
        self.assertIn("exceeds_grid", self._flags(self.coder2))
        # Unit grant without a cadre (never an exceeds-grid on its own).
        nocadre = self._grant("nocadre", R.interviewer, self.p1)
        self.assertEqual(self._flags(nocadre), ["no_cadre"])
        # Active grant on a deactivated user, and on a deactivated unit.
        self.cho1.user_status = VaStatuses.deactive
        self.p2.is_active = False
        db.session.commit()
        self.assertIn("inactive_user", self._flags(self.cho1))
        self.assertIn("inactive_unit", self._flags(self.coder2))
        self.assertNotIn("inactive_unit", self._flags(exceeds))

    def test_no_active_grant_and_dormant(self):
        self._team()
        gone = self._grant("gone", R.coder, self.p1, "MO", status=VaStatuses.deactive)
        flags = self._flags(gone, status="deactivated")
        self.assertIn("no_active_grant", flags)
        # A person with an active grant elsewhere is not flagged for the old one.
        both = self._grant("both", R.coder, self.p1, "MO")
        db.session.add(VaUserAccessGrants(
            user_id=both.user_id, role=R.coder, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.p2.org_unit_id, cadre_id=self.cadre["MO"].cadre_id,
            grant_status=VaStatuses.deactive))
        db.session.commit()
        rows = self._rows(self._call(self.base_admin_user, status="deactivated"), both)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("no_active_grant", rows[0]["audit"]["flags"])

        now = datetime.now(UTC)
        self.coder1.last_signed_in_at = now - timedelta(days=service.DORMANT_DAYS + 5)
        self.coder2.last_signed_in_at = now - timedelta(days=3)
        db.session.commit()
        self.assertIn("dormant", self._flags(self.coder1))
        self.assertNotIn("dormant", self._flags(self.coder2))
        # Never signed in since the column existed: not recorded, never dormant.
        row = self._row(self._call(self.base_admin_user), self.cho1)
        self.assertIsNone(row["audit"]["last_sign_in_at"])
        self.assertNotIn("dormant", row["audit"]["flags"])

    def test_granted_by_and_at_come_from_the_grant_row(self):
        self._team()
        granted = self._grant("granted", R.coder, self.p1, "MO", by=self.pi)
        audit = self._row(self._call(self.base_admin_user), granted)["audit"]
        self.assertEqual(audit["granted_by"], self.pi.name)
        self.assertTrue(audit["granted_at"].endswith("+00:00"))
        self.assertEqual(audit["grants"][0]["granted_by"], self.pi.name)
        # A grant written by the CLI or seed shows no granter.
        self.assertIsNone(self._row(self._call(self.base_admin_user), self.coder1)["audit"]["granted_by"])

    def test_audit_is_for_admin_pi_and_dm_shaped_viewers_only(self):
        self._team()
        reviewer = self._grant("reviewer", R.reviewer, self.p1)
        collab = self._grant("collab", R.collaborator, self.p1)
        for viewer in (self.coder1, reviewer, collab):
            with self.subTest(viewer=viewer.name):
                result = self._call(viewer)
                self._present(result, self.coder1)
                self.assertEqual(result["viewer"]["audit"], "none")
                self.assertTrue(all(r["audit"] is None for r in result["rows"]))
        for viewer in (self.base_admin_user, self.pi):
            self.assertEqual(self._call(viewer)["viewer"]["audit"], "all")

    def test_a_data_manager_and_an_in_charge_audit_their_own_subtree_only(self):
        self._team()
        # smo: data_manager at C01; coder2 at P02 and coder1 at P01 are inside, cs (D01) and
        # the PI (project) are outside.
        result = self._call(self.smo)
        self.assertEqual(result["viewer"]["audit"], "scoped")
        self.assertIsNotNone(self._row(result, self.coder1)["audit"])
        self.assertIsNotNone(self._row(result, self.coder2)["audit"])
        self.assertIsNotNone(self._row(result, self.smo)["audit"])
        self.assertIsNone(self._row(result, self.cs)["audit"])
        self.assertIsNone(self._row(result, self.pi)["audit"])
        # An In-charge at P01 audits P01, not its sibling P02.
        incharge = self._grant("incharge", R.site_pi, self.p1, "MO")
        result = self._call(incharge)
        self.assertIsNotNone(self._row(result, self.coder1)["audit"])
        self.assertIsNone(self._row(result, self.cs)["audit"])
        self._absent(result, self.coder2)
        in_p2 = self._grant("incharge2", R.site_pi, self.p2, "MO")
        self.assertIsNone(self._row(self._call(in_p2), self.smo)["audit"])


class RedactionTests(PeopleRolesBase):
    def test_plain_collaborator_sees_initials_and_no_email(self):
        self._team()
        collab = self._grant("collab", R.collaborator, self.p1)
        self._user("coder1").name = "Priya Sharma Rao"
        db.session.commit()
        result = self._call(collab)
        self.assertEqual(result["viewer"]["names"], "initials")
        row = self._row(result, self.coder1)
        self.assertEqual(row["person"]["name"], "P. S. R.")
        self.assertIsNone(row["person"]["email"])
        self.assertTrue(row["person"]["initials_only"])
        self.assertNotIn("Priya", str(result))
        self.assertNotIn("@test.local", str(result["rows"]))

    def test_a_death_reporter_sees_initials_and_redacted_staff_like_a_plain_collaborator(self):
        self._team()
        reporter = self._grant("reporter", R.death_reporter, self.p1)
        self._user("coder1").name = "Priya Sharma Rao"
        db.session.commit()
        # The role is outside the PII allowlist, so it unredacts nothing.
        self.assertTrue(should_redact_pii(reporter))
        result = self._call(reporter)
        self.assertEqual(result["viewer"]["names"], "initials")
        row = self._row(result, self.coder1)  # present first: an in-scope peer is listed
        self.assertEqual(row["person"]["name"], "P. S. R.")
        self.assertIsNone(row["person"]["email"])
        self.assertNotIn("Priya", str(result))

    def test_each_role_gets_its_tier(self):
        self._team()
        cases = {
            R.collaborator: ("initials", False),
            R.collaborator_pii: ("full", False),
            R.coder: ("full", False),
            R.coding_tester: ("full", False),
            R.interviewer: ("full", False),
            R.reviewer: ("full", True),
            R.interview_supervisor: ("full", True),
            R.data_manager: ("full", True),
            R.site_pi: ("full", True),
        }
        for role, (names, emails) in cases.items():
            with self.subTest(role=role.value):
                viewer = self._grant(f"v_{role.value}", role, self.p1)
                result = self._call(viewer)
                row = self._row(result, self.coder1)
                self.assertEqual(result["viewer"]["names"], names)
                self.assertEqual(result["viewer"]["identity"], emails)
                self.assertEqual(row["person"]["email"] is not None, emails)

    def test_deactivated_people_and_global_admins_only_for_the_identity_tier(self):
        self._team()
        self.cho1.user_status = VaStatuses.deactive
        db.session.commit()
        for viewer, sees in ((self.pi, True), (self.smo, True), (self.coder1, False)):
            with self.subTest(viewer=viewer.name):
                result = self._call(viewer)
                self._present(result, self.coder1)
                self.assertEqual(bool(self._rows(result, self.cho1)), sees)
                self.assertEqual(any(r["location"]["kind"] == "platform" for r in result["rows"]), sees)

    def test_job_title_is_never_redacted(self):
        self._team()
        self.coder1.job_title = "Medical Officer, Faridabad"
        collab = self._grant("collab", R.collaborator, self.p1)
        row = self._row(self._call(collab), self.coder1)
        self.assertEqual(row["person"]["job_title"], "Medical Officer, Faridabad")


class PiiVisibleUserIdsTests(PeopleRolesBase):
    def test_view_pii_is_scoped_to_this_project(self):
        self._team()
        both = self._grant("elsewhere", R.collaborator, self.p1)
        db.session.add(VaUserAccessGrants(
            user_id=both.user_id, role=R.coder, scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID, grant_status=ACTIVE))
        db.session.commit()
        self.assertFalse(should_redact_pii(both))          # elsewhere: sees PII
        self.assertIn(both.user_id, pii_visible_user_ids([both.user_id]))
        self.assertNotIn(both.user_id, pii_visible_user_ids([both.user_id], project_id=self.PROJECT))
        row = self._row(self._call(self.base_admin_user), both)
        self.assertFalse(row["person"]["sees_pii"])
        self.assertEqual(self._state(row, "view_pii"), "blank")
        self.assertTrue(self._row(self._call(self.base_admin_user), self.coder1)["person"]["sees_pii"])

    def test_bulk_helper_matches_should_redact_pii(self):
        users = {
            "coder": self._grant("coder", R.coder, self.p1, "MO"),
            "collab": self._grant("collab", R.collaborator, self.p1),
            "collab_pii": self._grant("collabpii", R.collaborator_pii, self.p1),
            "supervisor": self._grant("sup", R.interview_supervisor, self.p1),
            "coder_and_collab": self._grant("both", R.collaborator, self.p1),
            "pi": self._grant("pi", R.project_pi, project_scope=True),
            "inactive_unit": self._grant("inunit", R.coder, self.p2, "MO"),
            "deactivated_grant": self._grant("deact", R.coder, self.p1, "MO", status=VaStatuses.deactive),
            "admin": self.base_admin_user,
            "none": self._user("nogrants"),
        }
        db.session.add(VaUserAccessGrants(
            user_id=users["coder_and_collab"].user_id, role=R.coder,
            scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.p1.org_unit_id,
            cadre_id=self.cadre["MO"].cadre_id, grant_status=ACTIVE))
        # A coder grant on a project that is then closed.
        closed = self._user("closed")
        db.session.add(VaUserAccessGrants(
            user_id=closed.user_id, role=R.coder, scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID, grant_status=ACTIVE))
        users["closed_project"] = closed
        self.p2.is_active = False
        db.session.commit()

        for label, expect_visible in (("open", True), ("closed", False)):
            if label == "closed":
                db.session.get(VaProjectMaster, self.BASE_PROJECT_ID).project_status = VaStatuses.deactive
                db.session.commit()
            visible = pii_visible_user_ids([u.user_id for u in users.values()])
            in_project = pii_visible_user_ids([u.user_id for u in users.values()], project_id=self.PROJECT)
            for name, user in users.items():
                with self.subTest(name=name, project=label):
                    self.assertEqual(user.user_id in visible, not should_redact_pii(user))
                    # Restricted to CSC001: an admin, or a live PII grant that resolves there.
                    resolved = resolve_grants(user)
                    expected = resolved.is_admin or any(
                        g.project_id == self.PROJECT and not g.virtual
                        and g.role in service._PII_GRANTING_ROLES
                        for g in resolved.grants
                    )
                    self.assertEqual(user.user_id in in_project, expected)
            if label == "closed":
                self.assertNotIn(closed.user_id, visible)
            else:
                self.assertIn(closed.user_id, visible)
        self.assertIn(users["coder"].user_id, visible)
        self.assertNotIn(users["collab"].user_id, visible)
        self.assertEqual(pii_visible_user_ids([]), set())


class BoundTests(PeopleRolesBase):
    def test_truncation_is_reported_in_json_and_csv(self):
        self._team()
        self._login(str(self.pi.user_id))
        full = self.client.get(f"/api/v1/projects/{self.PROJECT}/people-roles")
        self.assertFalse(full.get_json()["truncated"])
        self.assertNotIn("X-Truncated", self.client.get(
            f"/api/v1/projects/{self.PROJECT}/people-roles.csv").headers)
        with patch.object(service, "MAX_GRANTS", 2):
            body = self.client.get(f"/api/v1/projects/{self.PROJECT}/people-roles").get_json()
            response = self.client.get(f"/api/v1/projects/{self.PROJECT}/people-roles.csv")
        self.assertTrue(body["truncated"])
        self.assertLessEqual(body["total"], 2)
        self.assertEqual(response.headers["X-Truncated"], "true")

    def test_no_active_grant_flag_is_not_fooled_by_the_cap(self):
        # The deactivated grant is the oldest row, so a cap of one keeps only it;
        # the person's active grant is still found by the flag's own query.
        both = self._grant("both", R.coder, self.p1, "MO", status=VaStatuses.deactive)
        db.session.add(VaUserAccessGrants(
            user_id=both.user_id, role=R.coder, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.p2.org_unit_id, cadre_id=self.cadre["MO"].cadre_id, grant_status=ACTIVE,
            grant_created_at=datetime(1990, 1, 2)))
        db.session.execute(sa.update(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == both.user_id, VaUserAccessGrants.grant_status == VaStatuses.deactive,
        ).values(grant_created_at=datetime(1990, 1, 1)))
        db.session.commit()
        with patch.object(service, "MAX_GRANTS", 1):
            result = self._call(self.base_admin_user, status="deactivated")
        self.assertTrue(result["truncated"])
        row = self._row(result, both)
        self.assertNotIn("no_active_grant", row["audit"]["flags"])

    def test_pickers_ride_on_the_first_page_only(self):
        self._team()
        first = self._call(self.base_admin_user, limit=2)
        self.assertEqual({u["unit_code"] for u in first["units"]["units"]}, {"D01", "C01", "P01", "P02"})
        self.assertEqual([lv["level_code"] for lv in first["units"]["levels"]][:3], ["district", "taluka", "chc"])
        self.assertTrue(first["cadres"])
        later = self._call(self.base_admin_user, limit=2, offset=2)
        self.assertNotIn("units", later)
        self.assertNotIn("cadres", later)
        self.assertIn("rows", later)
        self.assertNotIn("units", service.people_roles(
            self.base_admin_user, self.PROJECT, {}, paged=False))

    def test_cadres_are_the_audience_cadres_whatever_the_filter_or_page(self):
        self._team()
        nurse = self._grant("nurse", R.interviewer, self.p2, "SN")
        full = self._call(self.base_admin_user)
        self.assertEqual([c["code"] for c in full["cadres"]], ["CS", "CHO", "MO", "SMO", "SN"])
        self.assertEqual(sorted(full["cadres"][0]), ["cadre_id", "code", "name"])
        # A filter narrows the rows, not the picker.
        narrowed = self._call(self.base_admin_user, cadre="cho", capability="interview", q="cho1")
        self.assertEqual(len(narrowed["rows"]), 1)
        self.assertEqual(narrowed["cadres"], full["cadres"])
        # A PHC-P01 viewer's audience has no P02 nurse, so no SN in its picker.
        scoped = self._call(self.coder1)
        self._present(scoped, self.cho1)
        self._absent(scoped, nurse)
        self.assertEqual([c["code"] for c in scoped["cadres"]], ["CS", "CHO", "MO", "SMO"])
        self.assertEqual(self._call(self.coder1, limit=1)["cadres"], scoped["cadres"])


class QueryCountTests(PeopleRolesBase):
    def _statements(self, viewer):
        seen = []

        def record(conn, cursor, statement, *args):
            seen.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            result = self._call(viewer)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        return len(seen), result

    def test_query_count_does_not_grow_with_people(self):
        self._grant("first", R.coder, self.p1, "MO", by=self.base_admin_user)
        few, small = self._statements(self.base_admin_user)
        for i in range(30):
            self._grant(f"bulk{i}", R.coder if i % 2 else R.interviewer, self.p1 if i % 3 else self.p2,
                        "MO" if i % 2 else "CHO", by=self.base_admin_user)
        many, large = self._statements(self.base_admin_user)
        self.assertGreater(len(large["rows"]), len(small["rows"]) + 29)
        self.assertEqual(few, many)
        self.assertLessEqual(many, 14)


class RouteTests(PeopleRolesBase):
    def _url(self, suffix=""):
        return f"/api/v1/projects/{self.PROJECT}/people-roles{suffix}"

    def test_json_and_csv_agree_and_share_redaction(self):
        self._team()
        self._grant("formula", R.coder, self.p1, "MO", name="=HYPERLINK(1)")
        for viewer, audit in ((self.pi, True), (self._grant("collab", R.collaborator, self.p1), False)):
            with self.subTest(viewer=viewer.name):
                self._login(str(viewer.user_id))
                body = self.client.get(self._url()).get_json()
                response = self.client.get(self._url(".csv"))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.mimetype.startswith("text/csv"))
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                lines = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
                header, rows = lines[0], lines[1:]
                self.assertEqual(len(rows), body["total"])
                self.assertEqual([r[0] for r in rows], [org._spreadsheet_safe(r["person"]["name"]) for r in body["rows"]])
                self.assertEqual("granted_at" in header, audit)
                emails = {r[header.index("email")] for r in rows}
                self.assertEqual(emails == {""}, not body["viewer"]["identity"])
                self.assertFalse(any(r[0].startswith("=") for r in rows))

    def test_csv_neutralises_formulas_in_names(self):
        self._team()
        self._grant("formula", R.coder, self.p1, "MO", name="=HYPERLINK(1)")
        self._login(str(self.pi.user_id))
        text = self.client.get(self._url(".csv")).get_data(as_text=True)
        self.assertIn("'=HYPERLINK(1)", text)
        self.assertNotIn(",=HYPERLINK(1)", "\n" + text)

    def test_errors_are_flat_and_the_page_needs_a_session(self):
        self._team()
        self.assertEqual(self.client.get(self._url()).status_code, 401)
        self._login(str(self.coder1.user_id))
        bad = self.client.get(self._url("?mode=nope"))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(set(bad.get_json()), {"error", "code"})
        self.assertEqual(bad.get_json()["code"], "invalid_request")
        missing = self.client.get("/api/v1/projects/NOPE01/people-roles")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json(), {"error": "Not found.", "code": "not_found"})
        self.assertEqual(self.client.get(self._url(".csv?mode=nope")).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/projects/NOPE01/people-roles.csv").status_code, 404)
