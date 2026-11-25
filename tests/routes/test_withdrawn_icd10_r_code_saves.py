"""A withdrawn ICD-10 symptom code (R00-R94 except R50, R54) is refused on save
(digitva-82l9; docs/policy/who-2022-icd10-coding-allowability.md).

The tests set ``is_coding_selectable`` themselves, so they do not depend on the
withdrawal migration having run in the test database. Routes: the coder's
``/api/v1/coding/{initial,finalize}`` and the reviewer's
``/api/v1/reviewing/finalize``. Coder drafts for ICD-10 COD do not exist as a
separate store: the only saved in-progress COD is the masked Step 1 row
(``VaInitialAssessments``), covered below.
"""
import uuid
from datetime import UTC, datetime

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
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.authz import invalidate
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
)
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase

_TITLES = {
    "R10": "Abdominal and pelvic pain",
    "R17": "Unspecified jaundice",
    "R54": "Senility",
}
_WITHDRAWN = ("R10", "R17")
_SUFFIX = uuid.uuid4().hex[:4].upper()


def _seed_codes():
    now = datetime.now(UTC)
    for code, title in _TITLES.items():
        db.session.merge(MasIcd1020192(
            code=code, title=title, node_type="category", semantic_level="three_character",
            sort_order=1, parent_code=None, chapter_code="XVIII",
            chapter_title="Symptoms, signs and abnormal findings",
            block_code="R00-R99", block_title="Symptoms and signs",
            three_character_code=code, three_character_title=title,
            has_children=False, is_leaf=True, is_three_character_code=True,
            is_detailed_code=False, is_coding_selectable=code not in _WITHDRAWN,
            sex_selectable="both", age_group_selectable="all", policy_status="unreviewed",
            source_version="ICD-10-2019", source_path="test", is_active=True,
            created_at=now, updated_at=now,
        ))
    db.session.commit()


def _case(form_id, state):
    sid = f"uuid:82l9-{uuid.uuid4().hex[:10]}"
    now = datetime.now(UTC)
    submission = VaSubmissions(
        va_sid=sid, va_form_id=form_id, va_submission_date=now, va_odk_updatedat=now,
        va_data_collector="Collector", va_instance_name=sid, va_uniqueid_real=sid,
        va_uniqueid_masked=sid, va_consent="yes", va_narration_language="English",
        va_deceased_age=60, va_deceased_gender="Male",
        va_summary=[], va_catcount={}, va_category_list=[],
    )
    db.session.add(submission)
    db.session.flush()
    ensure_active_payload_version(
        submission, payload_data={}, source_updated_at=now, created_by_role="vasystem")
    set_submission_workflow_state(sid, state, reason="test_setup", by_role="vasystem")
    db.session.commit()
    return sid


def _set_project(project_id, masked):
    project = db.session.get(VaProjectMaster, project_id)
    project.masked_cod_required = masked
    project.icd_classification = "icd10"
    project.cod_entry_mode = "simple"
    project.narrative_qa_enabled = False
    project.social_autopsy_enabled = False
    project.reviewer_social_autopsy_enabled = False
    db.session.commit()


class WithdrawnRCodeCoderSaveTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}W8"
    BASE = "/api/v1/coding"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        now = datetime.now(UTC)
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
            odk_form_id=f"ODK_{cls.FORM_ID}", odk_project_id="1", form_type="WHO_2022_VA",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        _seed_codes()

    def setUp(self):
        super().setUp()
        limiter.reset()
        invalidate(self.base_coder_user.user_id)

    def _coded_case(self):
        sid = _case(self.FORM_ID, WORKFLOW_CODING_IN_PROGRESS)
        # One active allocation per user and kind: drop this test's earlier ones.
        db.session.execute(sa.delete(VaAllocations).where(
            VaAllocations.va_allocated_to == self.base_coder_user.user_id))
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid,
            va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()
        return sid

    def _post(self, route, sid, body):
        self._login(self.base_coder_id)
        return self.client.post(
            f"{self.BASE}/{route}/{sid}", json=body, headers=self._csrf_headers())

    def _final_body(self, code):
        return {"conclusive_cod": f"{code}-{_TITLES[code]}", "immediate_cod": f"{code}-{_TITLES[code]}"}

    def _state(self, sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == sid))

    def test_finalize_refuses_a_withdrawn_code_and_accepts_r54(self):
        _set_project(self.BASE_PROJECT_ID, masked=False)
        # Subject present: the withdrawn rows exist and are not selectable.
        for code in _WITHDRAWN:
            row = db.session.get(MasIcd1020192, code)
            self.assertIsNotNone(row)
            self.assertFalse(row.is_coding_selectable)
        for code in _WITHDRAWN:
            with self.subTest(code=code):
                sid = self._coded_case()
                response = self._post("finalize", sid, self._final_body(code))
                body = response.get_json()
                self.assertEqual((response.status_code, body["code"]), (422, "final_blocked"), body)
                self.assertIn(code, body["error"])
                self.assertTrue(any(code in m for m in body["messages"]), body)
                self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)
                self.assertIsNone(db.session.scalar(sa.select(VaFinalAssessments).where(
                    VaFinalAssessments.va_sid == sid)))
        sid = self._coded_case()
        response = self._post("finalize", sid, self._final_body("R54"))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNotNone(db.session.scalar(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == sid)))

    def test_step1_refuses_a_withdrawn_code_with_invalid_cod(self):
        _set_project(self.BASE_PROJECT_ID, masked=True)
        for code in _WITHDRAWN:
            with self.subTest(code=code):
                sid = self._coded_case()
                value = f"{code}-{_TITLES[code]}"
                response = self._post("initial", sid, {"immediate_cod": value, "antecedent_cod": value})
                body = response.get_json()
                self.assertEqual((response.status_code, body["code"]), (400, "invalid_cod"), body)
                self.assertIn(code, body["error"])
                self.assertIsNone(db.session.scalar(sa.select(VaInitialAssessments).where(
                    VaInitialAssessments.va_sid == sid)))
        sid = self._coded_case()
        value = f"R54-{_TITLES['R54']}"
        response = self._post("initial", sid, {"immediate_cod": value, "antecedent_cod": value})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_a_saved_step1_holding_a_withdrawn_code_survives_a_refused_final(self):
        # Step 1 saved while R10 was still selectable; the code is withdrawn after.
        _set_project(self.BASE_PROJECT_ID, masked=True)
        db.session.get(MasIcd1020192, "R10").is_coding_selectable = True
        db.session.commit()
        sid = self._coded_case()
        value = f"R10-{_TITLES['R10']}"
        saved = self._post("initial", sid, {"immediate_cod": value, "antecedent_cod": value})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(self._state(sid), WORKFLOW_CODER_STEP1_SAVED)
        db.session.get(MasIcd1020192, "R10").is_coding_selectable = False
        db.session.commit()

        initial = db.session.scalar(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid))
        self.assertIsNotNone(initial)
        before = (initial.va_iniassess_id, initial.va_immediate_cod, initial.va_antecedent_cod)

        response = self._post("finalize", sid, self._final_body("R10"))
        body = response.get_json()
        self.assertEqual((response.status_code, body["code"]), (422, "final_blocked"), body)
        self.assertIn("R10", body["error"])

        db.session.expire_all()
        initial = db.session.scalar(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid))
        self.assertIsNotNone(initial)
        self.assertEqual(
            (initial.va_iniassess_id, initial.va_immediate_cod, initial.va_antecedent_cod), before)
        self.assertEqual(self._state(sid), WORKFLOW_CODER_STEP1_SAVED)
        self.assertIsNone(db.session.scalar(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == sid)))


class WithdrawnRCodeReviewerSaveTests(BaseTestCase):
    BASE_PROJECT_ID = f"W8{_SUFFIX}"
    BASE_SITE_ID = f"W{_SUFFIX[:3]}"
    FORM_ID = f"W8F{_SUFFIX}001"
    API = "/api/v1/reviewing"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
            odk_form_id=f"ODK_{cls.FORM_ID}", odk_project_id="1", form_type="WHO_2022_VA",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.commit()
        pair_id = db.session.scalar(db.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == cls.BASE_PROJECT_ID,
            VaProjectSites.site_id == cls.BASE_SITE_ID,
        ))
        cls.reviewer = cls._make_user(f"w8.rev.{_SUFFIX.lower()}@test.local", "ReviewerW8123")
        cls.reviewer.landing_page = "reviewer"
        db.session.add(VaUserAccessGrants(
            user_id=cls.reviewer.user_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project_site, project_site_id=pair_id,
            notes="82l9 reviewer", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        _seed_codes()

    def setUp(self):
        super().setUp()
        limiter.reset()
        invalidate(self.reviewer.user_id)
        _set_project(self.BASE_PROJECT_ID, masked=False)

    def _reviewed_case(self):
        sid = _case(self.FORM_ID, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        db.session.execute(sa.delete(VaAllocations).where(
            VaAllocations.va_allocated_to == self.reviewer.user_id))
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=self.reviewer.user_id,
            va_allocation_for=VaAllocation.reviewing,
        ))
        db.session.commit()
        return sid

    def _final(self, sid, code):
        self._login(str(self.reviewer.user_id))
        value = f"{code}-{_TITLES[code]}"
        return self.client.post(
            f"{self.API}/finalize/{sid}",
            json={"conclusive_cod": value, "immediate_cod": value},
            headers=self._csrf_headers())

    def _saved(self, sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == sid))

    def test_reviewer_finalize_refuses_a_withdrawn_code_and_accepts_r54(self):
        for code in _WITHDRAWN:
            row = db.session.get(MasIcd1020192, code)
            self.assertIsNotNone(row)
            self.assertFalse(row.is_coding_selectable)
            with self.subTest(code=code):
                sid = self._reviewed_case()
                response = self._final(sid, code)
                body = response.get_json()
                self.assertEqual((response.status_code, body["code"]), (422, "final_blocked"), body)
                self.assertIn(code, body["error"])
                self.assertIsNone(self._saved(sid))
        sid = self._reviewed_case()
        response = self._final(sid, "R54")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNotNone(self._saved(sid))
