"""Coding screens on the authz module: the behaviour stage 1 changes on purpose.

digitva-0wc stage 1 (.tasks/digitva-0wc-design.md section 7) moves the coder
pool, pick, recode, the coder view and the area overview onto
``app.services.authz``. These tests pin the findings it closes
(.tasks/digitva-0wc-access-matrix-current.md):

- F15: a project or pair coding tester on a tree project gets the pool.
- F2: the area overview lists what a project or pair grant may view,
  routed or not, and the dashboard offers the link.
- F17: a tester-only user has an area, and every overview row opens.
- F16: pick and the pick list agree on language and on the coding gates.
- F4: the ``vacode``/``vaview`` partial validator honours a tester's VIEW.
"""
import sqlalchemy as sa
from flask_login import login_user
from werkzeug.exceptions import Forbidden

from app import db
from app.decorators.va_validate_permissions import _validate_vacode
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaFinalAssessments,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.authz import Action, can
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_pick_form,
    get_coder_ready_stats,
    get_pick_available_forms,
)
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


class CodingAuthzStageOneTests(CodingScopeFixtureMixin, BaseTestCase):
    """CSC001: District > CHC > PHC (two), coding scope level PHC, view_only."""

    def setUp(self):
        super().setUp()
        self.levels, _, self.chc, self.phc_a, self.phc_b = self._tree()
        self._set_scope(self.levels["phc"])
        self._submission("csc-s1-phc", unit=self.phc_a)
        self._submission("csc-s1-chc", unit=self.chc)
        self._submission("csc-s1-unrouted")

    # -- fixtures ----------------------------------------------------------

    def _user(self, key, *grants):
        """A fresh user holding *grants*: (role, "project") or (role, unit)."""
        user = self._make_user(f"stage1.{key}@test.local", "Stage1Test123")
        for role, where in grants:
            fields = (
                {"scope_type": VaAccessScopeTypes.project, "project_id": self.PROJECT}
                if where == "project"
                else {"scope_type": VaAccessScopeTypes.org_unit, "org_unit_id": where.org_unit_id}
            )
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, grant_status=VaStatuses.active, **fields,
            ))
        db.session.commit()
        return user

    def _pick_list(self, user):
        forms = user.get_coder_va_forms() | user.get_coding_tester_va_forms()
        return {row["va_sid"] for row in get_pick_available_forms(user, list(forms))}

    def _project_site(self):
        return db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.PROJECT,
            VaProjectSites.site_id == self.SITE,
        ))

    # -- F15 ---------------------------------------------------------------

    def test_a_project_tester_on_a_tree_project_gets_the_pool(self):
        tester = self._user("tester.project", (VaAccessRoles.coding_tester, "project"))
        self.assertTrue(can(tester, Action.CODE, "csc-s1-unrouted"))

        # Exempt from the scope level, and a project grant reaches unrouted.
        expected = {"csc-s1-phc", "csc-s1-chc", "csc-s1-unrouted"}
        self.assertEqual(self._pick_list(tester), expected)
        self.assertEqual(get_coder_ready_stats(tester)["pick_ready"], len(expected))
        result = allocate_pick_form(tester, "csc-s1-unrouted")
        self.assertEqual(result.va_sid, "csc-s1-unrouted")

    # -- F2 ----------------------------------------------------------------

    def test_the_area_lists_what_a_project_grant_views(self):
        coder = self._user("coder.project", (VaAccessRoles.coder, "project"))
        self._login(str(coder.user_id))

        dashboard = self.client.get("/coding/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('href="/coding/area"', dashboard.get_data(as_text=True))

        response = self.client.get("/coding/area")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for sid in ("csc-s1-phc", "csc-s1-chc", "csc-s1-unrouted"):
            self.assertIn(sid, body)
        # view_only: a project grant sits above the scope level, codes nothing.
        self.assertIn("view only", body)
        self.assertNotIn("no area to show", body)
        self.assertEqual(self.client.get("/coding/area/csc-s1-unrouted?role=coder").status_code, 200)

    # -- F17 ---------------------------------------------------------------

    def test_a_tester_only_user_has_an_area(self):
        tester = self._user("tester.chc", (VaAccessRoles.coding_tester, self.chc))
        self._login(str(tester.user_id))
        body = self.client.get("/coding/area").get_data(as_text=True)
        self.assertIn("csc-s1-chc", body)
        self.assertIn("csc-s1-phc", body)
        self.assertNotIn("csc-s1-unrouted", body)  # a unit grant never reaches unrouted

    def test_every_row_of_a_reviewer_area_opens(self):
        user = self._user(
            "mixed.tracks",
            (VaAccessRoles.coder, self.phc_a),
            (VaAccessRoles.reviewer, self.chc),
        )
        self._login(str(user.user_id))
        body = self.client.get("/coding/area?role=reviewer").get_data(as_text=True)
        self.assertIn("csc-s1-chc", body)
        self.assertIn("/coding/area/csc-s1-chc?role=reviewer", body)
        # Opened with or without the role: VIEW decides, not the track.
        self.assertEqual(self.client.get("/coding/area/csc-s1-chc?role=reviewer").status_code, 200)
        self.assertEqual(self.client.get("/coding/area/csc-s1-chc").status_code, 200)
        # Outside every grant stays refused: unit grants never reach unrouted.
        self.assertEqual(self.client.get("/coding/area/csc-s1-unrouted").status_code, 403)

    # -- F16 ---------------------------------------------------------------

    def test_pick_refuses_a_language_the_list_does_not_offer(self):
        coder = self._user("coder.phc", (VaAccessRoles.coder, self.phc_a))
        self._submission("csc-s1-hindi", unit=self.phc_a)
        db.session.get(VaSubmissions, "csc-s1-hindi").va_narration_language = "Hindi"
        db.session.commit()
        self.assertEqual(coder.vacode_language, ["English"])

        self.assertEqual(self._pick_list(coder), {"csc-s1-phc"})
        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(coder, "csc-s1-hindi")
        self.assertIn("does not support coding forms in Hindi", ctx.exception.message)
        self.assertEqual(allocate_pick_form(coder, "csc-s1-phc").va_sid, "csc-s1-phc")

    def test_the_pick_list_drops_a_site_whose_gate_is_closed(self):
        coder = self._user("coder.gated", (VaAccessRoles.coder, self.phc_a))
        tester = self._user("tester.gated", (VaAccessRoles.coding_tester, "project"))
        self.assertEqual(self._pick_list(coder), {"csc-s1-phc"})

        self._project_site().coding_enabled = False
        db.session.commit()
        self.assertEqual(self._pick_list(coder), set())
        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(coder, "csc-s1-phc")
        self.assertIn("disabled", ctx.exception.message)
        # A tester's waiver keeps the site open, in the list and in pick alike.
        self.assertIn("csc-s1-phc", self._pick_list(tester))

    # -- F4 ----------------------------------------------------------------

    def test_the_vaview_partial_validator_honours_a_testers_view(self):
        tester = self._user("tester.viewer", (VaAccessRoles.coding_tester, "project"))
        db.session.add(VaFinalAssessments(
            va_sid="csc-s1-phc", va_finassess_by=tester.user_id,
            va_conclusive_cod="R99", va_finassess_status=VaStatuses.active,
        ))
        db.session.commit()
        with self.app.test_request_context():
            login_user(tester)
            # In VIEW scope and the tester's own outcome: passes.
            _validate_vacode("vaview", "csc-s1-phc", "vademographicdetails")
            # In VIEW scope but not their own outcome: the workflow check refuses.
            with self.assertRaises(Forbidden):
                _validate_vacode("vaview", "csc-s1-chc", "vademographicdetails")
        nobody = self._user("nobody.viewer")
        with self.app.test_request_context():
            login_user(nobody)
            with self.assertRaises(Forbidden):
                _validate_vacode("vaview", "csc-s1-phc", "vademographicdetails")

    def test_a_closed_unit_gate_leaves_unrouted_submissions_in_the_pool(self):
        """A unit gate narrows routed submissions only. ``org_unit_id NOT IN``
        alone is NULL for an unrouted case, which used to drop every unrouted
        submission from the random pool once any unit gate closed."""
        from app.services import organization_service as org

        self._set_scope(self.levels["phc"], mode="code_any")
        coder = self._user("coder.unitgate", (VaAccessRoles.coder, "project"))
        self.assertIn("csc-s1-phc", self._pick_list(coder))

        org.set_unit_coding_gate(self.PROJECT, self.phc_a.org_unit_id, coding_enabled=False)
        db.session.commit()
        offered = self._pick_list(coder)
        self.assertNotIn("csc-s1-phc", offered)
        self.assertIn("csc-s1-unrouted", offered)
        self.assertIn("csc-s1-chc", offered)
