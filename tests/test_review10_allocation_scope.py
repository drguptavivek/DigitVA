"""Security review 10, findings 4, 5, 7 and 8 (digitva-4lv4).

#4 an active allocation is ownership, not scope: resume, the allocation API
and the service's existing-allocation branches ask authz again. #5 a
coding_tester never codes on a deactivated (project, site) pair. #7 the
coder history and recodeable lists carry the per-submission scope, not just
the form. #8 admin's SYNC_FORM bypass needs only the form to exist.
Policy: docs/policy/access-control-model.md, docs/policy/attachment-storage.md.
"""
import uuid
from unittest import mock

import sqlalchemy as sa
from flask import g

from app import db
from app.models import (
    VaAccessRoles,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaStatuses,
    VaSubmissionWorkflow,
)
from app.services.authz import Action, Reason, can, scope_filter
from app.services.coder_dashboard_service import (
    bust_coder_dashboard_cache,
    get_coder_completed_history,
    get_coder_recodeable_sids,
)
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_pick_form,
    allocate_random_form,
    require_active_coding_allocation,
    start_recode_allocation,
)
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.authz.fixture import FORMS, AuthzFixtureMixin
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


def _allocate(sid, user, kind=VaAllocation.coding):
    db.session.add(VaAllocations(
        va_allocation_id=uuid.uuid4(), va_sid=sid,
        va_allocated_to=user.user_id, va_allocation_for=kind,
        va_allocation_status=VaStatuses.active,
    ))
    db.session.commit()


class StaleAllocationTests(CodingScopeFixtureMixin, BaseTestCase):
    """#4: a held allocation is re-checked against the current scope."""

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(VaAllocations).where(
            VaAllocations.va_allocated_to == self.base_coder_user.user_id
        ))
        db.session.commit()
        _, _, _, self.phc_a, self.phc_b = self._tree()
        self.user = self.base_coder_user

    def _get(self, url):
        g.pop("_login_user", None)
        return self.client.get(url)

    def _held_coding(self):
        self.grant = self._grant(self.phc_a)
        # Keeps the form granted after the reroute, so a refusal is the
        # unit check's, not the form check's.
        self._submission("csc-anchor", unit=self.phc_a)
        held = self._submission("csc-held", unit=self.phc_a)
        _allocate("csc-held", self.user)
        return held

    def _reroute(self, submission):
        submission.org_unit_id = self.phc_b.org_unit_id
        db.session.commit()

    # -- service ---------------------------------------------------------

    def test_positive_control_resumes_with_the_grant_intact(self):
        self._held_coding()
        self.assertEqual(require_active_coding_allocation(self.user), "csc-held")
        result = allocate_random_form(self.user)
        self.assertEqual((result.va_sid, result.actiontype), ("csc-held", "varesumecoding"))
        self.assertEqual(allocate_pick_form(self.user, "csc-held").actiontype, "varesumecoding")

    def test_service_refuses_a_rerouted_allocation(self):
        self._reroute(self._held_coding())
        self.assertTrue(can(self.user, Action.CODE, "csc-anchor"))
        for call in (
            lambda: require_active_coding_allocation(self.user),
            lambda: allocate_random_form(self.user),
            lambda: allocate_pick_form(self.user, "csc-held"),
        ):
            with self.assertRaises(AllocationError) as ctx:
                call()
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("outside your coding scope", ctx.exception.message)
        # Refused, not released: the stale-allocation release clears it.
        self.assertEqual(db.session.scalar(sa.select(VaAllocations.va_allocation_status).where(
            VaAllocations.va_sid == "csc-held"
        )), VaStatuses.active)

    def test_recode_resume_refuses_a_rerouted_allocation(self):
        self._reroute(self._held_coding())
        with mock.patch(
            "app.services.coder_workflow_service.get_active_recode_episode",
            return_value=object(),
        ), self.assertRaises(AllocationError) as ctx:
            start_recode_allocation(self.user, "csc-held")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_service_refuses_after_the_grant_is_revoked(self):
        self._held_coding()
        self.grant.grant_status = VaStatuses.deactive
        db.session.commit()
        with self.assertRaises(AllocationError) as ctx:
            require_active_coding_allocation(self.user)
        self.assertEqual(ctx.exception.status_code, 403)

    # -- routes ----------------------------------------------------------

    def test_coding_resume_and_allocation_api_follow_the_scope(self):
        held = self._held_coding()
        self._login(str(self.user.user_id))
        with mock.patch("app.routes.coding.render_va_coding_page", return_value="rendered"):
            self.assertEqual(self._get("/coding/resume").status_code, 200)
            api = self._get("/api/v1/coding/allocation")
            self.assertEqual(api.status_code, 200)
            self.assertEqual(api.get_json()["allocation"]["va_sid"], "csc-held")

            self._reroute(held)
            self.assertEqual(self._get("/coding/resume").status_code, 403)
            api = self._get("/api/v1/coding/allocation")
            self.assertEqual(api.status_code, 200)
            self.assertIsNone(api.get_json()["allocation"])

    def test_reviewing_resume_follows_the_scope(self):
        self._grant(self.phc_a, role=VaAccessRoles.reviewer)
        held = self._submission("csc-review", unit=self.phc_a)
        self._submission("csc-review-anchor", unit=self.phc_a)
        _allocate("csc-review", self.user, VaAllocation.reviewing)
        self._login(str(self.user.user_id))
        with mock.patch("app.routes.reviewing.render_va_coding_page", return_value="rendered"):
            self.assertEqual(self._get("/reviewing/resume").status_code, 200)
            api = self._get("/api/v1/reviewing/allocation").get_json()
            self.assertEqual(api["allocation"], {"va_sid": "csc-review"})
            self._reroute(held)
            self.assertTrue(can(self.user, Action.REVIEW, "csc-review-anchor"))
            self.assertEqual(self._get("/reviewing/resume").status_code, 403)
            api = self._get("/api/v1/reviewing/allocation").get_json()
            self.assertIsNone(api["allocation"])
        with mock.patch("app.routes.reviewing.render_template", return_value="") as page:
            self._get("/reviewing/")
        self.assertIsNone(page.call_args.kwargs["va_has_allocation"])


