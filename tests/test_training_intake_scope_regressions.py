"""Regressions of security-audit run-7 leads 6-9 (.tasks/security-audit-run-7/NEEDS-VALIDATION.md).

Lead 6 (digitva-l9dp.6): a closed training session's draft, submission
revision and answers read are refused; a revoked interviewer's submitted case
is neither revised nor read (an unsent real draft stays, digitva-9xn9.22).
Lead 7 (.7): reviewer initial/finalize hold the training scope. Lead 8 (.8):
a closed session's reviewer_data_manager keeps report access (owner
decision). Lead 9 (.9): the social autopsy remark is bounded. The shared
fixtures are reused by subclassing; inherited tests are switched off.
"""
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from unittest import mock

from app import db
from app.models import (
    MasTrainingSession,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaSiteMaster,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaProjectSites,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import training_demo_service as svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.workflow.state_store import get_submission_workflow_state
from tests import test_training_scope as tts
from tests.routes import test_interview_revisions_api as rev
from tests.routes import test_social_autopsy_analysis as saa
from tests.services import test_training_report as rep

API = "/api/v1/intake"
ICD10_VALUE = "I24 Other acute ischaemic heart diseases"


def only_own_tests(cls):
    """Switch off the tests a fixture class inherits."""
    for name in dir(cls):
        if name.startswith("test_") and name not in cls.__dict__:
            setattr(cls, name, None)
    return cls


def _answers(**over):
    return {
        "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
        "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
        "narr_language": "english", **over,
    }


# ---------------------------------------------------------------------------
# Lead 6: web intake after a session closes / a grant is revoked
# ---------------------------------------------------------------------------

@only_own_tests
class Lead6ClosedTrainingSessionTests(tts.TrainingScopeBase):
    """Trainee of closed S001, still active in S002."""

    roles = ("death_reporter", "interviewer")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = svc.create_training_session("Training two", cls.admin, source_form_id=rep.SRC_FORM)
        db.session.commit()

    def setUp(self):
        super().setUp()
        svc.add_participant("S002", self.trainee.email, list(self.roles), self.admin)
        db.session.commit()
        self._login(str(self.trainee.user_id))
        self.site = svc._web_form().site_id
        # Keep later tests' S001 usable.
        self.addCleanup(lambda: svc.reopen_training_session("S001", self.admin))

    def _start_draft(self):
        death_id = self._training_death()
        response = self.post("/api/v1/intake/drafts?training=1", {
            "project_id": "TRN01", "site_id": self.site, "death_id": death_id})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["draft"]["draft_id"]

    def _complete(self, draft_id):
        return self.post(f"/api/v1/intake/drafts/{draft_id}/submit?training=1", {
            "completion": {"valid": True, "issues": [], "data": _answers()}})

    def _submitted_s001_case(self):
        draft_id = self._start_draft()
        done = self._complete(draft_id)
        self.assertIn(done.status_code, (200, 201), done.get_json())
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        db.session.refresh(draft)
        self.assertEqual(draft.status, "submitted")  # the subject exists
        self.assertIsNotNone(draft.va_sid)
        return draft.va_sid

    def _close_s001(self):
        svc.close_training_session("S001", self.admin)
        self.assertEqual(db.session.get(MasTrainingSession, self.first["training_session_id"]).status, "closed")
        # Present: the trainee still holds a live training right through S002 ...
        self.assertEqual(self.get("/api/v1/intake/drafts?training=1").status_code, 200)

    def test_closed_session_trainee_cannot_submit_an_s001_draft(self):
        draft_id = self._start_draft()
        self._close_s001()
        response = self._complete(draft_id)
        self.assertIn(response.status_code, (403, 404, 409), (response.status_code, response.get_json()))

    def test_closed_session_trainee_cannot_revise_an_s001_submission(self):
        va_sid = self._submitted_s001_case()
        self._close_s001()
        text = json.dumps(_answers(Id10017="Changed"), separators=(",", ":"))
        response = self.post(f"/api/v1/intake/submissions/{va_sid}/revisions?training=1", {
            "reason_code": "interviewer_correction", "draft": {}, "completion": {"valid": True, "issues": []},
            "answers_json": text, "answers_sha256": hashlib.sha256(text.encode()).hexdigest()})
        self.assertIn(response.status_code, (403, 404, 409), (response.status_code, response.get_json()))

    def test_active_trainee_reads_own_training_submission_with_the_flag(self):
        va_sid = self._submitted_s001_case()
        response = self.get(f"/api/v1/va/{va_sid}/workspace?mode=view&training=1")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.get(f"/api/v1/va/{va_sid}/workspace?mode=view").status_code, 403)

    def test_closed_session_trainee_cannot_read_s001_answers_without_training_flag(self):
        va_sid = self._submitted_s001_case()
        self._close_s001()
        response = self.get(f"/api/v1/va/{va_sid}/workspace?mode=view")
        self.assertIn(response.status_code, (403, 404, 409), (response.status_code, (response.get_json() or {}).keys()))


