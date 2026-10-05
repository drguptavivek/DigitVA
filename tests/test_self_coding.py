"""Per-project self-coding: "Code this case now", coder release and the admin
setting (digitva-xuxk). Policy: docs/policy/coding-workflow-state-machine.md
"Self-coding", docs/policy/coding-allocation-timeouts.md "Coder release".
"""
import uuid

import sqlalchemy as sa
from flask import g

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_own_case,
    allocate_pick_form,
    get_active_coding_allocation,
    release_own_coding_allocation,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


class SelfCodingFixture(CodingScopeFixtureMixin):
    """A self-coding site project (intake on) with a submitter and another coder."""

    def setUp(self):
        super().setUp()
        project = db.session.get(VaProjectMaster, self.PROJECT)
        project.self_coding_enabled = True
        project.web_intake_mode = "both"
        db.session.commit()
        self.submitter = self.base_coder_user
        self.other = self._get_or_make_user("sc.other.coder@test.local", "ScOther123")
        self.outsider = self._get_or_make_user("sc.outsider@test.local", "ScOutsider123")
        for user in (self.submitter, self.other):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            ))
        db.session.execute(sa.delete(VaAllocations).where(
            VaAllocations.va_allocated_to.in_([self.submitter.user_id, self.other.user_id])
        ))
        db.session.commit()

    def _set_project(self, **values):
        project = db.session.get(VaProjectMaster, self.PROJECT)
        for key, value in values.items():
            setattr(project, key, value)
        db.session.commit()

    def _own_case(self, sid, owner=None, state="ready_for_coding"):
        """A submission with the owner's submitted web intake draft."""
        submission = self._submission(sid)
        db.session.add(VaWebIntakeDraft(
            project_id=self.PROJECT, site_id=self.SITE, form_id=self.FORM_ID,
            user_id=(owner or self.submitter).user_id, unique_id=sid, meta={}, prefill={},
            status="submitted", va_sid=sid,
        ))
        if state != "ready_for_coding":
            set_submission_workflow_state(sid, state, reason="test", by_role="test")
        db.session.commit()
        return submission

    def _allocations(self, sid):
        return db.session.scalars(sa.select(VaAllocations).where(
            VaAllocations.va_sid == sid,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )).all()

    def _hold(self, sid, user):
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()


