"""Allowed roles per level x cadre (digitva-4650).

Rules under test (docs/policy/organization-model.md, "Allowed and default
roles per level x cadre"; interview-revisions.md, "Supervisor correction"):
the unit-grant validator, the mentor PII marker (a worker record), interview
supervisors' correction power, and ``flask org cadreless-grants``.
"""
from types import SimpleNamespace

from app import db
from app.commands.organization import org_group
from app.models import VaAccessRoles, VaAccessScopeTypes, VaStatuses, VaUserAccessGrants
from app.services import org_grant_service as og
from app.services import organization_service as org
from app.services.authz.grants import invalidate, resolve_grants
from app.services.authz.supervision import edits_interviews
from app.services.viewer_pii_service import pii_visible_user_ids
from tests.test_mentor_institute import REFUSED, MentorBase

R = VaAccessRoles
U = VaAccessScopeTypes.org_unit


class CadreRuleBase(MentorBase):
    def _grant(self, user, role, unit=None, cadre=None, *, project=None, scope=U):
        grant = VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=scope,
            org_unit_id=unit.org_unit_id if unit else None, project_id=project,
            cadre_id=cadre.cadre_id if cadre else None, grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        invalidate(user.user_id)
        return grant

    def _enrol(self, user, unit, cadre_code):
        org.create_worker(self.P1, org_unit_id=unit.org_unit_id,
                          cadre_id=self._cadre(self.P1, cadre_code).cadre_id,
                          worker_name="Enrolled", user=user.email)
        db.session.commit()
        invalidate(user.user_id)


class ValidatorTests(CadreRuleBase):
    def test_a_health_system_grant_names_a_cadre_that_allows_the_role(self):
        d1, _d2, chc, _member = self._setup_one()
        staff = self._get_or_make_user("staff.cadre@test.local", "x")
        # Allowed: (chc, SMO) allows reviewer in the template.
        unit, cadre = self._validate(staff, R.reviewer, chc, "SMO")
        self.assertEqual((unit.unit_code, cadre.cadre_code), ("C01", "SMO"))
        # No cadre: refused for anyone outside a mentoring institute.
        with self.assertRaises(REFUSED) as ctx:
            self._validate(staff, R.reviewer, chc)
        self.assertIn("needs the person's cadre", str(ctx.exception))
        # A role the cadre may not hold there: refused, every role gated.
        for role in (R.reviewer, R.collaborator, R.data_manager):
            with self.subTest(role=role.value), self.assertRaises(REFUSED) as ctx:
                self._validate(staff, role, chc, "MO")  # (chc, MO) allows coder only
            self.assertIn(f"may not hold {role.value}", str(ctx.exception))
        # Without the grantee the grantee-independent checks still run.
        with self.assertRaises(REFUSED):
            og.validate_org_unit_grant(role=R.reviewer, org_unit_id=chc.org_unit_id,
                                       cadre_id=self._cadre(self.P1, "MO").cadre_id)
        self.assertEqual(og.validate_org_unit_grant(role=R.reviewer, org_unit_id=d1.org_unit_id)[1], None)

    def test_a_mentor_grant_carries_no_cadre_and_takes_the_mentor_roles_anywhere_in_the_district(self):
        d1, d2, chc, member = self._setup_one()
        for role in (R.coder, R.reviewer, R.coding_tester, R.collaborator, R.data_manager):
            with self.subTest(role=role.value):
                self.assertIsNone(self._validate(member, role, chc)[1])  # below the district
                self.assertIsNone(self._validate(member, role, d1)[1])
        for role in (R.interviewer, R.site_pi, R.interview_supervisor):
            with self.subTest(role=role.value), self.assertRaises(REFUSED):
                self._validate(member, role, chc)
        with self.assertRaises(REFUSED) as ctx:
            self._validate(member, R.coder, d2)  # not attached
        self.assertIn("attached", str(ctx.exception))

    def test_a_member_grant_with_a_cadre_needs_their_worker_record_and_follows_allowed_roles(self):
        _d1, d2, chc, member = self._setup_one()
        # A borrowed cadre (no worker record) is refused, even for a mentor role.
        with self.assertRaises(REFUSED) as ctx:
            self._validate(member, R.reviewer, chc, "SMO")
        self.assertIn("worker record", str(ctx.exception))
        self._enrol(member, chc, "SMO")
        # Now a health-system grant: the cadre's allowed roles, mentor list or not.
        self.assertEqual(self._validate(member, R.site_pi, chc, "SMO")[1].cadre_code, "SMO")
        self.assertEqual(self._validate(member, R.interview_supervisor, chc, "SMO")[1].cadre_code, "SMO")
        with self.assertRaises(REFUSED):
            self._validate(member, R.data_manager, chc, "SMO")  # not allowed for SMO at chc
        # The worker record backs its own unit only.
        with self.assertRaises(REFUSED):
            self._validate(member, R.reviewer, d2, "SMO")


