"""Masked ICD-11 reviewer Step 1 (own DORIS certificate, seeded from the
coder's) and Step 2 (confirm the final UCOD) -- digitva-0n3 phase 4."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app import db
from app.models import (
    MasCategoryDisplayConfig,
    MasFormTypes,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.doris_process_proof import ProcessProofCertificateChanged
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    submit_reviewer_final_cod,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_REVIEWER_CODING_IN_PROGRESS
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase
from tests.services.test_masked_doris_coding import (
    _CERTIFICATE,
    _CODEDIT,
    _DORIS,
    _TB,
    _URI,
    _certificate,
)

_SUFFIX = uuid.uuid4().hex[:4].upper()
_PANEL_URL = "/vaform/{sid}/vacodassessment?action=vareview&actiontype=varesumereviewing"
_INITIAL_URL = "/api/v1/reviewing/initial/{sid}"
_PROCESS_URL = "/api/v1/doris-clinical/process/{sid}"
_HIV = "1C62.Z HIV disease"
_CODER_CERTIFICATE = _certificate(
    [{"Conditions": [{"Text": "Coder copy condition", "Code": "1B10.Z", "LinearizationURI": _URI}]}]
)
_REVIEWER_CERTIFICATE = _certificate(
    [{"Conditions": [{"Text": "Reviewer own condition", "Code": "1C62.Z", "LinearizationURI": _URI}]}]
)
_SMARTVA_CAUSE = "SmartVAOnlyCauseName"


class TestMaskedDorisReviewing(BaseTestCase):
    BASE_PROJECT_ID = f"MR{_SUFFIX}"
    BASE_SITE_ID = f"R{_SUFFIX[:3]}"
    FORM_ID = f"R{_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+maskeddorisrev{_SUFFIX.lower()}"

    @classmethod
    def _make_user(cls, email, password):
        local, domain = email.split("@", 1)
        return super()._make_user(f"{local}{cls.USER_EMAIL_SUFFIX}@{domain}", password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        # The reviewer COD panel is a category partial, so the form needs a
        # form type for the category navigation to resolve.
        form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code=f"MASKED_DORIS_REVIEW_{_SUFFIX}",
            form_type_name="Masked DORIS Review Test Form",
            is_active=True,
        )
        db.session.add(form_type)
        db.session.flush()
        db.session.add(
            MasCategoryDisplayConfig(
                form_type_id=form_type.form_type_id,
                category_code="vanarrationanddocuments",
                display_label="Narration / Documents / COD",
                nav_label="Narration / Documents / COD",
                icon_name="fa-file-medical-alt",
                display_order=1,
                render_mode="attachments",
                show_to_coder=True,
                show_to_reviewer=True,
                show_to_site_pi_datamanager=True,
                always_include=True,
                is_default_start=True,
                is_active=True,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="MASKED_DORIS_REVIEW_FORM",
                odk_project_id="1",
                form_type_id=form_type.form_type_id,
                form_type=form_type.form_type_code,
                form_status=VaStatuses.active,
            )
        )
        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        cls.reviewer = cls._make_user("reviewer.masked.dorisrev@test.local", "ReviewerMaskedDoris123")
        cls.reviewer.landing_page = "reviewer"
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
        cls.reviewer_id = str(cls.reviewer.user_id)

    def setUp(self):
        super().setUp()
        self._mode(masked=True, doris=True)
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = "sha256:pinned-image"
        # One active reviewing allocation per reviewer.
        for allocation in db.session.scalars(
            db.select(VaAllocations).where(
                VaAllocations.va_allocated_to == self.reviewer.user_id,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        ).all():
            allocation.va_allocation_status = VaStatuses.deactive
        db.session.commit()

    def _mode(self, masked, doris):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        project.icd_classification = "icd11" if doris else "icd10"
        project.cod_entry_mode = "doris" if doris else "simple"
        project.narrative_qa_enabled = False
        project.reviewer_social_autopsy_enabled = False
        db.session.commit()

    def _start_review(self, smartva_icd=None, allocate=True, payload_data=None):
        """A coder-finalized masked death in reviewer coding, with the
        coder's Step 1 certificate behind the authoritative coder final."""
        sid = f"uuid:masked-doris-rev-{uuid.uuid4()}"
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
            va_category_list=["vacodassessment"],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission,
            payload_data=payload_data or {},
            source_updated_at=submission.va_odk_updatedat,
        )
        coder_step1 = VaInitialAssessments(
            va_sid=sid,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod=_TB,
            va_antecedent_cod=_TB,
            doris_certificate=_CODER_CERTIFICATE,
            doris_result=_DORIS,
            codedit_result=_CODEDIT,
            va_iniassess_status=VaStatuses.deactive,
        )
        db.session.add(coder_step1)
        db.session.flush()
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                payload_version_id=submission.active_payload_version_id,
                va_finassess_by=self.base_coder_user.user_id,
                source_initial_assessment_id=coder_step1.va_iniassess_id,
                va_conclusive_cod=_TB,
                va_finassess_status=VaStatuses.active,
            )
        )
        if allocate:
            db.session.add(
                VaAllocations(
                    va_sid=sid,
                    va_allocated_to=self.reviewer.user_id,
                    va_allocation_for=VaAllocation.reviewing,
                    va_allocation_status=VaStatuses.active,
                )
            )
        if smartva_icd:
            db.session.add(
                VaSmartvaResults(
                    va_sid=sid,
                    va_smartva_status=VaStatuses.active,
                    va_smartva_cause1=_SMARTVA_CAUSE,
                    va_smartva_cause1icd=smartva_icd,
                )
            )
        set_submission_workflow_state(
            sid, WORKFLOW_REVIEWER_CODING_IN_PROGRESS, reason="test", by_role="vasystem"
        )
        db.session.commit()
        return sid

    def _reviewer_step1(self, sid, underlying=_HIV, certificate=_REVIEWER_CERTIFICATE):
        submission = db.session.get(VaSubmissions, sid)
        row = VaReviewerInitialAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_riniassess_by=self.reviewer.user_id,
            va_immediate_cod="1C62.Z Reviewer own condition",
            va_antecedent_cod=underlying,
            doris_certificate=certificate,
            doris_result=_DORIS if certificate else None,
            codedit_result=_CODEDIT if certificate else None,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def _panel(self, sid):
        self._login(self.reviewer_id)
        response = self.client.get(_PANEL_URL.format(sid=sid))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        return response.get_data(as_text=True)

    @staticmethod
    def _script_json(body, marker):
        start = body.index(marker + ">") + len(marker) + 1
        return json.loads(body[start:body.index("</script>", start)])

    def _post_initial(self, sid, **overrides):
        body = {
            "antecedent_cod": _HIV,
            "doris_certificate": _REVIEWER_CERTIFICATE,
            "doris_result": _DORIS,
            "codedit_result": _CODEDIT,
            "doris_process_token": "signed",
            "doris_result_digest": "digest",
        }
        body.update(overrides)
        self._login(self.reviewer_id)
        return self.client.post(
            _INITIAL_URL.format(sid=sid),
            json={key: value for key, value in body.items() if value is not None},
            headers=self._csrf_headers(),
        )

    def _coder_rows(self, sid):
        initial = db.session.scalar(
            db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid)
        )
        final = db.session.scalar(
            db.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)
        )
        return (
            initial.doris_certificate,
            initial.va_immediate_cod,
            initial.va_antecedent_cod,
            initial.va_iniassess_status,
            final.va_conclusive_cod,
            final.va_finassess_status,
        )

    # ---- Step 1 GET -------------------------------------------------------

    def test_step1_seeds_from_a_copy_of_the_coders_certificate_without_smartva(self):
        sid = self._start_review(smartva_icd="A16.9")

        body = self._panel(sid)

        self.assertIn('id="reviewerDorisInitialForm"', body)
        self.assertIn('data-role="reviewer"', body)
        self.assertIn('data-final-cod-input="reviewer-antecedent-cod"', body)
        self.assertEqual(self._script_json(body, "data-doris-initial"), _CODER_CERTIFICATE)
        self.assertIsNone(self._script_json(body, "data-doris-initial-processing"))
        self.assertNotIn("data-doris-continue", body)
        # No SmartVA before the reviewer's Step 1 is saved.
        self.assertNotIn("SmartVA Analysis", body)
        self.assertNotIn(_SMARTVA_CAUSE, body)
        self.assertNotIn('id="reviewer-select2-root"', body)
        self.assertNotIn('id="reviewerFinalCodForm"', body)

    def test_step1_saves_land_on_resume_not_a_reload(self):
        # Reloading /reviewing/start/<sid> re-runs the start, which is refused
        # once the review is under way, so both masked Step 1 forms go to resume.
        for doris in (True, False):
            with self.subTest(doris=doris):
                self._mode(masked=True, doris=doris)
                sid = self._start_review(smartva_icd="A16.9")
                body = self._panel(sid)
                form_id = "reviewerDorisInitialForm" if doris else "reviewerInitialCodForm"
                self.assertIn(f'id="{form_id}"', body)
                self.assertIn('"/reviewing/resume?section=vacodassessment"', body)
                self.assertNotIn("window.location.reload()", body)

    def test_step1_seeds_from_admin_defaults_without_a_coder_certificate(self):
        sid = self._start_review()
        coder_step1 = db.session.scalar(
            db.select(VaInitialAssessments).where(VaInitialAssessments.va_sid == sid)
        )
        coder_step1.doris_certificate = None
        db.session.commit()

        body = self._panel(sid)

        self.assertIn('id="reviewerDorisInitialForm"', body)
        self.assertNotEqual(self._script_json(body, "data-doris-initial"), _CODER_CERTIFICATE)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1B10.Z")
    def test_step1_reopens_from_the_reviewers_own_row_with_step2(self, _mapping):
        sid = self._start_review(smartva_icd="A16.9")
        self._reviewer_step1(sid)

        body = self._panel(sid)

        self.assertEqual(self._script_json(body, "data-doris-initial"), _REVIEWER_CERTIFICATE)
        saved = self._script_json(body, "data-doris-initial-processing")
        self.assertEqual(saved["certificate"], _REVIEWER_CERTIFICATE)
        self.assertEqual(saved["doris"], _DORIS)
        self.assertEqual(saved["final_choice"], _HIV)
        # Display only: no signed proof is minted on GET.
        self.assertNotIn("process_token", saved)
        self.assertNotIn("result_digest", saved)
        self.assertIn("data-doris-continue", body)
        self.assertIn("Continue to Step 2", body)
        # Step 2: SmartVA, the reviewer's own Step 1 result, three choices.
        step2 = body[body.index('id="reviewerFinalCodForm"'):]
        self.assertIn("SmartVA Analysis", step2)
        self.assertIn(_SMARTVA_CAUSE, step2)
        self.assertIn("data-doris-final-host", step2)
        self.assertIn('data-form-id="reviewerFinalCodForm"', step2)
        self.assertIn('data-final-cod-input="reviewer-conclusive-cod"', step2)
        self.assertIn(f'data-final-use-value="{_HIV}"', step2)
        self.assertIn('data-final-use-code="1B10.Z"', step2)
        self.assertNotIn("data-final-search-code", step2)
        self.assertEqual(self._script_json(step2, "data-step1-processing")["doris"], _DORIS)
        self.assertNotIn('id="reviewer-conclusive-cod-select"', step2)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00/1A01")
    def test_step2_multi_alternative_smartva_target_opens_search(self, _mapping):
        sid = self._start_review(smartva_icd="A00.9")
        self._reviewer_step1(sid)

        body = self._panel(sid)

        self.assertIn('data-final-search-code="1A00"', body)
        self.assertNotIn("data-final-use-code", body)

    def test_view_only_panel_skips_the_reviewer_doris_context(self):
        sid = self._start_review(smartva_icd="A16.9")
        self._login(self.reviewer_id)
        with patch(
            "app.routes.va_form._masked_reviewer_doris_context",
            return_value=(None, {}),
        ) as context:
            active = self.client.get(_PANEL_URL.format(sid=sid))
            self.assertEqual(active.status_code, 200)
            self.assertEqual(context.call_count, 1)
            view = self.client.get(
                _PANEL_URL.format(sid=sid).replace("varesumereviewing", "vaview")
            )

        self.assertEqual(view.status_code, 200, view.get_data(as_text=True)[:300])
        self.assertEqual(context.call_count, 1)

    # ---- Step 1 POST ------------------------------------------------------

    @patch("app.services.reviewer_coding_service.generate_process_proof", return_value="fresh-token")
    @patch("app.services.reviewer_coding_service.process_certificate")
    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    @patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_step1_post_changed_certificate_reprocesses_and_saves_nothing(
        self, verify, _validate, process, _generate
    ):
        sid = self._start_review()
        verify.side_effect = ProcessProofCertificateChanged("changed")
        process.return_value = {
            "certificate_digest": "new-cert",
            "result_digest": "new-result",
            "doris": _DORIS,
            "codedit": _CODEDIT,
        }

        response = self._post_initial(sid)

        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "DORIS_CERTIFICATE_CHANGED")
        self.assertEqual(response.get_json()["processing"]["process_token"], "fresh-token")
        self.assertEqual(verify.call_args.kwargs["role"], "reviewer")
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerInitialAssessments).where(
                    VaReviewerInitialAssessments.va_sid == sid
                )
            )
        )

    @patch("app.services.reviewer_final_assessment_service.build_icd11_provenance_for_values")
    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    @patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_step1_post_stores_envelopes_and_derives_text_columns(self, verify, validate, provenance):
        sid = self._start_review(payload_data={"Id10019": "male", "Id10077": "no"})
        before = self._coder_rows(sid)
        verify.return_value = {
            "certificate": {**_CERTIFICATE, "AdministrativeData": {"Sex": 1}},
            "doris": _DORIS,
            "codedit": _CODEDIT,
        }
        provenance.return_value = {"antecedent": {"code": "1C62.Z"}}

        response = self._post_initial(sid)

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = db.session.scalar(
            db.select(VaReviewerInitialAssessments).where(VaReviewerInitialAssessments.va_sid == sid)
        )
        self.assertEqual(row.va_immediate_cod, _TB)
        self.assertEqual(row.va_antecedent_cod, _HIV)
        self.assertIsNone(row.va_other_conditions)
        self.assertEqual(row.doris_certificate, {**_CERTIFICATE, "AdministrativeData": {"Sex": 1}})
        self.assertEqual(row.doris_result, _DORIS)
        self.assertEqual(row.codedit_result, _CODEDIT)
        self.assertEqual(row.cod_entry_mode_snapshot["cod_entry_mode"], "doris")
        self.assertTrue(row.cod_entry_mode_snapshot["masked_cod_required"])
        # The interview prefill, recomputed server-side: Sex kept, manner
        # of death (Id10077 = no -> disease) dropped by the reviewer.
        self.assertEqual(
            row.cod_entry_mode_snapshot["doris_prefill"],
            {
                "version": 1,
                "fields": {
                    "AdministrativeData.Sex": {"sources": ["Id10019"], "changed": False},
                    "MannerOfDeath.MannerOfDeath": {"sources": ["Id10077"], "changed": True},
                },
            },
        )
        self.assertEqual(row.icd11_provenance, {"antecedent": {"code": "1C62.Z"}})
        provenance.assert_called_once_with(sid, {"antecedent": _HIV})
        validate.assert_called_once_with(sid, _HIV)
        allocation_id = db.session.scalar(
            db.select(VaAllocations.va_allocation_id).where(
                VaAllocations.va_sid == sid,
                VaAllocations.va_allocated_to == self.reviewer.user_id,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
        self.assertEqual(verify.call_args.kwargs["role"], "reviewer")
        self.assertEqual(verify.call_args.kwargs["allocation_id"], allocation_id)
        self.assertEqual(verify.call_args.kwargs["user_id"], self.reviewer.user_id)
        # The coder's records never change.
        self.assertEqual(self._coder_rows(sid), before)

    @patch("app.services.reviewer_coding_service.validate_coding_value_for_submission")
    @patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_step1_post_without_part1_line1_is_400(self, verify, _validate):
        sid = self._start_review()
        verify.return_value = {"certificate": _certificate([]), "doris": _DORIS, "codedit": _CODEDIT}

        response = self._post_initial(sid)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Part I line 1", response.get_json()["error"])
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerInitialAssessments).where(VaReviewerInitialAssessments.va_sid == sid)
            )
        )

    @patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_step1_post_without_underlying_cause_is_400(self, verify):
        sid = self._start_review()

        response = self._post_initial(sid, antecedent_cod=None)

        self.assertEqual(response.status_code, 400)
        verify.assert_not_called()
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerInitialAssessments).where(VaReviewerInitialAssessments.va_sid == sid)
            )
        )

    def test_step1_post_non_object_body_is_400(self):
        sid = self._start_review()
        self._login(self.reviewer_id)

        response = self.client.post(
            _INITIAL_URL.format(sid=sid), json=["not", "an", "object"], headers=self._csrf_headers()
        )

        self.assertEqual(response.status_code, 400)

    @patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_step1_post_refused_without_reviewer_allocation(self, verify):
        sid = self._start_review(allocate=False)

        response = self._post_initial(sid)

        self.assertEqual(response.status_code, 403)
        verify.assert_not_called()

    def test_coder_cannot_use_reviewer_step1_endpoint(self):
        sid = self._start_review()
        self._login(self.base_coder_id)

        response = self.client.post(
            _INITIAL_URL.format(sid=sid), json={"antecedent_cod": _HIV}, headers=self._csrf_headers()
        )

        self.assertEqual(response.status_code, 403)

    # ---- DORIS gate ------------------------------------------------------

    def _process(self, sid, role):
        return self.client.post(
            _PROCESS_URL.format(sid=sid),
            json={"schema_version": 1, "client_revision": 0, "role": role, "certificate": _CERTIFICATE},
            headers=self._csrf_headers(),
        )

    @patch("app.routes.api.doris_clinical.process_certificate")
    def test_doris_gate_for_masked_reviewer(self, process):
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
        allocated = self._start_review()
        self._login(self.reviewer_id)
        opened = self._process(allocated, "reviewer")
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))
        self.assertTrue(opened.get_json()["process_token"])

        # Without the reviewer's own active allocation: refused.
        unallocated = self._start_review(allocate=False)
        refused = self._process(unallocated, "reviewer")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.get_json()["error"]["code"], "ACTIVE_ALLOCATION_REQUIRED")

        # Masked ICD-10 (not DORIS) stays closed.
        self._mode(masked=True, doris=False)
        closed = self._process(allocated, "reviewer")
        self.assertEqual(closed.status_code, 409)
        self.assertEqual(closed.get_json()["error"]["code"], "DORIS_NOT_ENABLED")

    # ---- Step 2 ----------------------------------------------------------

    def _finalize(self, sid, conclusive, **kwargs):
        with (
            patch("app.services.reviewer_coding_service.validate_coding_value_for_submission"),
            patch("app.services.reviewer_coding_service.build_icd11_provenance_for_values", return_value=None),
            patch("app.services.reviewer_final_assessment_service.build_icd11_provenance_for_values", return_value=None),
        ):
            return submit_reviewer_final_cod(self.reviewer, sid, conclusive_cod=conclusive, **kwargs)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1C62.Z")
    def test_step2_provenance_doris_wins_tie_and_envelopes_stay_null(self, _mapping):
        sid = self._start_review(smartva_icd="B24")
        step1 = self._reviewer_step1(sid)

        final = self._finalize(sid, _HIV)

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "doris")
        self.assertEqual(final.source_reviewer_initial_assessment_id, step1.va_riniassess_id)
        sql_null = db.session.execute(
            db.text(
                "SELECT doris_certificate IS NULL AND doris_result IS NULL"
                " AND codedit_result IS NULL FROM va_reviewer_final_assessments"
                " WHERE va_rfinassess_id = :id"
            ),
            {"id": final.va_rfinassess_id},
        ).scalar_one()
        self.assertTrue(sql_null)

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00/1A01")
    def test_step2_provenance_smartva(self, _mapping):
        sid = self._start_review(smartva_icd="A00.9")
        self._reviewer_step1(sid)

        final = self._finalize(sid, "1A01 Intestinal infection")

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "smartva")

    @patch("app.services.cod_entry_mode.smartva_icd11_mapping", return_value="1A00")
    def test_step2_provenance_own(self, _mapping):
        sid = self._start_review(smartva_icd="A00.9")
        self._reviewer_step1(sid)

        final = self._finalize(sid, "BA41.Z Acute myocardial infarction")

        self.assertEqual(final.cod_entry_mode_snapshot["final_ucod_source"], "own")

    def test_step2_refuses_a_certificate(self):
        sid = self._start_review()
        self._reviewer_step1(sid)

        with self.assertRaises(ReviewerCodingError) as raised:
            self._finalize(sid, _HIV, doris_certificate=_CERTIFICATE, doris_process_token="signed")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Step 1", raised.exception.message)
        self.assertIsNone(
            db.session.scalar(
                db.select(VaReviewerFinalAssessments).where(VaReviewerFinalAssessments.va_sid == sid)
            )
        )

    def test_step2_requires_reviewer_step1(self):
        sid = self._start_review()

        with self.assertRaises(ReviewerCodingError) as raised:
            self._finalize(sid, _HIV)

        self.assertEqual(raised.exception.status_code, 400)

    # ---- Masked ICD-10 reviewer: SmartVA now in Step 2 ----------------------

    def test_masked_simple_step2_shows_smartva_and_saves_unchanged(self):
        self._mode(masked=True, doris=False)
        sid = self._start_review(smartva_icd="A16.9")
        before = self._panel(sid)
        self._reviewer_step1(sid, underlying="B20 HIV disease", certificate=None)

        body = self._panel(sid)
        final = self._finalize(sid, "B20 HIV disease")

        # Step 1 of masked ICD-10 stays the simple form, without SmartVA.
        self.assertIn('id="reviewerInitialCodForm"', before)
        self.assertNotIn("SmartVA Analysis", before)
        self.assertNotIn("data-doris-editor", before)
        step2 = body[body.index('id="reviewerFinalCodForm"'):]
        self.assertIn("SmartVA Analysis", step2)
        self.assertIn(_SMARTVA_CAUSE, step2)
        self.assertIn('id="reviewer-conclusive-cod-select"', step2)
        self.assertNotIn("data-doris-final-host", step2)
        self.assertEqual(final.cod_entry_mode_snapshot["cod_entry_mode"], "simple")
        self.assertNotIn("final_ucod_source", final.cod_entry_mode_snapshot)
        self.assertIsNone(final.doris_certificate)
