"""GET /api/v1/users/<id>/placement (digitva-x79t): a listed user's place in the
organization, in "My organization"'s shape, cut to the viewer's projects.

Policy: docs/policy/access-control-model.md ("Users page"). Users and the
AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2, D2) come from the authz fixture;
``mixed`` holds coder at P1 (AZTA01) and collaborator at project AZSP01.
"""
import uuid

import sqlalchemy as sa

from app import db, limiter
from tests.authz.fixture import SP, TA, AuthzFixtureMixin
from tests.base import BaseTestCase
from tests.routes.test_users_api import URL


class UsersPlacementTests(AuthzFixtureMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _get(self, viewer, target, status=200):
        self._login(str(self.users[viewer].user_id))
        res = self.client.get(f"{URL}/{self.users[target].user_id}/placement")
        self.assertEqual(res.status_code, status, res.get_json())
        return res.get_json()

    def _projects(self, viewer, target):
        return {p["project_id"]: p for p in self._get(viewer, target)["projects"]}

    def test_permitted_target_is_placed_at_their_unit(self):
        projects = self._projects("dm_c1", "coder_p1")
        self.assertIn(TA, projects)  # present before asserting what is absent
        self.assertEqual([u["unit_name"] for u in projects[TA]["my_units"]], ["P1"])
        self.assertEqual(projects[TA]["my_units"][0]["roles"], [{"role": "coder", "cadre": None}])

    def test_outside_scope_is_not_found_like_status(self):
        self._get("dm_c1", "coder_ta", status=404)  # project-scope grant: not in C1's subtree
        self._get("dm_c1", "coder_sp", status=404)
        self._login(str(self.users["admin"].user_id))
        self.assertEqual(self.client.get(f"{URL}/{uuid.uuid4()}/placement").status_code, 404)
        self.assertEqual(self.client.get(f"{URL}/not-a-uuid/placement").status_code, 404)

    def test_other_roles_are_refused(self):
        self._get("coder_ta", "coder_p1", status=403)

    def test_viewer_sees_only_the_projects_they_manage(self):
        projects = self._projects("pi_ta", "mixed")
        self.assertIn(TA, projects)
        self.assertNotIn(SP, projects)
        self.assertEqual([u["unit_name"] for u in projects[TA]["my_units"]], ["P1"])

    def test_admin_sees_every_project_of_the_user(self):
        projects = self._projects("admin", "mixed")
        self.assertIn(TA, projects)
        self.assertEqual(set(projects), {TA, SP})
        self.assertEqual(projects[SP]["my_positions"]["project_roles"], ["collaborator"])

    def test_query_count_is_bounded(self):
        self._login(str(self.users["admin"].user_id))
        statements = []

        def count(conn, cursor, statement, *a):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", count)
        try:
            res = self.client.get(f"{URL}/{self.users['mixed'].user_id}/placement")
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", count)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()["projects"]), 2)
        self.assertLessEqual(len(statements), 40, len(statements))