class CodeThisCaseNowTests(SelfCodingFixture, BaseTestCase):

    def test_pick_project_allocates_the_case_to_its_submitter(self):
        self._set_project(coding_intake_mode="pick_and_choose")
        self._own_case("csc-own")
        result = allocate_own_case(self.submitter, "csc-own")
        self.assertEqual((result.va_sid, result.actiontype), ("csc-own", "vapickcoding"))
        self.assertEqual([a.va_allocated_to for a in self._allocations("csc-own")], [self.submitter.user_id])
        self.assertEqual(get_submission_workflow_state("csc-own"), "coding_in_progress")

    def test_random_project_allocates_it_too(self):
        self._set_project(coding_intake_mode="random_form_allocation")
        self._own_case("csc-own")
        # The plain pick stays refused in a random project: only the own-case path relaxes it.
        with self.assertRaises(AllocationError) as plain:
            allocate_pick_form(self.submitter, "csc-own")
        self.assertIn("does not use pick-and-choose", plain.exception.message)
        result = allocate_own_case(self.submitter, "csc-own")
        self.assertEqual((result.va_sid, result.actiontype), ("csc-own", "vapickcoding"))
        self.assertEqual(len(self._allocations("csc-own")), 1)

    def test_resuming_the_same_case_is_fine(self):
        self._own_case("csc-own")
        allocate_own_case(self.submitter, "csc-own")
        again = allocate_own_case(self.submitter, "csc-own")
        self.assertEqual((again.va_sid, again.actiontype), ("csc-own", "varesumecoding"))
        self.assertEqual(len(self._allocations("csc-own")), 1)

    def test_another_coder_cannot_code_it_now(self):
        self._own_case("csc-own")
        self.assertEqual(get_submission_workflow_state("csc-own"), "ready_for_coding")
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.other, "csc-own")
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (403, "forbidden"))
        self.assertEqual(self._allocations("csc-own"), [])
        self.assertEqual(get_submission_workflow_state("csc-own"), "ready_for_coding")

    def test_a_submitted_draft_of_someone_else_does_not_count(self):
        # A draft the user never submitted (an open one) is no ownership.
        self._submission("csc-open")
        db.session.add(VaWebIntakeDraft(
            project_id=self.PROJECT, site_id=self.SITE, form_id=self.FORM_ID,
            user_id=self.submitter.user_id, unique_id="csc-open", meta={}, prefill={},
            status="superseded", va_sid="csc-open",
        ))
        db.session.commit()
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.submitter, "csc-open")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_a_case_held_by_another_coder_is_refused(self):
        self._own_case("csc-own")
        allocate_pick_form(self.other, "csc-own")  # any coder may take it
        self.assertEqual(len(self._allocations("csc-own")), 1)
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.submitter, "csc-own")
        self.assertEqual(
            (ctx.exception.status_code, ctx.exception.code, ctx.exception.workflow_state),
            (409, "held_by_another", "coding_in_progress"),
        )
        self.assertEqual([a.va_allocated_to for a in self._allocations("csc-own")], [self.other.user_id])

    def test_attachments_or_smartva_pending_is_409_not_ready(self):
        for sid, state in (("csc-sv", "smartva_pending"), ("csc-att", "attachment_sync_pending")):
            self._own_case(sid, state=state)
            self.assertEqual(get_submission_workflow_state(sid), state)
            with self.assertRaises(AllocationError) as ctx:
                allocate_own_case(self.submitter, sid)
            self.assertEqual(
                (ctx.exception.status_code, ctx.exception.code, ctx.exception.workflow_state),
                (409, "not_ready", state),
            )
            self.assertEqual(self._allocations(sid), [])

    def test_a_project_that_is_not_self_coding_refuses(self):
        self._own_case("csc-own")
        self._set_project(self_coding_enabled=False)
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.submitter, "csc-own")
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (403, "forbidden"))
        self.assertEqual(self._allocations("csc-own"), [])

    def test_intake_off_refuses(self):
        self._own_case("csc-own")
        self._set_project(web_intake_mode="off")
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.submitter, "csc-own")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_another_active_allocation_refuses(self):
        self._own_case("csc-own")
        self._submission("csc-elsewhere")
        self._hold("csc-elsewhere", self.submitter)
        self.assertEqual(get_active_coding_allocation(self.submitter.user_id), "csc-elsewhere")
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.submitter, "csc-own")
        self.assertEqual(ctx.exception.code, "allocation_exists")
        self.assertEqual(self._allocations("csc-own"), [])

    def test_unknown_case_is_404(self):
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.submitter, "csc-nothing")
        self.assertEqual(ctx.exception.status_code, 404)


class CodeNowApiTests(SelfCodingFixture, BaseTestCase):

    def _post(self, user, sid, csrf=True):
        g.pop("_login_user", None)
        self._login(str(user.user_id))
        return self.client.post(
            f"/api/v1/coding/submissions/{sid}/code-now",
            headers=self._csrf_headers() if csrf else {},
        )

    def test_code_now_replies_the_allocation(self):
        self._own_case("csc-own")
        response = self._post(self.submitter, "csc-own")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json(), {"va_sid": "csc-own", "actiontype": "vapickcoding"})
        self.assertEqual(self._post(self.submitter, "csc-own").status_code, 200)

    def test_errors_carry_a_code_and_not_ready_the_state(self):
        self._own_case("csc-sv", state="smartva_pending")
        pending = self._post(self.submitter, "csc-sv")
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(
            pending.get_json()["code"], "not_ready")
        self.assertEqual(pending.get_json()["workflow_state"], "smartva_pending")
        self.assertTrue(pending.get_json()["error"])

        self._own_case("csc-own")
        refused = self._post(self.other, "csc-own")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "forbidden"))
        missing = self._post(self.submitter, "csc-nothing")
        self.assertEqual((missing.status_code, missing.get_json()["code"]), (404, "not_found"))

    def test_a_transition_lost_to_a_concurrent_take_is_a_409_and_leaves_no_trace(self):
        from unittest import mock

        from app.services.workflow.transitions import WorkflowTransitionError

        self._own_case("csc-own")
        count = self.submitter.vacode_formcount
        with mock.patch(
            "app.services.coder_workflow_service.mark_coding_started",
            side_effect=WorkflowTransitionError("not ready_for_coding"),
        ):
            with self.assertRaises(AllocationError) as ctx:
                allocate_own_case(self.submitter, "csc-own")
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "not_available"))
        self.assertEqual(ctx.exception.workflow_state, "ready_for_coding")
        self.assertEqual(self._allocations("csc-own"), [])
        self.assertEqual(db.session.get(type(self.submitter), self.submitter.user_id).vacode_formcount, count)

    def test_a_browser_post_without_the_csrf_token_is_refused(self):
        self._own_case("csc-own")
        response = self._post(self.submitter, "csc-own", csrf=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "csrf_failed")
        self.assertEqual(self._allocations("csc-own"), [])

    def test_a_user_without_the_coder_role_is_refused(self):
        self._own_case("csc-own")
        response = self._post(self.outsider, "csc-own")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._allocations("csc-own"), [])


