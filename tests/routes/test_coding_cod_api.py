"""POST /api/v1/coding/initial|finalize|not-codeable/<sid> (digitva-xl43 phase 1).

The coder's COD writes over JSON, with the browser cookie (``X-CSRFToken``) or
a device bearer token alike; errors are ``{error, code}``. The logic is
``coder_cod_service`` (tests/services/test_coder_cod_service.py); this covers
the routes: bodies, gates, replies and the two credentials. Device enrolment
helpers are reused from tests/routes/test_device_api.py.
"""
import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
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
    VaInitialAssessments,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.authz import invalidate
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
)
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

_COD = "I24-Other acute ischaemic heart diseases"
_DEV = device_tests.DeviceApiTests.__dict__
_ODK_OK = SimpleNamespace(success=True, review_state="hasIssues", error_message=None)
_CODER_EMAIL = "base.coder@test.local"
_CODER_PASSWORD = "BaseCoder123"
BASE = "/api/v1/coding"


class CodingCodApiTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}X2"
    # The coder signs a device in through an interviewer grant of their own.
    DEVICE_PROJECT_ID = "XL43D"
    DEVICE_SITE_ID = "XD43"
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
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID, odk_form_id="XL43_API_FORM", odk_project_id="44",
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
        if db.session.get(VaProjectMaster, cls.DEVICE_PROJECT_ID) is None:
            cls._make_project(cls.DEVICE_PROJECT_ID, cls.DEVICE_SITE_ID, now)
        cls._grant(cls.base_coder_user, cls.DEVICE_PROJECT_ID)
        cls.reviewer = cls._make_user(f"xl43.rev.{uuid.uuid4().hex[:6]}@test.local", "Reviewer123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.reviewer.user_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.BASE_PROJECT_ID,
            notes="xl43", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = device_tests._FreshGClient(
            self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}
        self._mode()
        invalidate(self.base_coder_user.user_id)

    def _mode(self, masked=False, doris=False):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        project.icd_classification = "icd11" if doris else "icd10"
        project.cod_entry_mode = "doris" if doris else "simple"
        project.narrative_qa_enabled = False
        project.social_autopsy_enabled = False
        db.session.commit()

    def _case(self, state=WORKFLOW_CODING_IN_PROGRESS, allocated=True):
        sid = f"uuid:xl43api-{uuid.uuid4().hex[:10]}"
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
            submission, payload_data={}, source_updated_at=now, created_by_role="vasystem")
        if allocated:
            db.session.add(VaAllocations(
                va_allocation_id=uuid.uuid4(), va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
            ))
        db.session.commit()
        return sid

    def _state(self, sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == sid))

    def _as_coder(self):
        self._login(self.base_coder_id)
        return self._csrf_headers()

    def _bearer_headers(self):
        _device, tokens = self._session(email=_CODER_EMAIL, password=_CODER_PASSWORD)
        return self._bearer(tokens)

    def _post(self, route, sid, body, headers=None):
        return self.client.post(
            f"{BASE}/{route}/{sid}", json=body,
            headers=self._as_coder() if headers is None else headers)

    # -- cookie + CSRF -----------------------------------------------------

    def test_finalize_with_a_cookie_and_csrf(self):
        sid = self._case()
        response = self._post("finalize", sid, {
            "conclusive_cod": _COD, "immediate_cod": _COD, "remark": "ok",
            "cod_search_id": "none", "cod_chosen_code": "I24", "cod_chosen_rank": 1,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        final = db.session.scalar(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == sid))
        self.assertEqual(response.get_json(), {
            "va_sid": sid, "final_assessment_id": str(final.va_finassess_id),
            "workflow_state": WORKFLOW_CODER_FINALIZED,
        })
        self.assertEqual(final.va_finassess_remark, "ok")

    def test_a_cookie_write_without_a_csrf_token_is_refused(self):
        sid = self._case()
        self._login(self.base_coder_id)
        response = self.client.post(f"{BASE}/finalize/{sid}", json={"conclusive_cod": _COD})
        self.assertEqual((response.status_code, response.get_json()["code"]), (400, "csrf_failed"))
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)

    def test_initial_then_finalize_on_a_masked_project(self):
        self._mode(masked=True)
        sid = self._case()
        response = self._post("initial", sid, {
            "immediate_cod": _COD, "antecedent_cod": _COD, "other_conditions": ["I10 - Essential Hypertension"],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        initial = db.session.scalar(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid))
        self.assertEqual(response.get_json(), {
            "va_sid": sid, "initial_assessment_id": str(initial.va_iniassess_id),
            "workflow_state": WORKFLOW_CODER_STEP1_SAVED,
        })
        self.assertEqual(initial.va_other_conditions, "I10 - Essential Hypertension")
        final = self._post("finalize", sid, {"conclusive_cod": _COD})
        self.assertEqual(final.status_code, 200, final.get_json())
        self.assertEqual(final.get_json()["workflow_state"], WORKFLOW_CODER_FINALIZED)

    def test_initial_takes_other_conditions_as_one_joined_text(self):
        self._mode(masked=True)
        sid = self._case()
        response = self._post("initial", sid, {
            "immediate_cod": _COD, "antecedent_cod": _COD,
            "other_conditions": "I10 - Essential Hypertension | E66 - Obesity",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        initial = db.session.scalar(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid))
        self.assertEqual(initial.va_other_conditions, "I10 - Essential Hypertension | E66 - Obesity")

    def test_not_codeable(self):
        sid = self._case()
        with mock.patch(
            "app.services.coder_cod_service.sync_not_codeable_review_state", return_value=_ODK_OK
        ):
            response = self._post("not-codeable", sid, {"reason": "others", "other": "scan unreadable"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {
            "va_sid": sid, "workflow_state": WORKFLOW_NOT_CODEABLE_BY_CODER,
            "odk_synced": True})

    # -- refusals: {error, code} -------------------------------------------

    def test_service_refusals_carry_their_status_and_code(self):
        sid = self._case()
        # Unmasked: no Step 1.
        response = self._post("initial", sid, {"immediate_cod": _COD, "antecedent_cod": _COD})
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "not_masked"))
        self.assertEqual(set(response.get_json()), {"error", "code"})
        unallocated = self._case(allocated=False)
        response = self._post("finalize", unallocated, {"conclusive_cod": _COD, "immediate_cod": _COD})
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_allocation"))
        response = self._post("finalize", "uuid:nope", {"conclusive_cod": _COD})
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "not_found"))
        response = self._post("not-codeable", sid, {"reason": "bored"})
        self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))

    def test_blocking_gates_list_every_message(self):
        sid = self._case()
        response = self._post("finalize", sid, {"conclusive_cod": "ZZZ not a code"})
        body = response.get_json()
        self.assertEqual((response.status_code, body["code"]), (422, "final_blocked"))
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["error"], body["messages"][0])
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)

    def test_step1_invalid_causes_list_every_message(self):
        self._mode(masked=True)
        sid = self._case()
        response = self._post("initial", sid, {
            "immediate_cod": "ZZZ not a code", "antecedent_cod": "YYY not a code"})
        body = response.get_json()
        self.assertEqual((response.status_code, body["code"]), (400, "invalid_cod"))
        self.assertEqual(len(body["messages"]), 2)

    def test_malformed_bodies_are_a_400(self):
        sid = self._case()
        headers = self._as_coder()
        for route, body in (
            ("finalize", ["not", "an", "object"]),
            ("finalize", {"conclusive_cod": 5}),
            ("finalize", {}),
            ("finalize", {"conclusive_cod": _COD, "doris_certificate": "text"}),
            ("initial", {"antecedent_cod": _COD, "other_conditions": {"a": 1}}),
            ("not-codeable", {"reason": 3}),
        ):
            response = self.client.post(f"{BASE}/{route}/{sid}", json=body, headers=headers)
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (400, "invalid_request"),
                (route, body))

    def test_a_body_over_the_cap_is_a_413_on_every_route(self):
        sid = self._case()
        headers = self._as_coder()
        big = {"pad": "x" * 1_300_000}
        for route in ("initial", "finalize", "not-codeable"):
            response = self.client.post(f"{BASE}/{route}/{sid}", json=big, headers=headers)
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (413, "payload_too_large"), route)
        # A body within the cap still reaches the service.
        self._mode(masked=True)
        response = self._post("initial", sid, {"antecedent_cod": _COD, "immediate_cod": _COD})
        self.assertEqual(response.status_code, 200)

    def test_a_body_without_a_content_length_is_a_413_on_every_route(self):
        # A chunked body has no Content-Length; it must not be buffered.
        self._mode(masked=True)
        sid = self._case()
        headers = self._as_coder()
        for route in ("initial", "finalize", "not-codeable"):
            response = self.client.post(
                f"{BASE}/{route}/{sid}", headers=headers,
                input_stream=io.BytesIO(b'{"immediate_cod": "x"}'), content_type="application/json",
                environ_overrides={"CONTENT_LENGTH": "", "HTTP_TRANSFER_ENCODING": "chunked"},
            )
            self.assertIsNone(response.request.content_length, route)
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (413, "payload_too_large"), route)
        # Present: a sized body reaches the service.
        response = self._post("initial", sid, {"antecedent_cod": _COD, "immediate_cod": _COD})
        self.assertEqual(response.status_code, 200)

    def test_free_text_over_4000_characters_is_a_422(self):
        self._mode(masked=True)
        sid = self._case()
        long_text = "x" * 4001
        for route, body in (
            ("initial", {"immediate_cod": _COD, "antecedent_cod": _COD, "other_conditions": [long_text]}),
            ("finalize", {"conclusive_cod": _COD, "remark": long_text}),
            ("finalize", {"conclusive_cod": _COD, "other_conditions": long_text}),
            ("not-codeable", {"reason": "others", "other": long_text}),
        ):
            response = self._post(route, sid, body)
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (422, "invalid_request"),
                (route, list(body)))
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)
        # Exactly at the cap is accepted.
        response = self._post("finalize", sid, {"conclusive_cod": _COD, "remark": "x" * 4000})
        self.assertEqual(response.status_code, 409)  # masked: refused for the missing Step 1, not the length

    def test_finalize_search_telemetry_fields_are_typed(self):
        sid = self._case()
        for field, value in (
            ("cod_chosen_code", 5), ("cod_search_id", ["a"]),
            ("cod_chosen_rank", "1"), ("cod_chosen_rank", True), ("cod_chosen_rank", 1.5),
        ):
            response = self._post("finalize", sid, {
                "conclusive_cod": _COD, "immediate_cod": _COD, field: value})
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (400, "invalid_request"),
                (field, value))
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)
        self.assertIsNone(db.session.scalar(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == sid)))
        allocation = db.session.scalar(sa.select(VaAllocations).where(
            VaAllocations.va_sid == sid, VaAllocations.va_allocated_to == self.base_coder_user.user_id))
        self.assertEqual(allocation.va_allocation_status, VaStatuses.active)

    def test_masked_final_without_step1_is_a_409(self):
        self._mode(masked=True)
        sid = self._case()
        response = self._post("finalize", sid, {"conclusive_cod": _COD})
        body = response.get_json()
        self.assertEqual((response.status_code, body["code"], body["error"]),
                         (409, "wrong_state", "Save Step 1 first."))
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)

    def test_only_coders_and_testers_reach_the_routes(self):
        sid = self._case()
        self._login(str(self.reviewer.user_id))
        response = self.client.post(
            f"{BASE}/finalize/{sid}", json={"conclusive_cod": _COD}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "forbidden")

    def test_a_coder_out_of_scope_is_refused_by_authz(self):
        sid = self._case()
        outsider = self._make_user(f"xl43.out.{uuid.uuid4().hex[:6]}@test.local", "Outsider123")
        db.session.add(VaUserAccessGrants(
            user_id=outsider.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project, project_id=self.DEVICE_PROJECT_ID,
            notes="xl43 other project", grant_status=VaStatuses.active,
        ))
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=outsider.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()
        invalidate(outsider.user_id)
        self._login(str(outsider.user_id))
        response = self.client.post(
            f"{BASE}/finalize/{sid}", json={"conclusive_cod": _COD, "immediate_cod": _COD},
            headers=self._csrf_headers())
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))
        self.assertEqual(self._state(sid), WORKFLOW_CODING_IN_PROGRESS)

    # -- device bearer -----------------------------------------------------

    def test_finalize_with_a_bearer_needs_no_csrf_and_sets_no_cookie(self):
        sid = self._case()
        headers = self._bearer_headers()
        bearer_only = device_tests._FreshGClient(
            self.app, self.app.response_class, use_cookies=True)
        response = bearer_only.post(
            f"{BASE}/finalize/{sid}", json={"conclusive_cod": _COD, "immediate_cod": _COD},
            headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["workflow_state"], WORKFLOW_CODER_FINALIZED)
        self.assertNotIn("Set-Cookie", response.headers)

    def test_initial_and_not_codeable_with_a_bearer(self):
        self._mode(masked=True)
        headers = self._bearer_headers()
        bearer_only = device_tests._FreshGClient(
            self.app, self.app.response_class, use_cookies=True)
        sid = self._case()
        response = bearer_only.post(
            f"{BASE}/initial/{sid}", json={"immediate_cod": _COD, "antecedent_cod": _COD},
            headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["workflow_state"], WORKFLOW_CODER_STEP1_SAVED)
        with mock.patch(
            "app.services.coder_cod_service.sync_not_codeable_review_state", return_value=_ODK_OK
        ):
            response = bearer_only.post(
                f"{BASE}/not-codeable/{sid}", json={"reason": "no_info"}, headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["workflow_state"], WORKFLOW_NOT_CODEABLE_BY_CODER)

    def test_a_bad_bearer_is_a_401(self):
        sid = self._case()
        response = self.client.post(
            f"{BASE}/finalize/{sid}", json={"conclusive_cod": _COD},
            headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "unauthorized"))
