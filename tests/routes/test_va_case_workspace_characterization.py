"""Characterization of GET /api/v1/va/<sid>/workspace (digitva-r8nh.11).

Pins the whole JSON body, byte for byte after normalising ids, for coding,
reviewing and view modes, PII-redacted and unredacted viewers, a demo/training
project, DORIS projects, and a case with drafts and a coding timeline. Written
on the unrefactored route so the move into the workspace service can be shown
to change nothing. Expectations live in ``fixtures/va_case_workspace_golden.json``;
re-record only for a reviewed, owner-approved behaviour change with
``RECORD_WORKSPACE_GOLDEN=1``.

Fixtures and helpers are those of ``VaCaseApiTests``; its own tests are
switched off here so they do not run twice.
"""
import json
import os
import pathlib
import re
from datetime import datetime

from app import db
from app.models import (
    VaAccessRoles,
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaProjectMaster,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionsAuditlog,
)
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.routes import test_va_case_api as base

import sqlalchemy as sa

_GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "va_case_workspace_golden.json"
_VOLATILE_KEYS = {"id", "payload_version_id", "doris_draft_context"}
_CERT = {"ICDVersion": "ICD11", "AdministrativeData": {"Sex": 1}, "Part1": [{"Conditions": []}]}
_RESULTS = {"doris_result": {"status": "ok"}, "codedit_result": {"status": "ok"}}
_T = datetime(2026, 10, 28, 9, 0)


