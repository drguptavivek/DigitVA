"""can_grant and grant_list_filter (digitva-0wc, design 2.5).

Expected outcomes are written from the policy, both project kinds:
access-control-model.md "Who creates which grants" (site projects: today's
rule; district projects: the subtree rule, owner 2026-10-02) and
dm-user-grant-management.md "Scope Rules" / "Toggle".
"""
import sqlalchemy as sa

from app import db
from app.models import VaStatuses, VaUserAccessGrants
from app.services.authz import GrantTarget, Reason, can_grant, grant_list_filter
from app.services.org_grant_service import validate_org_unit_grant
from app.services.organization_service import OrganizationError, list_cadres
from tests.authz.fixture import CL, PS, SP, TA, TB, AuthzFixtureMixin, P, R, U
from tests.base import BaseTestCase

T = True
F = False

# (actor, role, scope, where, expected); where = project id, (project, site) or unit key
CASES = [
    # admin creates every grant (ACM)
    ("admin", R.project_pi, P, TA, T),
    ("admin", R.admin, P, SP, T),
    # site project, project DM: coder, coding_tester, data_manager at project or pair
    ("dm_sp", R.coder, P, SP, T),
    ("dm_sp", R.coding_tester, PS, (SP, "AZS3"), T),
    ("dm_sp", R.data_manager, PS, (SP, "AZS1"), T),
    ("dm_sp", R.data_manager, P, SP, T),                 # own scope (site rule, unchanged)
    ("dm_sp", R.reviewer, P, SP, F),                     # never reviewer in a site project
    ("dm_sp", R.collaborator, P, SP, F),
    ("dm_sp", R.interviewer, PS, (SP, "AZS1"), F),
    ("dm_sp", R.coder, P, TA, F),                        # outside own project
    ("dm_sp", R.site_pi, PS, (SP, "AZS1"), F),
    # site project, pair DM: own pair only, never project level
    ("dm_sp1", R.coder, PS, (SP, "AZS1"), T),
    ("dm_sp1", R.data_manager, PS, (SP, "AZS1"), T),
    ("dm_sp1", R.coder, P, SP, F),
    ("dm_sp1", R.coder, PS, (SP, "AZS3"), F),
    ("dm_sp1", R.coder, PS, (TA, "AZS1"), F),            # same site id, other project
    # project_pi: any role but admin and project_pi, anywhere in the project
    ("pi_sp", R.reviewer, P, SP, T),
    ("pi_sp", R.site_pi, PS, (SP, "AZS1"), T),
    ("pi_sp", R.project_pi, P, SP, F),
    ("pi_sp", R.coder, P, TA, F),
    ("pi_ta", R.data_manager, P, TA, T),                 # PI creates DMs at any level
    ("pi_ta", R.data_manager, U, "SC1", T),
    ("pi_ta", R.interview_supervisor, U, "C1", T),
    ("pi_ta", R.coder, U, "F1", F),                      # another project's unit
    ("pi_ta", R.admin, P, TA, F),
    # district project, project DM: DM strictly below, the six roles anywhere
    ("dm_ta", R.data_manager, P, TA, F),                 # not at own level
    ("dm_ta", R.data_manager, PS, (TA, "AZS1"), T),
    ("dm_ta", R.data_manager, U, "C1", T),
    ("dm_ta", R.reviewer, P, TA, T),                     # six roles, own level included
    ("dm_ta", R.interviewer, U, "P1", T),
    ("dm_ta", R.collaborator_pii, PS, (TA, "AZS2"), T),
    ("dm_ta", R.site_pi, PS, (TA, "AZS1"), F),           # never site_pi / In-charge
    ("dm_ta", R.interview_supervisor, U, "C1", F),
    ("dm_ta", R.project_pi, P, TA, F),
    ("dm_ta", R.coder, U, "F1", F),
    # district project, pair DM: nothing lies below a pair
    ("dm_ta_s1", R.data_manager, PS, (TA, "AZS1"), F),
    ("dm_ta_s1", R.coder, PS, (TA, "AZS1"), T),
    ("dm_ta_s1", R.reviewer, PS, (TA, "AZS1"), T),
    ("dm_ta_s1", R.coder, PS, (TA, "AZS2"), F),
    ("dm_ta_s1", R.coder, U, "P1", F),
    ("dm_ta_s1", R.coder, P, TA, F),
    # district project, unit DM: DM on strict descendants, six roles in the subtree
    ("dm_c1", R.data_manager, U, "C1", F),
    ("dm_c1", R.data_manager, U, "P1", T),
    ("dm_c1", R.data_manager, U, "SC1", T),
    ("dm_c1", R.coder, U, "C1", T),
    ("dm_c1", R.reviewer, U, "SC1", T),
    ("dm_c1", R.coder, U, "P2", T),
    ("dm_c1", R.coder, U, "D1", F),                      # never above own unit
    ("dm_c1", R.coder, U, "D2", F),                      # never outside it
    ("dm_c1", R.coder, PS, (TA, "AZS1"), F),
    ("dm_c1", R.coder, P, TA, F),
    ("dm_c1", R.data_manager, U, "F1", F),
    ("dm_c1", R.interview_supervisor, U, "P1", F),
    # In-charge (site_pi at a unit): DM at own level and below, plus DM powers
    ("incharge_c1", R.data_manager, U, "C1", T),
    ("incharge_c1", R.data_manager, U, "P1", T),
    ("incharge_c1", R.coder, U, "SC1", T),
    ("incharge_c1", R.data_manager, U, "D1", F),
    ("incharge_c1", R.interview_supervisor, U, "C1", F),
    ("incharge_c1", R.site_pi, U, "P1", F),
    ("incharge_c1", R.coder, PS, (TA, "AZS1"), F),
    # no grant-writing grant
    ("coder_ta", R.coder, P, TA, Reason.NO_ROLE),
    ("collab_c1", R.collaborator, U, "C1", Reason.NO_ROLE),
    ("supervisor_c1", R.interviewer, U, "P1", Reason.NO_ROLE),
]