@only_own_tests
class Lead6RevokedInterviewerTests(rev.InterviewRevisionTests):
    """Interviewer revoked from site A (the unit U1 of the lead), active on site B (U2)."""

    PROJECT_ID = "RVN07"
    SITE_ID = "RV07"
    OTHER_SITE = "RV7B"
    ODK_FORM_ID = "RVN07RV0701"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(
            site_id=cls.OTHER_SITE, site_name="Other Site", site_abbr=cls.OTHER_SITE,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.OTHER_SITE, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.OTHER_SITE)
        db.session.add(VaForms(
            form_id=f"{cls.PROJECT_ID}{cls.OTHER_SITE}01", project_id=cls.PROJECT_ID, site_id=cls.OTHER_SITE,
            odk_form_id="ODK_REVISION_B", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now))
        cls.revoked = cls._get_or_make_user("run7.revoked@test.local", "Revoked123")
        db.session.flush()
        site_a = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == cls.PROJECT_ID, VaProjectSites.site_id == cls.SITE_ID))
        cls.grant_a = VaUserAccessGrants(
            user_id=cls.revoked.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=site_a.project_site_id, grant_status=VaStatuses.active, notes="run7 site A")
        site_b = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == cls.PROJECT_ID, VaProjectSites.site_id == cls.OTHER_SITE))
        db.session.add_all([cls.grant_a, VaUserAccessGrants(
            user_id=cls.revoked.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=site_b.project_site_id, grant_status=VaStatuses.active, notes="run7 site B")])
        db.session.commit()
        cls.revoked_id = str(cls.revoked.user_id)

    def _submitted_then_revoked(self):
        self.interviewer_id, keep = self.revoked_id, self.interviewer_id
        try:
            _death, va_sid = self._submitted()
        finally:
            self.interviewer_id = keep
        self.assertIsNotNone(self._draft(va_sid))  # the subject exists
        self.assertEqual(self._draft(va_sid).status, "submitted")
        self.grant_a.grant_status = VaStatuses.deactive
        db.session.commit()
        self.addCleanup(self._restore_grant)
        return va_sid

    def _restore_grant(self):
        self.grant_a.grant_status = VaStatuses.active
        db.session.commit()

    def test_revoked_interviewer_cannot_revise_a_submitted_case_or_release_its_coder(self):
        va_sid = self._submitted_then_revoked()
        allocation, _initial = self._start_coding(va_sid)
        response = self._revise(va_sid, _answers(Id10007="Ramesh"), reason="more_information", user_id=self.revoked_id)
        db.session.expire_all()
        released = db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status != VaStatuses.active
        self.assertEqual(
            (response.status_code in (403, 404, 409), released), (True, False),
            (response.status_code, "coder allocation released:", released))

    def test_revoked_interviewer_cannot_read_the_submitted_answers(self):
        va_sid = self._submitted_then_revoked()
        self._login(self.revoked_id)
        response = self.client.get(f"/api/v1/va/{va_sid}/workspace?mode=view")
        self.assertIn(response.status_code, (403, 404, 409), response.status_code)



# ---------------------------------------------------------------------------
# Lead 7: reviewer initial/finalize miss the training scope
# ---------------------------------------------------------------------------

