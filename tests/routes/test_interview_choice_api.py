"""A supervisor chooses between two complete interviews of one case (digitva-bqzm).

POST /api/v1/intake/supervision/cases/<death_id>/choose-interview. A second
interviewer's complete interview of a submitted case is kept as a superseded
copy and is a candidate; a supervisor, data manager or admin may choose it at
any stage (even after final COD) and may switch back. Policy: docs/policy/web-intake.md
"Parallel interviews"; reason ``supervisor_choice`` in docs/policy/interview-revisions.md.
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
    MapUserNotification,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaInitialAssessments,
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
from app.services import notification_service
from app.services.final_cod_authority_service import upsert_final_cod_authority
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase

API = "/api/v1/intake"
SUPERVISION = f"{API}/supervision/cases"


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


class InterviewChoiceTests(BaseTestCase):
    PROJECT_ID = "CHO01"
    OTHER_PROJECT_ID = "CHO02"
    SITE_ID = "CH01"
    ODK_FORM_ID = "CHO01CH0101"

    @classmethod
    def _project(cls, project_id):
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=project_id, project_nickname=project_id,
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
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Choice Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        cls._project(cls.PROJECT_ID)
        cls._project(cls.OTHER_PROJECT_ID)
        db.session.add(VaForms(
            form_id=cls.ODK_FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_CHOICE", odk_project_id="9", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        cls.users = {
            name: cls._get_or_make_user(f"cho.{name}@test.local", "Choice123")
            for name in ("alice", "bela", "dm", "other_dm")
        }
        for name, role, project in (
            ("alice", VaAccessRoles.interviewer, cls.PROJECT_ID),
            ("bela", VaAccessRoles.interviewer, cls.PROJECT_ID),
            ("dm", VaAccessRoles.data_manager, cls.PROJECT_ID),
            ("other_dm", VaAccessRoles.data_manager, cls.OTHER_PROJECT_ID),
        ):
            db.session.add(VaUserAccessGrants(
                user_id=cls.users[name].user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=project, notes="choice test grant", grant_status=VaStatuses.active,
            ))
        db.session.commit()
        for name, user in cls.users.items():
            setattr(cls, name, user)
            setattr(cls, f"{name}_id", str(user.user_id))

    # ── helpers ────────────────────────────────────────────────────────────

    def _case(self):
        self._login(self.alice_id)
        response = self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Bina Sahu",
            "deceased_sex": "female", "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["case"]["death_id"]

    def _upload(self, user_id, death_id, answers, *, valid=True, client_draft_id=None, **draft):
        self._login(user_id)
        text = _text(answers)
        return self.client.post(f"{API}/submissions", headers=self._csrf_headers(), json={
            "client_draft_id": str(client_draft_id or uuid.uuid4()), "project_id": self.PROJECT_ID,
            "site_id": self.SITE_ID, "death_id": death_id,
            "draft": {"startedAt": datetime.now(UTC).isoformat(), **draft},
            "completion": {"valid": valid, "issues": []}, "answers_json": text, "answers_sha256": _sha(text),
        })

    def _pair(self, *, alice_cdi=None):
        """Alice's complete interview wins; Bela's complete one is kept as a
        candidate. Returns (death_id, va_sid, alice_draft, bela_draft)."""
        death_id = self._case()
        won = self._upload(self.alice_id, death_id, _answers(), client_draft_id=alice_cdi)
        self.assertEqual(won.status_code, 201, won.get_json())
        late = self._upload(self.bela_id, death_id, _answers(Id10017="Meena"))
        self.assertEqual(late.status_code, 201, late.get_json())
        self.assertTrue(late.get_json()["superseded"])
        va_sid = won.get_json()["va_sid"]
        return death_id, va_sid, self._draft(self.alice_id, death_id), self._draft(self.bela_id, death_id)

    def _draft(self, user_id, death_id):
        db.session.expire_all()
        return db.session.scalar(
            sa.select(VaWebIntakeDraft).where(
                VaWebIntakeDraft.user_id == uuid.UUID(user_id), VaWebIntakeDraft.death_id == uuid.UUID(death_id),
                VaWebIntakeDraft.status.in_(("submitted", "superseded")),
            ).order_by(VaWebIntakeDraft.created_at)
        )

    def _choose(self, user_id, death_id, draft_id, reason="better_quality"):
        self._login(user_id)
        return self.client.post(
            f"{SUPERVISION}/{death_id}/choose-interview", headers=self._csrf_headers(),
            json={"draft_id": str(draft_id), "reason_code": reason},
        )

    def _state(self, va_sid, state=None):
        db.session.expire_all()
        if state is not None:
            set_submission_workflow_state(va_sid, state, reason="test", by_role="test")
            db.session.commit()
        return get_submission_workflow_state(va_sid)

    def _start_coding(self, va_sid):
        self._state(va_sid, WORKFLOW_CODING_IN_PROGRESS)
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

    def _finalise(self, va_sid, state=WORKFLOW_CODER_FINALIZED):
        final = VaFinalAssessments(
            va_sid=va_sid, va_finassess_by=self.base_coder_user.user_id, va_conclusive_cod="R99",
            payload_version_id=get_active_payload_version(va_sid).payload_version_id,
            va_finassess_status=VaStatuses.active, va_finassess_createdat=datetime.now(UTC) - timedelta(hours=30),
        )
        db.session.add(final)
        db.session.flush()
        upsert_final_cod_authority(va_sid, final, reason="final_cod_submitted", source_role="vacoder",
                                   updated_by=self.base_coder_user.user_id)
        self._state(va_sid, state)
        return final

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

    def _notifications(self, user, kind=notification_service.INTERVIEW_CHOSEN):
        db.session.expire_all()
        return db.session.scalars(
            sa.select(MapUserNotification).where(
                MapUserNotification.user_id == user.user_id, MapUserNotification.kind == kind,
            ).order_by(MapUserNotification.id)
        ).all()

    def _case_get(self, user_id, url):
        self._login(user_id)
        return self.client.get(url)

    # ── candidates ─────────────────────────────────────────────────────────

    def test_a_second_complete_interview_is_a_candidate_and_an_incomplete_one_is_not(self):
        death_id, _va_sid, alice_draft, bela_draft = self._pair()
        self.assertEqual((alice_draft.status, bela_draft.status), ("submitted", "superseded"))
        self.assertEqual(bela_draft.meta["interviewOutcome"], "completed")
        # An incomplete copy by the same interviewer never qualifies.
        partial = self._upload(
            self.bela_id, death_id, {**_answers(), "interview_outcome": "partially_completed"}, valid=False)
        self.assertEqual(partial.status_code, 201, partial.get_json())

        detail = self._case_get(self.dm_id, f"{SUPERVISION}/{death_id}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        candidates = detail.get_json()["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["draft_id"], str(bela_draft.draft_id))
        self.assertEqual(candidates[0]["interviewer_name"], self.bela.name)
        self.assertEqual(candidates[0]["outcome"], "completed")
        self.assertTrue(candidates[0]["completed_at"])
        self.assertIs(detail.get_json()["case"]["other_complete_interview"], True)

    def test_a_superseded_copy_made_by_a_browser_submit_records_its_outcome(self):
        death_id = self._case()
        self._login(self.bela_id)
        headers = self._csrf_headers()
        draft = self.client.post(f"{API}/drafts", headers=headers, json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_id": death_id,
        })
        self.assertEqual(draft.status_code, 201, draft.get_json())
        self.assertEqual(self._upload(self.alice_id, death_id, _answers()).status_code, 201)
        self._login(self.bela_id)
        submit = self.client.post(f"{API}/drafts/{draft.get_json()['draft']['draft_id']}/submit", headers=self._csrf_headers(), json={
            "completion": {"valid": True, "issues": [], "data": _answers(Id10017="Meena")},
        })
        self.assertEqual(submit.status_code, 200, submit.get_json())
        self.assertTrue(submit.get_json()["superseded"])
        copy = self._draft(self.bela_id, death_id)
        self.assertEqual((copy.status, (copy.meta or {}).get("interviewOutcome")), ("superseded", "completed"))

    def test_flag_and_queue_show_a_second_interview_to_everyone_and_names_to_supervisors_only(self):
        death_id, _va_sid, _alice, bela_draft = self._pair()
        plain = self._submitted_without_candidate()

        for user_id in (self.alice_id, self.bela_id):
            row = self._case_get(user_id, f"{API}/cases/{death_id}").get_json()["case"]
            self.assertIs(row["other_complete_interview"], True)
            self.assertNotIn(self.bela.name, json.dumps(row))
            self.assertNotIn(self.alice.name, json.dumps(row))
        alone = self._case_get(self.alice_id, f"{API}/cases/{plain}").get_json()["case"]
        self.assertIs(alone["other_complete_interview"], False)
        listed = {c["death_id"]: c for c in self._case_get(self.alice_id, f"{API}/cases").get_json()["cases"]}
        self.assertIs(listed[death_id]["other_complete_interview"], True)
        self.assertIs(listed[plain]["other_complete_interview"], False)

        queue = self._case_get(self.dm_id, f"{SUPERVISION}?candidates=true&limit=200").get_json()
        queued = [c["death_id"] for c in queue["cases"]]
        self.assertIn(death_id, queued)
        self.assertNotIn(plain, queued)
        self.assertTrue(all(c["other_complete_interview"] for c in queue["cases"]))
        everything = {c["death_id"]: c for c in self._case_get(self.dm_id, f"{SUPERVISION}?limit=200").get_json()["cases"]}
        self.assertIs(everything[plain]["other_complete_interview"], False)
        self.assertEqual(self._case_get(self.dm_id, f"{SUPERVISION}?candidates=maybe").status_code, 400)
        # An interviewer has no supervision detail, so no names.
        self.assertEqual(self._case_get(self.bela_id, f"{SUPERVISION}/{death_id}").status_code, 403)
        self.assertIsNotNone(bela_draft)

    def _submitted_without_candidate(self):
        death_id = self._case()
        self.assertEqual(self._upload(self.alice_id, death_id, _answers()).status_code, 201)
        return death_id

    # ── choosing ───────────────────────────────────────────────────────────

    def test_choosing_an_interview_copies_its_age_and_clears_a_date_of_birth_it_calls_unknown(self):
        death_id = self._case()
        death = db.session.get(VaDeathRegister, uuid.UUID(death_id))
        death.date_of_birth_partial = "1950"
        db.session.commit()
        self.assertEqual(self._upload(self.alice_id, death_id, _answers()).status_code, 201)
        bela = self._upload(self.bela_id, death_id, _answers(
            Id10017="Meena", Id10020="no", dob_precision="neither", age_group="adult", age_adult="45",
        ))
        self.assertTrue(bela.get_json()["superseded"], bela.get_json())
        db.session.expire_all()
        self.assertEqual((death.date_of_birth_partial, death.age_years), ("1950", 71))  # Alice's keeps both
        response = self._choose(self.dm_id, death_id, self._draft(self.bela_id, death_id).draft_id)
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.expire_all()
        death = db.session.get(VaDeathRegister, uuid.UUID(death_id))
        self.assertEqual((death.date_of_birth, death.date_of_birth_partial, death.age_years), (None, None, 45))

    def test_choosing_before_coding_replaces_the_coders_copy_and_keeps_the_sid(self):
        death_id, va_sid, alice_draft, bela_draft = self._pair()
        allocation, initial = self._start_coding(va_sid)
        before = get_active_payload_version(va_sid)
        before_id = before.payload_version_id
        self.assertEqual(before.payload_data["SubmitterID"], self.alice_id)

        with patch("app.services.case_transition_service._recompute_kpi_rows_after_commit") as recount:
            response = self._choose(self.dm_id, death_id, bela_draft.draft_id)

        self.assertEqual(response.status_code, 200, response.get_json())
        recount.assert_called_once_with(va_sid)
        case = response.get_json()["case"]
        self.assertEqual((case["va_sid"], case["state"]), (va_sid, "submitted"))
        self.assertIs(case["other_complete_interview"], True)  # Alice's is now the candidate
        db.session.expire_all()
        # The same submission, the new interviewer's answers as a new version.
        version = get_active_payload_version(va_sid)
        self.assertNotEqual(version.payload_version_id, before_id)
        self.assertEqual(db.session.get(VaSubmissionPayloadVersion, before_id).version_status, "superseded")
        self.assertEqual(version.revision_reason_code, "supervisor_choice")
        self.assertEqual(version.created_by, self.dm.user_id)
        self.assertEqual(version.answers_sha256, bela_draft.answers_sha256)
        payload = version.payload_data
        self.assertEqual((payload["sid"], payload["SubmitterID"], payload["Id10017"]), (va_sid, self.bela_id, "Meena"))
        self.assertEqual(payload["KEY"], before.payload_data["KEY"])
        self.assertEqual(payload["instanceID"], before.payload_data["instanceID"])
        self.assertEqual(payload["SubmissionDate"], before.payload_data["SubmissionDate"])
        self.assertEqual(db.session.get(VaSubmissions, va_sid).va_data_collector, self.bela.name)
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(death_id)).deceased_name, "Meena Sahu")
        # The drafts swap.
        alice_draft, bela_draft = self._draft(self.alice_id, death_id), self._draft(self.bela_id, death_id)
        self.assertEqual((bela_draft.status, bela_draft.va_sid), ("submitted", va_sid))
        self.assertIn("effectiveSavedAt", bela_draft.meta)
        self.assertEqual((alice_draft.status, alice_draft.va_sid), ("superseded", None))
        self.assertEqual((alice_draft.meta["previousVaSid"], alice_draft.meta["interviewOutcome"]), (va_sid, "completed"))
        # The coder's copy is dropped (history kept), coding restarts.
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status, VaStatuses.deactive)
        self.assertEqual(db.session.get(VaInitialAssessments, initial.va_iniassess_id).va_iniassess_status, VaStatuses.deactive)
        self.assertEqual(self._state(va_sid), WORKFLOW_SMARTVA_PENDING)
        # Audited.
        actions = self._actions(va_sid)
        self.assertIn("va_submission_interview_chosen_by_supervisor:better_quality", actions)
        self.assertIn("va_initialasses_deletion_during_supervisor_choice", actions)
        transition = db.session.scalar(sa.select(MapCaseTransition).where(
            MapCaseTransition.death_id == uuid.UUID(death_id), MapCaseTransition.action == "interview_chosen"))
        self.assertEqual(
            (transition.from_state, transition.to_state, transition.reason, transition.actor_user_id),
            ("submitted", "submitted", "better_quality", self.dm.user_id))
        # Both interviewers are nudged, ids only; only the chosen one gets the sid.
        chosen, previous = self._notifications(self.bela), self._notifications(self.alice)
        self.assertEqual((len(chosen), len(previous)), (1, 1))
        self.assertEqual((chosen[0].va_sid, chosen[0].draft_id, chosen[0].death_id), (va_sid, bela_draft.draft_id, uuid.UUID(death_id)))
        self.assertEqual((previous[0].va_sid, previous[0].draft_id), (None, alice_draft.draft_id))

    def test_choosing_after_final_cod_restarts_coding_and_keeps_the_old_cod_as_history(self):
        for state in (WORKFLOW_CODER_FINALIZED, WORKFLOW_REVIEWER_FINALIZED):
            death_id, va_sid, _alice, bela_draft = self._pair()
            final = self._finalise(va_sid, state)
            reviewer_final = None
            if state == WORKFLOW_REVIEWER_FINALIZED:
                reviewer_final = VaReviewerFinalAssessments(
                    va_sid=va_sid, va_rfinassess_by=self.base_coder_user.user_id, va_conclusive_cod="R99",
                    va_rfinassess_status=VaStatuses.active,
                )
                db.session.add(reviewer_final)
                db.session.commit()

            response = self._choose(self.dm_id, death_id, bela_draft.draft_id, "more_complete")

            self.assertEqual(response.status_code, 200, (state, response.get_json()))
            self.assertEqual(self._state(va_sid), WORKFLOW_SMARTVA_PENDING)
            db.session.expire_all()
            old = db.session.get(VaFinalAssessments, final.va_finassess_id)
            self.assertEqual(old.va_finassess_status, VaStatuses.deactive)  # present, as history
            if reviewer_final is not None:
                self.assertEqual(
                    db.session.get(VaReviewerFinalAssessments, reviewer_final.va_rfinassess_id).va_rfinassess_status,
                    VaStatuses.deactive)
            self.assertIsNone(db.session.scalar(sa.select(VaFinalCodAuthority.authoritative_final_assessment_id)
                                                .where(VaFinalCodAuthority.va_sid == va_sid)))
            chosen = [(e[1], e[2]) for e in self._events(va_sid) if e[0] == "interview_chosen"]
            self.assertEqual(
                chosen[:2], [("finalized_upstream_changed", "data_manager"), (WORKFLOW_SMARTVA_PENDING, "system")])
            self.assertIn("va_finalasses_deletion_during_supervisor_choice", self._actions(va_sid))

    def test_switching_back_restores_the_first_interview(self):
        death_id, va_sid, alice_draft, bela_draft = self._pair()
        self.assertEqual(self._choose(self.dm_id, death_id, bela_draft.draft_id).status_code, 200)
        self._finalise(va_sid)

        response = self._choose(self.dm_id, death_id, alice_draft.draft_id, "switch_back")

        self.assertEqual(response.status_code, 200, response.get_json())
        alice_draft, bela_draft = self._draft(self.alice_id, death_id), self._draft(self.bela_id, death_id)
        self.assertEqual((alice_draft.status, alice_draft.va_sid), ("submitted", va_sid))
        self.assertEqual((bela_draft.status, bela_draft.va_sid), ("superseded", None))
        self.assertNotIn("previousVaSid", alice_draft.meta)
        self.assertEqual(bela_draft.meta["previousVaSid"], va_sid)
        payload = get_active_payload_version(va_sid).payload_data
        self.assertEqual((payload["SubmitterID"], payload["Id10017"], payload["sid"]), (self.alice_id, "Bina", va_sid))
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(death_id)).deceased_name, "Bina Sahu")
        self.assertEqual(db.session.get(VaSubmissions, va_sid).va_data_collector, self.alice.name)
        self.assertEqual(self._state(va_sid), WORKFLOW_SMARTVA_PENDING)
        db.session.expire_all()
        versions = db.session.scalars(sa.select(VaSubmissionPayloadVersion.revision_reason_code).where(
            VaSubmissionPayloadVersion.va_sid == va_sid).order_by(VaSubmissionPayloadVersion.version_created_at)).all()
        self.assertEqual(versions, [None, "supervisor_choice", "supervisor_choice"])
        self.assertEqual(sum(a.startswith("va_submission_interview_chosen_by_supervisor") for a in self._actions(va_sid)), 2)

    # ── refusals ───────────────────────────────────────────────────────────

    def test_only_a_complete_superseded_interview_of_this_case_is_choosable(self):
        death_id, va_sid, alice_draft, bela_draft = self._pair()
        partial = self._upload(
            self.bela_id, death_id, {**_answers(), "interview_outcome": "partially_completed"}, valid=False)
        self.assertEqual(partial.status_code, 201)
        incomplete = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == uuid.UUID(death_id), VaWebIntakeDraft.status == "superseded",
            VaWebIntakeDraft.meta["interviewOutcome"].astext == "partially_completed"))
        self.assertIsNotNone(incomplete)
        other_case = self._submitted_without_candidate()
        other_alice = self._draft(self.alice_id, other_case)
        replaced = VaWebIntakeDraft(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=uuid.UUID(death_id), form_id=bela_draft.form_id,
            user_id=self.bela.user_id, unique_id=bela_draft.unique_id, status="replaced",
            meta={"interviewOutcome": "completed"},
        )
        db.session.add(replaced)
        db.session.commit()
        before = get_active_payload_version(va_sid).payload_version_id

        for draft_id, status, code in (
            (incomplete.draft_id, 409, "not_a_candidate"),
            (alice_draft.draft_id, 409, "not_a_candidate"),   # the interview the case holds
            (replaced.draft_id, 409, "not_a_candidate"),
            (other_alice.draft_id, 404, "not_found"),          # another case's draft
            (uuid.uuid4(), 404, "not_found"),
        ):
            response = self._choose(self.dm_id, death_id, draft_id)
            self.assertEqual((response.status_code, response.get_json()["code"]), (status, code), draft_id)
        self.assertEqual(self._choose(self.dm_id, death_id, bela_draft.draft_id, "because").status_code, 422)
        self._login(self.dm_id)
        malformed = self.client.post(f"{SUPERVISION}/{death_id}/choose-interview", headers=self._csrf_headers(),
                                     json={"draft_id": "nope", "reason_code": "better_quality"})
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(get_active_payload_version(va_sid).payload_version_id, before)

    def test_a_case_that_is_not_submitted_has_nothing_to_choose(self):
        self._login(self.alice_id)
        registered = self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Raj Kumar",
            "deceased_sex": "male", "date_of_death": (date.today() - timedelta(days=3)).isoformat(), "age_years": 40,
        }).get_json()["case"]["death_id"]
        response = self._choose(self.dm_id, registered, uuid.uuid4())
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "case_not_submitted"))

    def test_only_a_supervisor_in_reach_may_choose_and_an_admin_may(self):
        death_id, va_sid, _alice, bela_draft = self._pair()

        for user_id in (self.alice_id, self.bela_id):
            self.assertEqual(self._choose(user_id, death_id, bela_draft.draft_id).status_code, 403)
        outside = self._choose(self.other_dm_id, death_id, bela_draft.draft_id)
        self.assertEqual(outside.status_code, 404)
        self.assertEqual(self._case_get(self.other_dm_id, f"{SUPERVISION}/{death_id}").status_code, 404)
        self._login(self.dm_id)
        no_csrf = self.client.post(f"{SUPERVISION}/{death_id}/choose-interview",
                                   json={"draft_id": str(bela_draft.draft_id), "reason_code": "better_quality"})
        self.assertEqual(no_csrf.status_code, 400)
        self.assertEqual(self._draft(self.bela_id, death_id).status, "superseded")

        # An admin can find the candidate on the case detail before choosing.
        self._login(str(self.base_admin_user.user_id))
        detail = self.client.get(f"{SUPERVISION}/{death_id}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertIn(str(bela_draft.draft_id), [c["draft_id"] for c in detail.get_json()["candidates"]])
        admin = self._choose(str(self.base_admin_user.user_id), death_id, bela_draft.draft_id)
        self.assertEqual(admin.status_code, 200, admin.get_json())
        self.assertEqual(self._draft(self.bela_id, death_id).va_sid, va_sid)
        self.assertEqual(self._events(va_sid)[-1][2], "system")

    def test_a_live_reviewer_session_blocks_the_choice(self):
        death_id, va_sid, alice_draft, bela_draft = self._pair()
        self._state(va_sid, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

        response = self._choose(self.dm_id, death_id, bela_draft.draft_id)

        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "wrong_state"))
        self.assertEqual(self._draft(self.alice_id, death_id).va_sid, va_sid)
        self.assertEqual(self._state(va_sid), WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self.assertEqual(alice_draft.draft_id, self._draft(self.alice_id, death_id).draft_id)

    # ── afterwards ─────────────────────────────────────────────────────────

    def test_the_chosen_interviewer_can_correct_and_the_previous_winners_resend_is_history(self):
        alice_cdi = uuid.uuid4()
        death_id, va_sid, _alice, bela_draft = self._pair(alice_cdi=alice_cdi)
        self.assertEqual(self._choose(self.dm_id, death_id, bela_draft.draft_id).status_code, 200)
        versions_before = db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid))

        # The chosen interviewer's later correction keeps the case's sid.
        later = self._upload(self.bela_id, death_id, _answers(Id10017="Meenakshi"))
        self.assertEqual(later.status_code, 201, later.get_json())
        body = later.get_json()
        self.assertEqual((body["kept"], body["locked"], body["va_sid"]), ("incoming", False, va_sid))
        payload = get_active_payload_version(va_sid).payload_data
        self.assertEqual((payload["sid"], payload["Id10017"], payload["SubmitterID"]), (va_sid, "Meenakshi", self.bela_id))
        db.session.expire_all()
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid)), versions_before + 1)
        self.assertEqual(db.session.get(VaSubmissions, va_sid).va_sid, va_sid)

        # The previous winner's later upload of the same interview no longer changes it.
        resend = self._upload(self.alice_id, death_id, _answers(Id10017="Binita"), client_draft_id=alice_cdi)
        self.assertEqual(resend.status_code, 200, resend.get_json())
        self.assertEqual((resend.get_json()["kept"], resend.get_json()["locked"]), ("server", True))
        self.assertEqual(get_active_payload_version(va_sid).payload_data["Id10017"], "Meenakshi")
        db.session.expire_all()
        history = db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id == self.alice.user_id, VaWebIntakeDraft.death_id == uuid.UUID(death_id),
            VaWebIntakeDraft.status == "replaced")).all()
        self.assertEqual(len(history), 1)
