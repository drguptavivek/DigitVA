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
from tests.authz.fixture import DM, SP, TA, USERS, AuthzFixtureMixin, P, R
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

    def test_waivers_per_fixture_user(self):
        # Hand-written from the fixture roster (tests/authz/fixture.py USERS);
        # every field not listed is empty. A demo-training grant waives nothing.
        tester_c1_units = {self.units[code].org_unit_id for code in ("C1", "P1", "SC1", "P2")}
        expected = {
            "pi_ta": {"pi_projects": {TA}},
            "pi_sp": {"pi_projects": {SP}},
            "sitepi_sp1": {"pi_pairs": {(SP, "AZS1")}},
            "tester_ta": {"tester_projects": {TA}},
            "tester_sp": {"tester_projects": {SP}},
            "tester_c1": {"tester_unit_ids": tester_c1_units},
        }
        fields = ("pi_projects", "pi_pairs", "tester_projects", "tester_pairs", "tester_unit_ids")
        for key in USERS:
            with self.subTest(user=key):
                waivers = coding_gate_waivers(self.users[key])
                for field in fields:
                    self.assertEqual(
                        getattr(waivers, field), frozenset(expected.get(key, {}).get(field, ())),
                        field,
                    )

    def test_unit_tester_waives_inside_its_subtree_only(self):
        waivers = coding_gate_waivers(self.users["tester_c1"])
        self.assertTrue(waivers.is_tester(TA, "AZS1", self.units["SC1"].org_unit_id))
        self.assertFalse(waivers.is_tester(TA, "AZS1", self.units["D1"].org_unit_id))
