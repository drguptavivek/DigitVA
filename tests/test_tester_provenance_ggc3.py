"""coding_tester output is tester output, never the case's result (digitva-ggc3).

Security review 10 #12. Policy: docs/policy/access-control-model.md,
``coding_tester``: a tester's final COD (or not-codeable report) is stored
deactive with ``is_tester``, the case returns to ``ready_for_coding`` for a
real coder, and tester output is left out of every coder, DM and burndown
count and never makes a case reviewer-eligible. A user who is both coder and
tester there codes as a coder; demo practice is unaffected.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MasIcd1020192,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
)
from app.services.authz import codes_as_tester, invalidate
from app.services.coder_dashboard_service import (
    get_coder_completed_history,
    get_coder_output_summary,
)
from app.services.coder_workflow_service import (
    allocate_random_form,
    mark_reviewer_eligible_after_recode_window_submissions,
)
from app.services.final_cod_authority_service import (
    get_active_recode_episode,
    get_authoritative_final_assessment,
    start_recode_episode,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    TRANSITION_TESTER_CODING_RETURNED,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from tests.base import BaseTestCase

_COD = "I24-Other acute ischaemic heart diseases"


class TesterProvenanceTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}31"
    SID_PREFIX = "uuid:ggc3-"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID, odk_form_id="GGC3_FORM", odk_project_id="93",
                form_type="WHO_2022_VA", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.merge(MasIcd1020192(
            code="I24", title="Other acute ischaemic heart diseases",
            node_type="category", semantic_level="three_character", sort_order=1,
            parent_code=None, chapter_code="IX",
            chapter_title="Diseases of the circulatory system",
            block_code="I20-I25", block_title="Ischaemic heart diseases",
            three_character_code="I24",
            three_character_title="Other acute ischaemic heart diseases",
            has_children=False, is_leaf=True, is_three_character_code=True,
            is_detailed_code=False, is_coding_selectable=True, sex_selectable="both",
            age_group_selectable="all", policy_status="unreviewed",
            source_version="ICD-10-2019", source_path="test", is_active=True,
            created_at=now, updated_at=now,
        ))
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == cls.BASE_PROJECT_ID,
            VaProjectSites.site_id == cls.BASE_SITE_ID,
        ))
        cls.coder = cls.base_coder_user
        cls.tester = cls._make_user(f"ggc3.tester.{uuid.uuid4().hex[:6]}@test.local", "Tester123")
        cls.both = cls._make_user(f"ggc3.both.{uuid.uuid4().hex[:6]}@test.local", "Both123")
        for user, role in (
            (cls.tester, VaAccessRoles.coding_tester),
            (cls.both, VaAccessRoles.coding_tester),
            (cls.both, VaAccessRoles.coder),
        ):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id, notes="ggc3",
                grant_status=VaStatuses.active,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        # Only this class's submissions are open for coding in the base pair,
        # so a random allocation can only pick what a test seeded.
        db.session.execute(sa.update(VaAllocations).where(
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_allocation_for == VaAllocation.coding,
        ).values(va_allocation_status=VaStatuses.deactive))
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.workflow_state == WORKFLOW_READY_FOR_CODING,
        ).values(workflow_state="screening_pending"))
        db.session.commit()
        for user in (self.coder, self.tester, self.both):
            invalidate(user.user_id)

    # -- fixtures ----------------------------------------------------------

    def _submission(self, name, state=WORKFLOW_READY_FOR_CODING):
        sid = f"{self.SID_PREFIX}{name}-{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="Collector",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English",
            va_deceased_age=60, va_deceased_gender="Male",
            va_summary=[], va_catcount={},
            va_category_list=["vademographicdetails", "vacodassessment"],
        )
        db.session.add(submission)
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state,
            workflow_reason="test_seed", workflow_updated_by_role="vasystem",
        ))
        db.session.commit()
        ensure_active_payload_version(
            submission, payload_data={}, source_updated_at=now, created_by_role="vasystem",
        )
        db.session.commit()
        return sid

    def _open_session(self, sid, user):
        """An allocation, a Step 1 row and coding_in_progress, as a coder holds them."""
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        db.session.add(VaInitialAssessments(
            va_sid=sid, va_iniassess_by=user.user_id, va_immediate_cod="I24",
            va_antecedent_cod="I24", va_iniassess_status=VaStatuses.active,
        ))
        self._workflow(sid).workflow_state = WORKFLOW_CODING_IN_PROGRESS
        db.session.commit()

    def _workflow(self, sid):
        return db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == sid)
        )

    def _post_final(self, sid, user):
        self._login(str(user.user_id))
        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={"va_conclusive_cod": _COD, "va_finassess_remark": "", "va_save_assessment": "1"},
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        self.assertTrue(response.get_json()["success"])

    def _code(self, sid, user):
        self._open_session(sid, user)
        self._post_final(sid, user)

    def _state(self, sid):
        db.session.expire_all()
        return self._workflow(sid).workflow_state

    def _finals(self, sid, user):
        return db.session.scalars(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == sid, VaFinalAssessments.va_finassess_by == user.user_id,
        )).all()

    def _transitions(self, sid):
        return set(db.session.scalars(sa.select(VaSubmissionWorkflowEvent.transition_id).where(
            VaSubmissionWorkflowEvent.va_sid == sid,
        )).all())

    def _allocation_status(self, sid, user):
        return db.session.scalar(sa.select(VaAllocations.va_allocation_status).where(
            VaAllocations.va_sid == sid, VaAllocations.va_allocated_to == user.user_id,
        ))

    # -- who is a tester ---------------------------------------------------

    def test_tester_lane_is_decided_by_authz(self):
        sid = self._submission("lane")
        self.assertTrue(codes_as_tester(self.tester, sid))
        self.assertFalse(codes_as_tester(self.coder, sid))
        # Both grants on the pair: codes as a coder.
        self.assertFalse(codes_as_tester(self.both, sid))
        # No grant at all (admin) is never a tester.
        self.assertFalse(codes_as_tester(self.base_admin_user, sid))

    def test_demo_training_submission_is_not_tester_output(self):
        sid = self._submission("demo")
        self.assertTrue(codes_as_tester(self.tester, sid))
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.demo_training_enabled = True
        db.session.commit()
        invalidate(self.tester.user_id)
        # The demo-training virtual grant reaches it: demo, not tester.
        self.assertFalse(codes_as_tester(self.tester, sid))

    # -- tester finalize -----------------------------------------------------

    def test_tester_final_returns_the_case_to_the_pool(self):
        sid = self._submission("final")
        with mock.patch("app.services.coder_cod_service.bust_coder_dashboard_cache") as bust:
            self._code(sid, self.tester)
        bust.assert_called_once_with(self.tester.user_id)

        self.assertEqual(self._state(sid), WORKFLOW_READY_FOR_CODING)
        [final] = self._finals(sid, self.tester)
        self.assertTrue(final.is_tester)
        self.assertEqual(final.va_finassess_status, VaStatuses.deactive)
        self.assertIsNone(get_authoritative_final_assessment(sid))
        initial = db.session.scalar(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid,
            VaInitialAssessments.va_iniassess_by == self.tester.user_id,
        ))
        self.assertEqual(initial.va_iniassess_status, VaStatuses.deactive)
        self.assertEqual(self._allocation_status(sid, self.tester), VaStatuses.deactive)
        transitions = self._transitions(sid)
        self.assertIn(TRANSITION_TESTER_CODING_RETURNED, transitions)
        self.assertNotIn("coder_finalized", transitions)
        # The tester's labelled history row still opens read-only.
        self._login(str(self.tester.user_id))
        response = self.client.get(f"/vaform/{sid}/vausernote?action=vacode&actiontype=vaview")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])

        # Positive control: a real coder now allocates and finalizes normally.
        result = allocate_random_form(self.coder, project_id=self.BASE_PROJECT_ID)
        self.assertEqual(result.va_sid, sid)
        db.session.add(VaInitialAssessments(
            va_sid=sid, va_iniassess_by=self.coder.user_id, va_immediate_cod="I24",
            va_antecedent_cod="I24", va_iniassess_status=VaStatuses.active,
        ))
        db.session.commit()
        self._post_final(sid, self.coder)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_FINALIZED)
        [real] = self._finals(sid, self.coder)
        self.assertFalse(real.is_tester)
        self.assertEqual(real.va_finassess_status, VaStatuses.active)
        self.assertEqual(get_authoritative_final_assessment(sid).va_finassess_id, real.va_finassess_id)

    def test_user_with_both_grants_codes_as_a_coder(self):
        sid = self._submission("both")
        self._code(sid, self.both)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_FINALIZED)
        [final] = self._finals(sid, self.both)
        self.assertFalse(final.is_tester)
        self.assertEqual(final.va_finassess_status, VaStatuses.active)

    def test_tester_never_overwrites_a_coders_result(self):
        sid = self._submission("recode")
        self._code(sid, self.coder)
        real = get_authoritative_final_assessment(sid)
        self.assertIsNotNone(real)
        # An admin override reopens it with a recode episode; a tester takes it.
        start_recode_episode(sid, self.base_admin_user.user_id, base_final_assessment=real)
        self._workflow(sid).workflow_state = WORKFLOW_READY_FOR_CODING
        db.session.commit()
        self._code(sid, self.tester)

        self.assertEqual(self._state(sid), WORKFLOW_READY_FOR_CODING)
        db.session.refresh(real)
        self.assertEqual(real.va_finassess_status, VaStatuses.active)
        self.assertEqual(get_authoritative_final_assessment(sid).va_finassess_id, real.va_finassess_id)
        self.assertIsNotNone(get_active_recode_episode(sid))

    def test_tester_not_codeable_is_not_a_result(self):
        sid = self._submission("nc")
        self._open_session(sid, self.tester)
        self._login(str(self.tester.user_id))
        with mock.patch("app.services.coder_cod_service.sync_not_codeable_review_state") as odk:
            response = self.client.post(
                f"/vaform/{sid}/vacoderreview?action=vacode&actiontype=vastartcoding",
                data={"va_creview_reason": "no_info", "va_creview_other": ""},
                headers={**self._csrf_headers(), "HX-Request": "true"},
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        odk.assert_not_called()
        self.assertEqual(self._state(sid), WORKFLOW_READY_FOR_CODING)
        review = db.session.scalar(sa.select(VaCoderReview).where(VaCoderReview.va_sid == sid))
        self.assertTrue(review.is_tester)
        self.assertEqual(review.va_creview_status, VaStatuses.deactive)
        self.assertEqual(self._allocation_status(sid, self.tester), VaStatuses.deactive)

    # -- counts --------------------------------------------------------------

    def test_coder_dashboard_counts_leave_tester_output_out(self):
        tested, coded = self._submission("dash-t"), self._submission("dash-c")
        with mock.patch("app.services.coder_dashboard_service._cached_dashboard_project_value",
                        side_effect=lambda _u, _k, _p, compute: compute()), \
             mock.patch("app.services.coder_dashboard_service._cached_dashboard_value",
                        side_effect=lambda _u, _k, _f, compute: compute()):
            self._code(coded, self.coder)
            self._code(tested, self.tester)
            self.assertGreaterEqual(get_coder_output_summary(self.coder.user_id)["completed"], 1)
            self.assertEqual(get_coder_output_summary(self.tester.user_id)["completed"], 0)
            # The tester keeps their own test history, labelled.
            history = get_coder_completed_history(self.tester, [self.FORM_ID])
            self.assertEqual([(r["va_sid"], r["is_tester"]) for r in history], [(tested, True)])

    def test_reviewer_sweep_skips_tester_output(self):
        tested, coded = self._submission("sweep-t"), self._submission("sweep-c")
        self._code(coded, self.coder)
        self._code(tested, self.tester)
        later = datetime.now(UTC) + timedelta(hours=25)
        mark_reviewer_eligible_after_recode_window_submissions(now=later)
        self.assertEqual(self._state(coded), WORKFLOW_REVIEWER_ELIGIBLE)
        self.assertEqual(self._state(tested), WORKFLOW_READY_FOR_CODING)

    def test_dm_coder_output_burndown_and_utilization_leave_tester_out(self):
        tested, coded = self._submission("kpi-t"), self._submission("kpi-c")
        self._code(coded, self.coder)
        self._code(tested, self.tester)
        # The tester holds a live session again: utilization must not count it.
        self._open_session(self._submission("kpi-live"), self.tester)

        dm = self._make_user(f"ggc3.dm.{uuid.uuid4().hex[:6]}@test.local", "Dm123456")
        db.session.add(VaUserAccessGrants(
            user_id=dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )),
            notes="ggc3 dm", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(dm.user_id))

        def kpi(path):
            with mock.patch("app.routes.api.dm_kpi.dm_kpi_coders.cached_kpi",
                            side_effect=lambda _k, compute, *a, **kw: compute()), \
                 mock.patch("app.routes.api.dm_kpi.dm_kpi_burndown.cached_kpi",
                            side_effect=lambda _k, compute, *a, **kw: compute()):
                response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
            return response.get_json()

        output_coders = {c["coder_id"] for c in kpi("coders/output")["per_coder"]}
        self.assertIn(str(self.coder.user_id), output_coders)
        self.assertNotIn(str(self.tester.user_id), output_coders)

        burndown_coders = {str(c["coder_id"]) for c in kpi("burndown/")["c16_per_coder"]}
        self.assertIn(str(self.coder.user_id), burndown_coders)
        self.assertNotIn(str(self.tester.user_id), burndown_coders)

        self.assertEqual(kpi("coders/utilization")["active_count"], 0)
        # Positive control: a coder's live session is counted.
        self._open_session(self._submission("kpi-live-c"), self.coder)
        self.assertEqual(kpi("coders/utilization")["active_count"], 1)

    def test_dm_workflow_panels_leave_tester_runs_out(self):
        tested, coded = self._submission("wf-t"), self._submission("wf-c")
        self._code(coded, self.coder)
        self._code(tested, self.tester)
        events = db.session.execute(sa.select(
            VaSubmissionWorkflowEvent.va_sid, VaSubmissionWorkflowEvent.actor_user_id,
        )).all()
        tester_events = [e for e in events if e.actor_user_id == self.tester.user_id]
        coder_events = [e for e in events if e.actor_user_id == self.coder.user_id]
        self.assertTrue(tester_events)
        self.assertTrue(coder_events)

        dm = self._make_user(f"ggc3.dmwf.{uuid.uuid4().hex[:6]}@test.local", "Dm123456")
        db.session.add(VaUserAccessGrants(
            user_id=dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=self.BASE_PROJECT_ID,
            notes="ggc3 dm", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(dm.user_id))
        with mock.patch("app.routes.api.dm_kpi.dm_kpi_workflow.cached_kpi",
                        side_effect=lambda _k, compute, *a, **kw: compute()):
            daily = self.client.get("/api/v1/analytics/dm-kpi/workflow/daily-transitions").get_json()
            # state-velocity applies the same tester-run predicate.
            self.assertEqual(
                self.client.get("/api/v1/analytics/dm-kpi/workflow/state-velocity").status_code, 200
            )

        total = sum(day["total"] for day in daily["days"])
        self.assertEqual(total, len(events) - len(tester_events))
