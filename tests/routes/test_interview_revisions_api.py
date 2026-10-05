"""POST /api/v1/intake/submissions/<va_sid>/revisions (digitva-bhpl part A).

An interviewer revises their own submitted interview until the coder
finalises (docs/policy/interview-revisions.md): partial-finish and the
no-change rule. The ODK sync keeps its own tests of the shared release
(tests/services/test_odk_sync_workflow_guards.py).
"""
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import organization_service as org
from app.services.case_transition_service import WebIntakeError
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from app.services.workflow.transitions import WorkflowTransitionError
from tests.base import BaseTestCase

API = "/api/v1/intake"


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


class InterviewRevisionTests(BaseTestCase):
    PROJECT_ID = "RVN01"
    SITE_ID = "RV01"
    ODK_FORM_ID = "RVN01RV0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Revision Project",
            project_nickname="Revision", project_status=VaStatuses.active, project_registered_at=now,
            project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Revision Site", site_abbr=cls.SITE_ID,
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
            form_id=cls.ODK_FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_REVISION", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        cls.interviewer = cls._get_or_make_user("rev.interviewer@test.local", "Revision123")
        cls.teammate = cls._get_or_make_user("rev.teammate@test.local", "Revision123")
        for user in (cls.interviewer, cls.teammate):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
                project_id=cls.PROJECT_ID, notes="revision test grant", grant_status=VaStatuses.active,
            ))
        db.session.commit()
        cls.interviewer_id = str(cls.interviewer.user_id)
        cls.teammate_id = str(cls.teammate.user_id)

    # ── helpers ────────────────────────────────────────────────────────────

    def _case(self, **extra):
        self._login(self.interviewer_id)
        response = self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Bina Sahu",
            "deceased_sex": "female", "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71, **extra,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["case"]["death_id"]

    def _upload(self, death_id, answers, *, valid=True, user_id=None, **draft):
        """One upload as *user_id* (the interviewer by default); returns the response."""
        self._login(user_id or self.interviewer_id)
        text = _text(answers)
        return self.client.post(f"{API}/submissions", headers=self._csrf_headers(), json={
            "client_draft_id": str(uuid.uuid4()), "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
            "death_id": death_id, "draft": {"startedAt": datetime.now(UTC).isoformat(), **draft},
            "completion": {"valid": valid, "issues": []}, "answers_json": text, "answers_sha256": _sha(text),
        })

    def _submitted(self, case=None, **over):
        """A completed interview; returns (death_id, va_sid)."""
        death_id = self._case(**(case or {}))
        response = self._upload(death_id, _answers(**over))
        self.assertEqual(response.status_code, 201, response.get_json())
        return death_id, response.get_json()["va_sid"]

    def _revise(self, va_sid, answers, *, reason="interviewer_correction", valid=True, user_id=None, **over):
        self._login(user_id or self.interviewer_id)
        text = _text(answers)
        body = {
            "reason_code": reason, "draft": {}, "completion": {"valid": valid, "issues": []},
            "answers_json": text, "answers_sha256": _sha(text),
        }
        body.update(over)
        return self.client.post(f"{API}/submissions/{va_sid}/revisions", headers=self._csrf_headers(), json=body)

    def _versions(self, va_sid):
        db.session.expire_all()
        return db.session.scalars(
            sa.select(VaSubmissionPayloadVersion).where(VaSubmissionPayloadVersion.va_sid == va_sid)
            .order_by(VaSubmissionPayloadVersion.version_created_at)
        ).all()

    def _actions(self, va_sid):
        return [a for (a,) in db.session.execute(
            sa.select(VaSubmissionsAuditlog.va_audit_action).where(VaSubmissionsAuditlog.va_sid == va_sid)
            .order_by(VaSubmissionsAuditlog.va_audit_id)
        )]

    def _draft(self, va_sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == va_sid))

    def _start_coding(self, va_sid, state=WORKFLOW_CODING_IN_PROGRESS):
        set_submission_workflow_state(va_sid, state, reason="test", by_role="test")
        allocation = VaAllocations(
            va_sid=va_sid, va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        )
        initial = VaInitialAssessments(
            va_sid=va_sid, va_iniassess_by=self.base_coder_user.user_id, va_immediate_cod="R99",
            va_antecedent_cod="R99", va_iniassess_status=VaStatuses.active,
        )
        db.session.add_all([allocation, initial])
        db.session.commit()
        return allocation, initial

    # ── submit stores the complete raw answers ─────────────────────────────

    def test_a_submitted_draft_keeps_its_exact_raw_answers_and_hash(self):
        death_id, va_sid = self._submitted(Id10007="Ramesh")
        draft = self._draft(va_sid)
        final = next(s for s in draft.sections if s.section_name == "final")
        self.assertEqual(final.data["Id10007"], "Ramesh")
        self.assertEqual(final.data["interview_outcome"], "completed")
        got = self.client.get(f"{API}/drafts/{draft.draft_id}").get_json()
        self.assertEqual(got["envelope"]["data"], final.data)
        self.assertEqual(got["answers_sha256"], draft.answers_sha256)
        self.assertEqual(self._versions(va_sid)[0].answers_sha256, draft.answers_sha256)
        self.assertIsNone(self._versions(va_sid)[0].revision_reason_code)

    # ── a changed revision ─────────────────────────────────────────────────

    def test_revision_before_coding_makes_a_new_version_and_keeps_the_old_answers(self):
        for state in (WORKFLOW_SMARTVA_PENDING, WORKFLOW_READY_FOR_CODING):
            with self.subTest(state=state):
                _death, va_sid = self._submitted()
                set_submission_workflow_state(va_sid, state, reason="test", by_role="test")
                db.session.commit()
                before = self._draft(va_sid)
                old_raw = next(s for s in before.sections if s.section_name == "final").data
                new = _answers(Id10017="Binita", Id10007="Ramesh")

                response = self._revise(va_sid, new, reason="respondent_correction")

                self.assertEqual(response.status_code, 200, response.get_json())
                body = response.get_json()
                self.assertTrue(body["changed"])
                self.assertEqual((body["va_sid"], body["outcome"]), (va_sid, "completed"))
                self.assertEqual(body["workflow_state"], WORKFLOW_SMARTVA_PENDING)
                self.assertEqual(body["answers_sha256"], _sha(_text(new)))
                first, second = self._versions(va_sid)
                self.assertEqual((first.version_status, second.version_status), ("superseded", "active"))
                self.assertEqual(body["payload_version_id"], str(second.payload_version_id))
                self.assertEqual(
                    (second.revision_reason_code, second.answers_sha256), ("respondent_correction", _sha(_text(new)))
                )
                self.assertEqual(second.payload_data["Id10017"], "Binita")
                # The same submission id, its date unchanged, and the draft holds the new raw answers.
                submission = db.session.get(VaSubmissions, va_sid)
                self.assertEqual(submission.active_payload_version_id, second.payload_version_id)
                self.assertEqual(second.payload_data["SubmissionDate"], first.payload_data["SubmissionDate"])
                draft = self._draft(va_sid)
                self.assertEqual({s.section_name for s in draft.sections}, {"final"})
                self.assertEqual(draft.sections[0].data["Id10007"], "Ramesh")
                self.assertEqual(draft.answers_sha256, _sha(_text(new)))
                self.assertEqual(draft.status, "submitted")
                # The earlier raw answers are history, not the editable draft.
                (history,) = db.session.scalars(sa.select(VaWebIntakeDraft).where(
                    VaWebIntakeDraft.status == "replaced",
                    VaWebIntakeDraft.meta["replacedDraftId"].astext == str(draft.draft_id),
                )).all()
                self.assertEqual(history.sections[0].data, old_raw)
                self.assertIsNone(history.client_draft_id)
                self.assertEqual(self._actions(va_sid).count("va_submission_revised_by_interviewer"), 1)

    def test_revision_during_coding_drops_the_coders_work_with_its_own_audit_reason(self):
        _death, va_sid = self._submitted()
        allocation, initial = self._start_coding(va_sid)

        response = self._revise(va_sid, _answers(Id10007="Ramesh"), reason="more_information")

        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.expire_all()
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.deactive)
        self.assertEqual(
            db.session.get(VaInitialAssessments, initial.va_iniassess_id).va_iniassess_status, VaStatuses.deactive
        )
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_SMARTVA_PENDING)
        actions = self._actions(va_sid)
        self.assertIn("interviewer_revision", actions)
        self.assertIn("va_initialasses_deletion_during_interviewer_revision", actions)
        self.assertNotIn("va_allocation_released_during_datasync", actions)
        released = db.session.scalar(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == va_sid, VaSubmissionsAuditlog.va_audit_action == "interviewer_revision"))
        self.assertEqual((released.va_audit_by, released.va_audit_entityid), (self.interviewer.user_id, allocation.va_allocation_id))

    # ── the no-change rule ─────────────────────────────────────────────────

    def test_an_unchanged_revision_writes_nothing_and_keeps_the_coder_session(self):
        _death, va_sid = self._submitted()
        allocation, initial = self._start_coding(va_sid)
        versions = [v.payload_version_id for v in self._versions(va_sid)]
        actions = self._actions(va_sid)
        draft = self._draft(va_sid)
        before = (draft.answers_sha256, draft.updated_at, len(draft.sections))
        rows = db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft))

        response = self._revise(va_sid, _answers())

        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertFalse(body["changed"])
        self.assertEqual(body["payload_version_id"], str(versions[0]))
        self.assertEqual(body["workflow_state"], WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual([v.payload_version_id for v in self._versions(va_sid)], versions)
        self.assertEqual(self._actions(va_sid), actions)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.active)
        self.assertEqual(db.session.get(VaInitialAssessments, initial.va_iniassess_id).va_iniassess_status, VaStatuses.active)
        draft = self._draft(va_sid)
        self.assertEqual((draft.answers_sha256, draft.updated_at, len(draft.sections)), before)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft)), rows)

    def test_a_device_interview_resent_with_its_own_times_is_no_change(self):
        completed = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        death_id = self._case()
        va_sid = self._upload(death_id, _answers(), completedAt=completed).get_json()["va_sid"]
        same = self._revise(va_sid, _answers(), draft={"completedAt": completed})
        omitted = self._revise(va_sid, _answers())
        later = self._revise(va_sid, _answers(), draft={"completedAt": datetime.now(UTC).isoformat()})
        self.assertEqual([r.get_json()["changed"] for r in (same, omitted, later)], [False, False, True])

    def test_changing_only_an_irrelevant_answer_keeps_the_raw_answers_but_not_the_coding(self):
        # md_count is stripped while md_available is "no": the raw answer
        # differs but the coding payload does not.
        _death, va_sid = self._submitted(md_available="no", md_count="2")
        self.assertNotIn("md_count", self._versions(va_sid)[0].payload_data)
        allocation, _initial = self._start_coding(va_sid)
        before = self._draft(va_sid)
        old_hash = before.answers_sha256
        old_raw = next(s for s in before.sections if s.section_name == "final").data
        actions = self._actions(va_sid)
        new = _answers(md_available="no", md_count="3")

        response = self._revise(va_sid, new)

        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertFalse(body["changed"])
        # The phone's acknowledgement is the hash of what it sent, now stored.
        self.assertEqual(body["answers_sha256"], _sha(_text(new)))
        self.assertEqual(body["workflow_state"], WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(len(self._versions(va_sid)), 1)
        self.assertEqual(self._actions(va_sid), actions)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.active)
        draft = self._draft(va_sid)
        self.assertEqual(draft.answers_sha256, _sha(_text(new)))
        self.assertEqual([s.section_name for s in draft.sections], ["final"])
        self.assertEqual(draft.sections[0].data["md_count"], "3")
        (history,) = db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.status == "replaced",
            VaWebIntakeDraft.meta["replacedDraftId"].astext == str(draft.draft_id),
        )).all()
        self.assertEqual((history.sections[0].data, history.answers_sha256), (old_raw, old_hash))
        self.assertEqual(old_raw["md_count"], "2")
        # The same text again stores nothing more.
        self.assertFalse(self._revise(va_sid, new).get_json()["changed"])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.status == "replaced", VaWebIntakeDraft.unique_id == draft.unique_id)), 1)

    def test_renaming_the_interviewer_or_a_unit_after_the_submit_is_no_change(self):
        org.seed_default_organization(self.PROJECT_ID)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT_ID)}
        district = org.create_unit(
            self.PROJECT_ID, org_level_id=levels["district"].org_level_id, unit_code="RVD01", unit_name="Rev District",
        )
        original_name = self.interviewer.name
        self.interviewer.name = "Rev Interviewer"  # letters only: Id10010 is a locked answer
        db.session.commit()
        try:
            _death, va_sid = self._submitted(case={"org_unit_id": str(district.org_unit_id)})
            allocation, initial = self._start_coding(va_sid)
            first = self._versions(va_sid)[0].payload_data
            self.assertEqual(first["SubmitterName"], "Rev Interviewer")
            self.assertEqual(first["org_district_name"], "Rev District")
            self.assertEqual(first["Id10010"], "Rev Interviewer")

            self.interviewer.name = "Renamed Person"
            db.session.get(type(district), district.org_unit_id).unit_name = "Renamed District"
            db.session.commit()
            response = self._revise(va_sid, _answers())

            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertFalse(response.get_json()["changed"])
            self.assertEqual(len(self._versions(va_sid)), 1)
            db.session.expire_all()
            self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.active)
            self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_CODING_IN_PROGRESS)
            # A real change still carries the stored values, not today's.
            changed = self._revise(va_sid, _answers(Id10007="Ramesh"))
            self.assertTrue(changed.get_json()["changed"])
            second = self._versions(va_sid)[-1].payload_data
            self.assertEqual(
                (second["SubmitterName"], second["org_district_name"], second["Id10010"]),
                ("Rev Interviewer", "Rev District", "Rev Interviewer"),
            )
        finally:
            self.interviewer.name = original_name
            db.session.commit()

    # ── refusals ───────────────────────────────────────────────────────────

    def test_a_protected_workflow_state_is_locked(self):
        _death, va_sid = self._submitted()
        set_submission_workflow_state(va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.commit()
        versions = len(self._versions(va_sid))

        response = self._revise(va_sid, _answers(Id10017="Binita"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "revision_locked")
        self.assertEqual(len(self._versions(va_sid)), versions)
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_CODER_FINALIZED)

    def test_a_duplicate_or_cancelled_case_is_closed_to_revision(self):
        for status in ("duplicate", "cancelled"):
            with self.subTest(status=status):
                death_id, va_sid = self._submitted()
                db.session.get(VaDeathRegister, death_id).status = status
                db.session.commit()

                response = self._revise(va_sid, _answers(Id10017="Binita"))

                self.assertEqual((response.status_code, response.get_json()["code"]), (409, "case_closed"))
                self.assertEqual(len(self._versions(va_sid)), 1)
                self.assertEqual(self._draft(va_sid).answers_sha256, self._versions(va_sid)[0].answers_sha256)

    def test_a_coder_finalising_mid_revision_rolls_everything_back(self):
        _death, va_sid = self._submitted()
        allocation, initial = self._start_coding(va_sid)
        before = self._draft(va_sid).answers_sha256
        actions = self._actions(va_sid)

        with patch("app.services.web_intake_service.route_synced_submission", side_effect=WorkflowTransitionError("finalised")):
            response = self._revise(va_sid, _answers(Id10017="Binita"))

        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "revision_locked"))
        db.session.expire_all()
        (version,) = self._versions(va_sid)
        self.assertEqual(version.version_status, "active")
        self.assertEqual(version.payload_data["Id10017"], "Bina")
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.active)
        self.assertEqual(db.session.get(VaInitialAssessments, initial.va_iniassess_id).va_iniassess_status, VaStatuses.active)
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(self._actions(va_sid), actions)
        self.assertEqual(self._draft(va_sid).answers_sha256, before)

    def test_only_the_submitting_interviewer_may_revise(self):
        death_id, va_sid = self._submitted()
        # The teammate's own upload for the closed case is kept as a superseded copy.
        copy = self._upload(death_id, _answers(Id10017="Other"), user_id=self.teammate_id)
        self.assertEqual(copy.status_code, 201, copy.get_json())
        self.assertIsNone(copy.get_json()["va_sid"])
        self.assertEqual(self._revise(va_sid, _answers(Id10017="Binita"), user_id=self.teammate_id).status_code, 404)
        self.assertEqual(self._revise("web-nope-rvn01rv0101", _answers()).status_code, 404)
        self.assertEqual(len(self._versions(va_sid)), 1)

    def test_bad_reason_hash_or_body_stores_nothing(self):
        _death, va_sid = self._submitted()
        new = _answers(Id10017="Binita")
        text = _text(new)
        cases = (
            ({"reason_code": "because I said so"}, 422, "invalid_reason"),
            ({"reason_code": None}, 422, "invalid_interview"),
            ({"answers_sha256": _sha(text + " ")}, 422, "answers_hash_invalid"),
            ({"answers_sha256": "nope"}, 422, "answers_hash_required"),
            ({"draft": {"completedAt": "yesterday"}}, 422, "invalid_interview"),
            ({"draft": None}, 422, "invalid_interview"),
        )
        for over, status, code in cases:
            with self.subTest(over=over):
                response = self._revise(va_sid, new, **over)
                self.assertEqual((response.status_code, response.get_json()["code"]), (status, code))
        self.assertEqual(len(self._versions(va_sid)), 1)
        self.assertEqual(self._draft(va_sid).answers_sha256, self._versions(va_sid)[0].answers_sha256)

    def test_a_completed_interview_revised_to_incomplete_or_refused_leaves_coding_and_the_case(self):
        """The latest completed version wins even when the outcome regresses
        (digitva-xpqm): coding is released, the case leaves ``submitted`` and
        loses its winner, and finishing it again restores both."""
        for name, answers, valid, outcome, case_status in (
            ("partial", _answers(interview_outcome="partially_completed"), False, "partially_completed", "paused"),
            ("refused", _answers(Id10013="no"), True, "refused", "refused"),
            ("unavailable", _answers(interview_outcome="respondent_unavailable"), False,
             "respondent_unavailable", "not_reachable"),
        ):
            with self.subTest(name=name):
                death_id, va_sid = self._submitted()
                allocation, initial = self._start_coding(va_sid)
                response = self._revise(va_sid, answers, valid=valid)
                self.assertEqual(response.status_code, 200, response.get_json())
                body = response.get_json()
                self.assertEqual((body["changed"], body["outcome"], body["workflow_state"]), (True, outcome, WORKFLOW_CONSENT_REFUSED))
                db.session.expire_all()
                death = db.session.get(VaDeathRegister, death_id)
                self.assertEqual((death.status, death.va_sid), (case_status, None))
                self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.deactive)
                self.assertEqual(db.session.get(VaInitialAssessments, initial.va_iniassess_id).va_iniassess_status, VaStatuses.deactive)
                self.assertEqual(self._draft(va_sid).meta["interviewOutcome"], outcome)
                moved = db.session.scalar(sa.select(MapCaseTransition).where(
                    MapCaseTransition.death_id == uuid.UUID(death_id), MapCaseTransition.from_state == "submitted"))
                self.assertEqual((moved.to_state, moved.actor_user_id), (case_status, self.interviewer.user_id))
                # Finishing the interview again makes it the case's winner again.
                again = self._revise(va_sid, _answers(Id10017="Bina"), reason="finish_partial")
                self.assertEqual(again.status_code, 200, again.get_json())
                db.session.expire_all()
                death = db.session.get(VaDeathRegister, death_id)
                self.assertEqual((death.status, death.va_sid), ("submitted", va_sid))
                self.assertEqual(len(self._versions(va_sid)), 3)

    def test_a_regression_from_a_case_a_teammate_won_is_still_refused(self):
        death_id, va_sid = self._partial()
        self._upload(death_id, _answers(Id10017="Other"), user_id=self.teammate_id)
        response = self._revise(va_sid, {"Id10013": "no", "Id10017": "Bina"})
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "case_state_conflict"))

    def test_the_servers_own_reason_resubmitted_is_not_a_public_reason(self):
        _death, va_sid = self._submitted()
        response = self._revise(va_sid, _answers(Id10017="Binita"), reason="resubmitted")
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_reason"))
        self.assertEqual(len(self._versions(va_sid)), 1)

    def test_a_changed_revision_recounts_the_kpi_rows_and_stores_its_completion_time(self):
        _death, va_sid = self._submitted()
        with patch("app.services.case_transition_service._recompute_kpi_rows_after_commit") as recount:
            response = self._revise(va_sid, _answers(Id10017="Binita"))
            self.assertEqual(response.get_json()["changed"], True)
            recount.assert_called_once_with(va_sid)
            recount.reset_mock()
            unchanged = self._revise(va_sid, _answers(Id10017="Binita"))
            self.assertEqual(unchanged.get_json()["changed"], False)
            recount.assert_not_called()
        done = datetime.now(UTC) - timedelta(hours=1)
        changed = self._revise(
            va_sid, _answers(Id10017="Third"), draft={"completedAt": done.isoformat(), "deviceClockAt": datetime.now(UTC).isoformat()})
        self.assertEqual(changed.get_json()["changed"], True)
        stored = datetime.fromisoformat(self._draft(va_sid).meta["effectiveSavedAt"])
        self.assertLess(abs((stored - done).total_seconds()), 60)

    # ── finishing a partial interview ──────────────────────────────────────

    def _partial(self):
        death_id = self._case()
        response = self._upload(
            death_id, {"Id10013": "yes", "Id10017": "Bina", "interview_outcome": "partially_completed"}, valid=False,
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["outcome"], "partially_completed")
        return death_id, response.get_json()["va_sid"]

    def test_finishing_a_partial_interview_submits_the_case_and_enters_coding(self):
        death_id, va_sid = self._partial()
        db.session.expire_all()
        death = db.session.get(VaDeathRegister, death_id)
        self.assertEqual((death.status, death.va_sid), ("paused", None))
        self.assertNotEqual(get_submission_workflow_state(va_sid), WORKFLOW_SMARTVA_PENDING)

        response = self._revise(va_sid, _answers(), reason="finish_partial")

        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual((body["changed"], body["outcome"], body["workflow_state"]), (True, "completed", WORKFLOW_SMARTVA_PENDING))
        db.session.expire_all()
        death = db.session.get(VaDeathRegister, death_id)
        self.assertEqual((death.status, death.va_sid), ("submitted", va_sid))
        first, second = self._versions(va_sid)
        self.assertEqual((first.version_status, second.version_status), ("superseded", "active"))
        self.assertEqual(second.revision_reason_code, "finish_partial")
        self.assertEqual(self._draft(va_sid).meta["interviewOutcome"], "completed")
        # The case is now closed: a later complete upload is a superseded copy.
        later = self._upload(death_id, _answers(Id10017="Other"), user_id=self.teammate_id)
        self.assertIsNone(later.get_json()["va_sid"])

    def test_finishing_a_partial_after_a_teammate_submitted_is_refused(self):
        death_id, va_sid = self._partial()
        won = self._upload(death_id, _answers(Id10017="Other"), user_id=self.teammate_id)
        self.assertEqual(won.status_code, 201, won.get_json())
        winner = won.get_json()["va_sid"]
        self.assertIsNotNone(winner)

        response = self._revise(va_sid, _answers(), reason="finish_partial")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "case_already_submitted")
        self.assertEqual(len(self._versions(va_sid)), 1)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaDeathRegister, death_id).va_sid, winner)

    def test_a_partial_can_be_revised_and_stay_partial(self):
        death_id, va_sid = self._partial()
        response = self._revise(
            va_sid, {"Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "interview_outcome": "partially_completed"},
            valid=False, reason="more_information",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual((response.get_json()["changed"], response.get_json()["outcome"]), (True, "partially_completed"))
        db.session.expire_all()
        self.assertEqual(db.session.get(VaDeathRegister, death_id).status, "paused")

    def test_finishing_a_partial_needs_a_live_org_unit_before_anything_is_written(self):
        death_id, va_sid = self._partial()
        with patch(
            "app.services.web_intake_service._require_live_org_unit", side_effect=WebIntakeError("unit inactive", 409)
        ) as live:
            finish = self._revise(va_sid, _answers(), reason="finish_partial")
            still_partial = self._revise(
                va_sid, {"Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "interview_outcome": "partially_completed"},
                valid=False,
            )

        self.assertEqual(finish.status_code, 409)
        self.assertEqual(live.call_count, 1)  # only the revision that enters coding asks
        self.assertEqual(still_partial.status_code, 200)
        self.assertEqual(len(self._versions(va_sid)), 2)  # the partial-to-partial one only
        db.session.expire_all()
        self.assertEqual(db.session.get(VaDeathRegister, death_id).status, "paused")

    def test_changing_between_incomplete_outcomes_moves_the_case(self):
        death_id, va_sid = self._partial()
        steps = (
            ({"Id10013": "no", "Id10017": "Bina"}, True, "refused", "refused"),
            ({"Id10013": "yes", "Id10017": "Bina", "interview_outcome": "respondent_unavailable"}, False,
             "respondent_unavailable", "not_reachable"),
            ({"Id10013": "yes", "Id10017": "Bina", "interview_outcome": "partially_completed"}, False,
             "partially_completed", "paused"),
        )
        for answers, valid, outcome, case_status in steps:
            with self.subTest(outcome=outcome):
                response = self._revise(va_sid, answers, valid=valid)

                self.assertEqual(response.status_code, 200, response.get_json())
                self.assertEqual(response.get_json()["outcome"], outcome)
                db.session.expire_all()
                death = db.session.get(VaDeathRegister, death_id)
                self.assertEqual((death.status, death.va_sid), (case_status, None))
                self.assertEqual(self._draft(va_sid).meta["interviewOutcome"], outcome)

    def test_an_outcome_change_is_refused_when_the_case_has_moved_on(self):
        death_id, va_sid = self._partial()
        won = self._upload(death_id, _answers(Id10017="Other"), user_id=self.teammate_id)
        self.assertIsNotNone(won.get_json()["va_sid"])

        response = self._revise(va_sid, {"Id10013": "no", "Id10017": "Bina"})

        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "case_state_conflict"))
        self.assertEqual(len(self._versions(va_sid)), 1)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaDeathRegister, death_id).status, "submitted")
        self.assertEqual(self._draft(va_sid).meta["interviewOutcome"], "partially_completed")
