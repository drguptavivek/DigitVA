"""Security review 10 (docs/audits/10-authz-and-mobile-sign-in.md), findings
#1, #2, #3, #6, #9 and #13 (digitva-4lv4).

- #1  a unit rename rewrites paths in its own project only.
- #2  an ``interview_supervisor`` grant does not lift PII redaction.
- #3  a grant on a deactivated unit or pair does not lift PII redaction.
- #6  the coder roster names project and pair coders of the DM's projects only.
- #13 coder counts resolve a grant's project; NULL is never a wildcard.
- #9  a non-admin import gets one refusal for a missing or out-of-scope unit.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services import authz
from app.services import organization_service as org
from app.services import project_user_import_service as user_import
from app.services.viewer_pii_service import should_redact_pii
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

OTHER_PROJECT = "R10OTH"


def _make_project(project_id):
    now = datetime.now(UTC)
    if db.session.get(VaProjectMaster, project_id) is None:
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=project_id,
            project_nickname=project_id, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.flush()


def _unit(project_id, level_code, code, parent=None):
    levels = {lv.level_code: lv for lv in org.list_levels(project_id)}
    return org.create_unit(
        project_id, org_level_id=levels[level_code].org_level_id, unit_code=code,
        unit_name=f"Unit {code}", parent_org_unit_id=parent.org_unit_id if parent else None,
    )


def _grant(user, role, **scope):
    db.session.add(VaUserAccessGrants(
        user_id=user.user_id, role=role, grant_status=VaStatuses.active, **scope,
    ))
    db.session.commit()


class UnitRenameStaysInProjectTests(BaseTestCase):
    """#1: unit codes are unique per project only, so the same path exists in
    another project and must survive a rename here."""

    PROJECT_A = "R10PA"
    PROJECT_B = "R10PB"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _make_project(cls.PROJECT_A)
        _make_project(cls.PROJECT_B)
        db.session.commit()

    def _paths(self, project_id):
        return {
            u.unit_code: str(u.path)
            for u in db.session.scalars(sa.select(MasOrgUnit).where(MasOrgUnit.project_id == project_id))
        }

    def test_renaming_a_unit_leaves_the_same_path_in_another_project(self):
        for project_id in (self.PROJECT_A, self.PROJECT_B):
            org.seed_default_organization(project_id)
        a_d1 = _unit(self.PROJECT_A, "district", "D1")
        _unit(self.PROJECT_A, "phc", "P1", _unit(self.PROJECT_A, "chc", "C1", a_d1))
        b_d1 = _unit(self.PROJECT_B, "district", "D1")
        _unit(self.PROJECT_B, "phc", "P1", _unit(self.PROJECT_B, "chc", "C1", b_d1))
        _unit(self.PROJECT_B, "chc", "C9", _unit(self.PROJECT_B, "district", "D2"))
        db.session.commit()
        b_before = self._paths(self.PROJECT_B)
        self.assertEqual(b_before["P1"], "D1.C1.P1")

        org.update_unit(self.PROJECT_A, a_d1.org_unit_id, unit_code="D2")
        db.session.commit()

        a_after = self._paths(self.PROJECT_A)
        self.assertEqual(a_after, {"D2": "D2", "C1": "D2.C1", "P1": "D2.C1.P1"})
        self.assertEqual(self._paths(self.PROJECT_B), b_before)


class PiiRedactionGrantRelationTests(UnitScopeFixture, BaseTestCase):
    """#2 and #3: should_redact_pii counts only allowlisted roles on grants
    the authz relation calls live."""

    def setUp(self):
        super().setUp()
        _, _, _, self.phc_a, self.phc_b = self._tree()

    def _user(self, label):
        return self._get_or_make_user(f"r10.{label}.{uuid.uuid4().hex[:8]}@test.local", "Review10Pii1")

    def test_interview_supervisor_grant_does_not_lift_redaction(self):
        self._sub("csc-r10-b", unit=self.phc_b)
        user = self._user("sup")
        _grant(user, VaAccessRoles.collaborator,
               scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc_b.org_unit_id)
        _grant(user, VaAccessRoles.interview_supervisor,
               scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc_a.org_unit_id)

        self.assertTrue(authz.can(user, authz.Action.VIEW, "csc-r10-b"))
        self.assertTrue(should_redact_pii(user))

        _grant(user, VaAccessRoles.collaborator_pii,
               scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc_b.org_unit_id)
        self.assertFalse(should_redact_pii(user))

    def test_pii_grant_on_a_deactivated_unit_does_not_lift_redaction(self):
        user = self._user("unit")
        _grant(user, VaAccessRoles.collaborator_pii,
               scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc_a.org_unit_id)
        self.assertFalse(should_redact_pii(user))

        org.set_unit_active(self.PROJECT, self.phc_a.org_unit_id, False)
        db.session.commit()
        self.assertTrue(should_redact_pii(user))

        org.set_unit_active(self.PROJECT, self.phc_a.org_unit_id, True)
        db.session.commit()
        self.assertFalse(should_redact_pii(user))
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id))
        self.assertEqual(grant.grant_status, VaStatuses.active)

    def test_pii_grant_on_a_deactivated_pair_does_not_lift_redaction(self):
        pair = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE,
        ))
        user = self._user("pair")
        _grant(user, VaAccessRoles.collaborator_pii,
               scope_type=VaAccessScopeTypes.project_site, project_site_id=pair.project_site_id)
        self.assertFalse(should_redact_pii(user))

        pair.project_site_status = VaStatuses.deactive
        db.session.commit()
        self.assertTrue(should_redact_pii(user))

        pair.project_site_status = VaStatuses.active
        db.session.commit()
        self.assertFalse(should_redact_pii(user))
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id))
        self.assertEqual(grant.grant_status, VaStatuses.active)


class CoderKpiGrantProjectTests(UnitScopeFixture, BaseTestCase):
    """#6 and #13: coder roster and coder counts on the DM KPI panels."""

    LANG = "R10Lang"

    def setUp(self):
        super().setUp()
        _, _, _, self.phc_a, self.phc_b = self._tree()
        _make_project(OTHER_PROJECT)
        org.seed_default_organization(OTHER_PROJECT)
        self.other_unit = _unit(OTHER_PROJECT, "district", "OD1")
        db.session.commit()

    def _user(self, label, languages=None):
        user = self._get_or_make_user(f"r10.{label}.{uuid.uuid4().hex[:8]}@test.local", "Review10Kpi1")
        if languages is not None:
            user.vacode_language = languages
            db.session.commit()
        return user

    def _kpi(self, path, **dm_scope):
        """A fresh DM per call (project DM by default): KPI results are cached per user."""
        dm = self._user("dm")
        _grant(dm, VaAccessRoles.data_manager,
               **(dm_scope or dict(scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT)))
        self._login(str(dm.user_id))
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _unit_coder(self, unit, languages=None):
        coder = self._user("unit.coder", languages)
        _grant(coder, VaAccessRoles.coder,
               scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id)
        return coder

    def _roster_fixture(self):
        """Coders at every scope: project, two pairs, two units, another project."""
        other_pair = self._inactive_pair_form()
        other_pair.project_site_status = VaStatuses.active
        db.session.commit()
        pair_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE,
        ))
        coders = {"project": self._user("project.coder")}
        _grant(coders["project"], VaAccessRoles.coder,
               scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT)
        for key, ps_id in (("pair", pair_id), ("other_pair", other_pair.project_site_id)):
            coders[key] = self._user(f"{key}.coder")
            _grant(coders[key], VaAccessRoles.coder,
                   scope_type=VaAccessScopeTypes.project_site, project_site_id=ps_id)
        coders["unit"] = self._unit_coder(self.phc_a)
        coders["sibling_unit"] = self._unit_coder(self.phc_b)
        coders["other_project"] = self._unit_coder(self.other_unit)
        return pair_id, coders

    def _roster(self, **dm_scope):
        return {row["email"]: row for row in self._kpi("coders/roster", **dm_scope)["coders"]}

    def _assert_roster(self, roster, coders, expected):
        for key, coder in coders.items():
            if key in expected:
                self.assertIn(coder.email, roster, key)
            else:
                self.assertNotIn(coder.email, roster, key)

    def test_project_dm_roster_names_every_coder_of_its_project_only(self):
        _, coders = self._roster_fixture()
        roster = self._roster()
        self._assert_roster(roster, coders, {"project", "pair", "other_pair", "unit", "sibling_unit"})
        self.assertEqual({row["project_id"] for row in roster.values()}, {self.PROJECT})

    def test_site_dm_roster_names_only_its_own_pair_coders(self):
        # Owner decision 2026-10-03 (digitva-4b3e): the roster is the DM's own scope.
        pair_id, coders = self._roster_fixture()
        roster = self._roster(scope_type=VaAccessScopeTypes.project_site, project_site_id=pair_id)
        self._assert_roster(roster, coders, {"pair"})

    def test_unit_dm_roster_names_only_coders_in_its_subtree(self):
        _, coders = self._roster_fixture()
        roster = self._roster(scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc_a.org_unit_id)
        self._assert_roster(roster, coders, {"unit"})

    def test_utilization_counts_unit_coders_of_in_scope_projects_only(self):
        baseline = self._kpi("coders/utilization")["total_coders"]
        self._unit_coder(self.other_unit)
        self.assertEqual(self._kpi("coders/utilization")["total_coders"], baseline)
        self._unit_coder(self.phc_a)
        self.assertEqual(self._kpi("coders/utilization")["total_coders"], baseline + 1)

    def _lang_row(self):
        rows = [r for r in self._kpi("language/gap")["languages"] if r["language"] == self.LANG]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_language_gap_counts_unit_coders_of_in_scope_projects_only(self):
        self._sub("csc-r10-lang", unit=self.phc_a)
        db.session.get(VaSubmissions, "csc-r10-lang").va_narration_language = self.LANG
        db.session.commit()
        self.assertEqual(self._lang_row()["coders_available"], 0)

        self._unit_coder(self.other_unit, [self.LANG])
        row = self._lang_row()
        self.assertEqual(row["coders_available"], 0)
        self.assertTrue(row["gap"])

        self._unit_coder(self.phc_a, [self.LANG])
        row = self._lang_row()
        self.assertEqual(row["coders_available"], 1)
        self.assertFalse(row["gap"])