class CanGrantTests(AuthzFixtureMixin, BaseTestCase):

    def _target(self, role, scope, where):
        if scope == P:
            return GrantTarget(role=role, scope_type=scope, project_id=where)
        if scope == PS:
            return GrantTarget(role=role, scope_type=scope,
                               project_site_id=self.project_site_ids[where])
        return GrantTarget(role=role, scope_type=scope, org_unit_id=self.units[where].org_unit_id)

    def test_cases(self):
        for actor, role, scope, where, expected in CASES:
            with self.subTest(actor=actor, role=role.value, scope=scope.value, where=where):
                decision = can_grant(
                    self.users.get(actor), self._target(role, scope, where),
                    _grants=self.grants_for(actor),
                )
                if isinstance(expected, Reason):
                    self.assertFalse(decision.allowed)
                    self.assertIs(decision.reason, expected)
                else:
                    self.assertEqual(decision.allowed, expected, decision.reason)

    def test_a_dm_never_writes_their_own_data_manager_grant(self):
        actor = self.users["dm_c1"]
        target = self._target(R.data_manager, U, "P1")
        self.assertTrue(can_grant(actor, target, grantee_id=self.users["coder_ta"].user_id))
        self.assertFalse(can_grant(actor, target, grantee_id=actor.user_id))

    def test_a_closed_project_grant_writes_nothing(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.users["nobody"].user_id, role=R.data_manager, scope_type=P,
            project_id=CL, grant_status=VaStatuses.active,
        ))
        db.session.flush()
        decision = can_grant(self.users["nobody"], self._target(R.coder, P, CL))
        self.assertIs(decision.reason, Reason.NO_ROLE)

    def test_cadre_and_mentor_refusals_still_apply_after_a_true_decision(self):
        p1 = self.units["P1"].org_unit_id
        cadres = {c.cadre_code: c for c in list_cadres(TA)}
        # Cadre: can_grant allows a coder at P1; the write-time cadre check
        # still refuses it without a cadre that may code there, and passes
        # with one (so the refusal is the cadre rule's, not something else).
        self.assertTrue(can_grant(self.users["dm_c1"], self._target(R.coder, U, "P1")))
        with self.assertRaisesRegex(OrganizationError, "requires a cadre"):
            validate_org_unit_grant(role=R.coder, org_unit_id=p1)
        validate_org_unit_grant(role=R.coder, org_unit_id=p1, cadre_id=cadres["MO"].cadre_id)
        # Mentor guard: can_grant allows a DM grant at P1 for an institute
        # member; the guard still refuses it, and the same grant passes for a
        # grantee outside the institute.
        mentor = self.users["mentor"]
        self.assertTrue(can_grant(
            self.users["dm_ta"], self._target(R.data_manager, U, "P1"), grantee_id=mentor.user_id
        ))
        with self.assertRaisesRegex(OrganizationError, "mentoring institute"):
            validate_org_unit_grant(role=R.data_manager, org_unit_id=p1, user_id=mentor.user_id)
        validate_org_unit_grant(
            role=R.data_manager, org_unit_id=p1, user_id=self.users["nobody"].user_id
        )

    def test_grant_list_filter_lists_exactly_what_can_grant_allows(self):
        grantee = self._get_or_make_user("authz.grantee@test.local", "AuthzTest123")
        places = [
            (P, TA), (PS, (TA, "AZS1")), (PS, (TA, "AZS2")),
            (U, "D1"), (U, "C1"), (U, "P1"), (U, "SC1"), (U, "P2"), (U, "F1"),
            (P, SP), (PS, (SP, "AZS1")), (PS, (SP, "AZS3")), (P, TB),
        ]
        roles = [R.coder, R.reviewer, R.coding_tester, R.data_manager,
                 R.collaborator, R.collaborator_pii, R.interviewer]
        rows = [self._grant_row(grantee, role, scope, where)
                for role in roles for scope, where in places]
        rows += [
            self._grant_row(grantee, R.interview_supervisor, U, "C1"),
            self._grant_row(grantee, R.site_pi, PS, (SP, "AZS1")),
            self._grant_row(grantee, R.project_pi, P, TA),
            self._grant_row(grantee, R.project_pi, P, SP),
        ]
        db.session.add_all(rows)
        db.session.flush()
        targets = {
            row.grant_id: GrantTarget(
                role=row.role, scope_type=row.scope_type, project_id=row.project_id,
                project_site_id=row.project_site_id, org_unit_id=row.org_unit_id,
            )
            for row in rows
        }
        for actor in ("dm_sp", "dm_sp1", "pi_sp", "pi_ta", "dm_ta", "dm_ta_s1", "dm_c1",
                      "incharge_c1", "coder_ta"):
            with self.subTest(actor=actor):
                grants = self.grants_for(actor)
                user = self.users.get(actor)
                listed = set(db.session.scalars(
                    sa.select(VaUserAccessGrants.grant_id).where(
                        VaUserAccessGrants.user_id == grantee.user_id,
                        grant_list_filter(user, _grants=grants),
                    )
                ).all())
                allowed = {
                    grant_id for grant_id, target in targets.items()
                    if can_grant(user, target, grantee_id=grantee.user_id, _grants=grants)
                }
                self.assertEqual(listed, allowed)
                if actor != "coder_ta":
                    self.assertTrue(allowed, "an actor with grant powers lists something")
