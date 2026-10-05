"""Coder COD writes as a service (digitva-xl43 phase 1): Step 1, the final
COD and Not Codeable, shared by the web partials and /api/v1/coding.
"""
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MasIcd1020192,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.authz import invalidate
from app.services.coder_cod_service import (
    ADULT_OTHER_CONDITIONS,
    CHILD_OTHER_CONDITIONS,
    NEONATE_OTHER_CONDITIONS,
    CoderCodingError,
    other_conditions_choices,
    submit_coder_final_cod,
    submit_coder_initial_cod,
    submit_coder_not_codeable,
)
from app.services.doris_process_proof import ProcessProofCertificateChanged
from app.services.final_cod_authority_service import (
    get_active_recode_episode,
    get_authoritative_final_assessment,
    start_recode_episode,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
)
from tests.base import BaseTestCase

_COD = "I24-Other acute ischaemic heart diseases"
_CERT = {"ICDVersion": "ICD11", "Part1": [{"Conditions": [{"Text": "TB", "Code": "1B10.Z"}]}]}
_DORIS = {"status": "completed", "result": {"code": "1B10.Z"}}
_CODEDIT = {"status": "completed", "result": {"issueIds": ""}}
_ODK_OK = SimpleNamespace(success=True, review_state="hasIssues", error_message=None)