def _normalise(body, sid):
    """Body with the per-run ids replaced, so two runs compare equal."""
    body = json.loads(json.dumps(body).replace(sid, "SID"))

    def walk(node):
        if isinstance(node, dict):
            return {
                key: ("<volatile>" if key in _VOLATILE_KEYS and value is not None else walk(value))
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(body)


class WorkspaceCharacterizationTests(base.VaCaseApiTests):
    # Only this module's tests run; the inherited ones are in test_va_case_api.
    locals().update({name: None for name in dir(base.VaCaseApiTests) if name.startswith("test_")})

    def _golden(self, name, body, sid):
        actual = _normalise(body, sid)
        golden = json.loads(_GOLDEN.read_text()) if _GOLDEN.exists() else {}
        if os.environ.get("RECORD_WORKSPACE_GOLDEN"):
            golden[name] = actual
            _GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n")
            return
        self.assertIn(name, golden)
        self.assertEqual(actual, golden[name])

    def _stamp(self, sid):
        """Fixed allocation time so the coding timeline is deterministic."""
        for allocation in db.session.scalars(sa.select(VaAllocations).where(VaAllocations.va_sid == sid)):
            allocation.va_allocation_createdat = _T
        db.session.commit()

    def _final(self, sid, user, cod, remark=None, **extra):
        row = VaFinalAssessments(
            va_sid=sid, va_finassess_by=user,
            payload_version_id=get_active_payload_version(sid).payload_version_id,
            va_conclusive_cod=cod, va_finassess_remark=remark, va_finassess_status=VaStatuses.active,
            va_finassess_createdat=datetime(2026, 10, 28, 10, 0), **extra,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def _initial_at(self, sid, user=None, **fields):
        row = self._initial(sid, user=user, va_iniassess_createdat=datetime(2026, 10, 28, 9, 20), **fields)
        return row

    # -- coding ------------------------------------------------------------

    def test_coding_with_step_one_final_timeline_and_forms(self):
        self._mode(nqa=True, social_autopsy=True)
        sid = self._coding_case()
        self._stamp(sid)
        allocation = db.session.scalar(sa.select(VaAllocations).where(VaAllocations.va_sid == sid))
        self._initial_at(sid)
        self._final(sid, self.base_coder_user.user_id, "A16 final result", "remark")
        db.session.add(VaSubmissionsAuditlog(
            va_sid=sid, va_audit_byrole="vacoder", va_audit_by=self.base_coder_user.user_id,
            va_audit_operation="c", va_audit_action="DORIS processing completed",
            va_audit_entityid=allocation.va_allocation_id, va_audit_createdat=datetime(2026, 10, 28, 9, 15),
        ))
        db.session.add(VaSmartvaResults(
            va_sid=sid, payload_version_id=get_active_payload_version(sid).payload_version_id,
            va_smartva_status=VaStatuses.active, va_smartva_cause1="Stroke",
            va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
        ))
        db.session.commit()
        body = self._workspace(sid)
        self.assertTrue(body["case"]["doris_draft_context"])  # present, HMAC value normalised
        self._golden("coding_full", body, sid)

    def test_coding_masked_step_one_without_saved_work(self):
        self._mode(masked=True)
        sid = self._coding_case()
        self._stamp(sid)
        self._golden("coding_masked_empty", self._workspace(sid), sid)

    def test_coding_masked_not_codeable(self):
        self._mode(masked=True)
        sid = self._coding_case()
        self._stamp(sid)
        db.session.add(VaCoderReview(
            va_sid=sid, va_creview_by=self.base_coder_user.user_id, va_creview_reason="no_info",
            va_creview_other="note", va_creview_createdat=datetime(2026, 10, 28, 9, 30),
        ))
        db.session.commit()
        self._golden("coding_masked_not_codeable", self._workspace(sid), sid)

    def test_coding_in_a_demo_training_project(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.demo_training_enabled = True
        db.session.commit()
        self.addCleanup(self._set_project, demo_training_enabled=False)
        sid = self._coding_case()
        self._stamp(sid)
        body = self._workspace(sid)
        self.assertTrue(body["case"]["is_demo_project"])
        self._golden("coding_demo_training", body, sid)

    def test_coding_masked_doris_with_saved_step_one(self):
        self._set_project(masked_cod_required=True, cod_entry_mode="doris", icd_classification="icd11")
        sid = self._coding_case(payload={"Id10019": "female", "Id10077": "no"})
        self._stamp(sid)
        self._initial_at(sid, doris_certificate=_CERT, **_RESULTS)
        self._golden("coding_doris_masked_saved", self._workspace(sid), sid)

    def test_coding_doris_redacted_viewer(self):
        self._set_project(masked_cod_required=True, cod_entry_mode="doris", icd_classification="icd11")
        sid = self._coding_case(payload={"Id10019": "female", "survey_district": "Raisen"})
        self._stamp(sid)
        with base.patch("app.routes.api.va_case.should_redact_pii", return_value=True):
            body = self._workspace(sid)
        self._golden("coding_doris_redacted", body, sid)

    # -- reviewing ---------------------------------------------------------

    def _coder_work(self, sid):
        self._initial_at(sid, doris_certificate=_CERT, **_RESULTS)
        self._final(
            sid, self.base_coder_user.user_id, "1B10.Z TB", "coder remark",
            doris_certificate=_CERT,
            doris_result={"status": "completed", "result": {"code": "1B10.Z", "report": "free text"}},
        )
        db.session.add(VaCoderReview(
            va_sid=sid, va_creview_by=self.base_coder_user.user_id, va_creview_reason="no_info",
            va_creview_createdat=datetime(2026, 10, 28, 9, 30),
        ))
        db.session.commit()

    def test_reviewing_with_saved_reviewer_work(self):
        self._mode(nqa=True, social_autopsy=True)
        sid = self._reviewing_case()
        self._stamp(sid)
        self._coder_work(sid)
        version = get_active_payload_version(sid).payload_version_id
        db.session.add_all([
            VaReviewerInitialAssessments(
                va_sid=sid, va_riniassess_by=self.reviewer.user_id, va_immediate_cod=base._COD,
                payload_version_id=version, va_antecedent_cod="B20 HIV disease",
                va_other_conditions="I10 - Essential Hypertension | E11 - Diabetes",
                va_riniassess_createdat=datetime(2026, 10, 28, 11, 0),
            ),
            VaReviewerFinalAssessments(
                va_sid=sid, va_rfinassess_by=self.reviewer.user_id, payload_version_id=version,
                va_conclusive_cod="1B10.Z TB", va_rfinassess_remark="r",
                va_rfinassess_status=VaStatuses.active,
                va_rfinassess_createdat=datetime(2026, 10, 28, 11, 30),
            ),
        ])
        db.session.commit()
        self._golden("reviewing_full", self._workspace(sid, mode="reviewing", user=self.reviewer_id), sid)

    def test_reviewing_unmasked_doris_sees_coder_doris_codes(self):
        self._set_project(masked_cod_required=False, cod_entry_mode="doris", icd_classification="icd11")
        sid = self._reviewing_case()
        self._stamp(sid)
        self._coder_work(sid)
        self._golden("reviewing_doris_unmasked", self._workspace(sid, mode="reviewing", user=self.reviewer_id), sid)

    def test_reviewing_masked_doris_fresh(self):
        self._set_project(masked_cod_required=True, cod_entry_mode="doris", icd_classification="icd11")
        sid = self._reviewing_case()
        self._stamp(sid)
        self._coder_work(sid)
        self._golden("reviewing_doris_masked", self._workspace(sid, mode="reviewing", user=self.reviewer_id), sid)

    # -- view --------------------------------------------------------------

    def _coded_case(self):
        sid = self._case(state=WORKFLOW_CODER_FINALIZED, payload={
            "FldZ": "z-val", "FldPii": "Jane Realname", "survey_district": "Raisen",
        })
        self._stamp(sid)
        other = self._make_user(f"r8nh11.a.{sid[-6:]}@test.local", "OtherA123")
        db.session.add(VaAllocations(
            va_sid=sid, va_allocated_to=other.user_id, va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.deactive, va_allocation_createdat=_T,
        ))
        db.session.commit()
        initial = self._initial_at(sid, user=other.user_id)
        version = get_active_payload_version(sid).payload_version_id
        coder_final = VaFinalAssessments(
            va_sid=sid, va_finassess_by=other.user_id, payload_version_id=version,
            va_conclusive_cod="A16 coder result", va_finassess_remark="coder remark",
            va_finassess_status=VaStatuses.active, va_finassess_createdat=datetime(2026, 10, 28, 10, 0),
            source_initial_assessment_id=initial.va_iniassess_id,
        )
        db.session.add(coder_final)
        db.session.flush()
        db.session.add_all([
            VaReviewerFinalAssessments(
                va_sid=sid, va_rfinassess_by=self.reviewer.user_id, payload_version_id=version,
                va_conclusive_cod="B20 reviewer result", va_rfinassess_remark="r",
                va_rfinassess_status=VaStatuses.active, va_rfinassess_createdat=datetime(2026, 10, 28, 11, 0),
                supersedes_coder_final_assessment_id=coder_final.va_finassess_id,
            ),
            VaCoderReview(
                va_sid=sid, va_creview_by=other.user_id, va_creview_reason="other",
                va_creview_other="free text", va_creview_createdat=datetime(2026, 10, 28, 9, 30),
            ),
            VaSmartvaResults(
                va_sid=sid, payload_version_id=version, va_smartva_status=VaStatuses.active,
                va_smartva_cause1="Stroke", va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
            ),
        ])
        db.session.commit()
        return sid

    def test_view_of_a_coded_case_for_an_unredacted_viewer(self):
        sid = self._coded_case()
        self._golden("view_coded_unredacted", self._workspace(sid, mode="view"), sid)

    def test_view_of_a_coded_case_for_a_redacted_viewer(self):
        sid = self._coded_case()
        body = self._workspace(sid, mode="view", user=self._collaborator())
        self.assertIsNone(body["assessments"]["final"]["remark"])
        self._golden("view_coded_redacted", body, sid)

    def test_view_of_a_coded_case_for_a_pii_collaborator(self):
        sid = self._coded_case()
        body = self._workspace(sid, mode="view", user=self._collaborator(VaAccessRoles.collaborator_pii))
        self._golden("view_coded_collaborator_pii", body, sid)

    def test_view_of_a_case_still_in_coding(self):
        sid = self._case(payload={"FldZ": "z-val", "survey_district": "Raisen"})
        self._golden("view_in_coding", self._workspace(sid, mode="view", user=self._collaborator()), sid)

    def test_view_by_a_reviewer(self):
        sid = self._coded_case()
        self._golden("view_coded_reviewer", self._workspace(sid, mode="view", user=self.reviewer_id), sid)
