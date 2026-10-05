"""GET /api/v1/va/<sid>/workspace and /categories/<code> (digitva-xl43 phase 2).

The coding and review workspace content over JSON, with the browser cookie or
a device bearer token alike. The reads are ``case_content_service`` (shared
with the web partials); this covers the gate, the step state, the category
bodies and the section cache key. Device enrolment helpers are reused from
tests/routes/test_device_api.py.
"""
import io
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa

from app import cache as flask_cache
from app import db, limiter
from app.models import (
    MasCategoryDisplayConfig,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasSubcategoryOrder,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaReviewerFinalAssessments,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsernotes,
)
from app.services import case_content_service as case_content
from app.services.authz import invalidate
from app.services.category_rendering_service import get_category_rendering_service
from app.services.final_cod_authority_service import start_recode_episode
from app.services.submission_payload_version_service import (
    ensure_active_payload_version,
    get_active_payload_version,
)
from app.services.user_note_service import get_active_note, save_note
from app.services.workflow.definition import (
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
)
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

_DEV = device_tests.DeviceApiTests.__dict__
_CODER_EMAIL = "base.coder@test.local"
_CODER_PASSWORD = "BaseCoder123"
_COD = "I24-Other acute ischaemic heart diseases"
BASE = "/api/v1/va"