class ImportRefusesBeforeUnitValidationTests(UnitScopeFixture, BaseTestCase):
    """#9: a non-admin cannot tell a missing unit from one outside its scope."""

    def setUp(self):
        super().setUp()
        _, _, _, self.phc_a, self.phc_b = self._tree()
        db.session.get(VaProjectMaster, self.PROJECT).project_structure_mode = "organization"
        db.session.commit()
        self.unit_dm = self._user_with(
            f"r10.import.dm.{uuid.uuid4().hex[:8]}@test.local", VaAccessRoles.data_manager, self.phc_a,
        )
        self.grantee = self._get_or_make_user(
            f"r10.import.grantee.{uuid.uuid4().hex[:8]}@test.local", "Review10Imp1",
        )

    def _row(self, number, unit_code):
        return {"_line_number": number, "email": self.grantee.email, "name": "", "role": "data_manager",
                "org_unit_code": unit_code, "cadre_code": "", "language_codes": "", "phone": ""}

    def test_missing_and_out_of_scope_units_get_the_same_refusal(self):
        # Positive control: the actor may grant below its own unit's scope.
        sub = _unit(self.PROJECT, "subcentre", "R10S1", self.phc_a)
        db.session.commit()
        plan = user_import.prepare(self.PROJECT, [self._row(2, sub.unit_code)], actor=self.unit_dm)
        self.assertEqual([item["action"] for item in plan], ["grant"])

        with self.assertRaises(user_import.ProjectUserImportError) as raised:
            user_import.prepare(
                self.PROJECT, [self._row(2, "ZZ99"), self._row(3, self.phc_b.unit_code)], actor=self.unit_dm,
            )
        refusal = user_import.NOT_PERMITTED
        self.assertEqual(str(raised.exception), f"Row 2: {refusal}; Row 3: {refusal}")

    def test_admin_still_sees_the_unknown_unit_message(self):
        with self.assertRaises(user_import.ProjectUserImportError) as raised:
            user_import.prepare(self.PROJECT, [self._row(2, "ZZ99")], actor=self.base_admin_user)
        self.assertEqual(str(raised.exception), "Row 2: unit code is unknown or inactive")


def test_pii_granting_roles_are_pinned():
    """Review 10 #2: the allowlist changes only by a policy decision."""
    from app.models import VaAccessRoles as R
    from app.services.viewer_pii_service import _PII_GRANTING_ROLES

    assert _PII_GRANTING_ROLES == {
        R.admin, R.project_pi, R.site_pi, R.data_manager, R.coder,
        R.coding_tester, R.reviewer, R.interviewer, R.collaborator_pii,
    }
    assert R.collaborator not in _PII_GRANTING_ROLES
    assert R.interview_supervisor not in _PII_GRANTING_ROLES
