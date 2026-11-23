"""The coder's and the reviewer's final COD saves, mistake by mistake
(digitva-r8nh.2).

Each test makes the same final-COD mistake on ``POST /api/v1/coding/finalize``
and ``POST /api/v1/reviewing/finalize`` and pins the reply of each: status,
code and body keys. Owner decision 2026-11-23: the same mistake gets the same
reply (the coder's). Policy: docs/policy/final-cod-authority.md ("Refusals").
"""
import io
import uuid
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MasIcd1020192,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.authz import invalidate
from app.services.icd_coding_policy import AgeRestrictionConfirmationRequired
from app.services.icd_coding_value import NonLeafCategory
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
)
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase

_COD = "I24-Other acute ischaemic heart diseases"
_BAD = "ZZZ not a code"
_SERVICE = {"coder": "app.services.coder_cod_service", "reviewer": "app.services.reviewer_coding_service"}
_SA_GATE = {
    "coder": "app.services.coder_cod_service._social_autopsy_required",
    "reviewer": "app.services.reviewer_coding_service._reviewer_social_autopsy_required",
}
_ROUTE = {"coder": "/api/v1/coding/finalize", "reviewer": "/api/v1/reviewing/finalize"}
_IMMEDIATE_REQUIRED = "Immediate cause of death is required."


class FinalCodParityTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}P2"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID, odk_form_id="R8NH2_FORM", odk_project_id="45",
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
        cls.reviewer = cls._make_user(f"r8nh2.rev.{uuid.uuid4().hex[:6]}@test.local", "Reviewer123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.reviewer.user_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.BASE_PROJECT_ID,
            notes="r8nh2", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self._mode()
        invalidate(self.base_coder_user.user_id)
        invalidate(self.reviewer.user_id)

    # -- fixtures ------------------------------------------------------------

    def _mode(self, masked=False, doris=False):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        project.icd_classification = "icd11" if doris else "icd10"
        project.cod_entry_mode = "doris" if doris else "simple"
        project.narrative_qa_enabled = False
        project.social_autopsy_enabled = False
        project.reviewer_social_autopsy_enabled = False
        db.session.commit()

    def _case(self, role):
        """A case in the role's own session, allocated to the role's user."""
        sid = f"uuid:r8nh2-{uuid.uuid4().hex[:10]}"
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
        ensure_active_payload_version(
            submission, payload_data={}, source_updated_at=now, created_by_role="vasystem")
        coder = role == "coder"
        user_id = (self.base_coder_user if coder else self.reviewer).user_id
        purpose = VaAllocation.coding if coder else VaAllocation.reviewing
        # One active allocation per user: release the previous case's.
        db.session.execute(sa.update(VaAllocations).where(
            VaAllocations.va_allocated_to == user_id,
            VaAllocations.va_allocation_for == purpose,
            VaAllocations.va_allocation_status == VaStatuses.active,
        ).values(va_allocation_status=VaStatuses.deactive))
        set_submission_workflow_state(
            sid, WORKFLOW_CODING_IN_PROGRESS if coder else WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
            reason="test_setup", by_role="vasystem")
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=user_id,
            va_allocation_for=purpose, va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()
        return sid

    def _reviewer_step1(self, sid):
        submission = db.session.get(VaSubmissions, sid)
        db.session.add(VaReviewerInitialAssessments(
            va_sid=sid, payload_version_id=submission.active_payload_version_id,
            va_riniassess_by=self.reviewer.user_id, va_immediate_cod="R99",
            va_antecedent_cod="R99", va_riniassess_status=VaStatuses.active,
        ))
        db.session.commit()

    def _post(self, role, sid, body=None, **kwargs):
        user = self.base_coder_user if role == "coder" else self.reviewer
        self._login(str(user.user_id))
        if body is not None:
            kwargs["json"] = body
        response = self.client.post(f"{_ROUTE[role]}/{sid}", headers=self._csrf_headers(), **kwargs)
        return response.status_code, response.get_json()

    def _reply(self, role, body, patches=(), case=None):
        """(status, body) of one finalize on a fresh case of *role*."""
        sid = case(role) if case else self._case(role)
        managers = [mock.patch(target, **spec) for target, spec in patches]
        for manager in managers:
            manager.start()
        try:
            return self._post(role, sid, body)
        finally:
            for manager in managers:
                manager.stop()

    def _saved(self, role, sid):
        db.session.expire_all()
        model = VaFinalAssessments if role == "coder" else VaReviewerFinalAssessments
        return db.session.scalar(sa.select(model).where(model.va_sid == sid))

    # -- service mistakes ----------------------------------------------------

    def test_an_invalid_conclusive_cod(self):
        body = {"conclusive_cod": _BAD, "immediate_cod": _COD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body)
                self.assertEqual((status, reply["code"]), (422, "final_blocked"), reply)
                self.assertEqual(len(reply["messages"]), 1)
                self.assertEqual(reply["error"], reply["messages"][0])

    def test_a_missing_immediate_cod_on_an_unmasked_simple_project(self):
        body = {"conclusive_cod": _COD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body)
                self.assertEqual((status, reply["code"], reply["messages"]),
                                 (422, "final_blocked", [_IMMEDIATE_REQUIRED]), reply)

    def test_an_invalid_immediate_cod(self):
        body = {"conclusive_cod": _COD, "immediate_cod": _BAD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body)
                self.assertEqual((status, reply["code"], len(reply["messages"])),
                                 (422, "final_blocked", 1), reply)

    def test_invalid_conclusive_and_immediate_cods_together(self):
        body = {"conclusive_cod": _BAD, "immediate_cod": _BAD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body)
                self.assertEqual((status, reply["code"], len(reply["messages"])),
                                 (422, "final_blocked", 2), reply)

    def test_social_autopsy_not_done(self):
        body = {"conclusive_cod": _COD, "immediate_cod": _COD}
        status, reply = self._reply("coder", body, [(_SA_GATE["coder"], {"return_value": True})])
        self.assertEqual((status, reply["code"]), (422, "final_blocked"), reply)
        self.assertEqual(reply["messages"], [
            "Social Autopsy Analysis must be completed before submitting the final COD."])
        status, reply = self._reply("reviewer", body, [(_SA_GATE["reviewer"], {"return_value": True})])
        self.assertEqual((status, reply["code"]), (422, "final_blocked"), reply)
        self.assertEqual(reply["messages"], [
            "Social Autopsy Analysis must be completed before submitting the reviewer final COD."])

    def test_an_unconfirmed_age_restriction(self):
        restriction = AgeRestrictionConfirmationRequired("KB2C", "neonate_infant", "Perinatal")
        body = {"conclusive_cod": _COD, "immediate_cod": _COD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body, [(
                    f"{_SERVICE[role]}.validate_coding_value_for_submission", {"side_effect": restriction})])
                self.assertEqual(reply, {
                    "error": "KB2C is not selectable for this submission.",
                    "code": "AGE_RESTRICTION_CONFIRMATION_REQUIRED",
                    "age_restriction": {
                        "code": "KB2C", "age_group_selectable": "neonate_infant",
                        "restriction_note": "Perinatal"},
                })
                self.assertEqual(status, 422)

    def test_causing_condition_unknown_on_a_value_that_is_not_one_icd11_stem(self):
        body = {"conclusive_cod": _COD, "immediate_cod": _COD, "causing_condition_unknown": True}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body)
                self.assertEqual((status, reply["code"], set(reply)),
                                 (422, "INVALID_CAUSING_CONDITION_FLAG", {"error", "code"}), reply)

    def test_a_non_leaf_icd11_category(self):
        refused = NonLeafCategory("NC72 is a category, not a final code.")
        body = {"conclusive_cod": _COD, "immediate_cod": _COD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body, [(
                    f"{_SERVICE[role]}.validate_coding_value_for_submission", {"side_effect": refused})])
                self.assertEqual((status, reply["code"], set(reply)),
                                 (422, "non_leaf_category", {"error", "code"}), reply)

    def test_a_conclusive_provenance_failure(self):
        def provenance(_sid, values):
            if "conclusive" in values:
                raise ValueError("WHO could not resolve the code.")
            return None

        body = {"conclusive_cod": _COD, "immediate_cod": _COD}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply = self._reply(role, body, [(
                    f"{_SERVICE[role]}.build_icd11_provenance_for_values", {"side_effect": provenance})])
                self.assertEqual((status, reply["code"], reply["messages"]),
                                 (422, "final_blocked", ["WHO could not resolve the code."]), reply)

    def test_a_doris_certificate_sent_to_masked_doris_step2(self):
        self._mode(masked=True, doris=True)
        body = {"conclusive_cod": _COD, "doris_certificate": {"Part1": []}}
        status, reply = self._reply("coder", body)
        self.assertEqual((status, reply["code"]), (400, "invalid_request"), reply)

        def reviewer_case(role):
            sid = self._case(role)
            self._reviewer_step1(sid)
            return sid

        status, reply = self._reply("reviewer", body, [(
            f"{_SERVICE['reviewer']}.validate_coding_value_for_submission", {})], case=reviewer_case)
        self.assertEqual((status, reply["code"]), (400, "invalid_request"), reply)
        self.assertEqual(
            reply["error"],
            "Step 2 confirms the underlying cause only; the DORIS certificate belongs to Step 1.")

    def test_a_masked_final_without_step1(self):
        """Not part of the change: the two roles keep their own state replies."""
        self._mode(masked=True)
        status, reply = self._reply("coder", {"conclusive_cod": _COD})
        self.assertEqual((status, reply["code"], reply["error"]), (409, "wrong_state", "Save Step 1 first."))
        status, reply = self._reply("reviewer", {"conclusive_cod": _COD})
        self.assertEqual((status, reply["code"]), (400, "wrong_state"), reply)

    # -- request checks ------------------------------------------------------

    def _route_only(self, role, body=None, **kwargs):
        """(status, body, service called) with the role's service replaced."""
        target = ("app.routes.api.coding.submit_coder_final_cod" if role == "coder"
                  else "app.routes.api.reviewing.submit_reviewer_final_cod")
        sid = self._case(role)
        with mock.patch(target) as service:
            service.return_value.assessment.va_finassess_id = uuid.uuid4()
            service.return_value.va_rfinassess_id = uuid.uuid4()
            status, reply = self._post(role, sid, body, **kwargs)
        return status, reply, service.called

    def test_free_text_over_4000_characters(self):
        long_text = "x" * 4001
        for body in (
            {"conclusive_cod": _COD, "immediate_cod": _COD, "remark": long_text},
            {"conclusive_cod": _COD, "immediate_cod": _COD, "other_conditions": long_text},
        ):
            for role in ("coder", "reviewer"):
                with self.subTest(field=list(body)[-1], role=role):
                    status, reply, called = self._route_only(role, body)
                    self.assertEqual((status, reply["code"], called), (422, "invalid_request", False), reply)

    def test_doris_envelopes_that_are_not_objects(self):
        for name, value in (
            ("doris_certificate", "text"), ("doris_result", [1]), ("codedit_result", 5),
            ("doris_process_token", 5), ("doris_result_digest", ["d"]),
        ):
            body = {"conclusive_cod": _COD, "immediate_cod": _COD, name: value}
            for role in ("coder", "reviewer"):
                with self.subTest(name=name, role=role):
                    status, reply, called = self._route_only(role, body)
                    self.assertEqual((status, reply["code"], called), (400, "invalid_request", False), reply)

    def test_search_telemetry_fields_of_the_wrong_type(self):
        for name, value in (
            ("cod_chosen_rank", "1"), ("cod_chosen_rank", True), ("cod_chosen_rank", 1.5),
            ("cod_chosen_code", 5), ("cod_search_id", ["a"]),
        ):
            body = {"conclusive_cod": _COD, "immediate_cod": _COD, name: value}
            for role in ("coder", "reviewer"):
                with self.subTest(name=name, value=value, role=role):
                    status, reply, called = self._route_only(role, body)
                    self.assertEqual((status, reply["code"], called), (400, "invalid_request", False), reply)

    def test_a_body_over_the_cap_on_a_simple_project(self):
        big = {"conclusive_cod": _COD, "immediate_cod": _COD, "pad": "x" * 1_300_000}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                status, reply, called = self._route_only(role, big)
                self.assertEqual((status, reply["code"], called), (413, "payload_too_large", False), reply)

    def test_a_body_without_a_content_length_on_a_simple_project(self):
        chunked = dict(
            input_stream=io.BytesIO(b'{"conclusive_cod": "I24", "immediate_cod": "I24"}'),
            content_type="application/json",
            environ_overrides={"CONTENT_LENGTH": "", "HTTP_TRANSFER_ENCODING": "chunked"},
        )
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                chunked["input_stream"].seek(0)
                status, reply, called = self._route_only(role, **chunked)
                self.assertEqual((status, reply["code"], called), (413, "payload_too_large", False), reply)

    def test_a_well_formed_final_saves_for_both_roles(self):
        """Presence first: the valid body both roles share is accepted."""
        body = {"conclusive_cod": _COD, "immediate_cod": _COD, "remark": "x" * 4000,
                "cod_chosen_rank": 0, "cod_chosen_code": "I24", "cod_search_id": "none"}
        for role in ("coder", "reviewer"):
            with self.subTest(role=role):
                sid = self._case(role)
                status, reply = self._post(role, sid, body)
                self.assertEqual(status, 200, reply)
                self.assertIsNotNone(self._saved(role, sid))