class VaCaseApiTests(BaseTestCase):
    FORM_TYPE_CODE = "XL43P2_VA"
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}P2"
    # The coder signs a device in through an interviewer grant of their own;
    # that project is also the out-of-scope case for coding.
    DEVICE_PROJECT_ID = "XL43D"
    DEVICE_SITE_ID = "XD43"
    DEVICE_FORM_ID = f"{DEVICE_PROJECT_ID}{DEVICE_SITE_ID}01"[:12]
    PROJECT_ID = DEVICE_PROJECT_ID
    SITE_ID = DEVICE_SITE_ID

    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]
    _code = _DEV["_code"]
    _enrol = _DEV["_enrol"]
    _sign_in = _DEV["_sign_in"]
    _session = _DEV["_session"]
    _bearer = _DEV["_bearer"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        form_type = db.session.scalar(
            sa.select(MasFormTypes).where(MasFormTypes.form_type_code == cls.FORM_TYPE_CODE)
        )
        if form_type is None:
            form_type = MasFormTypes(
                form_type_code=cls.FORM_TYPE_CODE, form_type_name="Workspace API Form", is_active=True
            )
            db.session.add(form_type)
            db.session.flush()
        cls.form_type_id = form_type.form_type_id
        # cat1 shows to both roles, its fields in a non-alphabetical order;
        # catc to coders only; the narrative category holds the NQA gate.
        for code, label, order, coder, reviewer, mode in (
            ("cat1", "Category One", 1, True, True, "table_sections"),
            ("catc", "Coder Only", 2, True, False, "table_sections"),
            ("vanarrationanddocuments", "Narrative", 3, True, True, "attachments"),
            ("social_autopsy", "Social Autopsy", 4, True, True, "table_sections"),
        ):
            if db.session.scalar(sa.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == cls.form_type_id,
                MasCategoryDisplayConfig.category_code == code,
            )) is None:
                db.session.add(MasCategoryDisplayConfig(
                    form_type_id=cls.form_type_id, category_code=code, display_label=label,
                    nav_label=label, display_order=order, render_mode=mode,
                    show_to_coder=coder, show_to_reviewer=reviewer,
                    show_to_site_pi_datamanager=True, always_include=True,
                    is_default_start=code == "cat1", is_active=True,
                ))
        for category, sub in (("cat1", "sub1"), ("catc", "subc")):
            if db.session.scalar(sa.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == cls.form_type_id,
                MasSubcategoryOrder.category_code == category,
                MasSubcategoryOrder.subcategory_code == sub,
            )) is None:
                db.session.add(MasSubcategoryOrder(
                    form_type_id=cls.form_type_id, category_code=category, subcategory_code=sub,
                    subcategory_name=f"Sub {sub}", display_order=1, is_active=True,
                ))
        for field_id, category, sub, label, is_pii, order in (
            ("FldZ", "cat1", "sub1", "Zulu", False, 1),
            ("FldA", "cat1", "sub1", "Alpha", False, 2),
            ("FldM", "cat1", "sub1", "Mike", False, 3),
            ("FldPii", "cat1", "sub1", "Real Name", True, 4),
            ("FldC", "catc", "subc", "Coder Field", False, 1),
        ):
            if db.session.scalar(sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == cls.form_type_id,
                MasFieldDisplayConfig.field_id == field_id,
            )) is None:
                db.session.add(MasFieldDisplayConfig(
                    form_type_id=cls.form_type_id, field_id=field_id, category_code=category,
                    subcategory_code=sub, short_label=label, is_pii=is_pii, is_active=True,
                    display_order=order,
                ))
        db.session.flush()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
                odk_form_id="XL43_P2_FORM", odk_project_id="45", form_type="Workspace API Form",
                form_type_id=cls.form_type_id, form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        if db.session.get(VaProjectMaster, cls.DEVICE_PROJECT_ID) is None:
            cls._make_project(cls.DEVICE_PROJECT_ID, cls.DEVICE_SITE_ID, now)
        cls._grant(cls.base_coder_user, cls.DEVICE_PROJECT_ID)
        cls.reviewer = cls._make_user(f"xl43p2.rev.{uuid.uuid4().hex[:6]}@test.local", "Reviewer123")
        cls.reviewer_id = str(cls.reviewer.user_id)
        db.session.add(VaUserAccessGrants(
            user_id=cls.reviewer.user_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.BASE_PROJECT_ID,
            notes="xl43p2", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        flask_cache.clear()
        self.addCleanup(flask_cache.clear)
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}
        self._mode()
        invalidate(self.base_coder_user.user_id)
        invalidate(self.reviewer.user_id)

    def _mode(self, masked=False, nqa=False, social_autopsy=False):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        project.icd_classification = "icd10"
        project.cod_entry_mode = "simple"
        project.narrative_qa_enabled = nqa
        project.social_autopsy_enabled = social_autopsy
        project.reviewer_social_autopsy_enabled = social_autopsy
        db.session.commit()

    def _case(
        self,
        *,
        form_id=None,
        payload=None,
        state=WORKFLOW_CODING_IN_PROGRESS,
        allocated_to=None,
        allocation_for=VaAllocation.coding,
    ):
        sid = f"uuid:xl43p2-{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid, va_form_id=form_id or self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="Collector", va_instance_name=sid,
            va_uniqueid_real=sid, va_uniqueid_masked=f"masked-{sid}", va_consent="yes",
            va_narration_language="English", va_deceased_age=60, va_deceased_gender="Male",
            va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state, workflow_reason="test_seed",
            workflow_updated_by_role="vasystem",
        ))
        ensure_active_payload_version(
            submission,
            payload_data=payload or {"FldZ": "z-val", "FldA": "a-val", "FldM": "m-val", "FldC": "c-val"},
            source_updated_at=now, created_by_role="vasystem",
        )
        if allocated_to is not None:
            db.session.add(VaAllocations(
                va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=allocated_to,
                va_allocation_for=allocation_for, va_allocation_status=VaStatuses.active,
            ))
        db.session.commit()
        return sid

    def _coding_case(self, **kwargs):
        return self._case(allocated_to=self.base_coder_user.user_id, **kwargs)

    def _reviewing_case(self):
        return self._case(
            state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
            allocated_to=self.reviewer.user_id, allocation_for=VaAllocation.reviewing,
        )

    def _get(self, sid, tail, mode="coding", user=None, headers=None):
        if headers is None:
            self._login(user or self.base_coder_id)
        query = {} if mode is None else {"mode": mode}
        return self.client.get(f"{BASE}/{sid}/{tail}", query_string=query, headers=headers or {})

    def _workspace(self, sid, **kwargs):
        response = self._get(sid, "workspace", **kwargs)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _initial(self, sid, user=None, **fields):
        row = VaInitialAssessments(
            va_sid=sid, va_iniassess_by=user or self.base_coder_user.user_id,
            va_immediate_cod=_COD, va_antecedent_cod="B20 HIV disease",
            va_other_conditions="I10 - Essential Hypertension | E11 - Diabetes", **fields,
        )
        db.session.add(row)
        db.session.commit()
        return row

    # -- gate ------------------------------------------------------------------

    def test_mode_is_required_and_must_be_known(self):
        sid = self._coding_case()
        for mode in (None, "view", ""):
            response = self._get(sid, "workspace", mode=mode)
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (400, "invalid_request"), mode
            )
        self.assertEqual(self._get(sid, "categories/cat1", mode="view").status_code, 400)

    def test_a_coder_without_an_allocation_is_refused(self):
        sid = self._case()
        # Present: the same caller opens a case they hold.
        self.assertEqual(self._get(self._coding_case(), "workspace").status_code, 200)
        response = self._get(sid, "workspace")
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_allocation"))
        self.assertEqual(self._get(sid, "categories/cat1").status_code, 403)

    def test_an_unknown_case_is_404(self):
        response = self._get("uuid:does-not-exist", "workspace")
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "not_found"))

    def test_a_case_outside_the_coders_scope_is_refused_despite_an_allocation(self):
        sid = self._coding_case(form_id=self.DEVICE_FORM_ID)
        self.assertIsNotNone(db.session.scalar(sa.select(VaAllocations).where(
            VaAllocations.va_sid == sid, VaAllocations.va_allocation_status == VaStatuses.active)))
        response = self._get(sid, "workspace")
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))

    def test_the_mode_must_match_the_callers_role(self):
        coding = self._coding_case()
        reviewing = self._reviewing_case()
        self.assertEqual(self._get(reviewing, "workspace", mode="reviewing", user=self.reviewer_id).status_code, 200)
        self.assertEqual(self._get(coding, "workspace", mode="coding").status_code, 200)
        for sid, mode, user in (
            (coding, "reviewing", self.base_coder_id),
            (reviewing, "coding", self.reviewer_id),
        ):
            response = self._get(sid, "workspace", mode=mode, user=user)
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))

    def test_a_reviewer_without_an_allocation_is_refused(self):
        sid = self._case(state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        response = self._get(sid, "workspace", mode="reviewing", user=self.reviewer_id)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_allocation"))

    def test_a_bearer_credential_works_and_no_credential_is_401(self):
        sid = self._coding_case()
        _device, tokens = self._session(email=_CODER_EMAIL, password=_CODER_PASSWORD)
        bearer_only = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        response = bearer_only.get(
            f"{BASE}/{sid}/workspace", query_string={"mode": "coding"}, headers=self._bearer(tokens)
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["va_sid"], sid)
        anonymous = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.assertEqual(
            anonymous.get(f"{BASE}/{sid}/workspace", query_string={"mode": "coding"}).status_code, 401
        )

    # -- workspace: step state ------------------------------------------------------

    def test_an_unmasked_project_goes_straight_to_the_final(self):
        sid = self._coding_case()
        response = self._get(sid, "workspace")
        body = response.get_json()
        self.assertEqual(body["step"], "final")
        self.assertEqual(body["case"]["instance_name"], f"masked-{sid}")
        self.assertEqual(body["case"]["form_type_code"], self.FORM_TYPE_CODE)
        self.assertEqual(body["case"]["project_mode"], "unmasked_simple")
        self.assertEqual(body["case"]["workflow_state"], WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(body["blocked_by"], [])
        self.assertIsInstance(body["other_conditions_options"], list)
        self.assertTrue(body["other_conditions_options"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")

    def test_masked_step_one_then_final_after_a_saved_step_one(self):
        self._mode(masked=True)
        sid = self._coding_case()
        before = self._workspace(sid)
        self.assertEqual(before["step"], "initial")
        self.assertIsNone(before["assessments"]["initial"])
        self._initial(sid)
        after = self._workspace(sid)
        self.assertEqual(after["step"], "final")
        saved = after["assessments"]["initial"]
        self.assertEqual(saved["immediate_cod"], _COD)
        self.assertEqual(saved["antecedent_cod"], "B20 HIV disease")
        self.assertEqual(saved["other_conditions"], ["I10 - Essential Hypertension", "E11 - Diabetes"])
        self.assertEqual(after["assessments"]["initial_prefill"]["id"], saved["id"])

    def test_another_coders_step_one_is_not_shown_and_does_not_advance_the_step(self):
        self._mode(masked=True)
        sid = self._coding_case()
        other = self._make_user(f"xl43p2.other.{uuid.uuid4().hex[:6]}@test.local", "Other123")
        self._initial(sid, user=other.user_id)
        body = self._workspace(sid)
        self.assertEqual(body["step"], "initial")
        self.assertIsNone(body["assessments"]["initial"])
        self.assertIsNone(body["assessments"]["initial_prefill"])

    def test_a_not_codeable_review_without_a_step_one_is_done(self):
        self._mode(masked=True)
        sid = self._coding_case()
        db.session.add(VaCoderReview(
            va_sid=sid, va_creview_by=self.base_coder_user.user_id, va_creview_reason="no_info",
        ))
        db.session.commit()
        body = self._workspace(sid)
        self.assertEqual(body["step"], "done")
        self.assertEqual(body["assessments"]["not_codeable"]["reason"], "no_info")

    def test_the_recode_resume_prefill_falls_back_to_the_latest_prior_step_one(self):
        sid = self._coding_case()
        uid = self.base_coder_user.user_id
        prior = self._initial(sid, va_iniassess_status=VaStatuses.deactive)
        # Present: the prior draft exists but is not an active Step 1.
        self.assertEqual(prior.va_iniassess_status, VaStatuses.deactive)
        self.assertIsNone(case_content.get_step1_prefill(sid, uid, "vacode", recode_resume=True))
        start_recode_episode(sid, uid)
        db.session.commit()
        self.assertIsNone(case_content.get_step1_prefill(sid, uid, "vacode", recode_resume=False))
        found = case_content.get_step1_prefill(sid, uid, "vacode", recode_resume=True)
        self.assertEqual(found.va_iniassess_id, prior.va_iniassess_id)
        body = self._workspace(sid)
        self.assertIsNone(body["assessments"]["initial"])
        self.assertEqual(body["assessments"]["initial_prefill"]["id"], str(prior.va_iniassess_id))

    def test_narrative_qa_blocks_the_final_until_saved(self):
        self._mode(nqa=True)
        sid = self._coding_case()
        body = self._workspace(sid)
        self.assertTrue(body["case"]["narrative_qa_enabled"])
        self.assertEqual(body["blocked_by"], ["narrative_qa"])
        category = self._get(sid, "categories/vanarrationanddocuments").get_json()
        self.assertEqual(category["blocked_by"], ["narrative_qa"])
        self._mode(nqa=False)
        self.assertEqual(self._workspace(sid)["blocked_by"], [])

    def test_smartva_is_read_live_and_hidden_from_a_masked_step_one(self):
        self._mode(masked=True)
        sid = self._coding_case()
        db.session.add(VaSmartvaResults(
            va_sid=sid, va_smartva_status=VaStatuses.active, va_smartva_cause1="Stroke",
            va_smartva_cause1icd="I64", va_smartva_likelihood1="0.5", va_smartva_cause2="NaN",
            va_smartva_age="60", va_smartva_allsymptoms="fever; cough",
        ))
        db.session.commit()
        # Present: a result exists, yet blind Step 1 does not carry it.
        self.assertIsNotNone(case_content.get_active_smartva(sid))
        self.assertIsNone(self._workspace(sid)["smartva"])
        self._initial(sid)
        smartva = self._workspace(sid)["smartva"]
        self.assertEqual(smartva["causes"][0]["cause"], "Stroke")
        self.assertEqual(smartva["causes"][0]["icd10"], "I64")
        self.assertIsNone(smartva["causes"][1]["cause"])
        self.assertEqual(smartva["symptoms"], ["fever", "cough"])
        # Not cached with the section: a later row shows at once.
        db.session.execute(sa.update(VaSmartvaResults).where(VaSmartvaResults.va_sid == sid).values(
            va_smartva_cause1="Pneumonia"))
        db.session.commit()
        self.assertEqual(self._workspace(sid)["smartva"]["causes"][0]["cause"], "Pneumonia")

    def test_the_reviewer_workspace_shows_the_reviewer_steps(self):
        self._mode(masked=True)
        sid = self._reviewing_case()
        coder_initial = self._initial(sid)
        body = self._workspace(sid, mode="reviewing", user=self.reviewer_id)
        self.assertEqual(body["step"], "initial")
        self.assertIsNone(body["other_conditions_options"])
        self.assertEqual(body["assessments"]["coder_initial"]["id"], str(coder_initial.va_iniassess_id))
        self.assertIsNone(body["assessments"]["initial"])
        self._mode(masked=False)
        self.assertEqual(self._workspace(sid, mode="reviewing", user=self.reviewer_id)["step"], "final")

    def _other_coder_with_final_and_not_codeable(self, sid):
        other = self._make_user(f"xl43p2.a.{uuid.uuid4().hex[:6]}@test.local", "OtherA123")
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=other.user_id,
            payload_version_id=get_active_payload_version(sid).payload_version_id,
            va_conclusive_cod="A16 earlier coder result", va_finassess_remark="earlier remark",
            va_finassess_status=VaStatuses.active,
        ))
        db.session.add(VaCoderReview(
            va_sid=sid, va_creview_by=other.user_id, va_creview_reason="no_info",
        ))
        start_recode_episode(sid, other.user_id)
        db.session.commit()
        return other

    def test_a_masked_step_one_never_sees_another_coders_final_or_not_codeable(self):
        self._mode(masked=True)
        sid = self._coding_case()
        self._other_coder_with_final_and_not_codeable(sid)
        # Present: the earlier coder's final is the case's authoritative one.
        self.assertEqual(
            case_content.get_authoritative_final_cod_record(sid).va_conclusive_cod,
            "A16 earlier coder result",
        )
        body = self._workspace(sid)
        self.assertNotEqual(body["step"], "final")
        self.assertIsNone(body["assessments"]["final"])
        self.assertIsNone(body["assessments"]["not_codeable"])
        # Once the caller's own Step 1 is saved the Step 2 form shows the
        # prior final as its prefill; the other coder's review stays hidden.
        self._initial(sid)
        body = self._workspace(sid)
        self.assertEqual(body["step"], "final")
        self.assertEqual(body["assessments"]["final"]["conclusive_cod"], "A16 earlier coder result")
        self.assertEqual(body["assessments"]["final"]["remark"], "earlier remark")
        self.assertIsNone(body["assessments"]["not_codeable"])

    def test_an_own_not_codeable_review_is_shown_to_the_coder(self):
        self._mode(masked=True)
        sid = self._coding_case()
        db.session.add(VaCoderReview(
            va_sid=sid, va_creview_by=self.base_coder_user.user_id, va_creview_reason="no_info",
        ))
        db.session.commit()
        self.assertEqual(self._workspace(sid)["assessments"]["not_codeable"]["reason"], "no_info")

    def test_another_reviewers_final_neither_shows_nor_completes_the_step(self):
        self._mode(masked=True)
        sid = self._reviewing_case()
        other = self._make_user(f"xl43p2.rev2.{uuid.uuid4().hex[:6]}@test.local", "Reviewer2123")
        version = get_active_payload_version(sid).payload_version_id

        def final(by):
            db.session.add(VaReviewerFinalAssessments(
                va_sid=sid, va_rfinassess_by=by, payload_version_id=version,
                va_conclusive_cod=f"cod by {by}", va_rfinassess_remark="r",
                va_rfinassess_status=VaStatuses.active,
            ))
            db.session.commit()

        final(other.user_id)
        # Present: a reviewer final exists for the case.
        self.assertIsNotNone(db.session.scalar(sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == sid)))
        body = self._workspace(sid, mode="reviewing", user=self.reviewer_id)
        self.assertIsNone(body["assessments"]["reviewer_final"])
        self.assertEqual(body["step"], "initial")
        # One active reviewer final per payload: the other's is superseded.
        db.session.execute(sa.update(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == sid).values(va_rfinassess_status=VaStatuses.deactive))
        final(self.reviewer.user_id)
        body = self._workspace(sid, mode="reviewing", user=self.reviewer_id)
        self.assertEqual(body["step"], "done")
        self.assertEqual(
            body["assessments"]["reviewer_final"]["conclusive_cod"], f"cod by {self.reviewer.user_id}"
        )

    def test_social_autopsy_blocks_the_final_until_saved(self):
        self._mode(social_autopsy=True)
        sid = self._coding_case()
        body = self._workspace(sid)
        self.assertTrue(body["case"]["social_autopsy_enabled"])
        self.assertIn("social_autopsy", [c["code"] for c in body["categories"]])
        self.assertEqual(body["blocked_by"], ["social_autopsy"])
        category = self._get(sid, "categories/social_autopsy").get_json()
        self.assertEqual(category["blocked_by"], ["social_autopsy"])
        self._mode(social_autopsy=False)
        self.assertEqual(self._workspace(sid)["blocked_by"], [])

    # -- categories --------------------------------------------------------------------

    def test_categories_keep_their_configured_order(self):
        sid = self._coding_case()
        workspace = self._workspace(sid)
        self.assertEqual(
            [c["code"] for c in workspace["categories"]][:3], ["cat1", "catc", "vanarrationanddocuments"]
        )
        self.assertEqual(workspace["default_category"], "cat1")
        body = self._get(sid, "categories/cat1").get_json()
        labels = [item["label"] for sub in body["subcategories"] for item in sub["items"]]
        self.assertIn("Zulu", labels)
        self.assertEqual(labels[:3], ["Zulu", "Alpha", "Mike"])
        self.assertEqual(body["render_mode"], "table_sections")
        self.assertEqual(body["subcategories"][0]["code"], "sub1")

    def test_a_category_the_role_does_not_see_is_404(self):
        coding = self._coding_case()
        reviewing = self._reviewing_case()
        present = self._get(coding, "categories/catc")
        self.assertEqual(present.status_code, 200)
        self.assertEqual(present.get_json()["subcategories"][0]["items"][0]["value"], "c-val")
        for sid, mode, user, code in (
            (reviewing, "reviewing", self.reviewer_id, "catc"),
            (reviewing, "reviewing", self.reviewer_id, "no_such_category"),
            (coding, "coding", None, "no_such_category"),
        ):
            response = self._get(sid, f"categories/{code}", mode=mode, user=user)
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (404, "not_found"), (mode, code)
            )

    def test_every_category_reply_is_private_and_never_stored(self):
        sid = self._coding_case()
        data = self._get(sid, "categories/cat1")
        self.assertEqual(data.headers["Cache-Control"], "private, no-store, max-age=0")
        user_specific = self._get(sid, "categories/vanarrationanddocuments")
        self.assertEqual(user_specific.headers["Cache-Control"], "private, no-store, max-age=0")

    def test_the_coder_path_uses_the_unredacted_coder_cache_variant(self):
        sid = self._coding_case(payload={"FldZ": "z-val", "FldPii": "Jane Realname"})
        version = get_active_payload_version(sid).payload_version_id
        body = self._get(sid, "categories/cat1").get_json()
        values = {i["value"] for sub in body["subcategories"] for i in sub["items"]}
        self.assertEqual(values, {"z-val", "Jane Realname"})
        plain = case_content.section_data_cache_key(sid, version, "coder", "cat1")
        self.assertIsNotNone(flask_cache.get(plain))
        self.assertIsNone(flask_cache.get(f"{plain}:nopii"))
        # A redacting viewer gets the other variant and not the PII value.
        with patch("app.services.case_content_service.should_redact_pii", return_value=True):
            body = self._get(sid, "categories/cat1").get_json()
        values = {i["value"] for sub in body["subcategories"] for i in sub["items"]}
        self.assertIn("z-val", values)
        self.assertNotIn("Jane Realname", values)
        self.assertIsNotNone(flask_cache.get(f"{plain}:nopii"))

    def test_the_reviewing_mode_serves_a_category_its_role_sees(self):
        sid = self._reviewing_case()
        response = self._get(sid, "categories/cat1", mode="reviewing", user=self.reviewer_id)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        labels = [item["label"] for sub in body["subcategories"] for item in sub["items"]]
        self.assertEqual(labels[:3], ["Zulu", "Alpha", "Mike"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
        # The reviewer's bucket is its own cache entry, not the coder's.
        version = get_active_payload_version(sid).payload_version_id
        self.assertIsNotNone(flask_cache.get(
            case_content.section_data_cache_key(sid, version, "reviewer", "cat1")))
        self.assertIsNone(flask_cache.get(
            case_content.section_data_cache_key(sid, version, "coder", "cat1")))
        nav = self._workspace(sid, mode="reviewing", user=self.reviewer_id)["categories"]
        self.assertNotIn("catc", [c["code"] for c in nav])

    def test_the_workflow_panel_carries_the_evidence_subcategories(self):
        sid = self._coding_case()
        body = self._get(sid, "categories/vacodassessment").get_json()
        self.assertEqual(body["render_mode"], "workflow_panel")
        self.assertIn("summary_items", body)
        self.assertIsInstance(body["subcategories"], list)

    # -- section cache key -------------------------------------------------------------

    def test_roles_do_not_share_a_cached_section(self):
        sid = self._coding_case()
        submission = db.session.get(VaSubmissions, sid)
        version = get_active_payload_version(sid)
        category_service = get_category_rendering_service()
        visible = case_content.get_visible_category_codes(version.payload_data, submission.va_form_id)

        def section(action):
            return case_content.get_section_data(
                va_submission=submission, active_version=version,
                form_type_code=self.FORM_TYPE_CODE, va_action=action, va_partial="cat1",
                category_config=category_service.get_category_config(self.FORM_TYPE_CODE, action, "cat1"),
                visible_category_codes=visible, user=self.base_coder_user,
            )

        with self.app.test_request_context():
            coder = section("vacode")
            self.assertIn("sub1", coder["va_processedcategorydata"])
            coder_key = case_content.section_data_cache_key(sid, version.payload_version_id, "coder", "cat1")
            cached = flask_cache.get(coder_key)
            self.assertIsNotNone(cached)
            # Poison the coder entry: only the coder bucket may see it.
            cached["va_processedcategorydata"] = {"sub1": {"POISON": "x"}}
            flask_cache.set(coder_key, cached)
            self.assertIn("POISON", section("vacode")["va_processedcategorydata"]["sub1"])
            data_manager = section("vadata")
            self.assertNotIn("POISON", data_manager["va_processedcategorydata"]["sub1"])
            self.assertIn("Zulu", data_manager["va_processedcategorydata"]["sub1"])
            self.assertIsNotNone(flask_cache.get(
                case_content.section_data_cache_key(sid, version.payload_version_id, "data_manager", "cat1")
            ))

    def test_a_new_active_payload_version_is_not_served_the_old_cached_section(self):
        sid = self._coding_case(payload={"FldZ": "first-answer"})

        def zulu():
            body = self._get(sid, "categories/cat1").get_json()
            return [i["value"] for sub in body["subcategories"] for i in sub["items"]]

        self.assertEqual(zulu(), ["first-answer"])
        old_version = get_active_payload_version(sid).payload_version_id
        submission = db.session.get(VaSubmissions, sid)
        ensure_active_payload_version(
            submission, payload_data={"FldZ": "revised-answer"}, created_by_role="vasystem"
        )
        db.session.commit()
        self.assertNotEqual(get_active_payload_version(sid).payload_version_id, old_version)
        self.assertEqual(zulu(), ["revised-answer"])
        # Dropping the entries removes every variant of the current version.
        key = case_content.section_data_cache_key(
            sid, get_active_payload_version(sid).payload_version_id, "coder", "cat1"
        )
        self.assertIsNotNone(flask_cache.get(key))
        case_content.invalidate_section_data_cache(sid)
        self.assertIsNone(flask_cache.get(key))


    # -- private note ---------------------------------------------------------------

    def _note_get(self, sid, mode="coding", user=None, headers=None):
        return self._get(sid, "note", mode=mode, user=user, headers=headers)

    def _note_put(self, sid, body, mode="coding", user=None, raw=None):
        self._login(user or self.base_coder_id)
        kwargs = {"data": raw, "content_type": "application/json"} if raw is not None else {"json": body}
        return self.client.put(
            f"{BASE}/{sid}/note", query_string={"mode": mode}, headers=self._csrf_headers(), **kwargs
        )

    def test_a_note_is_saved_updated_and_read_back_privately(self):
        sid = self._coding_case()
        empty = self._note_get(sid)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.get_json(), {"va_sid": sid, "content": None, "updated_at": None})
        saved = self._note_put(sid, {"content": "first thought"})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        body = saved.get_json()
        self.assertEqual((body["va_sid"], body["content"]), (sid, "first thought"))
        self.assertIsNotNone(body["updated_at"])
        self.assertEqual(self._note_put(sid, {"content": "second thought"}).get_json()["content"], "second thought")
        read = self._note_get(sid)
        self.assertEqual(read.get_json()["content"], "second thought")
        self.assertIn("no-store", read.headers["Cache-Control"])
        self.assertIn("private", read.headers["Cache-Control"])
        rows = db.session.scalars(sa.select(VaUsernotes).where(
            VaUsernotes.note_vasubmission == sid, VaUsernotes.note_status == VaStatuses.active)).all()
        self.assertEqual([row.note_content for row in rows], ["second thought"])

    def test_the_note_is_one_row_shared_with_the_web_branch_and_both_modes(self):
        coding = self._coding_case()
        self.assertEqual(self._note_put(coding, {"content": "via api"}).status_code, 200)
        self._login(self.base_coder_id)
        self.assertEqual(get_active_note(self.base_coder_user.user_id, coding).note_content, "via api")
        # The web saves through the same service; the API reads what it wrote.
        save_note(self.base_coder_user.user_id, coding, "via web")
        self.assertEqual(self._note_get(coding).get_json()["content"], "via web")
        # A user who codes and reviews one case has one note across both modes.
        reviewing = self._reviewing_case()
        self.assertEqual(self._note_put(reviewing, {"content": "r"}, mode="reviewing", user=self.reviewer_id).status_code, 200)
        self.assertEqual(self._note_get(reviewing, mode="reviewing", user=self.reviewer_id).get_json()["content"], "r")
        # Another user's note on the same case is not read.
        self.assertIsNone(get_active_note(self.reviewer.user_id, coding))

    def test_a_note_needs_the_mode_the_role_and_the_allocation(self):
        sid = self._coding_case()
        # Present: the holder reads and writes.
        self.assertEqual(self._note_get(sid).status_code, 200)
        self.assertEqual(self._note_put(sid, {"content": "mine"}).status_code, 200)
        for call in (self._note_get, lambda s, **k: self._note_put(s, {"content": "x"}, **k)):
            response = call(sid, mode="view")
            self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))
            response = call(sid, mode="reviewing")
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))
            response = call(self._case())
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_allocation"))
            response = call(
                self._case(state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS), mode="reviewing", user=self.reviewer_id
            )
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_allocation"))
            # A reviewer's allocation grants a coder nothing, in either mode.
            response = call(self._reviewing_case(), mode="coding")
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_allocation"))
        # Nothing was written for the refused case.
        self.assertEqual(get_active_note(self.base_coder_user.user_id, sid).note_content, "mine")

    def test_a_note_needs_a_credential(self):
        sid = self._coding_case()
        _device, tokens = self._session(email=_CODER_EMAIL, password=_CODER_PASSWORD)
        bearer_only = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        put = bearer_only.put(
            f"{BASE}/{sid}/note", query_string={"mode": "coding"},
            json={"content": "bearer note"}, headers=self._bearer(tokens),
        )
        self.assertEqual(put.status_code, 200, put.get_json())
        get = bearer_only.get(f"{BASE}/{sid}/note", query_string={"mode": "coding"}, headers=self._bearer(tokens))
        self.assertEqual(get.get_json()["content"], "bearer note")
        anonymous = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.assertEqual(anonymous.get(f"{BASE}/{sid}/note", query_string={"mode": "coding"}).status_code, 401)

    def test_a_note_body_is_bounded_and_must_be_text(self):
        sid = self._coding_case()
        self.assertEqual(self._note_put(sid, {"content": "x" * 20_000}).status_code, 200)
        for body in ({"content": ""}, {"content": "  \n "}, {"content": 5}, {"content": None}, {}, ["x"]):
            response = self._note_put(sid, body)
            self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"), body)
        response = self._note_put(sid, None, raw="not json")
        self.assertEqual(response.status_code, 400)
        response = self._note_put(sid, {"content": "x" * 20_001})
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_request"))
        # The 64 KB cap answers before any lookup, even for a case not held.
        response = self._note_put(self._case(), {"content": "x" * 70_000})
        self.assertEqual((response.status_code, response.get_json()["code"]), (413, "too_large"))
        self.assertEqual(get_active_note(self.base_coder_user.user_id, sid).note_content, "x" * 20_000)


    def test_a_note_body_without_a_content_length_is_refused_unread(self):
        sid = self._coding_case()
        self._login(self.base_coder_id)
        # A chunked body carries no Content-Length: it must not be buffered.
        response = self.client.put(
            f"{BASE}/{sid}/note", query_string={"mode": "coding"}, headers=self._csrf_headers(),
            input_stream=io.BytesIO(b'{"content": "chunked"}'), content_type="application/json",
            environ_overrides={"CONTENT_LENGTH": "", "HTTP_TRANSFER_ENCODING": "chunked"},
        )
        self.assertIsNone(response.request.content_length)
        self.assertEqual((response.status_code, response.get_json()["code"]), (413, "too_large"))
        # Present: the same body with a length is saved.
        self.assertEqual(self._note_put(sid, {"content": "sized"}).status_code, 200)
        self.assertEqual(get_active_note(self.base_coder_user.user_id, sid).note_content, "sized")

    def test_a_note_with_a_nul_character_is_400_not_500(self):
        sid = self._coding_case()
        self.assertEqual(self._note_put(sid, {"content": "fine"}).status_code, 200)
        response = self._note_put(sid, {"content": "a\x00b"})
        self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))
        self.assertEqual(get_active_note(self.base_coder_user.user_id, sid).note_content, "fine")

    def test_timestamps_carry_an_explicit_utc_offset(self):
        self._mode(masked=True)
        sid = self._coding_case()
        self._initial(sid)
        created = self._workspace(sid)["assessments"]["initial"]["created_at"]
        self.assertTrue(created.endswith("+00:00"), created)
        self.assertIsNotNone(datetime.fromisoformat(created).utcoffset())
        updated = self._note_put(sid, {"content": "n"}).get_json()["updated_at"]
        self.assertTrue(updated.endswith("+00:00"), updated)
        # The value is what was stored (naive UTC), not shifted.
        stored = get_active_note(self.base_coder_user.user_id, sid).note_updated_at
        self.assertEqual(datetime.fromisoformat(updated).replace(tzinfo=None), stored)

    def test_a_note_saved_through_the_web_form_is_read_by_the_api_and_prefills_the_web(self):
        sid = self._coding_case()
        url = f"/vaform/{sid}/vausernote"
        query = {"action": "vacode", "actiontype": "varesumecoding"}
        self._login(self.base_coder_id)
        saved = self.client.post(
            url, query_string=query, data={"va_note_content": "from the web form"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        self.assertIn("Note Saved!", saved.get_data(as_text=True))
        self.assertEqual(self._note_get(sid).get_json()["content"], "from the web form")
        # The API writes; the web page opens with it.
        self.assertEqual(self._note_put(sid, {"content": "from the api"}).status_code, 200)
        page = self.client.get(url, query_string=query)
        self.assertEqual(page.status_code, 200)
        self.assertIn("from the api", page.get_data(as_text=True))
        rows = db.session.scalars(sa.select(VaUsernotes).where(
            VaUsernotes.note_vasubmission == sid, VaUsernotes.note_by == self.base_coder_user.user_id
        )).all()
        self.assertEqual(len(rows), 1)

    def test_another_users_note_is_never_read_and_a_case_held_by_another_coder_is_refused(self):
        sid = self._coding_case()
        save_note(self.reviewer.user_id, sid, "the reviewer's own note")
        self.assertEqual(self._note_put(sid, {"content": "coder note"}).status_code, 200)
        self.assertEqual(self._note_get(sid).get_json()["content"], "coder note")
        self._login(self.reviewer_id)
        # Present: the reviewer's own row exists and is theirs alone.
        self.assertEqual(
            get_active_note(self.reviewer.user_id, sid).note_content, "the reviewer's own note"
        )
        self.assertEqual(self._note_get(sid).get_json()["content"], "coder note")
        other = self._make_user(f"xl43p3a.other.{uuid.uuid4().hex[:6]}@test.local", "OtherCoder123")
        held_elsewhere = self._case(allocated_to=other.user_id)
        save_note(other.user_id, held_elsewhere, "not for the coder")
        for response in (
            self._note_get(held_elsewhere),
            self._note_put(held_elsewhere, {"content": "intruder"}),
        ):
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (403, "no_allocation")
            )
        self.assertEqual(
            get_active_note(other.user_id, held_elsewhere).note_content, "not for the coder"
        )
        self.assertIsNone(get_active_note(self.base_coder_user.user_id, held_elsewhere))


class CaseStepStateTests(BaseTestCase):
    """The pure step rules, as the COD panel picks them."""

    def test_coding_step(self):
        step = case_content.coding_step
        self.assertEqual(step(masked=True, has_initial=False, has_not_codeable=False), "initial")
        self.assertEqual(step(masked=False, has_initial=False, has_not_codeable=False), "final")
        self.assertEqual(step(masked=True, has_initial=True, has_not_codeable=False), "final")
        self.assertEqual(step(masked=True, has_initial=False, has_not_codeable=True), "done")
        self.assertEqual(step(masked=False, has_initial=False, has_not_codeable=True), "done")
        self.assertEqual(step(masked=True, has_initial=True, has_not_codeable=True), "final")

    def test_reviewing_step(self):
        step = case_content.reviewing_step
        self.assertEqual(step(masked=True, has_initial=False, has_final=False), "initial")
        self.assertEqual(step(masked=True, has_initial=True, has_final=False), "final")
        self.assertEqual(step(masked=False, has_initial=False, has_final=False), "final")
        self.assertEqual(step(masked=True, has_initial=True, has_final=True), "done")
