"""Masked ICD-11 coder Step 1 (DORIS certificate) and Step 2 (confirm the
final UCOD) -- digitva-0n3 phases 2 and 3."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.routes.va_form import _final_ucod_source
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODING_IN_PROGRESS
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:4].upper()
_URI = "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified"
_TB = "1B10.Z Respiratory tuberculosis"
_STEP1_URL = "/vaform/{sid}/vainitialasses?action=vacode&actiontype=vastartcoding"
_STEP2_URL = "/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding"


def _certificate(part1):
    return {"ICDVersion": "ICD11", "ICDMinorVersion": "2026-01", "Part1": part1}


_CERTIFICATE = _certificate(
    [
        {"Conditions": [{"Text": "Respiratory tuberculosis", "Code": "1B10.Z", "LinearizationURI": _URI, "Interval": "P14D"}]},
        {"Conditions": [{"Text": "HIV disease", "Code": "1C62.Z", "LinearizationURI": _URI, "Interval": "P2Y"}]},
    ]
)
_DORIS = {"status": "completed", "result": {"code": "1C62.Z", "stemCode": "1C62.Z"}}
_CODEDIT = {"status": "completed", "result": {"issueIds": ""}}


class TestMaskedDorisCoding(BaseTestCase):
    BASE_PROJECT_ID = f"MD{_SUFFIX}"
    BASE_SITE_ID = f"M{_SUFFIX[:3]}"
    FORM_ID = f"M{_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+maskeddoris{_SUFFIX.lower()}"

    @classmethod
    def _make_user(cls, email, password):
        local, domain = email.split("@", 1)
        return super()._make_user(f"{local}{cls.USER_EMAIL_SUFFIX}@{domain}", password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="MASKED_DORIS_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        cls.reviewer = cls._make_user("reviewer.masked.doris@test.local", "ReviewerMaskedDoris123")
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.reviewer.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="masked DORIS reviewer",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        self._mode(masked=True, doris=True)
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = "sha256:pinned-image"

    def _mode(self, masked, doris):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        # ICD-11 means DORIS (CHECK cod_entry_mode_classification).
        project.icd_classification = "icd11" if doris else "icd10"
        project.cod_entry_mode = "doris" if doris else "simple"
        project.narrative_qa_enabled = False
        db.session.commit()

    def _start_coder(self, smartva_icd=None, payload_data=None):
        sid = f"uuid:masked-doris-{uuid.uuid4()}"
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_instance_name=sid,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission,
            payload_data=payload_data or {},
            source_updated_at=submission.va_odk_updatedat,
        )
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        if smartva_icd:
            db.session.add(
                VaSmartvaResults(
                    va_sid=sid,
                    va_smartva_status=VaStatuses.active,
                    va_smartva_cause1="Tuberculosis",
                    va_smartva_cause1icd=smartva_icd,
                )
            )
        set_submission_workflow_state(
            sid, WORKFLOW_CODING_IN_PROGRESS, reason="test", by_role="vasystem"
        )
        db.session.commit()
        return sid

    def _step1_row(self, sid, underlying=_TB):
        row = VaInitialAssessments(
            va_sid=sid,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod=_TB,
            va_antecedent_cod=underlying,
            doris_certificate=_CERTIFICATE,
            doris_result=_DORIS,
            codedit_result=_CODEDIT,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def _post_step1(self, sid, **overrides):
        data = {
            "va_antecedent_cod": _TB,
            "doris_certificate": json.dumps(_CERTIFICATE),
            "doris_result": json.dumps(_DORIS),
            "codedit_result": json.dumps(_CODEDIT),
            "doris_process_token": "signed",
            "doris_result_digest": "digest",
            "va_save_assessment": "1",
        }
        data.update(overrides)
        return self.client.post(
            _STEP1_URL.format(sid=sid),
            data={key: value for key, value in data.items() if value is not None},
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

    def _post_step2(self, sid, conclusive, **extra):
        return self.client.post(
            _STEP2_URL.format(sid=sid),
            data={"va_conclusive_cod": conclusive, "va_save_assessment": "1", **extra},
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

    def _final(self, sid):
        return db.session.scalar(
            db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
        )

    # ---- Step 1 ---------------------------------------------------------

    def test_step1_get_shows_doris_editor_without_smartva(self):
        sid = self._start_coder(smartva_icd="A16.9")
        self._login(self.base_coder_id)

        step1 = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)
        self._step1_row(sid)
        step2 = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)

        # SmartVA exists for this death and Step 2 shows it...
        self.assertIn("SmartVA Analysis", step2)
        # ...but Step 1 is the DORIS certificate, entered blind.
        self.assertIn("data-doris-editor", step1)
        self.assertIn('data-final-cod-input="va_antecedent_cod"', step1)
        self.assertNotIn("SmartVA", step1)
        self.assertNotIn("Tuberculosis", step1)
        self.assertNotIn("select2-root", step1)

    @patch("app.routes.va_form.build_icd11_provenance_for_values")
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_step1_post_stores_envelopes_and_derives_text_columns(
        self, verify, validate, provenance
    ):
        sid = self._start_coder()
        self._login(self.base_coder_id)
        verify.return_value = {"certificate": _CERTIFICATE, "doris": _DORIS, "codedit": _CODEDIT}
        provenance.return_value = {"antecedent": {"code": "1C62.Z"}}

        response = self._post_step1(sid, va_antecedent_cod="1C62.Z HIV disease")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = db.session.scalar(
            db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid)
        )
        # Immediate: the first condition on Part I line 1.
        self.assertEqual(row.va_immediate_cod, _TB)
        # Underlying: the coder's own confirmed cause (owner decision 1).
        self.assertEqual(row.va_antecedent_cod, "1C62.Z HIV disease")
        self.assertEqual(row.doris_certificate, _CERTIFICATE)
        self.assertEqual(row.doris_result, _DORIS)
        self.assertEqual(row.codedit_result, _CODEDIT)
        self.assertEqual(row.cod_entry_mode_snapshot["cod_entry_mode"], "doris")
        self.assertTrue(row.cod_entry_mode_snapshot["masked_cod_required"])
        self.assertEqual(row.icd11_provenance, {"antecedent": {"code": "1C62.Z"}})
        validate.assert_called_once_with(sid, "1C62.Z HIV disease")
        self.assertEqual(verify.call_args.kwargs["role"], "coder")
        # The response is Step 2's picker host, with no second certificate.
        body = response.get_data(as_text=True)
        self.assertIn("data-doris-final-host", body)
        self.assertNotIn("data-doris-editor", body)

    # ---- Prefill from the interview (digitva-hln) ------------------------

    _INJURY_PAYLOAD = {
        "Id10019": "male",
        "Id10020": "yes",
        "Id10021": "1970-02-03",
        "Id10022": "yes",
        "Id10023": "2025-08-04T00:00:00.000+05:30",
        "Id10077": "yes",
        "Id10083": "yes",
        "Id10098": "yes",
    }

    @staticmethod
    def _json_script(body, attribute):
        start = body.index(f"<script type=\"application/json\" {attribute}>") + len(
            f"<script type=\"application/json\" {attribute}>"
        )
        return json.loads(body[start : body.index("</script>", start)])

    def test_step1_get_prefills_the_certificate_from_the_interview(self):
        sid = self._start_coder(smartva_icd="A16.9", payload_data=self._INJURY_PAYLOAD)
        self._login(self.base_coder_id)

        body = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)

        initial = self._json_script(body, "data-doris-initial")
        self.assertEqual(
            initial["AdministrativeData"],
            {"Sex": 1, "DateBirth": "1970-02-03", "DateDeath": "2025-08-04"},
        )
        self.assertEqual(initial["MannerOfDeath"]["MannerOfDeath"], 1)
        self.assertEqual(initial["MannerOfDeath"]["DescriptionExternalCause"], "Fall")
        provenance = self._json_script(body, "data-doris-prefill")
        self.assertEqual(provenance["MannerOfDeath.MannerOfDeath"], {"sources": ["Id10098"]})
        self.assertEqual(provenance["AdministrativeData.DateBirth"], {"sources": ["Id10021"]})
        # Every prefilled field has a control to carry its marker.
        for path in provenance:
            self.assertIn(f'data-doris-field="{path}"', body)
        # Interview facts, not SmartVA: masked Step 1 still hides SmartVA.
        self.assertNotIn("SmartVA", body)

    def test_step1_get_with_a_saved_certificate_shows_no_prefill(self):
        sid = self._start_coder(payload_data=self._INJURY_PAYLOAD)
        self._step1_row(sid)
        self._login(self.base_coder_id)

        body = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)

        self.assertEqual(self._json_script(body, "data-doris-initial"), _CERTIFICATE)
        self.assertEqual(self._json_script(body, "data-doris-prefill"), {})

    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value={})
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_step1_post_records_prefilled_fields_and_coder_changes(self, verify, _validate, _provenance):
        sid = self._start_coder(payload_data=self._INJURY_PAYLOAD)
        self._login(self.base_coder_id)
        saved = {
            **_CERTIFICATE,
            "AdministrativeData": {"Sex": 1, "DateBirth": "1970-02-03", "DateDeath": "2025-08-04"},
            # The coder changed accident (1) to assault (3).
            "MannerOfDeath": {"MannerOfDeath": 3, "DescriptionExternalCause": "Fall"},
        }
        verify.return_value = {"certificate": saved, "doris": _DORIS, "codedit": _CODEDIT}

        response = self._post_step1(sid, doris_certificate=json.dumps(saved))

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = db.session.scalar(
            db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid)
        )
        record = row.cod_entry_mode_snapshot["doris_prefill"]
        self.assertEqual(record["version"], 1)
        self.assertEqual(
            {path: entry["changed"] for path, entry in record["fields"].items()},
            {
                "AdministrativeData.Sex": False,
                "AdministrativeData.DateBirth": False,
                "AdministrativeData.DateDeath": False,
                "MannerOfDeath.MannerOfDeath": True,
                "MannerOfDeath.DescriptionExternalCause": False,
            },
        )
        # Source ids only: no interview value leaves the certificate.
        self.assertNotIn("1970", json.dumps(record))

    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_step1_post_without_part1_line1_is_400(self, verify, _validate):
        sid = self._start_coder()
        self._login(self.base_coder_id)
        verify.return_value = {"certificate": _certificate([]), "doris": _DORIS, "codedit": _CODEDIT}

        response = self._post_step1(sid)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Part I line 1", response.get_json()["error"])
        self.assertIsNone(
            db.session.scalar(db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid))
        )

    @patch("app.routes.va_form.verify_process_submission")
    def test_step1_post_without_underlying_cause_is_400(self, verify):
        sid = self._start_coder()
        self._login(self.base_coder_id)

        response = self._post_step1(sid, va_antecedent_cod=None)

        self.assertEqual(response.status_code, 400)
        self.assertIn("underlying cause", response.get_json()["error"])
        verify.assert_not_called()
        self.assertIsNone(
            db.session.scalar(db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid))
        )

    @patch("app.routes.api.doris_clinical.process_certificate")
    def test_doris_gate_open_for_masked_coder_and_masked_reviewer(self, process):
        sid = self._start_coder()
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.reviewer.user_id,
                va_allocation_for=VaAllocation.reviewing,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.commit()
        process.return_value = {
            "schema_version": 1,
            "client_revision": 0,
            "icd_release": "2026-01",
            "certificate": _CERTIFICATE,
            "certificate_digest": "c" * 64,
            "result_digest": "r" * 64,
            "doris": _DORIS,
            "codedit": _CODEDIT,
        }
        url = f"/api/v1/doris-clinical/process/{sid}"

        self._login(self.base_coder_id)
        coder = self.client.post(
            url,
            json={"schema_version": 1, "client_revision": 0, "role": "coder", "certificate": _CERTIFICATE},
            headers=self._csrf_headers(),
        )
        self._login(str(self.reviewer.user_id))
        reviewer = self.client.post(
            url,
            json={"schema_version": 1, "client_revision": 0, "role": "reviewer", "certificate": _CERTIFICATE},
            headers=self._csrf_headers(),
        )

        self.assertEqual(coder.status_code, 200, coder.get_data(as_text=True))
        self.assertTrue(coder.get_json()["process_token"])
        # The masked reviewer runs DORIS on their own Step 1 (phase 4).
        self.assertEqual(reviewer.status_code, 200, reviewer.get_data(as_text=True))
        self.assertTrue(reviewer.get_json()["process_token"])

    def _initial_processing(self, body):
        start = body.index("data-doris-initial-processing>") + len("data-doris-initial-processing>")
        return json.loads(body[start:body.index("</script>", start)])

    def test_step1_reopen_shows_saved_result_and_continue(self):
        sid = self._start_coder()
        self._step1_row(sid, underlying="1C62.Z HIV disease")
        self._login(self.base_coder_id)

        body = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)

        saved = self._initial_processing(body)
        self.assertEqual(saved["certificate"], _CERTIFICATE)
        self.assertEqual(saved["doris"], _DORIS)
        self.assertEqual(saved["codedit"], _CODEDIT)
        self.assertEqual(saved["final_choice"], "1C62.Z HIV disease")
        # Display only: no signed proof is minted on GET.
        self.assertNotIn("process_token", saved)
        self.assertNotIn("result_digest", saved)
        self.assertIn("data-doris-continue", body)
        self.assertIn("Continue to Step 2", body)
        self.assertIn('hx-params="none"', body)
        self.assertIn(f"/vaform/{sid}/vafinalasses?", body)

    def test_step1_without_saved_row_has_no_continue(self):
        sid = self._start_coder()
        self._login(self.base_coder_id)

        body = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn("data-doris-editor", body)
        self.assertIn("data-doris-initial-processing", body)
        self.assertIsNone(self._initial_processing(body))
        self.assertNotIn("data-doris-continue", body)

    def test_step1_reopen_ignores_superseded_row(self):
        sid = self._start_coder()
        row = self._step1_row(sid)
        row.va_iniassess_status = VaStatuses.deactive
        db.session.commit()
        self._login(self.base_coder_id)

        body = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn("data-doris-editor", body)
        self.assertIsNone(self._initial_processing(body))
        self.assertNotIn("data-doris-continue", body)

    # ---- NQA gate after a Step 1 save -----------------------------------

    def _require_nqa(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.commit()

    def _saved_step1(self, sid):
        return db.session.scalar(
            db.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == sid,
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
        )

    @patch("app.routes.va_form.get_current_payload_narrative_assessment", return_value=None)
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value=None)
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_masked_doris_step1_post_shows_nqa_notice_when_nqa_missing(
        self, verify, _validate, _provenance, _nqa
    ):
        self._require_nqa()
        sid = self._start_coder()
        self._login(self.base_coder_id)
        verify.return_value = {"certificate": _CERTIFICATE, "doris": _DORIS, "codedit": _CODEDIT}

        response = self._post_step1(sid)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn("data-nqa-required", body)
        self.assertIn("data-step1-saved", body)
        self.assertNotIn("data-doris-final-host", body)
        self.assertIsNotNone(self._saved_step1(sid))

    @patch("app.routes.va_form.get_current_payload_narrative_assessment", return_value=object())
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value=None)
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_masked_doris_step1_post_shows_step2_when_nqa_done(
        self, verify, _validate, _provenance, _nqa
    ):
        self._require_nqa()
        sid = self._start_coder()
        self._login(self.base_coder_id)
        verify.return_value = {"certificate": _CERTIFICATE, "doris": _DORIS, "codedit": _CODEDIT}

        body = self._post_step1(sid).get_data(as_text=True)

        self.assertIn("data-doris-final-host", body)
        self.assertNotIn("data-nqa-required", body)

    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value=None)
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_masked_doris_step1_post_shows_step2_when_nqa_not_required(
        self, verify, _validate, _provenance
    ):
        sid = self._start_coder()
        self._login(self.base_coder_id)
        verify.return_value = {"certificate": _CERTIFICATE, "doris": _DORIS, "codedit": _CODEDIT}

        body = self._post_step1(sid).get_data(as_text=True)

        self.assertIn("data-doris-final-host", body)
        self.assertNotIn("data-nqa-required", body)

    def _post_masked_simple_step1(self, sid):
        with (
            patch("app.routes.va_form.build_icd11_provenance_for_values", return_value=None),
            patch("app.routes.va_form.validate_coding_value_for_submission", return_value="icd10"),
        ):
            return self.client.post(
                _STEP1_URL.format(sid=sid),
                data={
                    "va_immediate_cod": "A16.9 Respiratory tuberculosis",
                    "va_antecedent_cod": "B20 HIV disease",
                    "va_save_assessment": "1",
                },
                headers={**self._csrf_headers(), "HX-Request": "true"},
            )

    @patch("app.routes.va_form.get_current_payload_narrative_assessment", return_value=None)
    def test_masked_simple_step1_post_shows_nqa_notice_when_nqa_missing(self, _nqa):
        self._mode(masked=True, doris=False)
        self._require_nqa()
        sid = self._start_coder()
        self._login(self.base_coder_id)

        response = self._post_masked_simple_step1(sid)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn("data-nqa-required", body)
        self.assertNotIn("conclusive-cod-select", body)
        self.assertIsNotNone(self._saved_step1(sid))

    @patch("app.routes.va_form.get_current_payload_narrative_assessment", return_value=object())
    def test_masked_simple_step1_post_shows_step2_when_nqa_done(self, _nqa):
        self._mode(masked=True, doris=False)
        self._require_nqa()
        sid = self._start_coder()
        self._login(self.base_coder_id)

        body = self._post_masked_simple_step1(sid).get_data(as_text=True)

        self.assertIn("conclusive-cod-select", body)
        self.assertNotIn("data-nqa-required", body)

    # ---- Step 2 ---------------------------------------------------------

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1B10.Z")
    def test_step2_single_smartva_target_is_one_click(self, _mapping):
        sid = self._start_coder(smartva_icd="A16.9")
        self._step1_row(sid, underlying="1C62.Z HIV disease")
        self._login(self.base_coder_id)

        body = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn('data-final-use-code="1B10.Z"', body)
        self.assertNotIn("data-final-search-code", body)
        self.assertIn('data-final-use-value="1C62.Z HIV disease"', body)
        self.assertIn("data-step1-processing", body)
        self.assertNotIn("data-doris-editor", body)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00/1A01")
    def test_step2_multi_alternative_smartva_target_opens_search(self, _mapping):
        sid = self._start_coder(smartva_icd="A00.9")
        self._step1_row(sid)
        self._login(self.base_coder_id)

        body = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn('data-final-search-code="1A00"', body)
        self.assertNotIn("data-final-use-code", body)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value=None)
    def test_step2_labels_step1_cause_not_doris_result(self, _mapping):
        # The one-click choice is the coder's Step 1 underlying cause, not
        # DORIS's computed code; DORIS's result stays as information.
        sid = self._start_coder()
        self._step1_row(sid, underlying="1C62.Z HIV disease")
        self._login(self.base_coder_id)

        body = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn("Use Step 1 underlying cause: 1C62.Z HIV disease", body)
        self.assertNotIn("Use DORIS result", body)
        self.assertIn("DORIS result from Step 1 (for information)", body)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value=None)
    def test_step2_recode_presets_previous_final_code(self, _mapping):
        sid = self._start_coder()
        self._step1_row(sid)
        self._login(self.base_coder_id)
        fresh = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)
        submission = db.session.get(VaSubmissions, sid)
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                payload_version_id=submission.active_payload_version_id,
                va_finassess_by=self.base_coder_user.user_id,
                va_conclusive_cod="BA41.Z Acute myocardial infarction",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        recode = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn('data-preset-final=""', fresh)
        self.assertIn('data-preset-final="BA41.Z Acute myocardial infarction"', recode)

    def _save_step2(self, sid, conclusive):
        with (
            patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False),
            patch("app.routes.va_form.validate_coding_value_for_submission"),
            patch("app.routes.va_form.build_icd11_provenance_for_values", return_value=None),
        ):
            response = self._post_step2(sid, conclusive)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return self._final(sid)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00")
    def test_step2_provenance_doris(self, _mapping):
        sid = self._start_coder(smartva_icd="A00.9")
        step1 = self._step1_row(sid)
        self._login(self.base_coder_id)

        final = self._save_step2(sid, _TB)

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "doris")
        self.assertEqual(final.source_initial_assessment_id, step1.va_iniassess_id)
        # Envelopes stay on the Step 1 row (decision 4).
        self.assertIsNone(final.doris_certificate)
        self.assertIsNone(final.doris_result)
        # SQL NULL, not a JSON null, so "IS NULL" queries find these rows.
        sql_null = db.session.execute(
            db.text(
                "SELECT doris_certificate IS NULL AND doris_result IS NULL"
                " AND codedit_result IS NULL FROM va_final_assessments"
                " WHERE va_finassess_id = :id"
            ),
            {"id": final.va_finassess_id},
        ).scalar_one()
        self.assertTrue(sql_null)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00")
    def test_step2_provenance_smartva(self, _mapping):
        sid = self._start_coder(smartva_icd="A00.9")
        self._step1_row(sid)
        self._login(self.base_coder_id)

        final = self._save_step2(sid, "1A00 Cholera")

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "smartva")

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00/1A01")
    def test_step2_provenance_smartva_any_who_alternative(self, _mapping):
        sid = self._start_coder(smartva_icd="A00.9")
        self._step1_row(sid)
        self._login(self.base_coder_id)

        final = self._save_step2(sid, "1A01 Intestinal infection")

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "smartva")

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00")
    def test_step2_provenance_own(self, _mapping):
        sid = self._start_coder(smartva_icd="A00.9")
        self._step1_row(sid)
        self._login(self.base_coder_id)

        final = self._save_step2(sid, "BA41.Z Acute myocardial infarction")

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "own")

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1B10.Z")
    def test_step2_tie_between_doris_and_smartva_records_doris(self, _mapping):
        # Tie rule: the final code equals both the Step 1 (DORIS) underlying
        # cause and SmartVA's WHO target -> doris.
        sid = self._start_coder(smartva_icd="A16.9")
        self._step1_row(sid, underlying=_TB)
        self._login(self.base_coder_id)

        final = self._save_step2(sid, _TB)

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "doris")

    def test_final_ucod_source_compares_code_expressions(self):
        self.assertEqual(_final_ucod_source("1b10.z typed", _TB, []), "doris")
        self.assertEqual(_final_ucod_source("1A00 Cholera", None, ["1A00"]), "smartva")
        self.assertEqual(_final_ucod_source("not a code", _TB, ["1A00"]), "own")

    def test_step2_refuses_a_certificate(self):
        sid = self._start_coder()
        self._step1_row(sid)
        self._login(self.base_coder_id)

        response = self._post_step2(
            sid, _TB, doris_certificate=json.dumps(_CERTIFICATE), doris_process_token="signed"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Step 1", response.get_json()["error"])
        self.assertIsNone(self._final(sid))

    # ---- Regression: other modes unchanged ------------------------------

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value=None)
    @patch("app.routes.va_form.validate_coding_value_for_submission", return_value="icd10")
    def test_masked_simple_step1_and_step2_unchanged(self, _validate, _provenance, _social):
        self._mode(masked=True, doris=False)
        sid = self._start_coder()
        self._login(self.base_coder_id)

        step1_get = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)
        step1 = self.client.post(
            _STEP1_URL.format(sid=sid),
            data={
                "va_immediate_cod": "A16.9 Respiratory tuberculosis",
                "va_antecedent_cod": "B20 HIV disease",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )
        row = db.session.scalar(
            db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid)
        )
        final = self._save_step2(sid, "B20 HIV disease")

        self.assertIn("immediate-cod-select", step1_get)
        self.assertNotIn("data-doris-editor", step1_get)
        self.assertEqual(step1.status_code, 200, step1.get_data(as_text=True))
        self.assertIn("conclusive-cod-select", step1.get_data(as_text=True))
        self.assertEqual(row.va_immediate_cod, "A16.9 Respiratory tuberculosis")
        self.assertEqual(row.va_antecedent_cod, "B20 HIV disease")
        self.assertIsNone(row.doris_certificate)
        self.assertIsNone(row.cod_entry_mode_snapshot)
        self.assertEqual(final.source_initial_assessment_id, row.va_iniassess_id)
        self.assertEqual(final.cod_entry_mode_snapshot["cod_entry_mode"], "simple")
        self.assertNotIn("final_ucod_source", final.cod_entry_mode_snapshot)

    def test_step1_editor_headings_retitled(self):
        sid = self._start_coder()
        self._login(self.base_coder_id)

        body = self.client.get(_STEP1_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn(">DORIS certificate</h4>", body)
        self.assertIn("Underlying cause of death <span", body)
        self.assertNotIn("Step 1: DORIS", body)
        self.assertNotIn("Step 2: Final underlying cause of death", body)

    def test_unmasked_doris_editor_headings_unchanged(self):
        self._mode(masked=False, doris=True)
        sid = self._start_coder()
        self._login(self.base_coder_id)

        body = self.client.get(_STEP2_URL.format(sid=sid)).get_data(as_text=True)

        self.assertIn("data-doris-editor", body)
        self.assertIn(">Step 1: DORIS</h4>", body)
        self.assertIn("Step 2: Final underlying cause of death <span", body)
        self.assertIn("Process the certificate in Step 1 first.", body)
        self.assertNotIn("DORIS certificate</h4>", body)

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value={})
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_unmasked_doris_final_unchanged(self, verify, _validate, _provenance, _social):
        self._mode(masked=False, doris=True)
        sid = self._start_coder()
        self._login(self.base_coder_id)
        verify.return_value = {"certificate": _CERTIFICATE, "doris": _DORIS, "codedit": _CODEDIT}

        response = self._post_step2(
            sid,
            _TB,
            doris_certificate=json.dumps(_CERTIFICATE),
            doris_result=json.dumps(_DORIS),
            codedit_result=json.dumps(_CODEDIT),
            doris_process_token="signed",
            doris_result_digest="digest",
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        final = self._final(sid)
        self.assertEqual(final.doris_certificate, _CERTIFICATE)
        self.assertIsNone(final.source_initial_assessment_id)
        self.assertEqual(
            set(final.cod_entry_mode_snapshot),
            {"masked_cod_required", "cod_entry_mode", "icd_release", "who_image_digest", "doris_prefill"},
        )
