"""Confirmed-duplicate web cases leave every coding reader (digitva-vzk.7).

Decisions 10 and 14 of .tasks/2026-09-28-interviewer-worklist.md; policy:
docs/policy/coding-workflow-state-machine.md, "Confirmed duplicate cases".
Implementation: ``app.services.duplicate_exclusion``; the path-coverage guard
is tests/test_duplicate_exclusion_coverage.py.

Each reader test is presence first: the submission is visible before the
case is confirmed a duplicate, gone after, and back after a supervisor
reopens the case -- so no test passes because the fixture was never seen.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import case_transition_service as cases
from app.services.coder_workflow_service import (
    AllocationError,
    _available_submission_filters,
    admin_override_to_recode,
)
from app.services.data_management_service import dm_submissions_page
from app.services.duplicate_exclusion import (
    DUPLICATE_MESSAGE,
    is_confirmed_duplicate,
    not_confirmed_duplicate_condition,
    not_confirmed_duplicate_sql,
)
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.sitepi_reporting_service import get_project_workflow_kpis
from app.services.smartva_service import pending_smartva_sids
from app.services.workflow.state_store import get_submission_workflow_state
from tests.base import BaseTestCase


class ConfirmedDuplicateExclusionTests(BaseTestCase):
    PROJECT_ID = "DUPX01"
    SITE_ID = "DX01"
    FORM_ID = "DUPX01DX0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name=cls.PROJECT_ID,
            project_nickname=cls.PROJECT_ID, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name=cls.SITE_ID, site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_DUPX", odk_project_id="7", form_type="WHO VA 2022",
            form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        cls.ian = cls._get_or_make_user("dupx.ian@test.local", "Duplicate123")
        # A data manager supervises the project's cases and may confirm a
        # coded one (decisions 10, 14).
        cls.dana = cls._get_or_make_user("dupx.dana@test.local", "Duplicate123")
        cls.coder = cls._get_or_make_user("dupx.coder@test.local", "Duplicate123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.dana.user_id, role=VaAccessRoles.data_manager, notes="dupx",
            grant_status=VaStatuses.active, scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
        ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _case(self, workflow_state):
        """A submitted web case whose submission is in *workflow_state*."""
        sid = f"uuid:dupx-{uuid.uuid4()}"
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="dupx", va_odk_reviewstate="reviewed",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language="English", va_deceased_age=50, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=workflow_state))
        number = db.session.scalar(sa.select(sa.func.coalesce(sa.func.max(VaDeathRegister.death_number), 0))) + 1
        case = cases.open_case(VaDeathRegister(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_number=number,
            unique_id=f"DUPX-{uuid.uuid4().hex[:12]}", deceased_name="Asha Devi",
            deceased_sex="female", date_of_death=date.today() - timedelta(days=5),
            registered_by=self.ian.user_id, source="register",
        ), actor=self.ian)
        case.va_sid = sid
        cases.transition(case, "in_progress", actor=self.ian, action="test")
        cases.transition(case, "submitted", actor=self.ian, action="test")
        # A second live case to be the kept original.
        kept_number = number + 1
        self.kept = cases.open_case(VaDeathRegister(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_number=kept_number,
            unique_id=f"DUPX-{uuid.uuid4().hex[:12]}", deceased_name="Asha Devi",
            deceased_sex="female", date_of_death=date.today() - timedelta(days=5),
            registered_by=self.ian.user_id, source="register",
        ), actor=self.ian)
        db.session.commit()
        return case

    def _confirm(self, case):
        # The data manager's own flag is confirmed at once.
        cases.flag_case(case, actor=self.dana, kind="duplicate", duplicate_of=self.kept, reason="same")
        db.session.commit()
        self.assertEqual(case.status, "duplicate")

    def _reopen(self, case):
        cases.reopen(case, actor=self.dana, reason="not the same death")
        db.session.commit()
        self.assertEqual(case.status, "submitted")

    def _assert_excluded_while_confirmed(self, case, visible):
        """*visible()* is true before confirmation, false after, true after reopen."""
        self.assertTrue(visible(), "the submission must be visible before confirmation")
        self._confirm(case)
        self.assertFalse(visible(), "a confirmed duplicate must be excluded")
        self._reopen(case)
        self.assertTrue(visible(), "a reopened case must come back")

    # ── the predicate ──────────────────────────────────────────────────────

    def test_the_predicate_matches_only_confirmed_duplicates(self):
        case = self._case("ready_for_coding")
        orm = sa.select(VaSubmissions.va_sid).where(
            VaSubmissions.va_sid == case.va_sid,
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        )
        raw = sa.text(
            "SELECT s.va_sid FROM va_submissions s WHERE s.va_sid = :sid AND "
            + not_confirmed_duplicate_sql("s.va_sid")
        )

        def visible():
            return (
                db.session.scalar(orm) == case.va_sid
                and db.session.scalar(raw, {"sid": case.va_sid}) == case.va_sid
                and not is_confirmed_duplicate(case.va_sid)
            )

        self._assert_excluded_while_confirmed(case, visible)
        # A pending (unconfirmed) flag excludes nothing.
        cases.flag_case(case, actor=self.ian, kind="duplicate", duplicate_of=self.kept)
        db.session.commit()
        self.assertEqual(case.pending_flag, "duplicate")
        self.assertTrue(visible())

    def test_a_submission_with_no_case_always_passes(self):
        self.assertFalse(is_confirmed_duplicate("uuid:no-such-case"))

    # ── readers ────────────────────────────────────────────────────────────

    def test_the_coding_pool_excludes_a_confirmed_duplicate(self):
        case = self._case("ready_for_coding")

        def visible():
            return case.va_sid in db.session.scalars(
                sa.select(VaSubmissions.va_sid)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(*_available_submission_filters([self.FORM_ID]))
            ).all()

        self._assert_excluded_while_confirmed(case, visible)

    def test_smartva_generation_skips_a_confirmed_duplicate(self):
        case = self._case("smartva_pending")
        self._assert_excluded_while_confirmed(
            case, lambda: case.va_sid in pending_smartva_sids(self.FORM_ID)
        )

    def test_the_data_manager_grid_and_exports_exclude_a_confirmed_duplicate(self):
        case = self._case("ready_for_coding")

        def visible():
            page = dm_submissions_page(self.dana, per_page=100, search=case.va_sid)
            return case.va_sid in {row["va_sid"] for row in page["data"]}

        self._assert_excluded_while_confirmed(case, visible)

    def test_reporting_counts_exclude_a_confirmed_duplicate(self):
        case = self._case("reviewer_finalized")
        before = get_project_workflow_kpis(self.PROJECT_ID)

        def counted():
            now = get_project_workflow_kpis(self.PROJECT_ID)
            return (
                now["total_submissions"] == before["total_submissions"]
                and now["current_state_kpis"]["reviewer_finalized"]
                == before["current_state_kpis"]["reviewer_finalized"]
            )

        self.assertGreaterEqual(before["current_state_kpis"]["reviewer_finalized"], 1)
        self._assert_excluded_while_confirmed(case, counted)

    def test_a_named_submission_is_refused_while_confirmed(self):
        # ready_for_coding is refused for its state first: the duplicate
        # check is what answers only after confirmation.
        case = self._case("ready_for_coding")
        with self.assertRaisesRegex(AllocationError, "Only coder-finalized"):
            admin_override_to_recode(self.dana, case.va_sid)
        self._confirm(case)
        with self.assertRaises(AllocationError) as refused:
            admin_override_to_recode(self.dana, case.va_sid)
        self.assertEqual((str(refused.exception), refused.exception.status_code),
                         (DUPLICATE_MESSAGE, 409))

    # ── allocation revocation and finalized duplicates ─────────────────────

    def _allocate(self, case, purpose):
        allocation = VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=case.va_sid,
            va_allocated_to=self.coder.user_id, va_allocation_for=purpose,
        )
        db.session.add(allocation)
        db.session.commit()
        return allocation

    def test_confirming_revokes_an_active_coding_allocation(self):
        case = self._case("coding_in_progress")
        allocation = self._allocate(case, VaAllocation.coding)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.active)

        self._confirm(case)
        db.session.refresh(allocation)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.deactive)
        # Released like a timed-out first pass: back to the pool state.
        self.assertEqual(get_submission_workflow_state(case.va_sid), "ready_for_coding")

        # Undo: coding resumes from the state it was in.
        self._reopen(case)
        self.assertEqual(get_submission_workflow_state(case.va_sid), "ready_for_coding")
        self.assertFalse(is_confirmed_duplicate(case.va_sid))

    def test_confirming_revokes_an_active_reviewer_allocation(self):
        case = self._case("reviewer_coding_in_progress")
        allocation = self._allocate(case, VaAllocation.reviewing)

        self._confirm(case)
        db.session.refresh(allocation)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.deactive)
        self.assertEqual(get_submission_workflow_state(case.va_sid), "reviewer_eligible")

    def test_a_finalized_duplicate_keeps_its_coding(self):
        case = self._case("reviewer_finalized")
        self._confirm(case)
        # No new state, no reuse of not_codeable_by_data_manager (decision 14).
        self.assertEqual(get_submission_workflow_state(case.va_sid), "reviewer_finalized")
        self._reopen(case)
        self.assertEqual(get_submission_workflow_state(case.va_sid), "reviewer_finalized")