class DefaultsWithinAllowedTests(CadreRuleBase):
    def test_saving_keeps_defaults_inside_allowed(self):
        self._tree(self.P1)
        lv = {level.level_code: level for level in org.list_levels(self.P1)}
        args = dict(org_level_id=lv["phc"].org_level_id, cadre_id=self._cadre(self.P1, "MO").cadre_id)
        row = org.upsert_level_cadre(self.P1, **args)
        self.assertEqual((row.allowed_roles, row.default_roles),
                         (["site_pi", "coder", "interview_supervisor"], ["site_pi", "coder"]))
        with self.assertRaises(REFUSED):
            org.upsert_level_cadre(self.P1, **args, default_roles=["reviewer"])
        db.session.rollback()
        row = org.upsert_level_cadre(self.P1, **args, allowed_roles=["coder"])
        self.assertEqual((row.allowed_roles, row.default_roles), (["coder"], ["coder"]))


class MentorPiiTests(CadreRuleBase):
    def _pii(self, user, grant):
        resolved = resolve_grants(user)
        match = next(g for g in resolved.grants if g.role == grant.role and g.org_unit_id == grant.org_unit_id
                     and g.project_id == (grant.project_id or g.project_id))
        return resolved.is_pii_grant(match)

    def test_mentor_unit_grants_are_pii_only_when_a_worker_record_backs_them(self):
        d1, _d2, chc, member = self._setup_one()
        dm = self._grant(member, R.data_manager, d1)
        borrowed = self._grant(member, R.coder, chc, self._cadre(self.P1, "SMO"))
        self.assertFalse(self._pii(member, dm))        # mentor data manager: Non-PII now
        self.assertFalse(self._pii(member, borrowed))  # borrowed cadre, no worker: Non-PII
        self.assertNotIn(member.user_id, pii_visible_user_ids([member.user_id]))
        self._enrol(member, chc, "SMO")
        self.assertTrue(self._pii(member, borrowed))   # health-system enrolment: PII
        self.assertFalse(self._pii(member, dm))
        self.assertIn(member.user_id, pii_visible_user_ids([member.user_id]))

    def test_non_members_and_sites_only_projects_are_unchanged(self):
        _d1, _d2, chc, member = self._setup_one()
        staff = self._get_or_make_user("staff.pii@test.local", "x")
        tier3 = self._grant(staff, R.collaborator, chc)  # even without a cadre: Tier 3 role? no
        coder = self._grant(staff, R.coder, chc, self._cadre(self.P1, "SMO"))
        self.assertFalse(self._pii(staff, tier3))  # plain collaborator is never PII
        self.assertTrue(self._pii(staff, coder))
        # P2 has no tree: the sites-only rule (a member's data_manager keeps PII).
        dm = self._grant(member, R.data_manager, project=self.P2, scope=VaAccessScopeTypes.project)
        coder_p2 = self._grant(member, R.coder, project=self.P2, scope=VaAccessScopeTypes.project)
        resolved = resolve_grants(member)
        by_role = {g.role: g for g in resolved.grants if g.project_id == self.P2}
        self.assertTrue(resolved.is_pii_grant(by_role[dm.role]))
        self.assertFalse(resolved.is_pii_grant(by_role[coder_p2.role]))


