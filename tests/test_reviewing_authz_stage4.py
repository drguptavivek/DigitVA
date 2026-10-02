"""Reviewing on the authz module: what stage 4 pins and changes.

digitva-0wc stage 4 (.tasks/digitva-0wc-design.md section 7) moves reviewer
start, Step 1, final, the dashboard, the view page, the ``vareview`` partial
validator and the reviewer JSON branches onto ``app.services.authz``:
REVIEW (the coding-scope rule, reviewer grants) to act, VIEW to look.

- Under ``view_only`` a project or pair reviewer views but does not review;
  under ``code_any`` they review.
- A unit reviewer never reviews a sibling unit's case, at any entry point.
- F7: the view page and its partials open for a reviewer who may view but
  not review.
- The reviewer dashboard offers the area link to a reviewer with an area.
- F19 stays: the dashboard lists in-scope cases in any workflow state.

Demo-training reviewing without a grant is pinned by
tests/routes/test_demo_training_project.py
(``test_plain_user_can_start_reviewing_demo_case_without_grant``).
"""
import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaProjectSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    start_reviewer_coding,
    submit_reviewer_final_cod,
    submit_reviewer_initial_cod,
)
from app.services.workflow.definition import WORKFLOW_REVIEWER_ELIGIBLE
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin

OUT_OF_SCOPE = "outside your reviewing scope"