class CoderReleaseTests(SelfCodingFixture, BaseTestCase):

    def test_release_returns_the_case_to_the_pool_audited_under_the_coder(self):
        self._own_case("csc-own")
        allocate_own_case(self.submitter, "csc-own")
        self.assertEqual(get_submission_workflow_state("csc-own"), "coding_in_progress")
        uid = self.submitter.user_id
        db.session.add_all([
            VaInitialAssessments(
                va_sid="csc-own", va_iniassess_by=uid, va_immediate_cod="R99",
                va_antecedent_cod="R99", va_iniassess_status=VaStatuses.active,
            ),
            VaNarrativeAssessment(
                va_sid="csc-own", va_nqa_by=uid, va_nqa_length=2, va_nqa_pos_symptoms=2,
                va_nqa_neg_symptoms=1, va_nqa_chronology=1, va_nqa_doc_review=1,
                va_nqa_comorbidity=1, va_nqa_score=8, va_nqa_status=VaStatuses.active,
            ),
            VaSocialAutopsyAnalysis(
                va_sid="csc-own", va_saa_by=uid, va_saa_remark="x",
                va_saa_status=VaStatuses.active,
            ),
        ])
        db.session.commit()
        self.assertEqual(release_own_coding_allocation(self.submitter), "csc-own")
        # Every reverted row is audited under the coder, not the system.
        reverted = db.session.scalars(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == "csc-own",
            VaSubmissionsAuditlog.va_audit_action.like("%reverted due to coder release"),
        )).all()
        self.assertEqual(len(reverted), 3)
        for audit in reverted:
            self.assertEqual((audit.va_audit_byrole, audit.va_audit_by), ("vacoder", uid))
        self.assertEqual(self._allocations("csc-own"), [])
        self.assertEqual(get_submission_workflow_state("csc-own"), "ready_for_coding")
        self.assertIsNone(get_active_coding_allocation(self.submitter.user_id))
        row = db.session.scalar(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == "csc-own",
            VaSubmissionsAuditlog.va_audit_action == "va_allocation_released_by_coder",
        ))
        self.assertIsNotNone(row)
        self.assertEqual((row.va_audit_byrole, row.va_audit_by), ("vacoder", self.submitter.user_id))
        # Any coder may now take it.
        self.assertEqual(allocate_pick_form(self.other, "csc-own").va_sid, "csc-own")

    def test_a_transition_lost_during_release_is_a_409_and_changes_nothing(self):
        from unittest import mock

        from app.services.workflow.transitions import WorkflowTransitionError

        self._own_case("csc-own")
        allocate_own_case(self.submitter, "csc-own")
        with mock.patch(
            "app.services.coding_allocation_service.reset_incomplete_first_pass",
            side_effect=WorkflowTransitionError("moved"),
        ):
            with self.assertRaises(AllocationError) as ctx:
                release_own_coding_allocation(self.submitter)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.workflow_state, "coding_in_progress")
        self.assertEqual(len(self._allocations("csc-own")), 1)

    def test_release_takes_the_first_when_two_active_rows_exist(self):
        self._own_case("csc-own")
        allocate_own_case(self.submitter, "csc-own")
        self._hold("csc-own", self.submitter)  # a stray second active row
        self.assertEqual(release_own_coding_allocation(self.submitter), "csc-own")

    def test_release_with_nothing_held_is_refused(self):
        self._own_case("csc-own")
        with self.assertRaises(AllocationError) as ctx:
            release_own_coding_allocation(self.submitter)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "no_allocation"))
        self.assertEqual(get_submission_workflow_state("csc-own"), "ready_for_coding")

    def test_only_the_own_allocation_is_released(self):
        self._own_case("csc-own")
        self._own_case("csc-theirs", owner=self.other)
        allocate_own_case(self.other, "csc-theirs")
        with self.assertRaises(AllocationError):
            release_own_coding_allocation(self.submitter)
        self.assertEqual(len(self._allocations("csc-theirs")), 1)

    def test_the_timeout_release_stays_the_systems(self):
        from datetime import datetime, timedelta

        from app.services.coding_allocation_service import release_stale_coding_allocations

        self._own_case("csc-own")
        allocate_own_case(self.submitter, "csc-own")
        record = self._allocations("csc-own")[0]
        record.va_allocation_createdat = datetime.now() - timedelta(hours=3)
        db.session.commit()
        self.assertEqual(release_stale_coding_allocations(timeout_hours=1) >= 1, True)
        row = db.session.scalar(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == "csc-own",
            VaSubmissionsAuditlog.va_audit_action == "va_allocation_released_due_to_timeout",
        ))
        self.assertIsNotNone(row)
        self.assertEqual((row.va_audit_byrole, row.va_audit_by), ("vasystem", None))

    def test_release_api(self):
        self._own_case("csc-own")
        allocate_own_case(self.submitter, "csc-own")
        g.pop("_login_user", None)
        self._login(str(self.submitter.user_id))
        refused = self.client.post("/api/v1/coding/allocation/release")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.get_json()["code"], "csrf_failed")
        self.assertEqual(len(self._allocations("csc-own")), 1)
        response = self.client.post("/api/v1/coding/allocation/release", headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json(), {"va_sid": "csc-own", "workflow_state": "ready_for_coding"})
        again = self.client.post("/api/v1/coding/allocation/release", headers=self._csrf_headers())
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "no_allocation"))


