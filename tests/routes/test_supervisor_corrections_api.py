"""Supervisor corrections (digitva-6dh9, digitva-76de).

A supervisor whose cadre is ticked "Can edit interviews" on the level x cadre
grid corrects a submitted interview in reach through the interviewer's own
endpoints (``GET /intake/drafts/<id>``, ``POST /intake/submissions/<sid>/revisions``);
any supervisor of a case opens its death report (``GET /intake/cases/<id>``).
Supervision rows carry the village, "last edited by" and ``can_edit_death``;
the case detail ``edit_interview``. Policy: docs/policy/interview-revisions.md
"Supervisor correction"; docs/policy/web-intake.md "Supervisors".

Tree SUP01: DST > CH1 > PH1 > SCA and CH1 > PH2. The MO cadre supervises at
PHC level; the CHO cadre too, but is never ticked to edit.
"""
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa
from flask import g
from flask.testing import FlaskClient

from app import db, limiter
from app.models import (
    MapMentorInstituteUser,
    MasMentorInstitute,
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
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import organization_service as org
from app.services import sign_in_qr_service
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.viewer_pii_service import PiiScope
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED, WORKFLOW_CODING_IN_PROGRESS
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase

API = "/api/v1/intake"
PROJECT, SITE = "SUP01", "SU01"
R = VaAccessRoles


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


class _FreshGClient(FlaskClient):
    """A fresh ``g`` per request, as production has (test_device_api): the
    suite keeps one app context, so a bearer request would otherwise reuse
    the previous request's user."""

    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        g.pop("device_session", None)
        return super().open(*args, **kwargs)


class SupervisorCorrectionTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=PROJECT, project_code=PROJECT, project_name="Supervisor Corrections",
            project_nickname=PROJECT, project_status=VaStatuses.active, project_registered_at=now,
            project_updated_at=now, web_intake_mode="both", project_structure_mode="organization",
        ))
        db.session.add(VaSiteMaster(
            site_id=SITE, site_name="Correction Site", site_abbr=SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=PROJECT, site_id=SITE, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(PROJECT, SITE)
        db.session.add(VaForms(
            form_id=f"{PROJECT}{SITE}01", project_id=PROJECT, site_id=SITE, odk_form_id="ODK_SUPCORR",
            odk_project_id="7", form_type="WHO VA 2022", form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        org.seed_default_organization(PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(PROJECT)}
        cls.phc_level_id = levels["phc"].org_level_id
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(PROJECT)}

        def unit(code, level, parent=None):
            return org.create_unit(
                PROJECT, org_level_id=levels[level].org_level_id, unit_code=code, unit_name=f"Unit {code}",
                parent_org_unit_id=parent.org_unit_id if parent else None,
            )

        cls.dst = unit("DST", "district")
        cls.ch1 = unit("CH1", "chc", cls.dst)
        cls.ph1, cls.ph2 = unit("PH1", "phc", cls.ch1), unit("PH2", "phc", cls.ch1)
        cls.sca = unit("SCA", "subcentre", cls.ph1)
        for cadre in ("MO", "CHO"):
            org.upsert_level_cadre(
                PROJECT, org_level_id=cls.phc_level_id, cadre_id=cls.cadres[cadre].cadre_id,
                can_fill_va_form=cadre == "CHO", can_code_va_form=cadre == "MO", can_supervise_interviews=True,
            )
        # A CHC's SMO edits; a CHC's MO does not even supervise there.
        org.upsert_level_cadre(
            PROJECT, org_level_id=levels["chc"].org_level_id, cadre_id=cls.cadres["SMO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=True, can_edit_interviews=True,
        )

        def user(key, *grants):
            person = cls._get_or_make_user(f"sc.{key}@test.local", "SupCorr123")
            for role, where, cadre in grants:
                row = ({"scope_type": VaAccessScopeTypes.project, "project_id": PROJECT} if where is None
                       else {"scope_type": VaAccessScopeTypes.org_unit, "org_unit_id": where.org_unit_id})
                if cadre:
                    row["cadre_id"] = cls.cadres[cadre].cadre_id
                db.session.add(VaUserAccessGrants(
                    user_id=person.user_id, role=role, grant_status=VaStatuses.active, notes="sup corr", **row))
            return person

        cls.ian = user("ian", (R.interviewer, cls.ph1, None))
        cls.tia = user("tia", (R.interviewer, cls.ph1, None))
        cls.hv = user("hv", (R.interview_supervisor, cls.ph1, "MO"))
        cls.far = user("far", (R.interview_supervisor, cls.ph2, "MO"))
        # Every other supervising power over PH1, and a supervisor grant whose cadre is never ticked.
        cls.boss = user("boss", (R.data_manager, cls.dst, None), (R.site_pi, cls.ph1, None),
                        (R.project_pi, None, None), (R.interview_supervisor, cls.ph1, "CHO"))
        cls.dana = user("dana", (R.data_manager, cls.dst, None))
        # The narrowest grant (PH1, CHO) is not ticked; a wider one (CH1, SMO) is.
        cls.wide = user("wide", (R.interview_supervisor, cls.ph1, "CHO"), (R.interview_supervisor, cls.ch1, "SMO"))
        # MO is ticked at PHC level only; this MO's grant is at a CHC.
        cls.mo_chc = user("mochc", (R.interview_supervisor, cls.ch1, "MO"))
        # A mentoring-institute member holds the same ticked supervisor grant but sees no personal data.
        cls.mento = user("mento", (R.interview_supervisor, cls.ph1, "MO"))
        institute = MasMentorInstitute(institute_code="SUPINST", institute_name="Sup Institute")
        db.session.add(institute)
        db.session.flush()
        db.session.add(MapMentorInstituteUser(institute_id=institute.institute_id, user_id=cls.mento.user_id))
        # One person who is both an interviewer and a ticked supervisor over PH1.
        cls.both = user("both", (R.interviewer, cls.ph1, None), (R.interview_supervisor, cls.ph1, "MO"))
        # Phone accounts: an In-charge and a data manager over PH1 who interview elsewhere (PH2),
        # and an In-charge with nothing else.
        cls.icx = user("icx", (R.interviewer, cls.ph2, None), (R.site_pi, cls.ph1, None))
        cls.dmx = user("dmx", (R.interviewer, cls.ph2, None), (R.data_manager, cls.dst, None))
        cls.incharge = user("incharge", (R.site_pi, cls.ph1, None))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._tick(True)

    # ── helpers ────────────────────────────────────────────────────────────

    def _tick(self, on):
        org.upsert_level_cadre(
            PROJECT, org_level_id=self.phc_level_id, cadre_id=self.cadres["MO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=True, can_edit_interviews=on,
        )
        db.session.commit()

    def _as(self, user):
        self._login(str(user.user_id))

    def _case(self, **extra):
        self._as(self.ian)
        response = self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": PROJECT, "site_id": SITE, "org_unit_id": str(self.sca.org_unit_id),
            "deceased_name": "Bina Sahu", "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=5)).isoformat(), "age_years": 71,
            "address_village_ward": "Rampur", "informant_name": "Ravi", **extra,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["case"]["death_id"]

    def _upload(self, death_id, answers, user=None):
        self._as(user or self.ian)
        text = _text(answers)
        return self.client.post(f"{API}/submissions", headers=self._csrf_headers(), json={
            "client_draft_id": str(uuid.uuid4()), "project_id": PROJECT, "site_id": SITE,
            "org_unit_id": str(self.sca.org_unit_id), "death_id": death_id,
            "draft": {"startedAt": datetime.now(UTC).isoformat()},
            "completion": {"valid": True, "issues": []}, "answers_json": text, "answers_sha256": _sha(text),
        })

    def _submitted(self):
        death_id = self._case()
        response = self._upload(death_id, _answers())
        self.assertEqual(response.status_code, 201, response.get_json())
        va_sid = response.get_json()["va_sid"]
        return death_id, va_sid, self._draft(va_sid)

    def _draft(self, va_sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.status == "submitted"))

    def _revise(self, user, va_sid, answers, reason="interviewer_correction", valid=True):
        self._as(user)
        text = _text(answers)
        return self.client.post(f"{API}/submissions/{va_sid}/revisions", headers=self._csrf_headers(), json={
            "reason_code": reason, "draft": {}, "completion": {"valid": valid, "issues": []},
            "answers_json": text, "answers_sha256": _sha(text),
        })

    def _get_draft(self, user, draft_id):
        self._as(user)
        return self.client.get(f"{API}/drafts/{draft_id}")

    def _active(self, va_sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid, VaSubmissionPayloadVersion.version_status == "active"))

    def _supervised(self, user, death_id):
        self._as(user)
        response = self.client.get(f"{API}/supervision/cases/{death_id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _row(self, user, death_id):
        self._as(user)
        response = self.client.get(f"{API}/supervision/cases?limit=100")
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = {row["death_id"]: row for row in response.get_json()["cases"]}
        self.assertIn(death_id, rows)
        return rows[death_id]

    # ── who may correct ─────────────────────────────────────────────────────

    def test_a_ticked_supervisor_in_reach_corrects_the_interview(self):
        death_id, va_sid, draft = self._submitted()
        before = self._active(va_sid)
        collector = db.session.get(VaSubmissions, va_sid).va_data_collector
        set_submission_workflow_state(va_sid, WORKFLOW_CODING_IN_PROGRESS, reason="test", by_role="test")
        allocation = VaAllocations(
            va_sid=va_sid, va_allocated_to=self.base_coder_user.user_id, va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active)
        initial = VaInitialAssessments(
            va_sid=va_sid, va_iniassess_by=self.base_coder_user.user_id, va_immediate_cod="R99",
            va_antecedent_cod="R99", va_iniassess_status=VaStatuses.active)
        db.session.add_all([allocation, initial])
        db.session.commit()

        opened = self._get_draft(self.hv, draft.draft_id)
        self.assertEqual(opened.status_code, 200, opened.get_json())
        body = opened.get_json()
        self.assertEqual((body["draft"]["va_sid"], body["answers_sha256"]), (va_sid, draft.answers_sha256))
        self.assertEqual(body["envelope"]["data"]["Id10017"], "Bina")
        locked = [n for n in body["prefill"].get("lockedQuestionNames", []) if n in body["envelope"]["data"]]
        self.assertTrue(locked)
        stored = dict(body["envelope"]["data"])
        # The revision screen's other reads already open to a supervisor-only account.
        self.assertEqual(self.client.get(f"/api/v1/organization/{PROJECT}/form-options").status_code, 200)

        tampered = {**stored, "Id10017": "Binita", **{name: "Tampered" for name in locked}}
        response = self._revise(self.hv, va_sid, tampered)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["changed"])

        version = self._active(va_sid)
        self.assertNotEqual(version.payload_version_id, before.payload_version_id)
        self.assertEqual((version.revision_reason_code, version.created_by),
                         ("supervisor_correction", self.hv.user_id))
        self.assertEqual(db.session.get(VaSubmissions, va_sid).va_data_collector, collector)
        self.assertEqual(version.payload_data["SubmitterID"], str(self.ian.user_id))
        final = self._draft(va_sid)
        self.assertEqual(final.user_id, self.ian.user_id)
        answers = next(s.data for s in final.sections if s.section_name == "final")
        self.assertEqual(answers["Id10017"], "Binita")
        self.assertEqual({n: answers[n] for n in locked}, {n: stored[n] for n in locked})
        # Coding released and re-routed under the supervisor's audit names.
        db.session.expire_all()
        self.assertEqual(db.session.get(VaAllocations, allocation.va_allocation_id).va_allocation_status,
                         VaStatuses.deactive)
        self.assertEqual(db.session.get(VaInitialAssessments, initial.va_iniassess_id).va_iniassess_status,
                         VaStatuses.deactive)
        audit = db.session.scalars(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == va_sid,
            VaSubmissionsAuditlog.va_audit_action == "va_submission_revised_by_supervisor")).all()
        self.assertEqual([(a.va_audit_by, a.va_audit_byrole) for a in audit],
                         [(self.hv.user_id, "interview_supervisor")])
        reasons = set(db.session.scalars(sa.select(VaSubmissionWorkflowEvent.transition_reason).where(
            VaSubmissionWorkflowEvent.va_sid == va_sid)))
        self.assertIn("supervisor_revision", reasons)
        self.assertNotIn("interviewer_revision", reasons)

    def test_without_the_tick_the_draft_and_the_revision_are_not_found(self):
        _death_id, va_sid, draft = self._submitted()
        self.assertEqual(self._get_draft(self.hv, draft.draft_id).status_code, 200)  # present first
        self._tick(False)
        self.assertEqual(self._get_draft(self.hv, draft.draft_id).status_code, 404)
        self.assertEqual(self._revise(self.hv, va_sid, _answers(Id10017="Binita")).status_code, 404)

    def test_out_of_reach_and_other_supervising_roles_are_not_found(self):
        _death_id, va_sid, draft = self._submitted()
        self.assertEqual(self._get_draft(self.hv, draft.draft_id).status_code, 200)  # present first
        # A ticked supervisor of another PHC; a data manager, In-charge and project PI over
        # the case whose own supervisor grant's cadre is not ticked.
        admin = db.session.get(type(self.hv), uuid.UUID(str(self.base_admin_id)))
        for user in (self.far, self.boss, self.mo_chc):
            self.assertEqual(self._get_draft(user, draft.draft_id).status_code, 404, user.email)
            self.assertEqual(self._revise(user, va_sid, _answers(Id10017="Binita")).status_code, 404, user.email)
        # A data manager alone, or an admin, does not pass the routes' role gate.
        for user in (self.dana, admin):
            self.assertEqual(self._get_draft(user, draft.draft_id).status_code, 403, user.email)
            self.assertEqual(self._revise(user, va_sid, _answers(Id10017="Binita")).status_code, 403, user.email)
        self.assertEqual(self._active(va_sid).revision_reason_code, None)

    def test_any_reaching_grant_with_a_ticked_cadre_counts(self):
        _death_id, _va_sid, draft = self._submitted()
        self.assertEqual(self._get_draft(self.wide, draft.draft_id).status_code, 200)

    def test_a_superseded_copy_is_never_the_supervisors(self):
        death_id, _va_sid, _draft = self._submitted()
        second = self._upload(death_id, _answers(Id10017="Bindu"), user=self.tia)
        self.assertEqual(second.status_code, 201, second.get_json())
        db.session.expire_all()
        copy = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == uuid.UUID(death_id), VaWebIntakeDraft.user_id == self.tia.user_id))
        self.assertEqual(copy.status, "superseded")
        self.assertEqual(self._get_draft(self.hv, copy.draft_id).status_code, 404)

    # ── the window and the refusals ─────────────────────────────────────────

    def test_a_finalised_case_is_locked_and_a_reopened_one_is_open(self):
        _death_id, va_sid, _draft = self._submitted()
        set_submission_workflow_state(va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.commit()
        locked = self._revise(self.hv, va_sid, _answers(Id10017="Binita"))
        self.assertEqual((locked.status_code, locked.get_json()["code"]), (409, "revision_locked"))
        set_submission_workflow_state(va_sid, "finalized_upstream_changed", reason="test", by_role="test")
        db.session.commit()
        with patch("app.services.web_intake_service.revision_unlocked", return_value=True):
            reopened = self._revise(self.hv, va_sid, _answers(Id10017="Binita"))
        self.assertEqual(reopened.status_code, 200, reopened.get_json())
        self.assertEqual(self._active(va_sid).revision_reason_code, "supervisor_correction")
        accepted = db.session.scalars(sa.select(VaSubmissionWorkflowEvent.transition_reason).where(
            VaSubmissionWorkflowEvent.va_sid == va_sid,
            VaSubmissionWorkflowEvent.transition_id == "upstream_change_accepted")).all()
        self.assertEqual(accepted, ["supervisor_revision"])
        self.assertNotEqual(get_submission_workflow_state(va_sid), "finalized_upstream_changed")

    def test_a_supervisor_cannot_change_the_outcome(self):
        _death_id, va_sid, _draft = self._submitted()
        response = self._revise(self.hv, va_sid, _answers(interview_outcome="partially_completed"), valid=False)
        self.assertEqual((response.status_code, response.get_json().get("code")), (409, "case_state_conflict"), response.get_json())

    def test_the_interviewer_may_not_send_the_supervisor_reason(self):
        _death_id, va_sid, _draft = self._submitted()
        response = self._revise(self.ian, va_sid, _answers(Id10017="Binita"), reason="supervisor_correction")
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_reason"))
        ok = self._revise(self.ian, va_sid, _answers(Id10017="Binita"))
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(self._active(va_sid).revision_reason_code, "interviewer_correction")

    # ── the death report form and the supervision screens ──────────────────

    def test_a_supervisor_opens_the_death_report_only_with_personal_data_access(self):
        death_id = self._case()
        self._as(self.hv)
        response = self.client.get(f"{API}/cases/{death_id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        case = response.get_json()["case"]
        self.assertEqual((case["informant"]["name"], case["household_address"]["village_ward"]), ("Ravi", "Rampur"))
        self.assertNotIn("prefill", case)
        self.assertEqual(set(case["links"]), {"update"})
        with patch("app.services.web_intake_service.pii_scope", return_value=PiiScope()):
            self.assertEqual(self.client.get(f"{API}/cases/{death_id}").status_code, 404)
        self._as(self.far)
        self.assertEqual(self.client.get(f"{API}/cases/{death_id}").status_code, 404)

    def test_rows_carry_village_last_edit_and_the_edit_openings(self):
        open_id = self._case()
        death_id, va_sid, draft = self._submitted()
        row = self._row(self.hv, open_id)
        self.assertEqual((row["village_ward"], row["can_edit_death"]), ("Rampur", True))
        self.assertEqual((row["last_edited_by_name"], row["last_edited_at"]), (None, None))
        self.assertNotIn("edit_interview", row)

        row = self._row(self.hv, death_id)
        self.assertEqual((row["village_ward"], row["can_edit_death"], row["last_edited_by_name"]),
                         ("Rampur", False, None))
        detail = self._supervised(self.hv, death_id)
        self.assertEqual(detail["edit_interview"], {
            "draft_id": str(draft.draft_id), "va_sid": va_sid, "project_id": PROJECT, "site_id": SITE})
        self.assertIsNone(self._supervised(self.boss, death_id)["edit_interview"])

        self.assertEqual(self._revise(self.hv, va_sid, _answers(Id10017="Binita")).status_code, 200)
        row = self._row(self.hv, death_id)
        self.assertEqual(row["last_edited_by_name"], self.hv.name)
        self.assertIsNotNone(row["last_edited_at"])
        # Without personal-data access: no village, no editor name.
        with patch("app.services.web_intake_service.pii_scope", return_value=PiiScope()), \
                patch("app.routes.api.intake.pii_scope", return_value=PiiScope()):
            row = self._row(self.hv, death_id)
        self.assertEqual((row["village_ward"], row["last_edited_by_name"], row["deceased_name"]), (None, None, None))
        self.assertIsNotNone(row["last_edited_at"])

        set_submission_workflow_state(va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.commit()
        self.assertIsNone(self._supervised(self.hv, death_id)["edit_interview"])

    def test_can_edit_death_is_false_once_the_case_is_no_longer_open(self):
        open_id = self._case()
        self.assertTrue(self._row(self.hv, open_id)["can_edit_death"])  # present first
        for status in ("draft_identity", "cancelled", "duplicate"):
            db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == uuid.UUID(open_id))
                               .values(status=status))
            db.session.commit()
            self.assertFalse(self._row(self.hv, open_id)["can_edit_death"], status)
        completed_id, _va_sid, _draft = self._submitted()
        self.assertFalse(self._row(self.hv, completed_id)["can_edit_death"])

    def test_a_supervisor_without_personal_data_access_cannot_edit_the_interview(self):
        death_id, va_sid, draft = self._submitted()
        self.assertEqual(self._get_draft(self.hv, draft.draft_id).status_code, 200)  # present first
        self.assertIsNotNone(self._supervised(self.hv, death_id)["edit_interview"])
        self.assertEqual(self._get_draft(self.mento, draft.draft_id).status_code, 404)
        self.assertEqual(self._revise(self.mento, va_sid, _answers(Id10017="Binita")).status_code, 404)
        self.assertIsNone(self._supervised(self.mento, death_id)["edit_interview"])
        self.assertIsNone(self._active(va_sid).revision_reason_code)

    def test_the_owner_who_also_supervises_revises_as_the_owner(self):
        death_id = self._case()
        self.assertEqual(self._upload(death_id, _answers(), user=self.both).status_code, 201)
        va_sid = db.session.get(VaDeathRegister, uuid.UUID(death_id)).va_sid
        self.assertIsNone(self._supervised(self.both, death_id)["edit_interview"])
        # A supervisor's reason is the server's, never the interviewer's to send.
        refused = self._revise(self.both, va_sid, _answers(Id10017="Binita"), reason="supervisor_correction")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (422, "invalid_reason"))
        ok = self._revise(self.both, va_sid, _answers(Id10017="Binita"))
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(self._active(va_sid).revision_reason_code, "interviewer_correction")

    def test_a_consent_withdrawn_case_is_not_found_to_the_supervisor(self):
        death_id, va_sid, draft = self._submitted()
        self.assertEqual(self._get_draft(self.hv, draft.draft_id).status_code, 200)  # present first
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == uuid.UUID(death_id))
                           .values(consent_withdrawn_at=datetime.now(UTC)))
        db.session.commit()
        self.assertEqual(self._get_draft(self.hv, draft.draft_id).status_code, 404)
        self.assertEqual(self._revise(self.hv, va_sid, _answers(Id10017="Binita")).status_code, 404)

    # ── on the phone (docs/policy/mobile-sign-in.md, "Interview supervisors on the phone") ──

    def _enrol(self, user):
        return self.client.post("/api/v1/auth/password-enroll", json={
            "identifier": user.email, "password": "SupCorr123", "device_name": "Supervisor phone",
            "platform": "android", "app_version": "0.3.30",
        })

    def _phone(self, user):
        response = self._enrol(user)
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        return body, {"Authorization": f"Bearer {body['access_token']}"}

    def test_a_supervisor_only_account_enrols_signs_in_and_refreshes(self):
        body, headers = self._phone(self.hv)
        self.assertEqual(body["project"]["project_id"], PROJECT)
        self.assertTrue(body["access"]["projects"][0]["supervises_deaths"])
        self.assertEqual([p["project_id"] for p in body["projects"]], [PROJECT])
        refreshed = self.client.post("/api/v1/auth/sessions/refresh", json={
            "refresh_token": body["refresh_token"], "device_id": body["device_id"],
            "device_secret": body["device_secret"]})
        self.assertEqual(refreshed.status_code, 200, refreshed.get_json())
        self.assertTrue(refreshed.get_json()["access"]["projects"][0]["supervises_deaths"])
        signed_in = self.client.post("/api/v1/auth/sessions", json={
            "device_id": body["device_id"], "device_secret": body["device_secret"],
            "email": self.hv.email, "password": "SupCorr123"})
        self.assertEqual(signed_in.status_code, 201, signed_in.get_json())

    def test_a_supervisor_gets_no_phone_while_project_intake_is_off(self):
        self.assertEqual(self._enrol(self.hv).status_code, 201)  # subject: allowed with intake on
        project = db.session.get(VaProjectMaster, PROJECT)
        project.web_intake_mode = "off"
        db.session.commit()
        try:
            response = self._enrol(self.hv)
            self.assertEqual(response.status_code, 403, response.get_json())
        finally:
            project.web_intake_mode = "both"
            db.session.commit()

    def test_data_manager_or_in_charge_alone_still_gets_no_phone(self):
        for user in (self.dana, self.incharge):
            response = self._enrol(user)
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_interviewer_grant"))

    def test_me_access_reports_supervision_to_a_supervisor_phone(self):
        _body, headers = self._phone(self.hv)
        access = self.client.get("/api/v1/me/access", headers=headers).get_json()
        self.assertIn("interview_supervisor", access["roles"])
        self.assertTrue(access["account"]["device_access"])
        project = next(p for p in access["projects"] if p["project_id"] == PROJECT)
        self.assertTrue(project["supervises_deaths"])
        self.assertEqual((project["actions"]["interview"], project["actions"]["register_death"]), ([], []))
        # An interviewer's phone does not.
        _body, headers = self._phone(self.icx)
        access = self.client.get("/api/v1/me/access", headers=headers).get_json()
        self.assertNotIn("interview_supervisor", access["roles"])
        self.assertFalse(any(p["supervises_deaths"] for p in access["projects"]))

    def test_a_supervisor_phone_lists_opens_and_acts_on_supervised_cases(self):
        death_id = self._case()
        _body, headers = self._phone(self.hv)
        listed = self.client.get(f"{API}/supervision/cases?limit=100", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertIn(death_id, {row["death_id"] for row in listed.get_json()["cases"]})
        for path in (f"supervision/cases/{death_id}", f"supervision/cases/{death_id}/possible-duplicates",
                     f"cases/{death_id}", "identifier-types", "consent-config"):
            response = self.client.get(f"{API}/{path}", headers=headers, query_string={"project_id": PROJECT})
            self.assertEqual(response.status_code, 200, (path, response.get_json()))
        edited = self.client.patch(f"{API}/deaths/{death_id}", headers=headers, json={"deceased_name": "Bina Devi"})
        self.assertEqual(edited.status_code, 200, edited.get_json())
        self.assertEqual(edited.get_json()["case"]["deceased_name"], "Bina Devi")
        cancelled = self.client.post(f"{API}/supervision/cases/{death_id}/cancel", headers=headers,
                                     json={"reason": "Phone test"})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(death_id)).status, "cancelled")
        reopened = self.client.post(f"{API}/supervision/cases/{death_id}/reopen", headers=headers,
                                    json={"reason": "Phone test"})
        self.assertEqual(reopened.status_code, 200, reopened.get_json())

    def test_a_ticked_supervisor_phone_corrects_the_interview(self):
        _death_id, va_sid, draft = self._submitted()
        _body, headers = self._phone(self.hv)
        opened = self.client.get(f"{API}/drafts/{draft.draft_id}", headers=headers)
        self.assertEqual(opened.status_code, 200, opened.get_json())
        text = _text({**opened.get_json()["envelope"]["data"], "Id10017": "Binita"})
        revised = self.client.post(f"{API}/submissions/{va_sid}/revisions", headers=headers, json={
            "reason_code": "interviewer_correction", "draft": {}, "completion": {"valid": True, "issues": []},
            "answers_json": text, "answers_sha256": _sha(text)})
        self.assertEqual(revised.status_code, 200, revised.get_json())
        self.assertEqual((self._active(va_sid).revision_reason_code, self._active(va_sid).created_by),
                         ("supervisor_correction", self.hv.user_id))
        self._tick(False)
        self.assertEqual(self.client.get(f"{API}/drafts/{draft.draft_id}", headers=headers).status_code, 404)

    def test_a_supervisor_phone_reads_the_form_it_needs_to_edit_an_interview(self):
        # The phone has no cached reference data for a supervised project: it fetches these live.
        _body, headers = self._phone(self.hv)
        options = self.client.get(f"/api/v1/organization/{PROJECT}/form-options", headers=headers,
                                  query_string={"project_id": PROJECT})
        self.assertEqual(options.status_code, 200, options.get_json())
        code = next((f["instrument_code"] for f in options.get_json().get("form_types", []) if f.get("is_default")),
                    "WHO_2022_VA")
        definition = self.client.get(f"/api/v1/instruments/{code}/definition", headers=headers,
                                     query_string={"project_id": PROJECT})
        self.assertEqual(definition.status_code, 200, definition.get_data(as_text=True)[:300])
        translations = self.client.get(f"/api/v1/instruments/{code}/translations/hi", headers=headers,
                                       query_string={"project_id": PROJECT})
        # The test database holds no Hindi pack (404 "Translation not found"); the point is it is not a 403.
        self.assertIn(translations.status_code, (200, 404), translations.get_data(as_text=True)[:300])
        self.assertNotEqual(translations.get_json().get("code"), "forbidden")

    def test_in_charge_and_data_manager_powers_stay_off_the_phone(self):
        death_id, va_sid, draft = self._submitted()
        for user in (self.icx, self.dmx):
            # Present first: the browser session supervises the PH1 case.
            self.assertEqual(self._supervised(user, death_id)["case"]["death_id"], death_id)
            _body, headers = self._phone(user)
            for path in ("supervision/cases", f"supervision/cases/{death_id}"):
                self.assertEqual(self.client.get(f"{API}/{path}", headers=headers).status_code, 403, path)
            self.assertEqual(self.client.post(f"{API}/supervision/cases/{death_id}/cancel", headers=headers,
                                              json={"reason": "x"}).status_code, 403)
            self.assertEqual(self.client.get(f"{API}/cases/{death_id}", headers=headers).status_code, 404)
            self.assertEqual(self.client.patch(f"{API}/deaths/{death_id}", headers=headers,
                                               json={"deceased_name": "X"}).status_code, 404)
            self.assertEqual(self.client.get(f"{API}/drafts/{draft.draft_id}", headers=headers).status_code, 404)
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(death_id)).deceased_name, "Bina Sahu")

    def test_a_supervisor_phone_carries_only_the_supervisor_grant_of_a_wider_account(self):
        # boss supervises PH1 (CHO, not ticked) and, in the browser, PH2 as data manager,
        # In-charge and project PI. A PH2 case is the discriminating one.
        self._as(self.icx)
        registered = self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": PROJECT, "site_id": SITE, "org_unit_id": str(self.ph2.org_unit_id),
            "deceased_name": "Asha Rao", "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=5)).isoformat(), "age_years": 60})
        self.assertEqual(registered.status_code, 201, registered.get_json())
        ph2_case = registered.get_json()["case"]["death_id"]
        ph1_case = self._case()
        self.assertEqual(self._supervised(self.boss, ph2_case)["case"]["death_id"], ph2_case)  # browser: present
        _body, headers = self._phone(self.boss)
        access = self.client.get("/api/v1/me/access", headers=headers).get_json()
        self.assertEqual(access["roles"], ["interview_supervisor"])
        self.assertFalse(access["account"]["privileged"])
        listed = {row["death_id"] for row in self.client.get(
            f"{API}/supervision/cases?limit=100", headers=headers).get_json()["cases"]}
        self.assertIn(ph1_case, listed)
        self.assertNotIn(ph2_case, listed)
        self.assertEqual(self.client.get(f"{API}/supervision/cases/{ph2_case}", headers=headers).status_code, 404)
        self.assertEqual(self.client.post(f"{API}/supervision/cases/{ph2_case}/cancel", headers=headers,
                                          json={"reason": "x"}).status_code, 404)
        self.assertEqual(self.client.patch(f"{API}/deaths/{ph2_case}", headers=headers,
                                           json={"deceased_name": "X"}).status_code, 404)
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(ph2_case)).status, "registered")

    def test_a_supervisor_phone_reopens_a_finalised_interview_as_the_supervisor(self):
        _death_id, va_sid, _draft = self._submitted()
        set_submission_workflow_state(va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.commit()
        _body, headers = self._phone(self.hv)
        response = self.client.post(f"{API}/supervision/submissions/{va_sid}/reopen-for-revision", headers=headers,
                                    json={"reason_code": "data_correction"})
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.expire_all()
        kind = db.session.scalar(sa.select(VaSubmissionWorkflowEvent.actor_kind).where(
            VaSubmissionWorkflowEvent.va_sid == va_sid).order_by(VaSubmissionWorkflowEvent.event_created_at.desc())
            .limit(1))
        self.assertEqual(kind, "interview_supervisor")

    def test_an_interviewer_phone_still_cannot_supervise(self):
        death_id = self._case()
        _body, headers = self._phone(self.ian)
        self.assertEqual(self.client.get(f"{API}/supervision/cases", headers=headers).status_code, 403)
        self.assertEqual(self.client.post(f"{API}/supervision/cases/{death_id}/cancel", headers=headers,
                                          json={"reason": "x"}).status_code, 403)

    def test_consent_withdrawal_is_refused_to_every_phone(self):
        death_id, _va_sid, _draft = self._submitted()
        for user in (self.hv, self.boss):
            _body, headers = self._phone(user)
            response = self.client.post(f"{API}/supervision/cases/{death_id}/consent-withdrawal", headers=headers,
                                        json={"requested_by": "Ravi", "requested_on": date.today().isoformat(),
                                              "channel": "phone"})
            self.assertEqual(response.status_code, 403, response.get_json())
        self.assertIsNone(db.session.get(VaDeathRegister, uuid.UUID(death_id)).consent_withdrawn_at)

    def test_a_supervisor_grant_keeps_the_sign_in_qr_away(self):
        self.assertIsNotNone(sign_in_qr_service.eligible_project(self.ian))  # an interviewer alone: eligible
        for user in (self.hv, self.both):
            self.assertIsNone(sign_in_qr_service.eligible_project(user))