class ReviewingAuthzStageFourTests(CodingScopeFixtureMixin, BaseTestCase):
    """CSC001: District > CHC > PHC A, PHC B; coding scope level PHC."""

    def setUp(self):
        super().setUp()
        self.levels, _, self.chc, self.phc_a, self.phc_b = self._tree()
        self._set_scope(self.levels["phc"])
        for sid, unit in (("csc-s4-a", self.phc_a), ("csc-s4-b", self.phc_b)):
            self._submission(sid, unit=unit)
        db.session.execute(
            sa.update(VaSubmissionWorkflow)
            .where(VaSubmissionWorkflow.va_sid.in_(["csc-s4-a", "csc-s4-b"]))
            .values(workflow_state=WORKFLOW_REVIEWER_ELIGIBLE)
        )
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _user(self, key, *grants):
        """A fresh user holding *grants*: (role, "project" | "pair" | unit)."""
        user = self._make_user(f"stage4.{key}@test.local", "Stage4Test123")
        for role, where in grants:
            if where == "project":
                fields = {"scope_type": VaAccessScopeTypes.project, "project_id": self.PROJECT}
            elif where == "pair":
                fields = {
                    "scope_type": VaAccessScopeTypes.project_site,
                    "project_site_id": self._project_site().project_site_id,
                }
            else:
                fields = {"scope_type": VaAccessScopeTypes.org_unit, "org_unit_id": where.org_unit_id}
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, grant_status=VaStatuses.active, **fields,
            ))
        db.session.commit()
        return user

    def _project_site(self):
        return db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.PROJECT,
            VaProjectSites.site_id == self.SITE,
        ))

    def _allocate(self, user, sid):
        """An active reviewing allocation, as if granted before a re-routing."""
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.reviewing,
        ))
        db.session.commit()

    def _partial(self, sid, actiontype):
        return self.client.get(
            f"/vaform/{sid}/vademographicdetails?action=vareview&actiontype={actiontype}"
        )

    def _refused(self, call):
        with self.assertRaises(ReviewerCodingError) as ctx:
            call()
        return ctx.exception

    # -- view_only / code_any ----------------------------------------------

    def test_a_wide_reviewer_on_a_view_only_project_views_but_cannot_review(self):
        for scope in ("project", "pair"):
            with self.subTest(scope=scope):
                reviewer = self._user(f"viewonly.{scope}", (VaAccessRoles.reviewer, scope))
                self._login(str(reviewer.user_id))
                self.assertEqual(self.client.get("/reviewing/view/csc-s4-a").status_code, 200)
                self.assertNotEqual(self._partial("csc-s4-a", "vaview").status_code, 403)

                error = self._refused(lambda: start_reviewer_coding(reviewer, "csc-s4-a"))
                self.assertEqual(error.status_code, 403)
                self.assertIn(OUT_OF_SCOPE, error.message)
                response = self.client.post(
                    "/reviewing/start/csc-s4-a", headers=self._csrf_headers()
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self._partial("csc-s4-a", "vastartreviewing").status_code, 403)

    def test_under_code_any_a_wide_reviewer_reviews(self):
        self._set_scope(self.levels["phc"], mode="code_any")
        for scope, sid in (("project", "csc-s4-a"), ("pair", "csc-s4-b")):
            with self.subTest(scope=scope):
                reviewer = self._user(f"codeany.{scope}", (VaAccessRoles.reviewer, scope))
                result = start_reviewer_coding(reviewer, sid)
                self.assertEqual((result.va_sid, result.actiontype), (sid, "vastartreviewing"))

    # -- sibling unit, every entry point -------------------------------------

    def test_a_unit_reviewer_cannot_review_a_sibling_units_case(self):
        reviewer = self._user("unit.a", (VaAccessRoles.reviewer, self.phc_a))
        self._login(str(reviewer.user_id))
        headers = self._csrf_headers()

        # Own unit: the allocation API admits it.
        response = self.client.post("/api/v1/reviewing/allocation/csc-s4-a", headers=headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["actiontype"], "vastartreviewing")
        self.assertNotEqual(self._partial("csc-s4-a", "vastartreviewing").status_code, 403)

        # Sibling unit: refused before any allocation or state check.
        self.assertEqual(
            self.client.post("/reviewing/start/csc-s4-b", headers=headers).status_code, 403
        )
        response = self.client.post("/api/v1/reviewing/allocation/csc-s4-b", headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertIn(OUT_OF_SCOPE, response.get_json()["error"])
        for call in (
            lambda: start_reviewer_coding(reviewer, "csc-s4-b"),
            lambda: submit_reviewer_initial_cod(
                reviewer, "csc-s4-b", immediate_cod="A00", antecedent_cod="A00"
            ),
            lambda: submit_reviewer_final_cod(reviewer, "csc-s4-b", conclusive_cod="A00"),
        ):
            error = self._refused(call)
            self.assertEqual(error.status_code, 403)
            self.assertIn(OUT_OF_SCOPE, error.message)
        for actiontype in ("vastartreviewing", "varesumereviewing", "vaview"):
            with self.subTest(partial=actiontype):
                self.assertEqual(self._partial("csc-s4-b", actiontype).status_code, 403)
        self.assertEqual(self.client.get("/reviewing/view/csc-s4-b").status_code, 403)

    def test_reviewer_json_saves_need_review_scope_as_well_as_the_allocation(self):
        """An allocation that outlived a re-routing no longer carries the save."""
        reviewer = self._user("unit.json", (VaAccessRoles.reviewer, self.phc_a))
        self._allocate(reviewer, "csc-s4-a")
        self._allocate(reviewer, "csc-s4-b")
        self._login(str(reviewer.user_id))
        body = {"va_actiontype": "varesumereviewing", "cannot_grade": True, "selected_options": []}
        for path in ("narrative-qa", "social-autopsy"):
            with self.subTest(api=path):
                mine = self.client.post(
                    f"/api/v1/va/csc-s4-a/{path}", json=body, headers=self._csrf_headers()
                )
                self.assertNotEqual(
                    (mine.get_json() or {}).get("error"), "Reviewer access is required."
                )
                theirs = self.client.post(
                    f"/api/v1/va/csc-s4-b/{path}", json=body, headers=self._csrf_headers()
                )
                self.assertEqual(theirs.status_code, 403)
                self.assertEqual(theirs.get_json()["error"], "Reviewer access is required.")

    # -- F7 ----------------------------------------------------------------

    def test_view_opens_for_a_reviewer_who_may_view_but_not_review(self):
        # CHC sits above the PHC scope level: under view_only it reviews nothing.
        reviewer = self._user("unit.chc", (VaAccessRoles.reviewer, self.chc))
        self._login(str(reviewer.user_id))
        self.assertEqual(self.client.get("/reviewing/view/csc-s4-b").status_code, 200)
        self.assertNotEqual(self._partial("csc-s4-b", "vaview").status_code, 403)
        self.assertEqual(self._partial("csc-s4-b", "vastartreviewing").status_code, 403)
        error = self._refused(lambda: start_reviewer_coding(reviewer, "csc-s4-b"))
        self.assertIn(OUT_OF_SCOPE, error.message)

    def test_the_reviewer_rendering_stays_a_reviewer_rendering(self):
        """VIEW decides scope; the reviewer rendering still needs the reviewer role."""
        coder = self._user("coder.chc", (VaAccessRoles.coder, self.chc))
        self._login(str(coder.user_id))
        self.assertEqual(self.client.get("/coding/area/csc-s4-b").status_code, 200)
        self.assertEqual(self._partial("csc-s4-b", "vaview").status_code, 403)

    def test_the_reviewer_rendering_ignores_the_demo_widened_role_flag(self):
        """An active demo project makes is_reviewer() true for everyone; the
        reviewer rendering must still need reviewer reach on this case."""
        from unittest.mock import patch

        from app.models import VaUsers

        coder = self._user("coder.demo", (VaAccessRoles.coder, self.chc))
        self._login(str(coder.user_id))
        with patch.object(VaUsers, "is_reviewer", return_value=True):
            self.assertEqual(self._partial("csc-s4-b", "vaview").status_code, 403)

    # -- dashboard ---------------------------------------------------------

    def test_the_dashboard_lists_the_review_scope_in_every_state(self):
        reviewer = self._user("unit.dash", (VaAccessRoles.reviewer, self.phc_a))
        self._submission("csc-s4-c-new", unit=self.phc_a)  # ready_for_coding (F19)
        self._login(str(reviewer.user_id))
        response = self.client.get("/reviewing/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("csc-s4-c-new", body)
        self.assertIn("csc-s4-a", body)
        self.assertNotIn("csc-s4-b", body)

    def test_the_dashboard_offers_the_area_link_to_a_reviewer_with_an_area(self):
        reviewer = self._user("unit.area", (VaAccessRoles.reviewer, self.chc))
        self._login(str(reviewer.user_id))
        body = self.client.get("/reviewing/").get_data(as_text=True)
        self.assertIn('href="/coding/area?role=reviewer"', body)

        # Without an active tree the same grant is no area.
        db.session.execute(
            sa.update(MasOrgLevel).where(MasOrgLevel.project_id == self.PROJECT).values(is_active=False)
        )
        db.session.commit()
        body = self.client.get("/reviewing/").get_data(as_text=True)
        self.assertIn("Language-Matched VA Forms", body)
        self.assertNotIn("/coding/area", body)