class EditsInterviewsTests(CadreRuleBase):
    def test_any_reaching_interview_supervisor_corrects_and_in_charge_and_dm_do_not(self):
        d1, d2, chc, _member = self._setup_one()
        case = SimpleNamespace(project_id=self.P1, site_id=None, org_unit_id=chc.org_unit_id)
        supervisor = self._get_or_make_user("sup.any@test.local", "x")
        # CS at the district: its grid row is never consulted.
        self._grant(supervisor, R.interview_supervisor, d1, self._cadre(self.P1, "CS"))
        self.assertTrue(edits_interviews(supervisor.user_id, case))
        far = self._get_or_make_user("sup.far@test.local", "x")
        self._grant(far, R.interview_supervisor, d2, self._cadre(self.P1, "CS"))
        self.assertFalse(edits_interviews(far.user_id, case))
        boss = self._get_or_make_user("boss.dm@test.local", "x")
        self._grant(boss, R.site_pi, d1, self._cadre(self.P1, "CS"))
        self._grant(boss, R.data_manager, d1, self._cadre(self.P1, "DPM"))
        self.assertFalse(edits_interviews(boss.user_id, case))


class CadrelessGrantsCommandTests(CadreRuleBase):
    def test_dry_run_lists_and_apply_revokes_and_clears_with_a_record(self):
        _d1, _d2, chc, member = self._setup_one()
        staff = self._get_or_make_user("staff.nocadre@test.local", "x")
        cadreless = self._grant(staff, R.reviewer, chc)
        kept = self._grant(staff, R.coder, chc, self._cadre(self.P1, "SMO"))
        mentor_plain = self._grant(member, R.reviewer, chc)
        borrowed = self._grant(member, R.coder, chc, self._cadre(self.P1, "SMO"))
        # A legacy mentor interview_supervisor grant: it would let them correct interviews.
        case = SimpleNamespace(project_id=self.P1, site_id=None, org_unit_id=chc.org_unit_id)
        outside = self._grant(member, R.interview_supervisor, chc)
        self.assertTrue(edits_interviews(member.user_id, case))  # present first
        runner = self.app.test_cli_runner()

        listed = runner.invoke(org_group, ["cadreless-grants"])
        self.assertEqual(listed.exit_code, 0, listed.output)
        for listed_grant in (cadreless, borrowed, outside):
            self.assertIn(str(listed_grant.grant_id), listed.output)
        for untouched in (kept, mentor_plain):
            self.assertNotIn(str(untouched.grant_id), listed.output)
        self.assertIn("Dry run only", listed.output)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaUserAccessGrants, cadreless.grant_id).grant_status, VaStatuses.active)

        refused = runner.invoke(org_group, ["cadreless-grants", "--apply"])
        self.assertNotEqual(refused.exit_code, 0)

        smo_id = self._cadre(self.P1, "SMO").cadre_id
        with self.assertLogs("GRANT_AUDIT", level="INFO") as logs:
            applied = runner.invoke(org_group, ["cadreless-grants", "--apply",
                                                "--actor", self.base_admin_user.email])
        self.assertEqual(applied.exit_code, 0, applied.output)
        db.session.expire_all()
        revoked = db.session.get(VaUserAccessGrants, cadreless.grant_id)
        self.assertEqual(revoked.grant_status, VaStatuses.deactive)
        self.assertIn("digitva-4650", revoked.notes)
        mentor_revoked = db.session.get(VaUserAccessGrants, outside.grant_id)
        self.assertEqual(mentor_revoked.grant_status, VaStatuses.deactive)
        self.assertIn("interview_supervisor grant outside the mentor roles", mentor_revoked.notes)
        invalidate(member.user_id)
        self.assertFalse(edits_interviews(member.user_id, case))
        cleared = db.session.get(VaUserAccessGrants, borrowed.grant_id)
        self.assertEqual((cleared.grant_status, cleared.cadre_id), (VaStatuses.active, None))
        self.assertIn(f"Cadre {smo_id} cleared", cleared.notes)
        self.assertIn("digitva-4650", cleared.notes)
        for active in (kept, mentor_plain):
            self.assertEqual(db.session.get(VaUserAccessGrants, active.grant_id).grant_status, VaStatuses.active)
        output = "\n".join(logs.output)
        self.assertIn(f"action=grant_revoked_no_cadre actor={self.base_admin_user.user_id}", output)
        self.assertIn(f"action=grant_revoked_mentor_role actor={self.base_admin_user.user_id}", output)
        self.assertIn(f"grant_id={borrowed.grant_id}", output)
        # A second apply finds nothing left.
        again = runner.invoke(org_group, ["cadreless-grants"])
        self.assertEqual(again.output.count("): 0\n"), 3, again.output)