class AdminSelfCodingSettingTests(BaseTestCase):
    PROJECT = "SCADM1"

    def _put(self, project_id, **body):
        self._login(self.base_admin_id)
        return self.client.put(
            f"/admin/api/projects/{project_id}", json=body, headers=self._csrf_headers()
        )

    def _post_project(self, **body):
        self._login(self.base_admin_id)
        return self.client.post(
            "/admin/api/projects",
            json={"project_id": self.PROJECT, "project_code": self.PROJECT,
                  "project_name": "Self Coding Admin", "project_nickname": "ScAdmin", **body},
            headers=self._csrf_headers(),
        )

    def test_create_with_intake_on_and_serialise(self):
        response = self._post_project(web_intake_mode="direct", self_coding_enabled=True)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertIs(response.get_json()["project"]["self_coding_enabled"], True)
        self.assertIs(db.session.get(VaProjectMaster, self.PROJECT).self_coding_enabled, True)

    def test_default_is_off(self):
        response = self._post_project()
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertIs(response.get_json()["project"]["self_coding_enabled"], False)

    def test_create_refuses_self_coding_with_intake_off(self):
        response = self._post_project(web_intake_mode="off", self_coding_enabled=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("web intake", response.get_json()["error"])
        self.assertIsNone(db.session.get(VaProjectMaster, self.PROJECT))

    def test_update_refuses_turning_it_on_while_intake_is_off(self):
        self.assertEqual(self._post_project().status_code, 201)
        response = self._put(self.PROJECT, self_coding_enabled=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("web intake", response.get_json()["error"])
        self.assertIs(db.session.get(VaProjectMaster, self.PROJECT).self_coding_enabled, False)
        # Both in one request is fine.
        ok = self._put(self.PROJECT, self_coding_enabled=True, web_intake_mode="both")
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertIs(ok.get_json()["project"]["self_coding_enabled"], True)

    def test_update_refuses_intake_off_while_self_coding_is_on(self):
        self.assertEqual(self._post_project(web_intake_mode="both", self_coding_enabled=True).status_code, 201)
        response = self._put(self.PROJECT, web_intake_mode="off")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.session.get(VaProjectMaster, self.PROJECT).web_intake_mode, "both")
        # Turning self-coding off in the same request lets intake go off.
        ok = self._put(self.PROJECT, web_intake_mode="off", self_coding_enabled=False)
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(ok.get_json()["project"]["web_intake_mode"], "off")

    def test_a_non_boolean_is_refused(self):
        self.assertEqual(self._post_project(web_intake_mode="both").status_code, 201)
        response = self._put(self.PROJECT, self_coding_enabled="yes")
        self.assertEqual(response.status_code, 400)
        self.assertIs(db.session.get(VaProjectMaster, self.PROJECT).self_coding_enabled, False)
