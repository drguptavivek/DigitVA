"""The project_pi role gate is an EXISTS, and its position in role_required() is free.

.tasks/auth-decorator-followups.md item 3 recorded `"project_pi": lambda u:
bool(u.get_project_pi_projects())` as "the only predicate that queries", and
worried that reordering `role_required("admin", "project_pi")` would make that
query unconditional. The premise was stale: `VaUsers.is_admin()` is itself a
query (an EXISTS), so the Layer-3 `any()` runs over booleans that each cost a
round trip and the decision is order-independent either way.

What was left is cost class: the gate asked "which projects?" to answer
"any project?". `VaUsers.is_project_pi()` asks the second question directly.

Three things are asserted here:
  a. the predicate's semantics, including the closed-project rule
     (docs/policy/access-control-model.md, "Closed projects")
  b. that both argument orders return identical statuses for an admin, a
     project PI and a plain user
  c. that the gate costs exactly one EXISTS statement, with
     get_project_pi_projects() as the discriminating positive control
"""

import importlib

import sqlalchemy as sa
from sqlalchemy import event

from app import db
from app.decorators.role_required import _ROLE_METHODS, role_required
from app.models import VaProjectMaster, VaStatuses
from tests.base import BaseTestCase

# The module object, not the dotted path: app/decorators/__init__.py re-exports
# `role_required`, so "app.decorators.role_required.current_user" resolves the
# middle segment to the FUNCTION and patches nothing that the decorator reads.
# See docs/policy/test-harness.md, "patch the module object".
_decorator_module = importlib.import_module("app.decorators.role_required")

# Statements SQLAlchemy emits to manage the class transaction and the per-test
# savepoint. They are not work the predicate asked for, so counting them would
# make the cost assertion depend on where in a test it is placed.
_TXN_CONTROL_PREFIXES = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK", "BEGIN", "COMMIT")


class ProjectPiPredicateTests(BaseTestCase):
    """Uses the base fixtures directly: base_project_pi_user holds an active
    project-scope project_pi grant on BASE_PROJECT_ID, base_admin_user holds a
    global admin grant, and base_coder_user holds neither."""

    def _capture_statements(self):
        """Record non-transaction-control SQL until the cleanup detaches us."""
        statements = []

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if not statement.lstrip().upper().startswith(_TXN_CONTROL_PREFIXES):
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", before_cursor_execute)
        self.addCleanup(
            event.remove, db.engine, "before_cursor_execute", before_cursor_execute
        )
        return statements

    def _run_gated_view(self, roles, user, path="/api/probe"):
        """Run a view gated on `roles` as `user`; return its HTTP status.

        Nothing is registered on the session app's url_map — that outlives the
        test (test-harness Rule 7). The decorator reads `current_user` off its
        own module namespace, so binding a real VaUsers there exercises the
        real predicates against the real grants.
        """
        original = _decorator_module.current_user
        _decorator_module.current_user = user
        try:

            @role_required(*roles)
            def view():
                return "ok", 200

            with self.app.test_request_context(path):
                _body, status = view()
                return status
        finally:
            _decorator_module.current_user = original

    # ── a. semantics ─────────────────────────────────────────────────────────

    def test_is_project_pi_is_true_for_an_active_grant_on_an_active_project(self):
        self.assertTrue(self.base_project_pi_user.is_project_pi())

    def test_is_project_pi_is_false_for_a_user_with_no_pi_grant(self):
        self.assertFalse(self.base_coder_user.is_project_pi())

    def test_is_project_pi_is_false_while_the_only_project_is_deactive(self):
        """Positive first, so the test cannot pass on a fixture that never
        granted anything (docs/policy/test-harness.md)."""
        self.assertTrue(self.base_project_pi_user.is_project_pi())

        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.project_status = VaStatuses.deactive
        db.session.flush()
        try:
            self.assertFalse(self.base_project_pi_user.is_project_pi())
        finally:
            project.project_status = VaStatuses.active
            db.session.flush()

        self.assertTrue(self.base_project_pi_user.is_project_pi())

    # ── b. order independence ────────────────────────────────────────────────

    def test_role_order_does_not_change_the_outcome_for_any_user(self):
        cases = (
            ("admin", self.base_admin_user, 200),
            ("project PI", self.base_project_pi_user, 200),
            ("plain coder", self.base_coder_user, 403),
        )
        for label, user, expected in cases:
            with self.subTest(user=label):
                admin_first = self._run_gated_view(("admin", "project_pi"), user)
                pi_first = self._run_gated_view(("project_pi", "admin"), user)
                self.assertEqual(admin_first, expected)
                self.assertEqual(pi_first, expected)

    # ── c. cost class ────────────────────────────────────────────────────────

    def test_the_gate_costs_one_exists_and_does_not_fetch_project_ids(self):
        """The discriminator is the SELECT list, not the word EXISTS.

        Both statements contain EXISTS — ``active_project_condition`` is a
        correlated EXISTS and both queries AND it in. What changed is what the
        outer SELECT returns: a boolean rather than every PI project id. So the
        positive control asserts the scope query still fetches the column, and
        the gate asserts it does not.
        """
        user = self.base_project_pi_user
        # Touch the identity before listening, so a lazy refresh of the user row
        # is not counted as the predicate's own work.
        assert user.user_id is not None
        db.session.scalar(sa.select(1))

        statements = self._capture_statements()

        user.get_project_pi_projects()
        self.assertEqual(len(statements), 1, statements)
        scope_sql = statements[0]
        self.assertIn("SELECT va_user_access_grants.project_id", scope_sql)
        self.assertFalse(scope_sql.lstrip().upper().startswith("SELECT EXISTS"))

        statements.clear()
        self.assertTrue(_ROLE_METHODS["project_pi"](user))
        self.assertEqual(len(statements), 1, statements)
        gate_sql = statements[0]
        self.assertIn("EXISTS", gate_sql.upper())
        # The point of the change: the gate returns a boolean, not the id set.
        self.assertTrue(gate_sql.lstrip().upper().startswith("SELECT EXISTS"))