class TestCoderCodService(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}X1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID, odk_form_id="XL43_FORM", odk_project_id="43",
                form_type="WHO_2022_VA", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.merge(MasIcd1020192(
            code="I24", title="Other acute ischaemic heart diseases",
            node_type="category", semantic_level="three_character", sort_order=1,
            parent_code=None, chapter_code="IX",
            chapter_title="Diseases of the circulatory system",
            block_code="I20-I25", block_title="Ischaemic heart diseases",
            three_character_code="I24",
            three_character_title="Other acute ischaemic heart diseases",
            has_children=False, is_leaf=True, is_three_character_code=True,
            is_detailed_code=False, is_coding_selectable=True, sex_selectable="both",
            age_group_selectable="all", policy_status="unreviewed",
            source_version="ICD-10-2019", source_path="test", is_active=True,
            created_at=now, updated_at=now,
        ))
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == cls.BASE_PROJECT_ID,
            VaProjectSites.site_id == cls.BASE_SITE_ID,
        ))
        cls.coder = cls.base_coder_user
        cls.tester = cls._make_user(f"xl43.tester.{uuid.uuid4().hex[:6]}@test.local", "Tester123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.tester.user_id, role=VaAccessRoles.coding_tester,
            scope_type=VaAccessScopeTypes.project_site, project_site_id=project_site_id,
            notes="xl43", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self._mode()
        for user in (self.coder, self.tester):
            invalidate(user.user_id)

    def _mode(self, masked=False, doris=False, nqa=False):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        project.icd_classification = "icd11" if doris else "icd10"
        project.cod_entry_mode = "doris" if doris else "simple"
        project.narrative_qa_enabled = nqa
        project.social_autopsy_enabled = False
        db.session.commit()

    def _case(self, user=None, state=WORKFLOW_CODING_IN_PROGRESS, allocated=True, payload=None):
        sid = f"uuid:xl43-{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="Collector",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English",
            va_deceased_age=60, va_deceased_gender="Male",
            va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state,
            workflow_reason="test_seed", workflow_updated_by_role="vasystem",
        ))
        ensure_active_payload_version(
            submission, payload_data=payload or {}, source_updated_at=now,
            created_by_role="vasystem",
        )
        if allocated:
            db.session.add(VaAllocations(
                va_allocation_id=uuid.uuid4(), va_sid=sid,
                va_allocated_to=(user or self.coder).user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            ))
        db.session.commit()
        return sid

    def _state(self, sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == sid))

    def _final(self, sid, **kwargs):
        return submit_coder_final_cod(
            self.coder, sid, conclusive_cod=_COD, immediate_cod=_COD, actiontype="", **kwargs)

    def _refused(self, call, status, code):
        with self.assertRaises(CoderCodingError) as caught:
            call()
        self.assertEqual((caught.exception.status_code, caught.exception.code), (status, code))
        return caught.exception

    # -- other conditions by age group (digitva-sndk) ---------------------

    def test_other_conditions_list_follows_the_age_group_flag(self):
        self.assertIs(other_conditions_choices({"isNeonatal": "1"}), NEONATE_OTHER_CONDITIONS)
        self.assertIs(other_conditions_choices({"isChild": "1.0"}), CHILD_OTHER_CONDITIONS)
        self.assertIs(other_conditions_choices({"isAdult": "1"}), ADULT_OTHER_CONDITIONS)
        self.assertIs(other_conditions_choices({"isNeonatal": "0"}), ADULT_OTHER_CONDITIONS)
        self.assertIs(other_conditions_choices(None), ADULT_OTHER_CONDITIONS)

    def test_step1_accepts_neonate_conditions_only_for_a_neonate(self):
        self._mode(masked=True)
        neonate = self._case(payload={"isNeonatal": "1"})
        saved = submit_coder_initial_cod(
            self.coder, neonate, immediate_cod=_COD, antecedent_cod=_COD,
            other_conditions=[NEONATE_OTHER_CONDITIONS[0], NEONATE_OTHER_CONDITIONS[1]],
            actiontype="",
        )
        self.assertEqual(
            saved.assessment.va_other_conditions,
            f"{NEONATE_OTHER_CONDITIONS[0]} | {NEONATE_OTHER_CONDITIONS[1]}",
        )
        adult = self._case(payload={"isAdult": "1"})
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, adult, immediate_cod=_COD, antecedent_cod=_COD,
            other_conditions=[NEONATE_OTHER_CONDITIONS[0]], actiontype="",
        ), 400, "invalid_other_conditions")

    def test_step1_screen_offers_the_neonate_list_to_a_neonate(self):
        self._mode(masked=True)
        for flag, offered, absent in (
            ("isNeonatal", "P36 - Neonatal Sepsis", "I10 - Essential Hypertension"),
            ("isAdult", "I10 - Essential Hypertension", "P36 - Neonatal Sepsis"),
        ):
            sid = self._case(payload={flag: "1"})
            self._login(self.base_coder_id)
            response = self.client.get(
                f"/vaform/{sid}/vainitialasses?action=vacode&actiontype=varesumecoding")
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(offered, body)
            self.assertNotIn(absent, body)

    # -- Step 1 -----------------------------------------------------------

    def test_step1_saves_supersedes_and_moves_the_case(self):
        self._mode(masked=True)
        sid = self._case()
        first = submit_coder_initial_cod(
            self.coder, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype="")
        self.assertFalse(first.resaved)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_STEP1_SAVED)
        second = submit_coder_initial_cod(
            self.coder, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype="")
        self.assertTrue(second.resaved)
        rows = db.session.scalars(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid)).all()
        active = [r for r in rows if r.va_iniassess_status == VaStatuses.active]
        self.assertEqual([r.va_iniassess_id for r in active], [second.assessment.va_iniassess_id])
        self.assertEqual(len(rows), 2)
        self.assertFalse(second.assessment.is_tester)

    def test_step1_refusals(self):
        sid = self._case()
        # An unmasked project has no Step 1.
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype=""),
            409, "not_masked")
        self._mode(masked=True)
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, "uuid:missing", immediate_cod=_COD, antecedent_cod=_COD, actiontype=""),
            404, "not_found")
        unallocated = self._case(allocated=False)
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, unallocated, immediate_cod=_COD, antecedent_cod=_COD, actiontype=""),
            403, "no_allocation")
        # Someone else's allocation does not open the case.
        theirs = self._case(user=self.tester)
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, theirs, immediate_cod=_COD, antecedent_cod=_COD, actiontype=""),
            403, "no_allocation")
        ready = self._case(state=WORKFLOW_READY_FOR_CODING)
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, ready, immediate_cod=_COD, antecedent_cod=_COD, actiontype=""),
            409, "wrong_state")
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, sid, immediate_cod="", antecedent_cod=_COD, actiontype=""),
            400, "invalid_request")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(
            VaInitialAssessments).where(VaInitialAssessments.va_sid == sid)), 0)

    def test_step1_reports_every_invalid_cause_with_its_field(self):
        self._mode(masked=True)
        sid = self._case()
        error = self._refused(lambda: submit_coder_initial_cod(
            self.coder, sid, immediate_cod="ZZZ not a code", antecedent_cod="YYY not a code",
            actiontype=""), 400, "invalid_cod")
        self.assertEqual(error.fields, ["immediate_cod", "antecedent_cod"])
        self.assertEqual(len(error.messages), 2)

    def test_step1_refuses_mixed_classifications(self):
        self._mode(masked=True)
        sid = self._case()
        with mock.patch(
            "app.services.coder_cod_service.validate_coding_value_for_submission",
            side_effect=["icd10", "icd11"],
        ):
            error = self._refused(lambda: submit_coder_initial_cod(
                self.coder, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype=""),
                400, "invalid_cod")
        self.assertEqual(error.fields, ["antecedent_cod"])

    @mock.patch("app.services.coder_cod_service.build_icd11_provenance_for_values", return_value=None)
    @mock.patch("app.services.coder_cod_service.validate_coding_value_for_submission")
    @mock.patch("app.services.reviewer_coding_service.verify_process_submission")
    def test_masked_doris_step1_derives_the_immediate_cause(self, verify, _validate, _prov):
        self._mode(masked=True, doris=True)
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = "sha256:pinned"
        verify.return_value = {"certificate": _CERT, "doris": _DORIS, "codedit": _CODEDIT}
        sid = self._case()
        saved = submit_coder_initial_cod(
            self.coder, sid, antecedent_cod="1B10.Z TB", doris_certificate=_CERT,
            doris_result=_DORIS, codedit_result=_CODEDIT, doris_process_token="t",
            doris_result_digest="d", other_conditions=["ignored"], actiontype="")
        row = saved.assessment
        self.assertEqual((row.va_immediate_cod, row.va_antecedent_cod), ("1B10.Z TB", "1B10.Z TB"))
        self.assertIsNone(row.va_other_conditions)
        self.assertEqual(row.doris_certificate, _CERT)
        # The proof was minted for the coder role.
        self.assertEqual(verify.call_args.kwargs["role"], "coder")

    def test_masked_doris_step1_needs_a_confirmed_cause_and_the_image(self):
        self._mode(masked=True, doris=True)
        sid = self._case()
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = ""
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, sid, antecedent_cod="x", actiontype=""), 503, "who_not_configured")
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = "sha256:pinned"
        self._refused(lambda: submit_coder_initial_cod(
            self.coder, sid, antecedent_cod="", actiontype=""), 400, "invalid_request")

    @mock.patch("app.services.coder_cod_service.validate_coding_value_for_submission")
    @mock.patch("app.services.reviewer_coding_service.generate_process_proof", return_value="fresh")
    @mock.patch("app.services.reviewer_coding_service.process_certificate")
    @mock.patch(
        "app.services.reviewer_coding_service.verify_process_submission",
        side_effect=ProcessProofCertificateChanged("changed"),
    )
    def test_masked_doris_step1_changed_certificate_returns_a_fresh_proof(
        self, _verify, process, _proof, _validate
    ):
        self._mode(masked=True, doris=True)
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = "sha256:pinned"
        process.return_value = {
            "certificate_digest": "c", "result_digest": "r",
            "doris": _DORIS, "codedit": _CODEDIT,
        }
        sid = self._case()
        error = self._refused(lambda: submit_coder_initial_cod(
            self.coder, sid, antecedent_cod="1B10.Z TB", doris_certificate=_CERT,
            actiontype=""), 409, "DORIS_CERTIFICATE_CHANGED")
        self.assertEqual(error.processing["process_token"], "fresh")
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)

    def test_step1_by_a_tester_is_stored_as_tester_output(self):
        self._mode(masked=True)
        sid = self._case(user=self.tester)
        saved = submit_coder_initial_cod(
            self.tester, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype="")
        self.assertTrue(saved.assessment.is_tester)

    # -- final COD --------------------------------------------------------

    def test_final_unmasked_simple_finalizes_and_releases(self):
        sid = self._case()
        with mock.patch("app.services.coder_cod_service.bust_coder_dashboard_cache") as bust, \
                mock.patch(
                    "app.services.coder_cod_service.coding_search_telemetry_service.record_choice"
                ) as record:
            result = self._final(sid, remark=" fine ", cod_search_id="s", cod_chosen_code="I24",
                                 cod_chosen_rank=2)
        bust.assert_called_once_with(self.coder.user_id)
        self.assertEqual(record.call_args.kwargs["chosen_code"], "I24")
        final = result.assessment
        self.assertFalse(result.tester)
        self.assertEqual(
            (final.va_conclusive_cod, final.va_immediate_cod, final.va_finassess_remark),
            (_COD, _COD, "fine"))
        self.assertEqual(final.va_finassess_status, VaStatuses.active)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_FINALIZED)
        self.assertEqual(get_authoritative_final_assessment(sid).va_finassess_id, final.va_finassess_id)
        allocation = db.session.scalar(sa.select(VaAllocations).where(VaAllocations.va_sid == sid))
        self.assertEqual(allocation.va_allocation_status, VaStatuses.deactive)

    def test_final_refusals_and_blocking_messages(self):
        unallocated = self._case(allocated=False)
        self._refused(lambda: self._final(unallocated), 403, "no_allocation")
        self._refused(lambda: submit_coder_final_cod(
            self.coder, "uuid:missing", conclusive_cod=_COD, actiontype=""), 404, "not_found")
        ready = self._case(state=WORKFLOW_READY_FOR_CODING)
        self._refused(lambda: self._final(ready), 409, "wrong_state")
        self.assertEqual(self._state(ready), WORKFLOW_READY_FOR_CODING)

        sid = self._case()
        # No immediate cause, and an invalid conclusive one: both are reported.
        error = self._refused(lambda: submit_coder_final_cod(
            self.coder, sid, conclusive_cod="ZZZ not a code", actiontype=""), 422, "final_blocked")
        self.assertEqual(len(error.messages), 2)
        self.assertIn("Immediate cause of death is required.", error.messages)
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(
            VaFinalAssessments).where(VaFinalAssessments.va_sid == sid)), 0)

    def test_final_needs_the_narrative_assessment_when_the_project_requires_it(self):
        self._mode(nqa=True)
        sid = self._case()
        error = self._refused(lambda: self._final(sid), 422, "final_blocked")
        self.assertEqual(error.messages, [
            "Narrative Quality Assessment must be completed before submitting the final COD."])
        with mock.patch(
            "app.services.coder_cod_service.get_current_payload_narrative_assessment",
            return_value=object(),
        ):
            self._final(sid)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_FINALIZED)

    def test_final_needs_the_social_autopsy_analysis_when_required(self):
        sid = self._case()
        with mock.patch("app.services.coder_cod_service._social_autopsy_required", return_value=True):
            error = self._refused(lambda: self._final(sid), 422, "final_blocked")
            self.assertEqual(error.messages, [
                "Social Autopsy Analysis must be completed before submitting the final COD."])
            with mock.patch(
                "app.services.coder_cod_service.get_current_payload_social_autopsy_analysis",
                return_value=object(),
            ):
                self._final(sid)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_FINALIZED)

    def test_final_masked_links_the_step1_row(self):
        self._mode(masked=True)
        sid = self._case()
        initial = submit_coder_initial_cod(
            self.coder, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype="")
        result = submit_coder_final_cod(self.coder, sid, conclusive_cod=_COD, actiontype="")
        self.assertEqual(
            result.assessment.source_initial_assessment_id, initial.assessment.va_iniassess_id)
        self.assertIsNone(result.assessment.va_immediate_cod)

    def test_final_masked_needs_the_callers_own_step1(self):
        self._mode(masked=True)
        sid = self._case()
        self._refused(
            lambda: submit_coder_final_cod(self.coder, sid, conclusive_cod=_COD, actiontype=""),
            409, "wrong_state")
        # Another user's active Step 1 is not the caller's.
        db.session.add(VaInitialAssessments(
            va_sid=sid, va_iniassess_by=self.tester.user_id, va_immediate_cod="I24",
            va_antecedent_cod="I24", va_iniassess_status=VaStatuses.active))
        # Nor is the caller's own tester-output row.
        db.session.add(VaInitialAssessments(
            va_sid=sid, va_iniassess_by=self.coder.user_id, va_immediate_cod="I24",
            va_antecedent_cod="I24", va_iniassess_status=VaStatuses.active, is_tester=True))
        db.session.commit()
        error = self._refused(
            lambda: submit_coder_final_cod(self.coder, sid, conclusive_cod=_COD, actiontype=""),
            409, "wrong_state")
        self.assertEqual(error.message, "Save Step 1 first.")
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(db.session.scalars(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == sid)).all(), [])
        # The caller's own Step 1 links, whoever else saved one.
        own = submit_coder_initial_cod(
            self.coder, sid, immediate_cod=_COD, antecedent_cod=_COD, actiontype="")
        result = submit_coder_final_cod(self.coder, sid, conclusive_cod=_COD, actiontype="")
        self.assertEqual(
            result.assessment.source_initial_assessment_id, own.assessment.va_iniassess_id)

    def test_masked_doris_step2_refuses_a_certificate(self):
        self._mode(masked=True, doris=True)
        sid = self._case(state=WORKFLOW_CODER_STEP1_SAVED)
        self._refused(lambda: submit_coder_final_cod(
            self.coder, sid, conclusive_cod=_COD, doris_certificate=_CERT, actiontype=""),
            400, "invalid_request")

    def test_recode_replaces_the_authoritative_final_and_completes_the_episode(self):
        sid = self._case()
        first = self._final(sid).assessment
        episode = start_recode_episode(sid, self.coder.user_id, base_final_assessment=first)
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=self.coder.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid == sid).values(workflow_state=WORKFLOW_CODING_IN_PROGRESS))
        db.session.commit()
        self.assertIsNotNone(get_active_recode_episode(sid))

        # No actiontype: derived (RECODE in a recode episode).
        replacement = submit_coder_final_cod(
            self.coder, sid, conclusive_cod=_COD, immediate_cod=_COD).assessment

        db.session.refresh(first)
        db.session.refresh(episode)
        self.assertEqual(first.va_finassess_status, VaStatuses.deactive)
        self.assertEqual(
            get_authoritative_final_assessment(sid).va_finassess_id, replacement.va_finassess_id)
        self.assertEqual(episode.replacement_final_assessment_id, replacement.va_finassess_id)
        self.assertIsNone(get_active_recode_episode(sid))
        self.assertEqual(self._state(sid), WORKFLOW_CODER_FINALIZED)

    def test_final_by_a_tester_is_not_a_result_and_returns_the_case(self):
        sid = self._case(user=self.tester)
        result = submit_coder_final_cod(
            self.tester, sid, conclusive_cod=_COD, immediate_cod=_COD, actiontype="")
        self.assertTrue(result.tester)
        self.assertTrue(result.assessment.is_tester)
        self.assertEqual(result.assessment.va_finassess_status, VaStatuses.deactive)
        self.assertEqual(self._state(sid), WORKFLOW_READY_FOR_CODING)
        self.assertIsNone(get_authoritative_final_assessment(sid))

    def test_final_in_a_demo_session_stamps_an_expiry(self):
        sid = self._case()
        result = submit_coder_final_cod(
            self.coder, sid, conclusive_cod=_COD, immediate_cod=_COD,
            actiontype="vademo_start_coding")
        self.assertIsNotNone(result.assessment.demo_expires_at)

    # -- Not Codeable -----------------------------------------------------

    def test_not_codeable_excludes_the_case_and_flags_odk(self):
        sid = self._case(state=WORKFLOW_CODER_STEP1_SAVED)
        with mock.patch(
            "app.services.coder_cod_service.sync_not_codeable_review_state", return_value=_ODK_OK
        ) as odk:
            result = submit_coder_not_codeable(
                self.coder, sid, reason="others", other=" unreadable ", actiontype="")
        odk.assert_called_once_with(sid, "others", "unreadable")
        self.assertEqual((result.tester, result.odk_synced, result.odk_error), (False, True, None))
        review = db.session.scalar(sa.select(VaCoderReview).where(VaCoderReview.va_sid == sid))
        self.assertEqual((review.va_creview_reason, review.va_creview_other), ("others", "unreadable"))
        self.assertEqual(review.va_creview_status, VaStatuses.active)
        self.assertEqual(self._state(sid), WORKFLOW_NOT_CODEABLE_BY_CODER)
        allocation = db.session.scalar(sa.select(VaAllocations).where(VaAllocations.va_sid == sid))
        self.assertEqual(allocation.va_allocation_status, VaStatuses.deactive)

    def test_not_codeable_reports_an_odk_failure_without_failing(self):
        sid = self._case()
        failed = SimpleNamespace(success=False, review_state=None, error_message="ODK down")
        with mock.patch(
            "app.services.coder_cod_service.sync_not_codeable_review_state", return_value=failed
        ):
            result = submit_coder_not_codeable(self.coder, sid, reason="no_info", actiontype="")
        self.assertEqual((result.odk_synced, result.odk_error), (False, "ODK down"))
        self.assertEqual(self._state(sid), WORKFLOW_NOT_CODEABLE_BY_CODER)

    def test_not_codeable_refusals(self):
        sid = self._case()
        self._refused(lambda: submit_coder_not_codeable(
            self.coder, sid, reason="bored", actiontype=""), 400, "invalid_request")
        self._refused(lambda: submit_coder_not_codeable(
            self.coder, sid, reason="others", other="  ", actiontype=""), 400, "invalid_request")
        self._refused(lambda: submit_coder_not_codeable(
            self.coder, self._case(allocated=False), reason="no_info", actiontype=""),
            403, "no_allocation")
        self._refused(lambda: submit_coder_not_codeable(
            self.coder, self._case(state=WORKFLOW_READY_FOR_CODING), reason="no_info",
            actiontype=""), 409, "wrong_state")
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)

    def test_not_codeable_by_a_tester_is_not_counted_and_skips_odk(self):
        sid = self._case(user=self.tester)
        with mock.patch("app.services.coder_cod_service.sync_not_codeable_review_state") as odk:
            result = submit_coder_not_codeable(self.tester, sid, reason="no_info", actiontype="")
        odk.assert_not_called()
        self.assertTrue(result.tester)
        review = db.session.scalar(sa.select(VaCoderReview).where(VaCoderReview.va_sid == sid))
        self.assertTrue(review.is_tester)
        self.assertEqual(review.va_creview_status, VaStatuses.deactive)
        self.assertEqual(self._state(sid), WORKFLOW_READY_FOR_CODING)
