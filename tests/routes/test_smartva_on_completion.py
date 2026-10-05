"""SmartVA runs in the background when an interview is completed or corrected
(digitva-533t), and the coding page shows and starts it.

Web and device interviews route to ``smartva_pending`` but are not on any
scheduled SmartVA path (``sync_runtime_forms_from_site_mappings`` never
returns a web form), so the submit queues ``run_smartva_for_submission`` after
commit. Policy: docs/policy/coding-workflow-state-machine.md, "SmartVA on
completion".
"""
import hashlib
import json
import uuid
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
)
from app.services import smartva_service
from app.services.runtime_form_sync_service import (
    _ensure_legacy_project_site_rows,
    sync_runtime_forms_from_site_mappings,
)
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase

INTAKE = "/api/v1/intake"
CODING = "/api/v1/coding"
DELAY = "app.tasks.sync_tasks.run_smartva_for_submission.delay"


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


class SmartvaOnCompletionTests(BaseTestCase):
    PROJECT_ID = "SVC01"
    OTHER_PROJECT_ID = "SVC02"
    SITE_ID = "SV01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="SmartVA Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        for project_id in (cls.PROJECT_ID, cls.OTHER_PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
            ))
            db.session.flush()
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.flush()
            _ensure_legacy_project_site_rows(project_id, cls.SITE_ID)
        db.session.add(VaForms(
            form_id="SVC01SV0101", project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_SVC", odk_project_id="9", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        names = ("interviewer", "coder", "reviewer", "dm", "outsider_coder", "collab", "viewer_coder")
        users = {n: cls._get_or_make_user(f"svc.{n}@test.local", "SmartvaCtl123") for n in names}
        for name, role, project in (
            ("interviewer", VaAccessRoles.interviewer, cls.PROJECT_ID),
            ("coder", VaAccessRoles.coder, cls.PROJECT_ID),
            ("reviewer", VaAccessRoles.reviewer, cls.PROJECT_ID),
            ("dm", VaAccessRoles.data_manager, cls.PROJECT_ID),
            ("outsider_coder", VaAccessRoles.coder, cls.OTHER_PROJECT_ID),
            ("collab", VaAccessRoles.collaborator, cls.PROJECT_ID),
            # Passes the role gate by coding in the other project; may only view this one.
            ("viewer_coder", VaAccessRoles.coder, cls.OTHER_PROJECT_ID),
            ("viewer_coder", VaAccessRoles.collaborator, cls.PROJECT_ID),
        ):
            db.session.add(VaUserAccessGrants(
                user_id=users[name].user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=project, notes="smartva test grant", grant_status=VaStatuses.active,
            ))
        db.session.commit()
        for name, user in users.items():
            setattr(cls, f"{name}_id", str(user.user_id))

    def setUp(self):
        super().setUp()
        self._markers = ["SID-ROLLED-BACK", "SID-NESTED"]
        limiter.reset()  # the in-memory per-user counts are shared across the class

    def tearDown(self):
        for va_sid in self._markers:
            smartva_service.clear_run_marker(va_sid)
        super().tearDown()

    # ── helpers ────────────────────────────────────────────────────────────

    def _case(self):
        self._login(self.interviewer_id)
        response = self.client.post(f"{INTAKE}/deaths", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Bina Sahu",
            "deceased_sex": "female", "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["case"]["death_id"]

    def _upload(self, death_id, answers, *, valid=True):
        self._login(self.interviewer_id)
        text = _text(answers)
        return self.client.post(f"{INTAKE}/submissions", headers=self._csrf_headers(), json={
            "client_draft_id": str(uuid.uuid4()), "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
            "death_id": death_id, "draft": {"startedAt": datetime.now(UTC).isoformat()},
            "completion": {"valid": valid, "issues": []}, "answers_json": text, "answers_sha256": _sha(text),
        })

    def _revise(self, va_sid, answers):
        self._login(self.interviewer_id)
        text = _text(answers)
        return self.client.post(f"{INTAKE}/submissions/{va_sid}/revisions", headers=self._csrf_headers(), json={
            "reason_code": "interviewer_correction", "draft": {}, "completion": {"valid": True, "issues": []},
            "answers_json": text, "answers_sha256": _sha(text),
        })

    def _submitted(self):
        """A device-uploaded completed interview with the queue call mocked
        away; returns (death_id, va_sid)."""
        death_id = self._case()
        with mock.patch(DELAY):
            response = self._upload(death_id, _answers())
        self.assertEqual(response.status_code, 201, response.get_json())
        va_sid = response.get_json()["va_sid"]
        self._markers.append(va_sid)
        smartva_service.clear_run_marker(va_sid)
        return death_id, va_sid

    def _result(self, va_sid, *, outcome=VaSmartvaResults.OUTCOME_SUCCESS, payload=True):
        row = VaSmartvaResults(
            va_smartva_id=uuid.uuid4(), va_sid=va_sid,
            payload_version_id=get_active_payload_version(va_sid).payload_version_id if payload else None,
            va_smartva_outcome=outcome, va_smartva_status=VaStatuses.active,
            va_smartva_cause1="Stroke" if outcome == VaSmartvaResults.OUTCOME_SUCCESS else None,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def _state(self, va_sid, state):
        set_submission_workflow_state(va_sid, state, reason="test", by_role="test")
        db.session.commit()

    # ── verification (digitva-533t): nothing scheduled ever reaches a web form ──

    def test_a_web_submission_waits_in_smartva_pending_outside_every_scheduled_path(self):
        _death, va_sid = self._submitted()
        form_id = db.session.get(VaSubmissions, va_sid).va_form_id
        form = db.session.get(VaForms, form_id)

        self.assertEqual(form.form_source, "web")
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_SMARTVA_PENDING)
        # generate_all_pending walks exactly this list; the web form is not in it.
        self.assertNotIn(form_id, {f.form_id for f in sync_runtime_forms_from_site_mappings()})
        self.assertIn(va_sid, smartva_service.pending_smartva_sids(form_id))

    # ── queue on completion, after commit only ─────────────────────────────

    def test_a_device_upload_queues_smartva_once_after_commit(self):
        death_id = self._case()
        with mock.patch(DELAY) as delay:
            response = self._upload(death_id, _answers())
        self.assertEqual(response.status_code, 201, response.get_json())
        va_sid = response.get_json()["va_sid"]
        self._markers.append(va_sid)

        delay.assert_called_once_with(va_sid=va_sid, triggered_by="web_intake_submit", regenerate=False)
        self.assertEqual(smartva_service.smartva_status(va_sid), smartva_service.SMARTVA_QUEUED)

    def test_a_browser_submit_queues_smartva(self):
        death_id = self._case()
        self._login(self.interviewer_id)
        draft = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_id": death_id,
        }).get_json()["draft"]
        with mock.patch(DELAY) as delay:
            response = self.client.post(f"{INTAKE}/drafts/{draft['draft_id']}/submit", headers=self._csrf_headers(),
                                        json={"completion": {"valid": True, "issues": [], "data": _answers()}})
        self.assertEqual(response.status_code, 201, response.get_json())
        va_sid = response.get_json()["va_sid"]
        self._markers.append(va_sid)

        delay.assert_called_once_with(va_sid=va_sid, triggered_by="web_intake_submit", regenerate=False)

    def test_nothing_is_queued_when_the_transaction_rolls_back(self):
        with mock.patch(DELAY) as delay:
            db.session.execute(sa.text("SELECT 1"))  # the transaction the case writes belong to
            smartva_service.queue_smartva_after_commit("SID-ROLLED-BACK", "web_intake_submit")
            db.session.rollback()
            db.session.commit()
        delay.assert_not_called()
        self.assertEqual(smartva_service.smartva_status("SID-ROLLED-BACK"), smartva_service.SMARTVA_NOT_REQUESTED)

    def test_the_queued_marker_is_set_before_the_commit_so_the_sweep_skips_the_sid(self):
        self._markers.append("SID-NESTED")
        with mock.patch(DELAY):
            db.session.execute(sa.text("SELECT 1"))
            smartva_service.queue_smartva_after_commit("SID-NESTED", "interview_revision")
            self.assertEqual(smartva_service.smartva_status("SID-NESTED"), smartva_service.SMARTVA_QUEUED)
            db.session.rollback()

    def test_the_queue_waits_for_the_outer_commit(self):
        self._markers.append("SID-NESTED")
        with mock.patch(DELAY) as delay:
            db.session.execute(sa.text("SELECT 1"))
            smartva_service.queue_smartva_after_commit("SID-NESTED", "interview_revision")
            savepoint = db.session.begin_nested()
            savepoint.commit()
            delay.assert_not_called()
            db.session.commit()
        delay.assert_called_once_with(va_sid="SID-NESTED", triggered_by="interview_revision", regenerate=False)

    def test_a_refused_or_partial_interview_is_never_queued(self):
        for name, answers, valid in (
            ("refused", _answers(Id10013="no"), True),
            ("partial", {"Id10013": "yes", "Id10017": "Bina", "interview_outcome": "partially_completed"}, False),
        ):
            with self.subTest(name=name):
                death_id = self._case()
                with mock.patch(DELAY) as delay:
                    response = self._upload(death_id, answers, valid=valid)
                self.assertEqual(response.status_code, 201, response.get_json())
                self.assertEqual(get_submission_workflow_state(response.get_json()["va_sid"]), WORKFLOW_CONSENT_REFUSED)
                delay.assert_not_called()

    def test_a_superseded_copy_is_never_queued(self):
        death_id = self._case()
        with mock.patch(DELAY):
            first = self._upload(death_id, _answers())
        self.assertEqual(first.status_code, 201)
        self._markers.append(first.get_json()["va_sid"])
        # The interviewer's own second upload is a correction, not a copy; a
        # teammate's upload on the now submitted case is the superseded copy.
        teammate = self._get_or_make_user("svc.teammate@test.local", "SmartvaCtl123")
        db.session.add(VaUserAccessGrants(
            user_id=teammate.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID, notes="smartva test grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(teammate.user_id))
        text = _text(_answers(Id10017="Other"))
        with mock.patch(DELAY) as delay:
            response = self.client.post(f"{INTAKE}/submissions", headers=self._csrf_headers(), json={
                "client_draft_id": str(uuid.uuid4()), "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
                "death_id": death_id, "draft": {"startedAt": datetime.now(UTC).isoformat()},
                "completion": {"valid": True, "issues": []}, "answers_json": text, "answers_sha256": _sha(text),
            })
        self.assertIn(response.status_code, (200, 201, 409), response.get_json())
        delay.assert_not_called()

    def test_a_changed_revision_queues_smartva_and_an_unchanged_one_does_not(self):
        _death, va_sid = self._submitted()
        self._state(va_sid, WORKFLOW_READY_FOR_CODING)

        with mock.patch(DELAY) as delay:
            unchanged = self._revise(va_sid, _answers())
        self.assertFalse(unchanged.get_json()["changed"])
        delay.assert_not_called()

        with mock.patch(DELAY) as delay:
            changed = self._revise(va_sid, _answers(Id10017="Binita"))
        self.assertTrue(changed.get_json()["changed"], changed.get_json())
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_SMARTVA_PENDING)
        delay.assert_called_once_with(va_sid=va_sid, triggered_by="interview_revision", regenerate=False)

    # ── the task is idempotent ─────────────────────────────────────────────

    def test_the_task_skips_a_submission_that_already_has_a_current_result(self):
        from app.tasks.sync_tasks import run_smartva_for_submission

        _death, va_sid = self._submitted()
        self._result(va_sid)
        with mock.patch.object(smartva_service, "generate_for_submission") as generate:
            result = run_smartva_for_submission.run(va_sid, "web_intake_submit")
        generate.assert_not_called()
        self.assertEqual(result, {"va_sid": va_sid, "smartva_updated": 0, "skipped": True})

    def test_the_task_runs_without_a_result_or_when_regenerating_and_always_clears_the_marker(self):
        from app.tasks.sync_tasks import run_smartva_for_submission

        _death, va_sid = self._submitted()
        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_QUEUED)
        with mock.patch.object(smartva_service, "generate_for_submission", return_value=1) as generate:
            run_smartva_for_submission.run(va_sid, "web_intake_submit")
        generate.assert_called_once_with(va_sid, trigger_source="web_intake_submit", regenerate=False)
        self.assertEqual(smartva_service.smartva_status(va_sid), smartva_service.SMARTVA_NOT_REQUESTED)

        self._result(va_sid)
        with mock.patch.object(smartva_service, "generate_for_submission", return_value=1) as generate:
            run_smartva_for_submission.run(va_sid, "coding_page", regenerate=True)
        generate.assert_called_once_with(va_sid, trigger_source="coding_page", regenerate=True)

        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_QUEUED)
        with mock.patch.object(smartva_service, "generate_for_submission", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_smartva_for_submission.run(va_sid, "coding_page", regenerate=True)
        self.assertEqual(smartva_service.smartva_status(va_sid), smartva_service.SMARTVA_DONE)

    def test_the_task_runs_smartva_for_a_web_case_and_releases_it_to_coders(self):
        """End to end with the real SmartVA binary: a web interview in
        ``smartva_pending`` leaves it with a result row (success or a recorded
        failure; both release the case) and the marker is gone."""
        from app.tasks.sync_tasks import run_smartva_for_submission

        _death, va_sid = self._submitted()
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_SMARTVA_PENDING)
        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_QUEUED)

        result = run_smartva_for_submission.run(va_sid, "web_intake_submit")

        db.session.expire_all()
        self.assertEqual(result["smartva_updated"], 1)
        self.assertEqual(get_submission_workflow_state(va_sid), WORKFLOW_READY_FOR_CODING)
        # These few answers are too sparse for SmartVA to produce output (a recorded
        # failure); a full interview succeeds (checked by hand with an ODK payload).
        self.assertIn(smartva_service.smartva_status(va_sid), ("done", "failed"))
        # A second delivery of the same task writes nothing.
        again = run_smartva_for_submission.run(va_sid, "web_intake_submit")
        self.assertEqual(again, {"va_sid": va_sid, "smartva_updated": 0, "skipped": True})

    def test_regenerate_replaces_a_successful_result_that_a_plain_run_keeps(self):
        _death, va_sid = self._submitted()
        form = db.session.get(VaForms, db.session.get(VaSubmissions, va_sid).va_form_id)
        old = self._result(va_sid)
        frame = mock.Mock()
        frame.itertuples.return_value = [mock.Mock(sid=va_sid)]
        saved = mock.Mock()
        # Everything the SmartVA binary and its files do is replaced; only the
        # skip-or-replace decision on the stored result is under test.
        with ExitStack() as stack:
            for target, kwargs in (
                ("app.utils.va_smartva_prepdata", {"return_value": {}}),
                ("app.utils.va_smartva_runsmartva", {}),
                ("app.utils.va_smartva_formatsmartvaresult", {"return_value": "out.csv"}),
                ("app.services.smartva_service._read_formatted_results", {"return_value": frame}),
                ("app.services.smartva_service._read_raw_likelihood_outputs", {"return_value": {}}),
                ("app.services.smartva_service._read_rejected_sids_from_report", {"return_value": {}}),
                ("app.services.smartva_service._create_smartva_form_run",
                 {"return_value": mock.Mock(form_run_id=uuid.uuid4())}),
                ("app.services.smartva_service._finalize_smartva_form_run", {}),
                ("app.services.smartva_service._archive_completed_form_run", {}),
                ("app.services.smartva_service._save_smartva_result", {"new": saved}),
            ):
                stack.enter_context(mock.patch(target, **kwargs))
            plain = smartva_service._generate_batch(form, {va_sid})
            replaced = smartva_service._generate_batch(form, {va_sid}, replace_existing=True)
        self.assertEqual((plain, replaced), (0, 1))
        saved.assert_called_once()
        self.assertEqual(saved.call_args.kwargs["existing"], [old])

    # ── a regeneration replaces the old result only when the new run succeeds ──

    def _regenerate(self, va_sid, record, **kwargs):
        """One real ``_generate_batch(replace_existing=True)`` with the SmartVA
        binary and its files replaced: *record* is the output row, None for no
        output file at all."""
        form = db.session.get(VaForms, db.session.get(VaSubmissions, va_sid).va_form_id)
        frame = None
        if record is not None:
            frame = mock.Mock()
            frame.itertuples.return_value = [record]
        with ExitStack() as stack:
            for target, patch_kwargs in (
                ("app.utils.va_smartva_prepdata", {"return_value": {}}),
                ("app.utils.va_smartva_runsmartva", {}),
                ("app.utils.va_smartva_formatsmartvaresult", {"return_value": "out.csv"}),
                ("app.services.smartva_service._read_formatted_results", {"return_value": frame}),
                ("app.services.smartva_service._read_raw_likelihood_outputs", {"return_value": {}}),
                ("app.services.smartva_service._read_rejected_sids_from_report", {"return_value": {}}),
                ("app.services.smartva_service._finalize_smartva_form_run", {}),
                ("app.services.smartva_service._archive_completed_form_run", {}),
            ):
                stack.enter_context(mock.patch(target, **patch_kwargs))
            return smartva_service._generate_batch(form, {va_sid}, replace_existing=True, **kwargs)

    def _audit(self, va_sid, entity_id):
        return db.session.scalars(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == va_sid, VaSubmissionsAuditlog.va_audit_entityid == entity_id,
        )).all()

    def test_a_failed_regenerate_keeps_the_working_result_and_records_the_failure_on_the_run(self):
        from app.models import VaSmartvaRun

        _death, va_sid = self._submitted()
        old = self._result(va_sid)
        by = (self.coder_id, "vacoder")

        saved = self._regenerate(va_sid, None, requested_by=by)  # SmartVA produced no output

        db.session.expire_all()
        self.assertEqual(saved, 1)
        self.assertEqual(old.va_smartva_status, VaStatuses.active)
        self.assertEqual(smartva_service.smartva_status(va_sid), "done")
        rows = db.session.scalars(sa.select(VaSmartvaResults).where(VaSmartvaResults.va_sid == va_sid)).all()
        self.assertEqual([r.va_smartva_id for r in rows], [old.va_smartva_id])  # no failed result row
        run = db.session.scalar(sa.select(VaSmartvaRun).where(
            VaSmartvaRun.va_sid == va_sid, VaSmartvaRun.va_smartva_outcome == VaSmartvaRun.OUTCOME_FAILED))
        self.assertEqual(run.va_smartva_failure_stage, "format_output")
        (entry,) = self._audit(va_sid, run.va_smartva_run_id)
        self.assertEqual(
            (str(entry.va_audit_by), entry.va_audit_byrole, entry.va_audit_action),
            (self.coder_id, "vacoder", "va_smartva_regenerate_failed"))

    def test_a_failed_run_over_no_working_result_still_records_a_failed_result(self):
        _death, va_sid = self._submitted()
        self._regenerate(va_sid, None)
        self.assertEqual(smartva_service.smartva_status(va_sid), "failed")

    def test_a_successful_regenerate_replaces_the_result_and_the_audit_names_the_requester(self):
        from types import SimpleNamespace

        _death, va_sid = self._submitted()
        old = self._result(va_sid)
        by = (self.reviewer_id, "reviewer")

        saved = self._regenerate(
            va_sid, SimpleNamespace(sid=va_sid, age=71, sex="female", cause1="Pneumonia"), requested_by=by)

        db.session.expire_all()
        self.assertEqual(saved, 1)
        self.assertEqual(old.va_smartva_status, VaStatuses.deactive)
        (new,) = db.session.scalars(sa.select(VaSmartvaResults).where(
            VaSmartvaResults.va_sid == va_sid, VaSmartvaResults.va_smartva_status == VaStatuses.active)).all()
        self.assertEqual(new.va_smartva_cause1, "Pneumonia")
        for entity, action in ((old.va_smartva_id, "va_smartva_replaced_by_regeneration"),
                               (new.va_smartva_id, "va_smartva_regenerated")):
            (entry,) = self._audit(va_sid, entity)
            self.assertEqual((str(entry.va_audit_by), entry.va_audit_byrole, entry.va_audit_action),
                             (self.reviewer_id, "reviewer", action))

    def test_the_task_hands_the_requester_to_the_service(self):
        from app.tasks.sync_tasks import run_smartva_for_submission

        _death, va_sid = self._submitted()
        with mock.patch.object(smartva_service, "generate_for_submission", return_value=1) as generate:
            run_smartva_for_submission.run(va_sid, "coding_page", regenerate=True, requested_by=[self.coder_id, "vacoder"])
        generate.assert_called_once_with(
            va_sid, trigger_source="coding_page", regenerate=True, requested_by=(self.coder_id, "vacoder"))

    # ── status ─────────────────────────────────────────────────────────────

    def test_status_for_every_state(self):
        _death, va_sid = self._submitted()
        self.assertEqual(smartva_service.smartva_status(va_sid), "not_requested")

        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_QUEUED)
        self.assertEqual(smartva_service.smartva_status(va_sid), "queued")
        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_RUNNING)
        self.assertEqual(smartva_service.smartva_status(va_sid), "running")
        smartva_service.clear_run_marker(va_sid)

        failed = self._result(va_sid, outcome=VaSmartvaResults.OUTCOME_FAILED)
        self.assertEqual(smartva_service.smartva_status(va_sid), "failed")
        failed.va_smartva_status = VaStatuses.deactive
        self._result(va_sid)
        self.assertEqual(smartva_service.smartva_status(va_sid), "done")

        # The marker wins over the old result: a regeneration reads as queued.
        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_QUEUED)
        self.assertEqual(smartva_service.smartva_status(va_sid), "queued")

    def test_a_result_of_an_earlier_payload_does_not_count(self):
        _death, va_sid = self._submitted()
        self._result(va_sid, payload=False)
        self.assertEqual(smartva_service.smartva_status(va_sid), "not_requested")
        self.assertFalse(smartva_service.has_current_payload_result(va_sid))

    # ── POST /api/v1/coding/submissions/<va_sid>/smartva ───────────────────

    def _run(self, va_sid, user_id, **body):
        self._login(user_id)
        return self.client.post(f"{CODING}/submissions/{va_sid}/smartva", headers=self._csrf_headers(), json=body)

    def test_run_queues_for_a_coder_reviewer_data_manager_and_admin(self):
        for user_id in (self.coder_id, self.reviewer_id, self.dm_id, self.base_admin_id):
            with self.subTest(user_id=user_id):
                _death, va_sid = self._submitted()
                with mock.patch(DELAY) as delay:
                    response = self._run(va_sid, user_id)
                self.assertEqual(response.status_code, 202, response.get_json())
                self.assertEqual(response.get_json(), {"va_sid": va_sid, "status": "queued"})
                delay.assert_called_once_with(
                    va_sid=va_sid, triggered_by="coding_page", regenerate=False, requested_by=mock.ANY)

    def test_the_requester_and_role_ride_with_the_queued_task(self):
        _death, va_sid = self._submitted()
        for user_id, role in ((self.coder_id, "vacoder"), (self.reviewer_id, "reviewer"), (self.dm_id, "data_manager")):
            smartva_service.clear_run_marker(va_sid)
            with mock.patch(DELAY) as delay:
                self.assertEqual(self._run(va_sid, user_id).status_code, 202)
            self.assertEqual(delay.call_args.kwargs["requested_by"], (user_id, role))

    def test_run_is_not_queued_twice_and_a_finished_result_needs_regenerate(self):
        _death, va_sid = self._submitted()
        with mock.patch(DELAY) as delay:
            self.assertEqual(self._run(va_sid, self.coder_id).status_code, 202)
            again = self._run(va_sid, self.coder_id)
        self.assertEqual((again.status_code, again.get_json()["status"]), (202, "queued"))
        self.assertEqual(delay.call_count, 1)

        smartva_service.clear_run_marker(va_sid)
        self._result(va_sid)
        with mock.patch(DELAY) as delay:
            plain = self._run(va_sid, self.coder_id)
            regenerated = self._run(va_sid, self.coder_id, regenerate=True)
        self.assertEqual((plain.status_code, plain.get_json()["code"]), (409, "already_done"))
        self.assertEqual(regenerated.status_code, 202, regenerated.get_json())
        delay.assert_called_once_with(
            va_sid=va_sid, triggered_by="coding_page", regenerate=True, requested_by=mock.ANY)

    def test_a_failed_run_runs_again_as_a_replacement(self):
        _death, va_sid = self._submitted()
        self._result(va_sid, outcome=VaSmartvaResults.OUTCOME_FAILED)
        with mock.patch(DELAY) as delay:
            response = self._run(va_sid, self.coder_id)
        self.assertEqual(response.status_code, 202, response.get_json())
        delay.assert_called_once_with(
            va_sid=va_sid, triggered_by="coding_page", regenerate=True, requested_by=mock.ANY)

    def test_run_refuses_a_case_past_coding_and_a_bad_body(self):
        _death, va_sid = self._submitted()
        self._state(va_sid, WORKFLOW_CODER_FINALIZED)
        with mock.patch(DELAY) as delay:
            finalised = self._run(va_sid, self.coder_id)
            self._state(va_sid, WORKFLOW_SMARTVA_PENDING)
            bad = self._run(va_sid, self.coder_id, regenerate="yes")
        self.assertEqual((finalised.status_code, finalised.get_json()["code"]), (409, "wrong_state"))
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (422, "invalid_request"))
        delay.assert_not_called()

    def test_run_answers_503_and_leaves_no_marker_when_the_broker_is_down(self):
        _death, va_sid = self._submitted()
        with mock.patch(DELAY, side_effect=ConnectionError("broker down")):
            response = self._run(va_sid, self.coder_id)
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "queue_unavailable"))
        self.assertEqual(smartva_service.smartva_status(va_sid), "not_requested")

    def test_run_authorization_and_csrf(self):
        _death, va_sid = self._submitted()
        with mock.patch(DELAY) as delay:
            self.assertEqual(self._run(va_sid, self.outsider_coder_id).status_code, 403)
            self.assertEqual(self._run(va_sid, self.interviewer_id).status_code, 403)
            self.assertEqual(self._run(va_sid, self.collab_id).status_code, 403)
            # A view grant is not a coding grant.
            viewer = self._run(va_sid, self.viewer_coder_id)
            self.assertEqual((viewer.status_code, viewer.get_json()["code"]), (403, "forbidden"))
            self.assertEqual(self._run("NO-SUCH-SID", self.coder_id).status_code, 404)
            self._login(self.coder_id)
            no_csrf = self.client.post(f"{CODING}/submissions/{va_sid}/smartva", json={})
            self.assertEqual(no_csrf.status_code, 400)
            # Signed out, with a valid token: the rate limiter's key must not need a user.
            with self.client.session_transaction() as sess:
                sess.clear()
            self.assertEqual(self.client.post(
                f"{CODING}/submissions/{va_sid}/smartva", headers=self._csrf_headers(), json={}).status_code, 401)
        delay.assert_not_called()

    def test_run_is_rate_limited_per_user(self):
        _death, va_sid = self._submitted()
        with mock.patch(DELAY):
            codes = [self._run(va_sid, self.coder_id).status_code for _ in range(12)]
        self.assertEqual(codes[:10], [202] * 10)
        self.assertEqual(codes[10:], [429, 429])

    # ── the panel ──────────────────────────────────────────────────────────

    # ── the 30-second sweep of everything still in smartva_pending ──────────

    def _odk_pending(self):
        now = datetime.now(UTC)
        va_sid = f"sweep-{uuid.uuid4().hex[:8]}-svc01sv0101"
        db.session.add(VaSubmissions(
            va_sid=va_sid, va_form_id="SVC01SV0101", va_submission_date=now,
            va_odk_updatedat=now.replace(tzinfo=None), va_data_collector="C", va_odk_reviewstate=None,
            va_consent="yes", va_narration_language="English", va_deceased_age=45,
            va_deceased_gender="male", va_uniqueid_masked="masked", va_summary=[], va_catcount={},
            va_category_list=[],
        ))
        db.session.flush()
        self._state(va_sid, WORKFLOW_SMARTVA_PENDING)
        self._markers.append(va_sid)
        smartva_service.clear_run_marker(va_sid)
        return va_sid

    def _sweep(self, generate=None):
        from app.tasks.sync_tasks import sweep_smartva_pending

        generate = generate or mock.Mock(return_value=0)
        with mock.patch.object(smartva_service, "generate_for_form", generate):
            return sweep_smartva_pending.run(), generate

    def test_an_empty_sweep_is_one_query_and_runs_no_smartva(self):
        statements = []
        connection = db.session.connection()

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        sa.event.listen(connection, "before_cursor_execute", count)
        try:
            result, generate = self._sweep()
        finally:
            sa.event.remove(connection, "before_cursor_execute", count)
        self.assertEqual(result, {"sids": 0, "forms": 0})
        generate.assert_not_called()
        self.assertEqual(len(statements), 1)
        self.assertIn("workflow_state", statements[0])

    def test_pending_web_and_odk_sids_run_once_per_form_with_the_sweep_trigger(self):
        _d1, web1 = self._submitted()
        _d2, web2 = self._submitted()
        odk = self._odk_pending()
        web_form = db.session.get(VaSubmissions, web1).va_form_id

        result, generate = self._sweep()

        self.assertEqual(result, {"sids": 3, "forms": 2})
        calls = {c.args[0].form_id: c.kwargs for c in generate.call_args_list}
        self.assertEqual(set(calls), {web_form, "SVC01SV0101"})
        self.assertEqual(calls[web_form]["target_sids"], {web1, web2})
        self.assertEqual(calls["SVC01SV0101"]["target_sids"], {odk})
        self.assertTrue(all(k["trigger_source"] == "smartva_sweep" for k in calls.values()))

    def test_the_sweep_skips_marked_sids_and_ones_it_just_ran_without_moving_them_on(self):
        _d, queued = self._submitted()
        _d, stuck = self._submitted()
        _d, fresh = self._submitted()
        smartva_service.set_run_marker(queued, smartva_service.SMARTVA_QUEUED)

        _result, generate = self._sweep()
        # The mock moves nothing out of smartva_pending, so `stuck` and `fresh` stay pending ...
        self.assertEqual(generate.call_args.kwargs["target_sids"], {stuck, fresh})
        # ... and the next tick leaves them alone instead of re-running them every 30 s.
        result, generate = self._sweep()
        self.assertEqual(result, {"sids": 0, "forms": 0})
        generate.assert_not_called()

        from app import cache
        cache.delete_many(*(f"smartva-sweep-skip:{sid}" for sid in (stuck, fresh)))

    def test_the_sweep_marks_its_sids_running_during_a_form_run_and_clears_them_after(self):
        _d, web = self._submitted()
        seen = []

        def generate(form, **kwargs):
            seen.extend(smartva_service.smartva_status(sid) for sid in kwargs["target_sids"])
            raise RuntimeError("boom")  # the marker is cleared even when the form fails

        self._sweep(mock.Mock(side_effect=generate))
        self.assertEqual(seen, ["running"])
        self.assertEqual(smartva_service.smartva_status(web), smartva_service.SMARTVA_NOT_REQUESTED)

        from app import cache
        cache.delete(f"smartva-sweep-skip:{web}")

    def test_the_sweep_takes_at_most_the_cap_and_leaves_the_rest_for_the_next_tick(self):
        for _ in range(3):
            self._odk_pending()
        with mock.patch("app.tasks.sync_tasks.SMARTVA_SWEEP_MAX_SIDS", 2):
            result, generate = self._sweep()
        self.assertEqual(result["sids"], 2)
        self.assertEqual(len(generate.call_args.kwargs["target_sids"]), 2)

    def test_a_failing_form_does_not_stop_the_others(self):
        self._submitted()
        self._odk_pending()
        generate = mock.Mock(side_effect=[RuntimeError("boom"), 1])
        result, generate = self._sweep(generate)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(result["forms"], 1)

    def test_the_lock_stops_a_second_sweep_from_overlapping_and_is_released_after(self):
        class FakeRedis:
            def __init__(self):
                self.data = {}

            def set(self, key, value, nx=False, ex=None):
                if nx and key in self.data:
                    return None
                self.data[key] = value
                return True

            def get(self, key):
                return self.data.get(key)

            def delete(self, key):
                self.data.pop(key, None)

        from app.tasks.sync_tasks import SMARTVA_SWEEP_LOCK_KEY

        self._odk_pending()
        client = FakeRedis()
        with mock.patch("app.tasks.sync_tasks._lock_client", return_value=client):
            client.data[SMARTVA_SWEEP_LOCK_KEY] = "someone-else"
            result, generate = self._sweep()
            self.assertEqual(result["skipped"], "locked")
            generate.assert_not_called()
            self.assertEqual(client.data[SMARTVA_SWEEP_LOCK_KEY], "someone-else")  # not ours to release

            del client.data[SMARTVA_SWEEP_LOCK_KEY]
            result, generate = self._sweep()
            self.assertEqual(result["forms"], 1)
            self.assertNotIn(SMARTVA_SWEEP_LOCK_KEY, client.data)

    def test_beat_seeding_is_idempotent(self):
        """The beat tables only exist in the migrated dev database, so the
        seeding runs against a stand-in connection that remembers its inserts."""
        from contextlib import contextmanager

        from app.tasks.sync_tasks import ensure_smartva_sweep_scheduled

        inserted = []

        class Conn:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "INSERT INTO public.celery_periodictask " in sql or "INSERT INTO public.celery_periodictask\n" in sql:
                    inserted.append(params)
                result = mock.Mock()
                if "SELECT id FROM public.celery_intervalschedule" in sql:
                    result.scalar.return_value = 7
                elif "SELECT id FROM public.celery_periodictask" in sql:
                    result.scalar.return_value = 1 if inserted else None
                return result

        @contextmanager
        def begin():
            yield Conn()

        with mock.patch("app.db", mock.Mock(engine=mock.Mock(begin=begin))):
            ensure_smartva_sweep_scheduled()
            ensure_smartva_sweep_scheduled()
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0]["task"], "app.tasks.sync_tasks.sweep_smartva_pending")
        self.assertEqual(inserted[0]["schedule_id"], 7)
        self.assertEqual(inserted[0]["expire_seconds"], 25)

    def test_data_manager_accept_queues_through_enqueue_smartva(self):
        _death, va_sid = self._submitted()
        self._login(self.dm_id)
        routes = "app.routes.api.data_management"
        with mock.patch(f"{routes}.dm_accept_upstream_change"), \
                mock.patch(f"{routes}._refresh_dm_dashboard_analytics"), \
                mock.patch.object(smartva_service, "enqueue_smartva", return_value=True) as enqueue:
            response = self.client.post(
                f"/api/v1/data-management/submissions/{va_sid}/accept-upstream-change",
                headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        enqueue.assert_called_once_with(va_sid, "data-manager-accept")
        self.assertTrue(response.get_json()["smartva_queued"])

    def test_the_panel_shows_the_status_and_the_right_button(self):
        _death, va_sid = self._submitted()
        html = self._panel(va_sid)
        self.assertIn("Not requested", html)
        self.assertIn('id="smartva-run-btn" data-regenerate="false"', html)

        smartva_service.set_run_marker(va_sid, smartva_service.SMARTVA_RUNNING)
        html = self._panel(va_sid)
        self.assertIn("Running", html)
        self.assertNotIn('id="smartva-run-btn"', html)

        smartva_service.clear_run_marker(va_sid)
        self._result(va_sid)
        html = self._panel(va_sid)
        self.assertIn("Done", html)
        self.assertIn('id="smartva-run-btn" data-regenerate="true"', html)

        self._result(va_sid, outcome=VaSmartvaResults.OUTCOME_FAILED)
        html = self._panel(va_sid)
        self.assertIn("Failed", html)
        self.assertIn("Run again", html)

        self._state(va_sid, WORKFLOW_CODER_FINALIZED)
        self.assertNotIn('id="smartva-run-btn"', self._panel(va_sid))

    def _panel(self, va_sid, **context):
        from flask import render_template

        with self.app.test_request_context("/"):
            return render_template(
                "va_frontpages/_smartva_status_panel.html", va_sid=va_sid, va_action="vacode",
                back_dashboard_role="coder", **context,
            )
