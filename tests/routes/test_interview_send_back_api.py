"""Send-back and reopen of a submitted interview (digitva-bhpl part B).

POST /api/v1/coding/submissions/<va_sid>/send-back (the coder who finalised, a
reviewer) and POST /api/v1/intake/supervision/submissions/<va_sid>/reopen-for-revision
(supervisor, data manager, admin) put a finalised web or device interview into
``finalized_upstream_changed`` for its interviewer; the interviewer's changed
revision then restarts coding at once. Rules 3 and 4 of
docs/policy/interview-revisions.md. Part A's tests are in
tests/routes/test_interview_revisions_api.py.
"""
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services.data_management_service import dm_reject_upstream_change
from app.services.final_cod_authority_service import upsert_final_cod_authority
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.submission_payload_version_service import (
    create_or_update_pending_upstream_payload_version,
    get_active_payload_version,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from app.services.workflow.transitions import mark_upstream_change_detected, system_actor
from tests.base import BaseTestCase

INTAKE = "/api/v1/intake"
CODING = "/api/v1/coding"


def _answers(**over):
    return {
        "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
        "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
        "narr_language": "english", **over,
    }


def _text(answers):
    return json.dumps(answers, separators=(",", ":"))


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class InterviewSendBackTests(BaseTestCase):
    PROJECT_ID = "SBK01"
    OTHER_PROJECT_ID = "SBK02"
    SITE_ID = "SB01"
    ODK_FORM_ID = "SBK01SB0101"

    @classmethod
    def _project(cls, project_id, name):
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=name, project_nickname=name,
            project_status=VaStatuses.active, project_registered_at=now, project_updated_at=now,
            web_intake_mode="both",
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=project_id, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(project_id, cls.SITE_ID)

    @classmethod
    def _grant(cls, user, role, project_id):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project, project_id=project_id,
            notes="send-back test grant", grant_status=VaStatuses.active,
        ))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Send-back Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        cls._project(cls.PROJECT_ID, "SendBack")
        cls._project(cls.OTHER_PROJECT_ID, "SendBackOther")
        db.session.add(VaForms(
            form_id=cls.ODK_FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_SENDBACK", odk_project_id="8", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        users = {
            name: cls._get_or_make_user(f"sb.{name}@test.local", "SendBack123")
            for name in ("interviewer", "coder", "coder2", "reviewer", "reviewer2", "dm", "other_dm", "outsider_coder")
        }
        for name, role, project in (
            ("interviewer", VaAccessRoles.interviewer, cls.PROJECT_ID),
            ("coder", VaAccessRoles.coder, cls.PROJECT_ID),
            ("coder2", VaAccessRoles.coder, cls.PROJECT_ID),
            ("reviewer", VaAccessRoles.reviewer, cls.PROJECT_ID),
            ("reviewer2", VaAccessRoles.reviewer, cls.PROJECT_ID),
            ("dm", VaAccessRoles.data_manager, cls.PROJECT_ID),
            ("other_dm", VaAccessRoles.data_manager, cls.OTHER_PROJECT_ID),
            ("outsider_coder", VaAccessRoles.coder, cls.OTHER_PROJECT_ID),
        ):
            cls._grant(users[name], role, project)
        db.session.commit()
        for name, user in users.items():
            setattr(cls, name, user)
            setattr(cls, f"{name}_id", str(user.user_id))

    # ── helpers ────────────────────────────────────────────────────────────

    def _submit(self, **over):
        """A completed interview by the interviewer; returns its va_sid."""
        self._login(self.interviewer_id)
        headers = self._csrf_headers()
        response = self.client.post(f"{INTAKE}/deaths", headers=headers, json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Bina Sahu",
            "deceased_sex": "female", "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        text = _text(_answers(**over))
        response = self.client.post(f"{INTAKE}/submissions", headers=headers, json={
            "client_draft_id": str(uuid.uuid4()), "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
            "death_id": response.get_json()["case"]["death_id"],
            "draft": {"startedAt": datetime.now(UTC).isoformat()},
            "completion": {"valid": True, "issues": []}, "answers_json": text, "answers_sha256": _sha(text),
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["va_sid"]

    def _state(self, va_sid, state):
        set_submission_workflow_state(va_sid, state, reason="test", by_role="test")
        db.session.commit()

    def _finalised(self, state=WORKFLOW_CODER_FINALIZED, coder=None):
        """A submitted interview whose active final COD is *coder*'s (the
        default), in *state*; returns (va_sid, final assessment)."""
        va_sid = self._submit()
        coder = coder or self.coder
        final = VaFinalAssessments(
            va_sid=va_sid, va_finassess_by=coder.user_id, va_conclusive_cod="R99",
            payload_version_id=get_active_payload_version(va_sid).payload_version_id,
            va_finassess_status=VaStatuses.active, va_finassess_createdat=datetime.now(UTC) - timedelta(hours=30),
        )
        db.session.add(final)
        db.session.flush()
        upsert_final_cod_authority(va_sid, final, reason="final_cod_submitted", source_role="vacoder", updated_by=coder.user_id)
        self._state(va_sid, state)
        return va_sid, final

    def _post(self, url, user_id, **body):
        self._login(user_id)
        return self.client.post(url, headers=self._csrf_headers(), json=body)

    def _send_back(self, va_sid, user_id, reason="missing_information"):
        return self._post(f"{CODING}/submissions/{va_sid}/send-back", user_id, reason_code=reason)

    def _reopen(self, va_sid, user_id, reason="cod_review_requested"):
        return self._post(f"{INTAKE}/supervision/submissions/{va_sid}/reopen-for-revision", user_id, reason_code=reason)

    def _revise(self, va_sid, answers):
        text = _text(answers)
        return self._post(
            f"{INTAKE}/submissions/{va_sid}/revisions", self.interviewer_id, reason_code="interviewer_correction",
            draft={}, completion={"valid": True, "issues": []}, answers_json=text, answers_sha256=_sha(text),
        )

    def _events(self, va_sid):
        db.session.expire_all()
        return db.session.execute(
            sa.select(VaSubmissionWorkflowEvent.transition_reason, VaSubmissionWorkflowEvent.current_state,
                      VaSubmissionWorkflowEvent.actor_kind)
            .where(VaSubmissionWorkflowEvent.va_sid == va_sid).order_by(VaSubmissionWorkflowEvent.event_created_at)
        ).all()

    def _actions(self, va_sid):
        db.session.expire_all()
        return [a for (a,) in db.session.execute(
            sa.select(VaSubmissionsAuditlog.va_audit_action).where(VaSubmissionsAuditlog.va_sid == va_sid)
            .order_by(VaSubmissionsAuditlog.va_audit_id)
        )]

    def _assert_state(self, va_sid, state):
        db.session.expire_all()
        self.assertEqual(get_submission_workflow_state(va_sid), state)

    # ── a coder sends back, the interviewer revises, coding restarts ───────

    def test_coder_send_back_opens_the_case_and_a_changed_revision_restarts_coding_at_once(self):
        va_sid, final = self._finalised()
        before = get_active_payload_version(va_sid).payload_version_id

        response = self._send_back(va_sid, self.coder_id, "inconsistent_answers")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {
            "va_sid": va_sid, "workflow_state": WORKFLOW_FINALIZED_UPSTREAM_CHANGED, "reason_code": "inconsistent_answers",
        })
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self.assertEqual(self._events(va_sid)[-1], ("sent_back_for_revision", WORKFLOW_FINALIZED_UPSTREAM_CHANGED, "coder"))
        self.assertIn("sent_back_for_revision:inconsistent_answers", self._actions(va_sid))
        # The COD stays until the revision arrives, so a data manager can still reject.
        self.assertEqual(db.session.get(VaFinalAssessments, final.va_finassess_id).va_finassess_status, VaStatuses.active)

        response = self._revise(va_sid, _answers(Id10017="Binita"))

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["changed"])
        self._assert_state(va_sid, WORKFLOW_SMARTVA_PENDING)
        db.session.expire_all()
        old = db.session.get(VaFinalAssessments, final.va_finassess_id)
        self.assertEqual(old.va_finassess_status, VaStatuses.deactive)  # kept as history
        # Auditable like any changed revision: one row per released artifact.
        self.assertIn("va_finalasses_deletion_during_interviewer_revision", self._actions(va_sid))
        self.assertIsNone(db.session.scalar(
            sa.select(VaFinalCodAuthority.authoritative_final_assessment_id).where(VaFinalCodAuthority.va_sid == va_sid)))
        self.assertNotEqual(get_active_payload_version(va_sid).payload_version_id, before)
        self.assertEqual(db.session.get(VaSubmissionPayloadVersion, before).version_status, "superseded")
        restart = next(e for e in self._events(va_sid) if e[0] == "interviewer_revision" and e[2] == "system" and e[1] == WORKFLOW_SMARTVA_PENDING)
        self.assertIsNotNone(restart)

    def test_an_unchanged_revision_leaves_the_case_sent_back(self):
        va_sid, final = self._finalised()
        self.assertEqual(self._send_back(va_sid, self.coder_id).status_code, 200)

        response = self._revise(va_sid, _answers())

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()["changed"])
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self.assertEqual(db.session.get(VaFinalAssessments, final.va_finassess_id).va_finassess_status, VaStatuses.active)
        self.assertEqual(self._events(va_sid)[-1][0], "sent_back_for_revision")

    def test_a_revision_supersedes_a_lingering_pending_upstream_payload(self):
        va_sid, _final = self._finalised()
        self.assertEqual(self._send_back(va_sid, self.coder_id).status_code, 200)
        pending = create_or_update_pending_upstream_payload_version(
            db.session.get(VaSubmissions, va_sid), payload_data={"stale": "pending"}, source_updated_at=datetime.now(UTC))
        db.session.commit()

        self.assertEqual(self._revise(va_sid, _answers(Id10017="Binita")).status_code, 200)

        db.session.expire_all()
        self.assertEqual(db.session.get(VaSubmissionPayloadVersion, pending.payload_version_id).version_status, "rejected")
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid, VaSubmissionPayloadVersion.version_status == "pending_upstream")),
            0,
        )

    # ── a reviewer sends back ──────────────────────────────────────────────

    def test_a_reviewer_sends_back_from_reviewer_eligible(self):
        va_sid, _final = self._finalised(WORKFLOW_REVIEWER_ELIGIBLE)

        response = self._send_back(va_sid, self.reviewer_id, "wrong_respondent_or_case")

        self.assertEqual(response.status_code, 200, response.get_json())
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self.assertEqual(self._events(va_sid)[-1], ("sent_back_for_revision", WORKFLOW_FINALIZED_UPSTREAM_CHANGED, "reviewer"))

    def test_a_send_back_racing_the_reviewers_own_finish_is_409_not_500(self):
        va_sid, _final = self._finalised(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        db.session.add(VaAllocations(
            va_sid=va_sid, va_allocated_to=self.reviewer.user_id, va_allocation_for=VaAllocation.reviewing,
            va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()
        with mock.patch(
            "app.services.interview_send_back_service.release_reviewer_session_for_send_back",
            side_effect=__import__("app.services.workflow.transitions", fromlist=["x"]).WorkflowTransitionError("moved on"),
        ):
            response = self._send_back(va_sid, self.reviewer_id, "needs_clarification")
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "wrong_state"))
        self._assert_state(va_sid, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

    def test_a_reviewer_sending_back_mid_review_releases_their_session_first(self):
        va_sid, _final = self._finalised(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        allocation = VaAllocations(
            va_sid=va_sid, va_allocated_to=self.reviewer.user_id, va_allocation_for=VaAllocation.reviewing,
            va_allocation_status=VaStatuses.active,
        )
        db.session.add(allocation)
        db.session.commit()

        other = self._send_back(va_sid, self.reviewer2_id)  # in scope, but not the reviewer working on it
        self.assertEqual(other.status_code, 403)
        self._assert_state(va_sid, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

        response = self._send_back(va_sid, self.reviewer_id, "needs_clarification")

        self.assertEqual(response.status_code, 200, response.get_json())
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.deactive)
        self.assertIn("reviewer_session_released_for_send_back", self._actions(va_sid))
        states = [e[1] for e in self._events(va_sid)][-2:]
        self.assertEqual(states, [WORKFLOW_REVIEWER_ELIGIBLE, WORKFLOW_FINALIZED_UPSTREAM_CHANGED])

    def test_a_reviewer_who_finalised_sends_back_from_reviewer_finalized(self):
        va_sid, _final = self._finalised(WORKFLOW_REVIEWER_FINALIZED)
        db.session.add(VaReviewerFinalAssessments(
            va_sid=va_sid, va_rfinassess_by=self.reviewer.user_id, va_conclusive_cod="R99",
            va_rfinassess_status=VaStatuses.active,
        ))
        db.session.commit()

        self.assertEqual(self._send_back(va_sid, self.reviewer2_id).status_code, 403)
        self.assertEqual(self._send_back(va_sid, self.reviewer_id).status_code, 200)
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)

    # ── a supervisor, data manager or admin reopens ────────────────────────

    def test_a_data_manager_reopens_a_reviewer_finalized_case(self):
        va_sid, final = self._finalised(WORKFLOW_REVIEWER_FINALIZED)

        response = self._reopen(va_sid, self.dm_id, "new_information")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["workflow_state"], WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self.assertEqual(self._events(va_sid)[-1], ("reopened_for_revision", WORKFLOW_FINALIZED_UPSTREAM_CHANGED, "data_manager"))
        self.assertIn("reopened_for_revision:new_information", self._actions(va_sid))
        self.assertEqual(db.session.get(VaFinalAssessments, final.va_finassess_id).va_finassess_status, VaStatuses.active)
        # ... and the interviewer's revision recodes it from scratch.
        self.assertEqual(self._revise(va_sid, _answers(Id10017="Binita")).status_code, 200)
        self._assert_state(va_sid, WORKFLOW_SMARTVA_PENDING)
        self.assertEqual(db.session.get(VaFinalAssessments, final.va_finassess_id).va_finassess_status, VaStatuses.deactive)

    def test_an_admin_reopens_a_coder_finalized_case(self):
        va_sid, _final = self._finalised()

        response = self._reopen(va_sid, self.base_admin_id, "data_correction")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._events(va_sid)[-1], ("reopened_for_revision", WORKFLOW_FINALIZED_UPSTREAM_CHANGED, "admin"))

    def test_reopen_needs_a_final_cod_and_is_not_repeatable(self):
        va_sid = self._submit()
        self._state(va_sid, WORKFLOW_READY_FOR_CODING)
        refused = self._reopen(va_sid, self.dm_id)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "wrong_state"))

        va_sid, _final = self._finalised(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self.assertEqual(self._reopen(va_sid, self.dm_id).get_json()["code"], "wrong_state")

        va_sid, _final = self._finalised()
        self.assertEqual(self._reopen(va_sid, self.dm_id).status_code, 200)
        again = self._reopen(va_sid, self.dm_id)
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "wrong_state"))
        self.assertEqual(self._send_back(va_sid, self.coder_id).get_json()["code"], "wrong_state")

    # ── who may not ────────────────────────────────────────────────────────

    def test_a_coder_out_of_scope_or_not_the_finalising_coder_is_refused(self):
        va_sid, final = self._finalised()
        for user_id in (self.outsider_coder_id, self.coder2_id):
            with self.subTest(user=user_id):
                response = self._send_back(va_sid, user_id)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self._send_back("no-such-sid", self.coder_id).status_code, 404)
        self.assertEqual(self._send_back(va_sid, self.interviewer_id).status_code, 403)  # not a coder or reviewer
        self._assert_state(va_sid, WORKFLOW_CODER_FINALIZED)
        self.assertNotIn("sent_back_for_revision", [e[0] for e in self._events(va_sid)])

    def test_a_data_manager_of_another_project_cannot_reopen_and_a_coder_cannot_either(self):
        va_sid, _final = self._finalised()
        self.assertEqual(self._reopen(va_sid, self.other_dm_id).status_code, 404)
        self.assertEqual(self._reopen(va_sid, self.coder_id).status_code, 403)  # role gate
        self.assertEqual(self._reopen(va_sid, self.interviewer_id).status_code, 403)
        self._assert_state(va_sid, WORKFLOW_CODER_FINALIZED)

    def test_an_odk_submission_cannot_be_sent_back_or_reopened_here(self):
        now = datetime.now(UTC)
        va_sid = f"uuid:{uuid.uuid4()}"
        db.session.add(VaSubmissions(
            va_sid=va_sid, va_form_id=self.ODK_FORM_ID, va_submission_date=now, va_odk_updatedat=now,
            va_data_collector="Collector", va_instance_name=va_sid, va_uniqueid_real=va_sid, va_uniqueid_masked=va_sid,
            va_consent="yes", va_narration_language="English", va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        final = VaFinalAssessments(
            va_sid=va_sid, va_finassess_by=self.coder.user_id, va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active, va_finassess_createdat=now - timedelta(hours=30),
        )
        db.session.add(final)
        db.session.flush()
        upsert_final_cod_authority(va_sid, final, reason="final_cod_submitted", source_role="vacoder", updated_by=self.coder.user_id)
        self._state(va_sid, WORKFLOW_CODER_FINALIZED)

        for response in (self._send_back(va_sid, self.coder_id), self._reopen(va_sid, self.dm_id), self._reopen(va_sid, self.base_admin_id)):
            self.assertEqual((response.status_code, response.get_json()["code"]), (409, "not_web_submission"))
        self._assert_state(va_sid, WORKFLOW_CODER_FINALIZED)

    def test_a_confirmed_duplicate_case_is_closed_to_both(self):
        va_sid, _final = self._finalised()
        death_id = db.session.scalar(sa.select(VaWebIntakeDraft.death_id).where(VaWebIntakeDraft.va_sid == va_sid))
        db.session.get(VaDeathRegister, death_id).status = "duplicate"
        db.session.commit()

        for response in (self._send_back(va_sid, self.coder_id), self._reopen(va_sid, self.dm_id)):
            self.assertEqual((response.status_code, response.get_json()["code"]), (409, "case_closed"))
        self._assert_state(va_sid, WORKFLOW_CODER_FINALIZED)

    def test_only_the_listed_reason_codes_are_accepted(self):
        va_sid, _final = self._finalised()
        for response in (
            self._send_back(va_sid, self.coder_id, "cod_review_requested"),  # a reopen reason
            self._send_back(va_sid, self.coder_id, "because I said so"),
            self._post(f"{CODING}/submissions/{va_sid}/send-back", self.coder_id),
            self._reopen(va_sid, self.dm_id, "missing_information"),  # a send-back reason
            self._reopen(va_sid, self.dm_id, ""),
        ):
            self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_reason"))
        self._assert_state(va_sid, WORKFLOW_CODER_FINALIZED)

    def test_a_send_back_is_refused_before_the_coder_has_finalised(self):
        va_sid = self._submit()
        self._state(va_sid, WORKFLOW_READY_FOR_CODING)
        response = self._send_back(va_sid, self.coder_id)
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "wrong_state"))
        self._assert_state(va_sid, WORKFLOW_READY_FOR_CODING)

    # ── the other locks stay ───────────────────────────────────────────────

    def test_an_odk_upstream_change_still_locks_the_interviewer_out(self):
        va_sid, _final = self._finalised()
        mark_upstream_change_detected(va_sid, reason="upstream_odk_data_changed", actor=system_actor())
        db.session.commit()

        response = self._revise(va_sid, _answers(Id10017="Binita"))

        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "revision_locked"))
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)

    def test_a_coder_cannot_use_the_odk_upstream_reason_to_open_a_case(self):
        from app.services.workflow.transitions import WorkflowTransitionError, coder_actor

        va_sid, _final = self._finalised()
        with self.assertRaises(WorkflowTransitionError):
            mark_upstream_change_detected(va_sid, reason="upstream_odk_data_changed", actor=coder_actor(self.coder.user_id))
        db.session.rollback()

    # ── a data manager's reject cancels a send-back ────────────────────────

    def test_a_data_manager_reject_cancels_the_send_back(self):
        va_sid, final = self._finalised()
        self.assertEqual(self._send_back(va_sid, self.coder_id).status_code, 200)

        self._login(self.dm_id)
        accept = self.client.post(
            f"/api/v1/data-management/submissions/{va_sid}/accept-upstream-change", headers=self._csrf_headers())
        self.assertEqual(accept.status_code, 400)  # nothing to accept: no upstream payload
        self._assert_state(va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)

        reject = self.client.post(
            f"/api/v1/data-management/submissions/{va_sid}/reject-upstream-change", headers=self._csrf_headers())

        self.assertEqual(reject.status_code, 200, reject.get_json())
        self._assert_state(va_sid, WORKFLOW_CODER_FINALIZED)
        self.assertEqual(db.session.get(VaFinalAssessments, final.va_finassess_id).va_finassess_status, VaStatuses.active)
        self.assertIn("revision_request_cancelled_by_data_manager", self._actions(va_sid))
        revise = self._revise(va_sid, _answers(Id10017="Binita"))
        self.assertEqual((revise.status_code, revise.get_json()["code"]), (409, "revision_locked"))

    def test_a_cancelled_reviewer_session_send_back_returns_to_reviewer_eligible(self):
        va_sid, _final = self._finalised(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        db.session.add(VaAllocations(
            va_sid=va_sid, va_allocated_to=self.reviewer.user_id, va_allocation_for=VaAllocation.reviewing,
            va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertEqual(self._send_back(va_sid, self.reviewer_id).status_code, 200)

        dm_reject_upstream_change(self.dm, va_sid)
        db.session.commit()

        self._assert_state(va_sid, WORKFLOW_REVIEWER_ELIGIBLE)