@only_own_tests
class Lead7ReviewerScopeTests(tts.ReviewingScopeTests):
    def _hold(self, sid, suffix=""):
        started = self.client.post(f"/api/v1/reviewing/allocation/{sid}{suffix}", headers=self._csrf_headers())
        self.assertEqual(started.status_code, 201, started.get_json())  # the subject exists

    def _assert_not_available(self, path, body):
        """Secure: refused 409 not_available before the coding service runs.
        The service is stubbed so a missing guard shows as a call, not as an
        unrelated downstream refusal."""
        stub = mock.Mock(side_effect=AssertionError("service reached"))
        name = "submit_reviewer_final_cod" if "/finalize/" in path else "submit_reviewer_initial_cod"
        with mock.patch(f"app.routes.api.reviewing.{name}", stub):
            response = self.post(path, body)
        self.assertFalse(stub.called, f"{name} was reached: {path}")
        self.assertEqual(
            (response.status_code, (response.get_json() or {}).get("code")), (409, "not_available"),
            (path, response.status_code, response.get_json()))

    def test_training_sid_without_the_flag_is_refused_on_finalize(self):
        self._hold(self.training_sid, "?training=1")
        self._assert_not_available(f"/api/v1/reviewing/finalize/{self.training_sid}", {"conclusive_cod": ICD10_VALUE})

    def test_training_sid_without_the_flag_is_refused_on_initial(self):
        self._hold(self.training_sid, "?training=1")
        self._assert_not_available(
            f"/api/v1/reviewing/initial/{self.training_sid}",
            {"immediate_cod": ICD10_VALUE, "antecedent_cod": ICD10_VALUE})

    def test_real_sid_with_the_training_flag_is_refused_on_finalize(self):
        self._hold(tts.REAL_SID)
        self._assert_not_available(
            f"/api/v1/reviewing/finalize/{tts.REAL_SID}?training=1", {"conclusive_cod": ICD10_VALUE})

    def test_real_sid_with_the_training_flag_is_refused_on_initial(self):
        self._hold(tts.REAL_SID)
        self._assert_not_available(
            f"/api/v1/reviewing/initial/{tts.REAL_SID}?training=1",
            {"immediate_cod": ICD10_VALUE, "antecedent_cod": ICD10_VALUE})


# ---------------------------------------------------------------------------
# Lead 8: a closed session's manager keeps the trainer report (owner decision, digitva-l9dp.8)
# ---------------------------------------------------------------------------

@only_own_tests
class Lead8ClosedSessionReportTests(rep.ReportTestBase):
    BASE = "/data-management/training"

    PATHS = ("/S001", "/S001/cases.csv", "/S001/coders.csv")

    def _statuses(self):
        return {path: self.client.get(self.BASE + path).status_code for path in self.PATHS}

    def test_manager_of_a_closed_session_keeps_report_and_csv_access(self):
        manager = self._add("run7.legacy", "reviewer_data_manager")
        svc.complete_onboarding(manager.user_id)
        self._legacy_dm_grant(manager)
        db.session.commit()
        self._login(str(manager.user_id))
        self.assertEqual(self._statuses(), dict.fromkeys(self.PATHS, 200))
        svc.close_training_session("S001", self.admin)
        self.addCleanup(lambda: svc.reopen_training_session("S001", self.admin))
        self.assertEqual(self._statuses(), dict.fromkeys(self.PATHS, 200))


# ---------------------------------------------------------------------------
# Lead 9: social autopsy remark has no length bound
# ---------------------------------------------------------------------------

@only_own_tests
class Lead9SocialAutopsyRemarkTests(saa.TestSocialAutopsyAnalysisRoute):
    def _save(self, remark):
        return self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json={
                "va_actiontype": "vademo_start_coding",
                "selected_options": [
                    {"delay_level": "delay_1_decision", "option_code": "recognition"},
                    {"delay_level": "delay_2_reaching", "option_code": "financial_barrier"},
                    {"delay_level": "delay_3_receiving", "option_code": "delay_in_referral"},
                ],
                "remark": remark,
            },
            headers=self._csrf_headers(),
        )

    def test_a_huge_remark_is_rejected(self):
        self._login(self.base_admin_id)
        baseline = self._save("short remark")
        self.assertEqual(baseline.status_code, 200, baseline.get_json())  # the subject exists
        response = self._save("x" * 500_000)
        stored = db.session.scalar(sa.select(sa.func.max(sa.func.length(VaSocialAutopsyAnalysis.va_saa_remark)))
                                   .where(VaSocialAutopsyAnalysis.va_sid == self.social_sid))
        self.assertGreaterEqual(response.status_code, 400, (response.status_code, "stored chars:", stored))
        self.assertLess(stored or 0, 500_000)

    def test_remark_cap_is_4000_characters(self):
        self._login(self.base_admin_id)
        self.assertEqual(self._save("x" * 4000).status_code, 200)
        response = self._save("x" * 4001)
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_request"))

    def test_a_non_text_remark_is_rejected(self):
        self._login(self.base_admin_id)
        self.assertEqual(self._save(["x"]).status_code, 400)