class DashboardScopeTests(CodingScopeFixtureMixin, BaseTestCase):
    """#7: history and recodeable carry the submission's own unit."""

    def test_history_and_recodeable_exclude_a_sibling_unit_on_the_same_form(self):
        _, _, _, phc_a, phc_b = self._tree()
        self._grant(phc_a)
        user = self.base_coder_user
        for sid, unit in (("csc-mine", phc_a), ("csc-sibling", phc_b)):
            self._submission(sid, unit=unit)
            db.session.add(VaFinalAssessments(
                va_sid=sid, va_finassess_by=user.user_id,
                va_conclusive_cod="R99", va_finassess_status=VaStatuses.active,
            ))
        db.session.execute(
            sa.update(VaSubmissionWorkflow)
            .where(VaSubmissionWorkflow.va_sid.in_(("csc-mine", "csc-sibling")))
            .values(workflow_state=WORKFLOW_CODER_FINALIZED)
        )
        db.session.commit()
        bust_coder_dashboard_cache(user.user_id)

        history = {row["va_sid"] for row in get_coder_completed_history(user, [self.FORM_ID])}
        recodeable = set(get_coder_recodeable_sids(user, [self.FORM_ID]))
        self.assertIn("csc-mine", history)
        self.assertNotIn("csc-sibling", history)
        self.assertIn("csc-mine", recodeable)
        self.assertNotIn("csc-sibling", recodeable)


class TesterInactivePairTests(AuthzFixtureMixin, BaseTestCase):
    """#5: a coding_tester's grant stops at a deactivated pair; demo still works."""

    def _ready(self, *sids):
        for sid in sids:
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state="ready_for_coding",
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))
        db.session.commit()

    def test_tester_forms_skip_a_deactivated_pair_and_keep_demo(self):
        forms = self.user("tester_sp").get_coding_tester_va_forms()
        self.assertIn(FORMS["sp3"][0], forms)
        self.assertIn(FORMS["dm1"][0], forms)
        self.assertNotIn(FORMS["sp4"][0], forms)

    def test_tester_cannot_allocate_on_a_deactivated_pair(self):
        self._ready("sp-3", "sp-4")
        tester = self.user("tester_sp")
        self.assertTrue(can(tester, Action.CODE, "dm-1"))
        self.assertEqual(can(tester, Action.CODE, "sp-4").reason, Reason.OUT_OF_SCOPE)
        with self.assertRaises(AllocationError):
            allocate_pick_form(tester, "sp-4")

    def test_tester_allocates_on_an_active_pair(self):
        self._ready("sp-3", "sp-4")
        result = allocate_pick_form(self.user("tester_sp"), "sp-3")
        self.assertEqual(result.va_sid, "sp-3")


class AdminSyncFormParityTests(AuthzFixtureMixin, BaseTestCase):
    """#8: admin's single-form SYNC_FORM matches its list bypass."""

    def test_admin_syncs_a_form_on_a_deactivated_pair(self):
        admin = self.user("admin")
        listed = self.scoped_sids(scope_filter(admin, Action.SYNC_FORM))
        self.assertIn("sp-4", listed)
        self.assertTrue(can(admin, Action.SYNC_FORM, FORMS["sp4"][0]))
        self.assertEqual(
            can(admin, Action.SYNC_FORM, "NO_SUCH_FORM").reason, Reason.NOT_FOUND
        )
        # A data manager still stops at the deactivated pair.
        self.assertFalse(can(self.user("dm_sp"), Action.SYNC_FORM, FORMS["sp4"][0]))
        self.assertTrue(can(self.user("dm_sp"), Action.SYNC_FORM, FORMS["sp3"][0]))

