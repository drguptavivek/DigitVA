"""resolve_grants, its memo, effective_roles and coding_gate_waivers (digitva-0wc)."""
from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import event

from app import db
from app.services.authz import (
    coding_gate_waivers,
    effective_roles,
    invalidate,
    resolve_grants,
)
from tests.authz.fixture import DM, TA, USERS, AuthzFixtureMixin, P, R
from tests.base import BaseTestCase


@contextmanager
def count_queries():
    statements = []

    def before(conn, cursor, statement, *args):
        statements.append(statement)

    engine = db.session.get_bind()
    target = getattr(engine, "engine", engine)
    event.listen(target, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(target, "before_cursor_execute", before)


class ResolveGrantsTests(AuthzFixtureMixin, BaseTestCase):

    def test_two_queries_whatever_the_number_of_grants(self):
        user = SimpleNamespace(user_id=self.users["mixed"].user_id)
        with count_queries() as statements:
            resolved = resolve_grants(user)
        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(selects), 2, statements)
        self.assertEqual(
            {(g.role, g.project_id) for g in resolved.grants if not g.virtual},
            {(R.coder, TA), (R.collaborator, "AZSP01")},
        )

    def test_closed_project_grants_are_absent_and_demo_is_virtual(self):
        resolved = resolve_grants(self.users["closed_coder"])
        self.assertTrue(resolved.grants)  # the demo grants: the subject is present
        self.assertTrue(all(g.virtual and g.project_id == DM for g in resolved.grants))
        self.assertEqual(
            {g.role for g in resolved.grants}, {R.coder, R.coding_tester, R.reviewer}
        )

    def test_admin_is_the_global_grant(self):
        self.assertTrue(resolve_grants(self.users["admin"]).is_admin)
        self.assertFalse(resolve_grants(self.users["dm_ta"]).is_admin)

    def test_memoised_per_request_and_invalidated_by_a_grant_write(self):
        user = self.users["nobody"]
        with self.app.test_request_context("/"):
            first = resolve_grants(user)
            self.assertIs(resolve_grants(user), first)
            db.session.add(self._grant_row(user, R.data_manager, P, TA))
            db.session.flush()
            self.assertIs(resolve_grants(user), first)  # memo holds within the request
            invalidate(user.user_id)
            self.assertTrue(resolve_grants(user).holds(R.data_manager))
        # Outside a request nothing is cached.
        self.assertIsNot(resolve_grants(user), resolve_grants(user))


class EffectiveRolesTests(AuthzFixtureMixin, BaseTestCase):

    def test_roles(self):
        demo = {"coder", "coding_tester", "reviewer"}
        cases = {
            "admin": {"admin"} | demo,
            "nobody": demo,
            "dm_c1": {"data_manager"} | demo,
            "pi_ta": {"project_pi", "data_manager", "interview_supervisor"} | demo,
            "pi_sp": {"project_pi"} | demo,
            "sitepi_sp1": {"site_pi"} | demo,
            "incharge_c1": {"site_pi", "data_manager", "interview_supervisor"} | demo,
            "collab_c1": {"collaborator", "collaborator_pii"} | demo,
            "supervisor_c1": {"interview_supervisor"} | demo,
            "closed_coder": demo,
        }
        for key, expected in cases.items():
            with self.subTest(user=key):
                roles = effective_roles(self.users.get(key), _grants=self.grants_for(key))
                self.assertEqual(roles, frozenset(expected))


class CodingGateWaiverTests(AuthzFixtureMixin, BaseTestCase):

    def test_same_waivers_as_the_original(self):
        # The original (coder_workflow_service._coding_waivers, deleted in
        # stage 1) was these five VaUsers getters; compare against them.
        checked = 0
        for key in USERS:
            if key == "incharge_c1":
                continue
            with self.subTest(user=key):
                user = self.users[key]
                new = coding_gate_waivers(user)
                old = {
                    "pi_projects": user.get_project_pi_projects(),
                    "pi_pairs": user.get_site_pi_project_site_pairs(),
                    "tester_projects": user.get_coding_tester_projects(),
                    "tester_pairs": user.get_coding_tester_project_site_pairs(),
                    "tester_unit_ids": user.get_coding_tester_org_unit_ids(),
                }
                for field, expected in old.items():
                    self.assertEqual(getattr(new, field), frozenset(expected), field)
                    checked += bool(getattr(new, field))
        self.assertGreater(checked, 3)  # some user holds each kind of waiver

    def test_unit_tester_waives_inside_its_subtree_only(self):
        waivers = coding_gate_waivers(self.users["tester_c1"])
        self.assertTrue(waivers.is_tester(TA, "AZS1", self.units["SC1"].org_unit_id))
        self.assertFalse(waivers.is_tester(TA, "AZS1", self.units["D1"].org_unit_id))
