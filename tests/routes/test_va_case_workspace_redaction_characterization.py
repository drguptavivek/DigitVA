"""Redacted-viewer reviewing workspace, pinned before the redact_pii/icd refactor (digitva-r8nh.11).

The first characterization file covers redaction in coding and view only; this
adds reviewing with a redacted viewer in a DORIS project (survey location and
the DORIS seed both take the redaction flag). Record with RECORD_WORKSPACE_GOLDEN=1.
"""
import json
import os
import pathlib

from app.models import VaAllocation
from app.services.workflow.definition import WORKFLOW_REVIEWER_CODING_IN_PROGRESS
from tests.routes import test_va_case_workspace_characterization as char

_GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "va_case_workspace_redaction_golden.json"


class WorkspaceRedactionCharacterizationTests(char.WorkspaceCharacterizationTests):
    locals().update({
        name: None for name in dir(char.WorkspaceCharacterizationTests) if name.startswith("test_")
    })

    def _golden(self, name, body, sid):
        actual = char._normalise(body, sid)
        golden = json.loads(_GOLDEN.read_text()) if _GOLDEN.exists() else {}
        if os.environ.get("RECORD_WORKSPACE_GOLDEN"):
            golden[name] = actual
            _GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n")
            return
        self.assertIn(name, golden)
        self.assertEqual(actual, golden[name])

    def test_reviewing_doris_redacted_viewer(self):
        self._set_project(masked_cod_required=False, cod_entry_mode="doris", icd_classification="icd11")
        sid = self._case(
            state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
            allocated_to=self.reviewer.user_id, allocation_for=VaAllocation.reviewing,
            payload={"Id10019": "female", "survey_district": "Raisen"},
        )
        self._stamp(sid)
        self._coder_work(sid)
        with char.base.patch("app.routes.api.va_case.should_redact_pii", return_value=True):
            body = self._workspace(sid, mode="reviewing", user=self.reviewer_id)
        self._golden("reviewing_doris_redacted", body, sid)
