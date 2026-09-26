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
    VaProjectMaster,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
)
from app.services.doris_process_proof import (
    ProcessProofCertificateChanged,
    generate_process_proof,
)
from app.services.doris_processing import certificate_digest, processor_result_digest
from app.services.final_cod_authority_service import get_authoritative_final_cod_record
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    start_reviewer_coding,
    submit_reviewer_final_cod,
    submit_reviewer_initial_cod,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODING_IN_PROGRESS, WORKFLOW_REVIEWER_ELIGIBLE
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestDorisClinicalFinalization(BaseTestCase):
    BASE_PROJECT_ID = f"DF{_SUFFIX}"
    BASE_SITE_ID = f"D{_SUFFIX[:3]}"
    FORM_ID = f"D{_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+dorisfinal{_SUFFIX.lower()}"

    @classmethod
    def _make_user(cls, email, password):
        local, domain = email.split("@", 1)
        return super()._make_user(
            f"{local}{cls.USER_EMAIL_SUFFIX}@{domain}", password
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        project.icd_classification = "icd11"
        cls._ensure_base_research_project_and_site()
        db.session.commit()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="DORIS_FINAL_FORM",
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
        cls.reviewer = cls._make_user(
            "reviewer.doris.final@test.local", "ReviewerDorisFinal123"
        )
        cls.reviewer.landing_page = "reviewer"
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.reviewer.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="DORIS final reviewer",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = True
        project.cod_entry_mode = "simple"
        project.icd_classification = "icd11"
        db.session.flush()

    def _start(self, sid):
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
            submission, payload_data={}, source_updated_at=submission.va_odk_updatedat
        )
        set_submission_workflow_state(
            sid, WORKFLOW_REVIEWER_ELIGIBLE, reason="test", by_role="vasystem"
        )
        db.session.commit()
        start_reviewer_coding(self.reviewer, sid)
        return submission

    def _unmasked(self, mode):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = False
        project.cod_entry_mode = mode
        db.session.commit()

    def _start_coder(self, sid):
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
            submission, payload_data={}, source_updated_at=submission.va_odk_updatedat
        )
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        set_submission_workflow_state(
            sid, WORKFLOW_CODING_IN_PROGRESS, reason="test", by_role="vasystem"
        )
        db.session.commit()
        return submission

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.build_icd11_provenance_for_values")
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    def test_coder_unmasked_simple_saves_final_without_initial(
        self, _validate, provenance, _social
    ):
        sid = f"uuid:coder-simple-{uuid.uuid4()}"
        self._unmasked("simple")
        self._start_coder(sid)
        self._login(self.base_coder_id)
        provenance.side_effect = lambda _sid, values: {
            next(iter(values)): {"code": "BA41.Z"}
        }

        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_immediate_cod": "BA41.Z Acute myocardial infarction",
                "va_conclusive_cod": "BA41.Z Acute myocardial infarction",
                "va_other_conditions": "Diabetes",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        final = db.session.scalar(
            db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
        )
        self.assertEqual(final.va_immediate_cod, "BA41.Z Acute myocardial infarction")
        self.assertEqual(final.va_other_conditions, "Diabetes")
        self.assertIsNone(final.source_initial_assessment_id)

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value={})
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    @patch("app.routes.va_form.verify_process_submission")
    def test_coder_doris_persists_verified_payload(
        self, verify, _validate, _provenance, _social
    ):
        sid = f"uuid:coder-doris-{uuid.uuid4()}"
        self._unmasked("doris")
        self._start_coder(sid)
        self._login(self.base_coder_id)
        certificate = {"ICDVersion": "ICD11", "Part1": []}
        doris = {"status": "rejected", "result": {"reject": True}}
        codedit = {"status": "completed", "result": {"issueIds": []}}
        verify.return_value = {
            "certificate": certificate,
            "doris": doris,
            "codedit": codedit,
        }

        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_conclusive_cod": "BA41.Z Acute myocardial infarction",
                "doris_certificate": '{"browser":"certificate"}',
                "doris_result": '{"browser":"doris"}',
                "codedit_result": '{"browser":"codedit"}',
                "doris_process_token": "signed",
                "doris_result_digest": "digest",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        final = db.session.scalar(
            db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
        )
        self.assertEqual(final.doris_certificate, certificate)
        self.assertEqual(final.doris_result, doris)
        self.assertEqual(final.codedit_result, codedit)
        self.assertEqual(final.va_conclusive_cod, "BA41.Z Acute myocardial infarction")
        authority = get_authoritative_final_cod_record(sid)
        self.assertEqual(authority.coder_final_assessment_id, final.va_finassess_id)
        self.assertEqual(authority.va_conclusive_cod, final.va_conclusive_cod)
        self.assertIsNotNone(
            db.session.scalar(
                db.select(VaSubmissionsAuditlog).where(
                    VaSubmissionsAuditlog.va_sid == sid,
                    VaSubmissionsAuditlog.va_audit_action == "final cod submitted",
                )
            )
        )

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value={})
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    def test_coder_exact_signed_proof_saves_envelopes_ucod_and_authority(
        self, _validate, _provenance, _social
    ):
        sid = f"uuid:signed-final-{uuid.uuid4()}"
        self._unmasked("doris")
        submission = self._start_coder(sid)
        allocation = db.session.scalar(
            db.select(VaAllocations).where(VaAllocations.va_sid == sid)
        )
        certificate = {
            "ICDVersion": "ICD11",
            "ICDMinorVersion": "2026-01",
            "Part1": [{"Conditions": [{
                "Text": "Respiratory tuberculosis",
                "Code": "1B10.Z",
                "LinearizationURI": "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified",
                "Interval": "P14D",
            }]}],
        }
        doris = {"status": "unavailable", "result": None}
        codedit = {"status": "unavailable", "result": None}
        digest = self.app.config["DORIS_WHO_IMAGE_DIGEST"]
        result_digest = processor_result_digest(
            doris, codedit, release="2026-01", who_image_digest=digest
        )
        token = generate_process_proof(
            certificate_digest=certificate_digest(certificate),
            result_digest=result_digest,
            va_sid=sid,
            role="coder",
            user_id=self.base_coder_user.user_id,
            allocation_id=allocation.va_allocation_id,
            payload_version_id=submission.active_payload_version_id,
            icd_release="2026-01",
            who_image_digest=digest,
        )
        self._login(self.base_coder_id)
        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_conclusive_cod": "1B10.Z Respiratory tuberculosis",
                "doris_certificate": json.dumps(certificate),
                "doris_result": json.dumps(doris),
                "codedit_result": json.dumps(codedit),
                "doris_process_token": token,
                "doris_result_digest": result_digest,
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        final = db.session.scalar(
            db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
        )
        self.assertEqual(final.doris_certificate, certificate)
        self.assertEqual(final.doris_result, doris)
        self.assertEqual(final.codedit_result, codedit)
        self.assertEqual(final.va_conclusive_cod, "1B10.Z Respiratory tuberculosis")
        self.assertEqual(
            get_authoritative_final_cod_record(sid).coder_final_assessment_id,
            final.va_finassess_id,
        )
        self.assertIsNotNone(
            db.session.scalar(
                db.select(VaSubmissionsAuditlog).where(
                    VaSubmissionsAuditlog.va_sid == sid,
                    VaSubmissionsAuditlog.va_audit_action == "final cod submitted",
                )
            )
        )

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.verify_process_submission")
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    def test_coder_failed_nqa_save_rerenders_submitted_certificate_and_error(
        self, _validate, verify, _social
    ):
        sid = f"uuid:failed-nqa-{uuid.uuid4()}"
        self._unmasked("doris")
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.commit()
        self._start_coder(sid)
        self._login(self.base_coder_id)
        certificate = {
            "ICDVersion": "ICD11",
            "Part1": [{"Conditions": [{"Text": "New clinical entry"}]}],
        }
        verify.return_value = {
            "certificate": certificate,
            "doris": {"status": "unavailable", "result": None},
            "codedit": {"status": "unavailable", "result": None},
        }

        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_conclusive_cod": "1B10.Z Respiratory tuberculosis",
                "va_finassess_remark": "Keep this clinical remark",
                "doris_certificate": json.dumps(certificate),
                "doris_result": '{"status":"unavailable","result":null}',
                "codedit_result": '{"status":"unavailable","result":null}',
                "doris_process_token": "signed",
                "doris_result_digest": "digest",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Narrative Quality Assessment must be completed", html)
        self.assertIn("New clinical entry", html)
        self.assertIn("Keep this clinical remark", html)
        self.assertIsNone(
            db.session.scalar(
                db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
            )
        )

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.build_icd11_provenance_for_values", return_value={})
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    def test_coder_failed_simple_save_rerenders_submitted_fields(
        self, _validate, _provenance, _social
    ):
        sid = f"uuid:failed-simple-{uuid.uuid4()}"
        self._unmasked("simple")
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.commit()
        self._start_coder(sid)
        self._login(self.base_coder_id)

        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_immediate_cod": "BA41.Z Immediate selection",
                "va_conclusive_cod": "1B10.Z Underlying selection",
                "va_other_conditions": "Associated clinical details",
                "va_finassess_remark": "Remark after failure",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Narrative Quality Assessment must be completed", html)
        for value in (
            "BA41.Z Immediate selection",
            "1B10.Z Underlying selection",
            "Associated clinical details",
            "Remark after failure",
        ):
            self.assertIn(value, html)
        self.assertIsNone(
            db.session.scalar(
                db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
            )
        )

    @patch("app.routes.va_form._is_social_autopsy_enabled_for_submission", return_value=False)
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    def test_coder_rerender_reports_malformed_submitted_certificate(
        self, _validate, _social
    ):
        sid = f"uuid:malformed-certificate-{uuid.uuid4()}"
        self._unmasked("doris")
        submission = self._start_coder(sid)
        # Force the route down its blocking-message rerender path before it
        # reaches processor proof parsing. The submitted raw value must still
        # produce an explicit validation message.
        payload = db.session.scalar(
            db.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.payload_version_id
                == submission.active_payload_version_id
            )
        )
        payload.version_status = "superseded"
        submission.active_payload_version_id = None
        db.session.commit()
        self._login(self.base_coder_id)

        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_conclusive_cod": "1B10.Z Respiratory tuberculosis",
                "doris_certificate": "{not-json",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("doris_certificate must be valid JSON.", response.get_data(as_text=True))

    def test_coder_doris_final_rejects_oversized_body_before_form_parse(self):
        sid = f"uuid:oversized-final-{uuid.uuid4()}"
        self._unmasked("doris")
        self._start_coder(sid)
        self._login(self.base_coder_id)
        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={"doris_certificate": "x" * 1_200_000},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 413)

    @patch("app.routes.va_form.generate_process_proof", return_value="fresh-token")
    @patch("app.routes.va_form.process_certificate")
    @patch(
        "app.routes.va_form.verify_process_submission",
        side_effect=ProcessProofCertificateChanged("changed"),
    )
    @patch("app.routes.va_form.validate_coding_value_for_submission")
    def test_coder_changed_certificate_returns_fresh_proof_without_saving(
        self, _validate, _verify, process, _proof
    ):
        sid = f"uuid:coder-changed-{uuid.uuid4()}"
        self._unmasked("doris")
        self._start_coder(sid)
        self._login(self.base_coder_id)
        process.return_value = {
            "certificate_digest": "new-certificate",
            "result_digest": "new-results",
            "doris": {"status": "unavailable", "result": None},
            "codedit": {"status": "unavailable", "result": None},
        }

        response = self.client.post(
            f"/vaform/{sid}/vafinalasses?action=vacode&actiontype=vastartcoding",
            data={
                "va_conclusive_cod": "BA41.Z Acute myocardial infarction",
                "doris_certificate": '{"ICDVersion":"ICD11","Part1":[]}',
                "doris_result": '{}',
                "codedit_result": '{}',
                "doris_process_token": "old-token",
                "doris_result_digest": "old-results",
                "va_save_assessment": "1",
            },
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "DORIS_CERTIFICATE_CHANGED")
        self.assertEqual(response.get_json()["processing"]["process_token"], "fresh-token")
        self.assertIsNone(
            db.session.scalar(
                db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
            )
        )
        self.assertIsNotNone(
            db.session.scalar(
                db.select(VaAllocations).where(
                    VaAllocations.va_sid == sid,
                    VaAllocations.va_allocation_status == VaStatuses.active,
                )
            )
        )

    @patch(
        "app.services.reviewer_coding_service._reviewer_social_autopsy_required",
        return_value=False,
    )
    @patch("app.services.reviewer_coding_service.build_icd11_provenance_for_values")
    @patch(
        "app.services.reviewer_final_assessment_service.build_icd11_provenance_for_values",
        return_value={"conclusive": {"code": "BA41.Z"}},
    )
    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    def test_unmasked_simple_saves_one_final_row_without_step_one(
        self, _validate, _final_provenance, provenance, _social
    ):
        sid = f"uuid:unmasked-simple-{uuid.uuid4()}"
        self._unmasked("simple")
        self._start(sid)
        provenance.side_effect = lambda _sid, values: {
            next(iter(values)): {"code": "BA41.Z"}
        }

        final = submit_reviewer_final_cod(
            self.reviewer,
            sid,
            immediate_cod="BA41.Z Acute myocardial infarction",
            conclusive_cod="BA41.Z Acute myocardial infarction",
            other_conditions="Diabetes",
        )

        self.assertEqual(final.va_immediate_cod, "BA41.Z Acute myocardial infarction")
        self.assertEqual(final.va_other_conditions, "Diabetes")
        self.assertIsNone(final.source_reviewer_initial_assessment_id)
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerInitialAssessments).where(
                    VaReviewerInitialAssessments.va_sid == sid
                )
            )
        )
        self.assertEqual(final.cod_entry_mode_snapshot["cod_entry_mode"], "simple")

    def test_unmasked_mode_rejects_reviewer_step_one(self):
        sid = f"uuid:unmasked-step-one-{uuid.uuid4()}"
        self._unmasked("simple")
        self._start(sid)

        with self.assertRaises(ReviewerCodingError) as caught:
            submit_reviewer_initial_cod(
                self.reviewer,
                sid,
                immediate_cod="BA41.Z Acute myocardial infarction",
                antecedent_cod="BA41.Z Acute myocardial infarction",
            )

        self.assertEqual(caught.exception.status_code, 409)

    @patch(
        "app.services.reviewer_coding_service._reviewer_social_autopsy_required",
        return_value=False,
    )
    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    @patch(
        "app.services.reviewer_coding_service.build_icd11_provenance_for_values",
        return_value={"conclusive": {"code": "BA41.Z"}},
    )
    def test_unmasked_final_does_not_link_legacy_reviewer_initial(
        self, _provenance, _validate, _social
    ):
        sid = f"uuid:legacy-initial-{uuid.uuid4()}"
        self._start(sid)
        initial = VaReviewerInitialAssessments(
            va_sid=sid,
            payload_version_id=db.session.get(VaSubmissions, sid).active_payload_version_id,
            va_riniassess_by=self.reviewer.user_id,
            va_immediate_cod="BA41.Z Old immediate",
            va_antecedent_cod="BA41.Z Old antecedent",
        )
        db.session.add(initial)
        db.session.commit()
        self._unmasked("doris")
        with patch(
            "app.services.reviewer_coding_service.verify_process_submission",
            return_value={"certificate": {}, "doris": {}, "codedit": {}},
        ):
            final = submit_reviewer_final_cod(
                self.reviewer,
                sid,
                conclusive_cod="BA41.Z Acute myocardial infarction",
                doris_process_token="signed",
            )
        self.assertIsNone(final.source_reviewer_initial_assessment_id)

    def test_reviewer_finalize_rejects_non_text_cod_without_server_error(self):
        self._login(str(self.reviewer.user_id))
        response = self.client.post(
            "/api/v1/reviewing/finalize/uuid:invalid-json-input",
            json={"conclusive_cod": {"code": "BA41.Z"}},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("conclusive_cod must be text", response.get_json()["error"])

    def test_reviewer_doris_final_rejects_oversized_json(self):
        sid = f"uuid:reviewer-oversize-{uuid.uuid4()}"
        self._unmasked("doris")
        self._start(sid)
        self._login(str(self.reviewer.user_id))
        response = self.client.post(
            f"/api/v1/reviewing/finalize/{sid}",
            json={"conclusive_cod": "1B10.Z", "padding": "x" * 1_200_000},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 413)
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerFinalAssessments).where(
                    VaReviewerFinalAssessments.va_sid == sid
                )
            )
        )

    @patch(
        "app.services.reviewer_coding_service._reviewer_social_autopsy_required",
        return_value=False,
    )
    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    @patch(
        "app.services.reviewer_coding_service.build_icd11_provenance_for_values",
        return_value={"conclusive": {"code": "BA41.Z"}},
    )
    @patch(
        "app.services.reviewer_final_assessment_service.build_icd11_provenance_for_values",
        return_value={"conclusive": {"code": "BA41.Z"}},
    )
    @patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_unmasked_doris_persists_only_verified_final_payload(
        self, verify, _final_helper_provenance, _service_provenance, _validate, _social
    ):
        sid = f"uuid:doris-final-{uuid.uuid4()}"
        self._unmasked("doris")
        submission = self._start(sid)
        certificate = {"ICDVersion": "ICD11", "Part1": []}
        doris = {"status": "rejected", "result": {"reject": True}}
        codedit = {"status": "completed", "result": {"issueIds": []}}
        verify.return_value = {
            "certificate": certificate,
            "doris": doris,
            "codedit": codedit,
        }

        final = submit_reviewer_final_cod(
            self.reviewer,
            sid,
            conclusive_cod="BA41.Z Acute myocardial infarction",
            doris_certificate={"browser": "value"},
            doris_result={"browser": "value"},
            codedit_result={"browser": "value"},
            doris_process_token="signed",
            doris_result_digest="digest",
        )

        self.assertEqual(final.doris_certificate, certificate)
        self.assertEqual(final.doris_result, doris)
        self.assertEqual(final.codedit_result, codedit)
        self.assertEqual(final.va_conclusive_cod, "BA41.Z Acute myocardial infarction")
        authority = get_authoritative_final_cod_record(sid)
        self.assertEqual(authority.reviewer_final_assessment_id, final.va_rfinassess_id)
        self.assertEqual(authority.va_conclusive_cod, final.va_conclusive_cod)
        self.assertIsNotNone(
            db.session.scalar(
                db.select(VaSubmissionsAuditlog).where(
                    VaSubmissionsAuditlog.va_sid == sid,
                    VaSubmissionsAuditlog.va_audit_action == "reviewer final cod submitted",
                )
            )
        )
        self.assertEqual(
            verify.call_args.kwargs["payload_version_id"],
            submission.active_payload_version_id,
        )

    @patch("app.services.reviewer_coding_service.generate_process_proof")
    @patch("app.services.reviewer_coding_service.process_certificate")
    @patch("app.services.reviewer_coding_service.verify_process_submission")
    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    def test_changed_doris_certificate_reprocesses_and_saves_nothing(
        self, _validate, verify, process, generate
    ):
        sid = f"uuid:doris-changed-{uuid.uuid4()}"
        self._unmasked("doris")
        self._start(sid)
        verify.side_effect = ProcessProofCertificateChanged("changed")
        process.return_value = {
            "certificate_digest": "new-cert",
            "result_digest": "new-result",
            "doris": {"status": "rejected", "result": {"reject": True}},
            "codedit": {"status": "completed", "result": {"issueIds": []}},
        }
        generate.return_value = "fresh-token"

        with self.assertRaises(ReviewerCodingError) as caught:
            submit_reviewer_final_cod(
                self.reviewer,
                sid,
                conclusive_cod="BA41.Z Acute myocardial infarction",
                doris_certificate={"ICDVersion": "ICD11", "Part1": []},
                doris_result={},
                codedit_result={},
                doris_process_token="old",
                doris_result_digest="old",
            )

        self.assertEqual(caught.exception.code, "DORIS_CERTIFICATE_CHANGED")
        self.assertEqual(caught.exception.processing["process_token"], "fresh-token")
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerFinalAssessments).where(
                    VaReviewerFinalAssessments.va_sid == sid
                )
            )
        )
        self.assertIsNotNone(
            db.session.scalar(
                db.select(VaAllocations).where(
                    VaAllocations.va_sid == sid,
                    VaAllocations.va_allocation_status == VaStatuses.active,
                )
            )
        )
