"""Reviewing API, phase 3b (digitva-xl43.5): flat ``{error, code}`` errors, the
reviewer queue (stats, available, history) and the reviewer's own release.

Policy: docs/policy/coding-allocation-timeouts.md ("Reviewer release"),
docs/policy/api-v1.md. Owner decision 2026-10-05 (``reviewer-release-keeps-step1``):
a release clears the review, NQA and Social Autopsy but keeps the saved Step 1.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from flask import template_rendered

from app import db, limiter
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaForms,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaReviewerReview,
    VaSiteMaster,
    VaSites,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
)
from app.services import reviewer_dashboard_service
from app.services.coding_allocation_service import release_stale_reviewer_allocations
from app.services.doris_certificate import DorisCertificateError
from app.services.doris_process_proof import (
    ProcessProofCertificateChanged,
    ProcessProofContextMismatch,
    ProcessProofResultMismatch,
)
from app.services.odk_retirement_service import MISSING_IN_ODK
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    _who_image_digest,
    start_reviewer_coding,
    verify_doris_submission,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.who_icd_api import WhoIcdApiUnavailable
from app.services.workflow.definition import (
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from app.services.workflow.transitions import WorkflowTransitionError
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
_API = "/api/v1/reviewing"
_VA = "/api/v1/va"
_VALIDATE = "app.services.reviewer_coding_service.validate_coding_value_for_submission"
_PROVENANCE = "app.services.reviewer_coding_service.build_icd11_provenance_for_values"


class ReviewingApiPhase3bTests(BaseTestCase):
    BASE_PROJECT_ID = f"R3{_RUN_SUFFIX}"
    BASE_SITE_ID = f"S{_RUN_SUFFIX[:3]}"
    OTHER_SITE_ID = f"T{_RUN_SUFFIX[:3]}"
    FORM_ID = f"R3F{_RUN_SUFFIX}001"
    OTHER_FORM_ID = f"R3G{_RUN_SUFFIX}001"
    USER_EMAIL_SUFFIX = f"+r3b{_RUN_SUFFIX.lower()}"

    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        return super()._make_user(f"{local_part}{cls.USER_EMAIL_SUFFIX}@{domain}", password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        db.session.commit()
        # A second pair the reviewers hold no grant on.
        db.session.add(VaSiteMaster(
            site_id=cls.OTHER_SITE_ID, site_name="Other pair site", site_abbr=cls.OTHER_SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.add(VaSites(
            site_id=cls.OTHER_SITE_ID, project_id=cls.BASE_PROJECT_ID, site_name="Other pair site",
            site_abbr=cls.OTHER_SITE_ID, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.BASE_PROJECT_ID, site_id=cls.OTHER_SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        for form_id, site_id in ((cls.FORM_ID, cls.BASE_SITE_ID), (cls.OTHER_FORM_ID, cls.OTHER_SITE_ID)):
            db.session.add(VaForms(
                form_id=form_id, project_id=cls.BASE_PROJECT_ID, site_id=site_id,
                odk_form_id=f"ODK_{form_id}", odk_project_id="1", form_type="WHO_2022_VA",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()
        pair_id = db.session.scalar(db.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == cls.BASE_PROJECT_ID,
            VaProjectSites.site_id == cls.BASE_SITE_ID,
        ))
        cls.reviewer = cls._make_user("rev.one@test.local", "ReviewerOne123")
        cls.reviewer2 = cls._make_user("rev.two@test.local", "ReviewerTwo123")
        for user in (cls.reviewer, cls.reviewer2):
            user.landing_page = "reviewer"
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site, project_site_id=pair_id,
                notes="phase 3b reviewer", grant_status=VaStatuses.active,
            ))
        db.session.commit()

    # -- fixtures ------------------------------------------------------------

    def _mode(self, *, masked=False, doris=False, nqa=False, social=False):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.masked_cod_required = masked
        project.icd_classification = "icd11" if doris else "icd10"
        project.cod_entry_mode = "doris" if doris else "simple"
        project.narrative_qa_enabled = nqa
        project.reviewer_social_autopsy_enabled = social
        db.session.commit()

    def _case(
        self,
        state=WORKFLOW_REVIEWER_ELIGIBLE,
        *,
        form_id=None,
        language="English",
        retired=False,
        submitted=None,
    ):
        sid = f"uuid:r3b-{uuid.uuid4()}"
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid, va_form_id=form_id or self.FORM_ID,
            va_submission_date=submitted or now, va_odk_updatedat=now,
            va_data_collector="tester", va_instance_name=sid,
            va_uniqueid_real=None, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language=language, va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
            va_sync_issue_code=MISSING_IN_ODK if retired else None,
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission, payload_data={}, source_updated_at=submission.va_odk_updatedat,
        )
        set_submission_workflow_state(sid, state, reason="test_setup", by_role="vasystem")
        db.session.commit()
        return sid

    def _allocate(self, user, sid, state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS):
        """An active reviewing allocation with the case in a reviewer session."""
        allocation = VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.reviewing,
        )
        db.session.add(allocation)
        if state:
            set_submission_workflow_state(sid, state, reason="test_setup", by_role="vasystem")
        db.session.commit()
        return allocation

    def _as(self, user):
        self._login(str(user.user_id))

    def _post(self, path, **kwargs):
        return self.client.post(path, headers=self._csrf_headers(), **kwargs)

    def _flat(self, response, status, code):
        """The body is exactly ``{error, code}``: no nesting, no schema_version."""
        body = response.get_json()
        self.assertEqual(response.status_code, status, body)
        self.assertEqual(body["code"], code, body)
        self.assertIsInstance(body["error"], str, body)
        self.assertNotIn("schema_version", body)
        return body

    # -- flat errors: allocation ---------------------------------------------

    def test_allocation_errors_are_flat_and_coded(self):
        self._as(self.reviewer)
        self._flat(self._post(f"{_API}/allocation/uuid:missing"), 404, "not_found")

        other_pair = self._case(form_id=self.OTHER_FORM_ID)
        self._flat(self._post(f"{_API}/allocation/{other_pair}"), 403, "forbidden")

        hindi = self._case(language="Hindi")
        self._flat(self._post(f"{_API}/allocation/{hindi}"), 403, "forbidden")

        not_eligible = self._case(WORKFLOW_READY_FOR_CODING)
        self._flat(self._post(f"{_API}/allocation/{not_eligible}"), 403, "wrong_state")

        retired = self._case(retired=True)
        self._flat(self._post(f"{_API}/allocation/{retired}"), 409, "conflict")

        first, second = self._case(), self._case()
        self.assertEqual(self._post(f"{_API}/allocation/{first}").status_code, 201)
        self._flat(self._post(f"{_API}/allocation/{second}"), 409, "allocation_exists")

    def test_a_confirmed_duplicate_is_a_409_conflict(self):
        sid = self._case()
        db.session.add(VaDeathRegister(
            project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID, death_number=990001,
            unique_id=f"R3B-{_RUN_SUFFIX}", deceased_name="Asha Devi", deceased_sex="female",
            date_of_death=date.today(), registered_by=self.base_coder_user.user_id,
            status="duplicate", va_sid=sid,
        ))
        db.session.commit()
        self._as(self.reviewer)
        self._flat(self._post(f"{_API}/allocation/{sid}"), 409, "conflict")

    # -- flat errors: Step 1 and final ---------------------------------------

    def test_final_and_initial_request_errors_are_coded(self):
        self._as(self.reviewer)
        sid = self._case()
        for path in ("finalize", "initial"):
            with self.subTest(path=path):
                self._flat(self._post(f"{_API}/{path}/{sid}", json=[1]), 400, "invalid_request")
                self._flat(self._post(f"{_API}/{path}/{sid}", data="not json"), 400, "invalid_request")
                self._flat(
                    self._post(f"{_API}/{path}/{sid}", json={"immediate_cod": 5, "conclusive_cod": "A00"}),
                    400, "invalid_request",
                )
        self._flat(self._post(f"{_API}/finalize/{sid}", json={"remark": "x"}), 400, "invalid_request")
        self._flat(self._post(f"{_API}/initial/{sid}", json={"antecedent_cod": "A00"}), 400, "invalid_request")
        self._flat(self._post(f"{_API}/initial/{sid}", json={"immediate_cod": "A00"}), 400, "invalid_request")

    def test_final_and_initial_state_errors_are_coded(self):
        self._mode(masked=False)
        self._as(self.reviewer)
        eligible = self._case()
        in_session = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        body = {"conclusive_cod": "R99", "immediate_cod": "R99"}
        with patch(_VALIDATE), patch(_PROVENANCE, return_value={}):
            self._flat(self._post(f"{_API}/finalize/uuid:missing", json=body), 404, "not_found")
            self._flat(self._post(f"{_API}/finalize/{eligible}", json=body), 403, "wrong_state")
            self._flat(self._post(f"{_API}/finalize/{in_session}", json=body), 403, "no_allocation")
        # Not a code the catalogue knows.
        self._allocate(self.reviewer, in_session)
        self._flat(
            self._post(f"{_API}/finalize/{in_session}", json={"conclusive_cod": "NOT-A-CODE", "immediate_cod": "X"}),
            400, "invalid_cod",
        )
        other_pair = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS, form_id=self.OTHER_FORM_ID)
        self._flat(self._post(f"{_API}/finalize/{other_pair}", json=body), 403, "forbidden")

        # Step 1 belongs to masked projects.
        initial = {"immediate_cod": "R99", "antecedent_cod": "R99"}
        self._flat(self._post(f"{_API}/initial/{in_session}", json=initial), 409, "not_masked")
        self._mode(masked=True)
        self._flat(self._post(f"{_API}/initial/{eligible}", json=initial), 403, "wrong_state")
        other_session = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self._flat(self._post(f"{_API}/initial/{other_session}", json=initial), 403, "no_allocation")
        self._flat(
            self._post(f"{_API}/initial/{in_session}", json={"immediate_cod": "NOPE", "antecedent_cod": "NOPE"}),
            400, "invalid_cod",
        )

    def test_a_final_without_the_required_social_autopsy_is_final_blocked(self):
        self._mode(masked=False, social=True)
        sid = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self._allocate(self.reviewer, sid, state=None)
        self._as(self.reviewer)
        with patch(_VALIDATE), patch(_PROVENANCE, return_value={}), patch(
            "app.services.reviewer_coding_service._reviewer_social_autopsy_required",
            return_value=True,
        ):
            self._flat(
                self._post(f"{_API}/finalize/{sid}", json={"conclusive_cod": "R99", "immediate_cod": "R99"}),
                400, "final_blocked",
            )

    def test_a_release_between_the_state_check_and_the_transition_is_a_409_not_a_500(self):
        """The session ends after submit_reviewer_final_cod checked the state:
        nothing of the save stays and the reply is 409 wrong_state."""
        self._mode(masked=False)
        sid = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        allocation = self._allocate(self.reviewer, sid, state=None)
        allocation_id = allocation.va_allocation_id
        self._as(self.reviewer)
        body = {"conclusive_cod": "R99", "immediate_cod": "R99"}
        with patch(_VALIDATE), patch(_PROVENANCE, return_value={}), patch(
            "app.services.reviewer_coding_service.mark_reviewer_finalized",
            side_effect=WorkflowTransitionError("released meanwhile"),
        ) as transition:
            self._flat(self._post(f"{_API}/finalize/{sid}", json=body), 409, "wrong_state")
        # Presence first: the save got as far as the transition.
        transition.assert_called_once()
        db.session.expire_all()
        self.assertIsNone(db.session.scalar(
            db.select(VaReviewerFinalAssessments).where(VaReviewerFinalAssessments.va_sid == sid)
        ))
        self.assertEqual(db.session.get(VaAllocations, allocation_id).va_allocation_status, VaStatuses.active)
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

    def test_a_masked_final_without_step_one_is_wrong_state(self):
        self._mode(masked=True)
        sid = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self._allocate(self.reviewer, sid, state=None)
        self._as(self.reviewer)
        with patch(_VALIDATE):
            self._flat(self._post(f"{_API}/finalize/{sid}", json={"conclusive_cod": "R99"}), 400, "wrong_state")

    def test_oversized_doris_bodies_are_too_large(self):
        self._as(self.reviewer)
        big = '{"x": "' + "a" * 1_300_000 + '"}'
        headers = {**self._csrf_headers(), "Content-Type": "application/json"}
        self._mode(masked=False, doris=True)
        sid = self._case()
        response = self.client.post(f"{_API}/finalize/{sid}", data=big, headers=headers)
        self._flat(response, 413, "too_large")
        self._mode(masked=True, doris=True)
        response = self.client.post(f"{_API}/initial/{sid}", data=big, headers=headers)
        self._flat(response, 413, "too_large")

    def test_doris_refusals_carry_their_codes(self):
        user, args = self.reviewer, ("uuid:x", uuid.uuid4(), uuid.uuid4(), "digest")
        kwargs = dict(
            certificate={}, doris_result={}, codedit_result={}, process_token="t", result_digest="d",
        )
        target = "app.services.reviewer_coding_service.verify_process_submission"
        cases = (
            (ProcessProofResultMismatch("x"), 409, "DORIS_PROCESS_MISMATCH"),
            (ProcessProofContextMismatch("x"), 409, "DORIS_PROCESS_EXPIRED"),
            (DorisCertificateError("bad certificate"), 422, "invalid_doris"),
        )
        for raised, status, code in cases:
            with self.subTest(code=code), patch(target, side_effect=raised):
                with self.assertRaises(ReviewerCodingError) as ctx:
                    verify_doris_submission(user, *args, **kwargs)
                self.assertEqual((ctx.exception.status_code, ctx.exception.code), (status, code))
        with patch(target, side_effect=ProcessProofCertificateChanged("x")), patch(
            "app.services.reviewer_coding_service.process_certificate",
            side_effect=DorisCertificateError("bad"),
        ):
            with self.assertRaises(ReviewerCodingError) as ctx:
                verify_doris_submission(user, *args, **kwargs)
            self.assertEqual((ctx.exception.status_code, ctx.exception.code), (422, "invalid_doris"))
        with patch(target, side_effect=ProcessProofCertificateChanged("x")), patch(
            "app.services.reviewer_coding_service.process_certificate",
            side_effect=WhoIcdApiUnavailable("down"),
        ):
            with self.assertRaises(ReviewerCodingError) as ctx:
                verify_doris_submission(user, *args, **kwargs)
            self.assertEqual((ctx.exception.status_code, ctx.exception.code), (503, "who_unavailable"))
        with patch.dict(self.app.config, {"DORIS_WHO_IMAGE_DIGEST": ""}):
            with self.assertRaises(ReviewerCodingError) as ctx:
                _who_image_digest()
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (503, "who_not_configured"))

    # -- flat errors: NQA and Social Autopsy ---------------------------------

    def _nqa_so(self):
        return (
            ("narrative-qa", {"length": 2, "pos_symptoms": 2, "neg_symptoms": 1,
                              "chronology": 1, "doc_review": 1, "comorbidity": 1}),
            ("social-autopsy", {"selected_options": []}),
        )

    def test_nqa_and_social_autopsy_errors_are_flat_and_coded(self):
        self._mode(masked=False, nqa=False, social=False)
        sid = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        other_pair = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS, form_id=self.OTHER_FORM_ID)
        reviewing = {"va_actiontype": "varesumereviewing"}
        for path, payload in self._nqa_so():
            with self.subTest(api=path):
                self._as(self.reviewer)
                url = f"{_VA}/{sid}/{path}"
                # Body is not an object.
                self._flat(self._post(url, json=[1]), 400, "invalid_request")
                self._flat(self._post(url, data="not json"), 400, "invalid_request")
                # Reviewer session: unknown case, outside review scope, no allocation.
                self._flat(self._post(f"{_VA}/uuid:missing/{path}", json=reviewing), 404, "not_found")
                self._flat(self._post(f"{_VA}/{other_pair}/{path}", json=reviewing), 403, "forbidden")
                self._flat(self._post(url, json=reviewing), 403, "no_allocation")
                # Coder session: no coding allocation; demo sessions only on demo projects.
                self._as(self.base_coder_user)
                self._flat(self._post(url, json=payload), 403, "no_allocation")
                self._flat(
                    self._post(url, json={**payload, "va_actiontype": "vademo_start_coding"}),
                    403, "forbidden",
                )

        # With an allocation the project switches decide.
        self._allocate(self.reviewer, sid, state=None)
        self._as(self.reviewer)
        body = self._flat(
            self._post(f"{_VA}/{sid}/narrative-qa", json={**reviewing, "length": 2}), 400, "invalid_request"
        )
        self.assertIn("not enabled", body["error"])
        self._flat(self._post(f"{_VA}/{sid}/social-autopsy", json=reviewing), 403, "forbidden")

    def test_nqa_and_social_autopsy_validation_errors_are_coded(self):
        self._mode(masked=False, nqa=True, social=True)
        sid = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self._allocate(self.reviewer, sid, state=None)
        self._as(self.reviewer)
        reviewing = {"va_actiontype": "varesumereviewing"}
        self._flat(
            self._post(f"{_VA}/{sid}/narrative-qa", json={**reviewing, "length": 9}), 400, "invalid_request"
        )
        url = f"{_VA}/{sid}/social-autopsy"
        self._flat(self._post(url, json={**reviewing, "selected_options": "x"}), 400, "invalid_request")
        self._flat(self._post(url, json={**reviewing, "selected_options": ["x"]}), 400, "invalid_request")
        self._flat(
            self._post(url, json={**reviewing, "selected_options": [{"delay_level": "?", "option_code": "?"}]}),
            400, "invalid_request",
        )
        missing = self._flat(self._post(url, json=reviewing), 400, "invalid_request")
        self.assertTrue(missing["missing_delay_levels"])

    # -- queue ---------------------------------------------------------------

    def _available(self, user=None, **params):
        self._as(user or self.reviewer)
        return self.client.get(f"{_API}/available", query_string=params)

    def _available_sids(self, user=None):
        return {case["va_sid"] for case in self._available(user, limit=200).get_json()["cases"]}

    def test_the_available_list_never_offers_what_start_refuses(self):
        """One case per reason start refuses, and one it accepts."""
        refused = {
            "not eligible": self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS),
            "ready for coding": self._case(WORKFLOW_READY_FOR_CODING),
            "language": self._case(language="Hindi"),
            "retired": self._case(retired=True),
            "other pair": self._case(form_id=self.OTHER_FORM_ID),
        }
        duplicate = self._case()
        db.session.add(VaDeathRegister(
            project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID, death_number=990002,
            unique_id=f"R3B2-{_RUN_SUFFIX}", deceased_name="Asha Devi", deceased_sex="female",
            date_of_death=date.today(), registered_by=self.base_coder_user.user_id,
            status="duplicate", va_sid=duplicate,
        ))
        refused["confirmed duplicate"] = duplicate
        with_final = self._case()
        submission = db.session.get(VaSubmissions, with_final)
        db.session.add(VaReviewerFinalAssessments(
            va_sid=with_final, payload_version_id=submission.active_payload_version_id,
            va_rfinassess_by=self.reviewer2.user_id, va_conclusive_cod="R99",
            va_rfinassess_status=VaStatuses.active,
        ))
        refused["reviewer final exists"] = with_final
        # An inactive project-site leaves the list, and start refuses it too.
        closed = self._case()
        pair = db.update(VaProjectSites).where(
            VaProjectSites.project_id == self.BASE_PROJECT_ID, VaProjectSites.site_id == self.BASE_SITE_ID
        )
        db.session.execute(pair.values(project_site_status=VaStatuses.deactive))
        db.session.commit()
        with self.app.test_request_context():
            rows, _more = reviewer_dashboard_service.list_available(
                self.reviewer, limit=200, offset=0
            )
        listed_while_inactive = {row["va_sid"] for row in rows}
        refused_while_inactive = False
        try:
            start_reviewer_coding(self.reviewer, closed)
        except ReviewerCodingError:
            refused_while_inactive = True
        db.session.execute(pair.values(project_site_status=VaStatuses.active))
        db.session.commit()
        self.assertNotIn(closed, listed_while_inactive)
        self.assertTrue(refused_while_inactive)

        ok = self._case()
        listed = self._available_sids()
        # Presence first: the one acceptable case is offered.
        self.assertIn(ok, listed)
        for reason, sid in refused.items():
            with self.subTest(reason=reason):
                self.assertNotIn(sid, listed)
                with self.assertRaises(ReviewerCodingError):
                    start_reviewer_coding(self.reviewer, sid)
        # And the converse: what is listed starts.
        self.assertEqual(start_reviewer_coding(self.reviewer, ok).va_sid, ok)
        self.assertNotIn(ok, self._available_sids(self.reviewer2))

    def test_available_rows_and_paging(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        sids = [self._case(submitted=base + timedelta(days=i)) for i in range(5)]
        listed = self._available().get_json()
        self.assertEqual(listed["limit"], 50)
        self.assertEqual(listed["offset"], 0)
        row = next(case for case in listed["cases"] if case["va_sid"] == sids[0])
        self.assertEqual(
            set(row),
            {"va_sid", "va_uniqueid_masked", "va_form_id", "project_id", "site_id", "va_submission_date",
             "va_data_collector", "va_deceased_age", "va_deceased_gender", "va_narration_language"},
        )
        self.assertEqual(row["va_narration_language"], "English")
        self.assertEqual(row["project_id"], self.BASE_PROJECT_ID)
        self.assertEqual(self._available(project_id=self.BASE_PROJECT_ID.lower()).get_json()["count"], 5)
        self.assertEqual(self._available(project_id="NOSUCH").get_json()["cases"], [])

        # Oldest submission first; pages are disjoint and cover the list.
        first = self._available(limit=2, offset=0)
        self.assertEqual(first.headers["Cache-Control"], "private, no-store, max-age=0")
        first = first.get_json()
        second = self._available(limit=2, offset=2).get_json()
        third = self._available(limit=2, offset=4).get_json()
        self.assertEqual([c["va_sid"] for c in first["cases"]], sids[:2])
        self.assertEqual([c["va_sid"] for c in second["cases"]], sids[2:4])
        self.assertEqual(
            (first["count"], first["has_more"], second["has_more"], third["count"], third["has_more"]),
            (2, True, True, 1, False),
        )
        self.assertEqual(self._available(limit=5).get_json()["has_more"], False)
        self.assertEqual(self._available(offset=500).get_json()["cases"], [])

    def test_list_paging_parameters_are_bounded(self):
        for route in ("available", "history"):
            self._as(self.reviewer)
            for params in (
                {"limit": 0}, {"limit": 201}, {"limit": "x"}, {"limit": "1.5"},
                {"offset": -1}, {"offset": "x"}, {"offset": 1_000_001}, {"project_id": "P" * 65},
            ):
                with self.subTest(route=route, **params):
                    response = self.client.get(f"{_API}/{route}", query_string=params)
                    self._flat(response, 400, "invalid_request")
            for params in ({"limit": 200}, {"limit": 1, "offset": 0}):
                self.assertEqual(self.client.get(f"{_API}/{route}", query_string=params).status_code, 200)

    def test_history_is_the_callers_own_active_finals_newest_first_in_view_scope(self):
        base = datetime(2026, 2, 1, tzinfo=UTC)

        def final(sid, user, minutes, status=VaStatuses.active):
            submission = db.session.get(VaSubmissions, sid)
            db.session.add(VaReviewerFinalAssessments(
                va_sid=sid, payload_version_id=submission.active_payload_version_id,
                va_rfinassess_by=user.user_id, va_conclusive_cod="R99",
                va_rfinassess_status=status,
                va_rfinassess_createdat=base + timedelta(minutes=minutes),
            ))

        sids = [self._case() for _ in range(3)]
        final(sids[0], self.reviewer, 0)
        final(sids[1], self.reviewer, 30)
        final(sids[2], self.reviewer, 10)
        theirs = self._case()
        final(theirs, self.reviewer2, 40)
        superseded = self._case()
        final(superseded, self.reviewer, 50, status=VaStatuses.deactive)
        out_of_scope = self._case(form_id=self.OTHER_FORM_ID)
        final(out_of_scope, self.reviewer, 60)
        db.session.commit()

        self._as(self.reviewer)
        response = self.client.get(f"{_API}/history")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
        body = response.get_json()
        self.assertEqual([r["va_sid"] for r in body["history"]], [sids[1], sids[2], sids[0]])
        self.assertEqual((body["count"], body["limit"], body["offset"], body["has_more"]), (3, 50, 0, False))
        # The column is naive UTC; the API says so with an explicit offset.
        self.assertEqual(body["history"][0]["va_reviewed_at"], "2026-02-01T00:30:00+00:00")
        for hidden in (theirs, superseded, out_of_scope):
            self.assertNotIn(hidden, [r["va_sid"] for r in body["history"]])
        page = self.client.get(f"{_API}/history", query_string={"limit": 2, "offset": 1}).get_json()
        self.assertEqual([r["va_sid"] for r in page["history"]], [sids[2], sids[0]])
        self.assertFalse(page["has_more"])
        page = self.client.get(f"{_API}/history", query_string={"limit": 2}).get_json()
        self.assertEqual((len(page["history"]), page["has_more"]), (2, True))
        scoped = self.client.get(f"{_API}/history", query_string={"project_id": self.BASE_PROJECT_ID.lower()})
        self.assertEqual(scoped.get_json()["count"], 3)
        other = self.client.get(f"{_API}/history", query_string={"project_id": "NOSUCH"})
        self.assertEqual(other.get_json()["history"], [])

    def test_stats_match_the_web_dashboard_counts(self):
        eligible = self._case()
        self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self._case(language="Hindi")  # in neither count
        submission = db.session.get(VaSubmissions, eligible)
        db.session.add(VaReviewerFinalAssessments(
            va_sid=eligible, payload_version_id=submission.active_payload_version_id,
            va_rfinassess_by=self.reviewer.user_id, va_conclusive_cod="R99",
            va_rfinassess_status=VaStatuses.active,
        ))
        db.session.commit()
        self._as(self.reviewer)
        captured = []

        def capture(_app, template, context, **_extra):
            captured.append((template.name, context))

        template_rendered.connect(capture, self.app)
        try:
            page = self.client.get("/reviewing/")
        finally:
            template_rendered.disconnect(capture, self.app)
        self.assertEqual(page.status_code, 200)
        context = next(ctx for name, ctx in captured if name == "va_frontpages/va_reviewer.html")

        response = self.client.get(f"{_API}/stats")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
        stats = response.get_json()
        self.assertEqual(stats["in_scope"], context["va_total_forms"])
        self.assertEqual(stats["completed"], context["va_forms_completed"])
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["available"], len(self._available_sids()))
        self.assertGreaterEqual(stats["in_scope"], stats["available"] + 1)
        self.assertIsNone(stats["allocation"])
        narrowed = self.client.get(f"{_API}/stats", query_string={"project_id": "NOSUCH"}).get_json()
        self.assertEqual((narrowed["in_scope"], narrowed["completed"], narrowed["available"]), (0, 0, 0))
        self.assertEqual(
            self.client.get(f"{_API}/stats", query_string={"project_id": self.BASE_PROJECT_ID}).get_json()[
                "in_scope"
            ],
            stats["in_scope"],
        )
        self._flat(
            self.client.get(f"{_API}/stats", query_string={"project_id": "P" * 65}), 400, "invalid_request"
        )

        self._allocate(self.reviewer, self._case())
        held = self.client.get(f"{_API}/stats").get_json()["allocation"]
        self.assertEqual(held, self.client.get(f"{_API}/allocation").get_json()["allocation"])
        self.assertTrue(held["va_sid"])

    def test_the_queue_routes_are_for_reviewers(self):
        for path in ("stats", "available", "history"):
            with self.subTest(path=path):
                self._as(self.base_coder_user)
                self.assertEqual(self.client.get(f"{_API}/{path}").status_code, 403)
        self._as(self.base_coder_user)
        self.assertEqual(self._post(f"{_API}/allocation/release").status_code, 403)

    # -- release -------------------------------------------------------------

    def _step_one(self, sid, user):
        submission = db.session.get(VaSubmissions, sid)
        row = VaReviewerInitialAssessments(
            va_sid=sid, payload_version_id=submission.active_payload_version_id,
            va_riniassess_by=user.user_id, va_immediate_cod="R99", va_antecedent_cod="R99",
        )
        db.session.add(row)
        return row

    def _session_work(self, sid, user):
        """Step 1, a review, NQA and Social Autopsy: everything a session saves."""
        submission = db.session.get(VaSubmissions, sid)
        payload_id = submission.active_payload_version_id
        step_one = self._step_one(sid, user)
        review = VaReviewerReview(
            va_sid=sid, va_rreview_by=user.user_id, payload_version_id=payload_id,
            va_rreview_narrpos="1", va_rreview_narrneg="1", va_rreview_narrchrono="1",
            va_rreview_narrdoc="1", va_rreview_narrcomorb="1", va_rreview="1",
        )
        nqa = VaNarrativeAssessment(
            va_sid=sid, va_nqa_by=user.user_id, payload_version_id=payload_id,
            va_nqa_length=1, va_nqa_pos_symptoms=1, va_nqa_neg_symptoms=0, va_nqa_chronology=0,
            va_nqa_doc_review=0, va_nqa_comorbidity=0, va_nqa_score=2, va_nqa_cannot_grade=False,
            va_nqa_status=VaStatuses.active,
        )
        social = VaSocialAutopsyAnalysis(
            va_sid=sid, va_saa_by=user.user_id, payload_version_id=payload_id,
            va_saa_status=VaStatuses.active,
        )
        db.session.add_all([review, nqa, social])
        db.session.commit()
        return step_one, review, nqa, social

    def test_release_clears_the_session_keeps_step_one_and_is_audited_under_the_reviewer(self):
        sid = self._case()
        self._as(self.reviewer)
        self.assertEqual(self._post(f"{_API}/allocation/{sid}").status_code, 201)
        step_one, review, nqa, social = self._session_work(sid, self.reviewer)
        # What must stay untouched: another reviewer's session and a coder's allocation.
        other_sid = self._case()
        other = self._allocate(self.reviewer2, other_sid)
        coder_sid = self._case(WORKFLOW_READY_FOR_CODING)
        coder_allocation = VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=coder_sid, va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding,
        )
        db.session.add(coder_allocation)
        db.session.commit()
        allocation_id = db.session.scalar(db.select(VaAllocations.va_allocation_id).where(
            VaAllocations.va_sid == sid, VaAllocations.va_allocated_to == self.reviewer.user_id,
        ))
        # Presence first: the session holds all of it.
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self.assertEqual(
            [r.va_nqa_status for r in (nqa,)] + [social.va_saa_status, step_one.va_riniassess_status],
            [VaStatuses.active] * 3,
        )

        response = self._post(f"{_API}/allocation/release")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json(), {"va_sid": sid, "workflow_state": WORKFLOW_REVIEWER_ELIGIBLE}
        )
        db.session.expire_all()
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_REVIEWER_ELIGIBLE)
        self.assertEqual(db.session.get(VaAllocations, allocation_id).va_allocation_status, VaStatuses.deactive)
        # Step 1 kept (owner decision); the rest cleared.
        self.assertEqual(db.session.get(type(step_one), step_one.va_riniassess_id).va_riniassess_status, VaStatuses.active)
        self.assertEqual(db.session.get(VaNarrativeAssessment, nqa.va_nqa_id).va_nqa_status, VaStatuses.deactive)
        self.assertEqual(db.session.get(VaSocialAutopsyAnalysis, social.va_saa_id).va_saa_status, VaStatuses.deactive)
        self.assertEqual(db.session.get(VaReviewerReview, review.va_rreview_id).va_rreview_status, VaStatuses.deactive)
        # Audit: the allocation row and the artifact rows are the reviewer's.
        released = db.session.scalar(db.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == sid,
            VaSubmissionsAuditlog.va_audit_action == "reviewer_allocation_released_by_reviewer",
        ))
        self.assertIsNotNone(released)
        self.assertEqual(
            (released.va_audit_byrole, released.va_audit_by, released.va_audit_entityid),
            ("reviewer", self.reviewer.user_id, allocation_id),
        )
        reverted = db.session.scalars(db.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == sid,
            VaSubmissionsAuditlog.va_audit_action.like("%reverted due to%release"),
        )).all()
        self.assertEqual(len(reverted), 3)
        self.assertEqual({(r.va_audit_byrole, r.va_audit_by) for r in reverted}, {("reviewer", self.reviewer.user_id)})
        # Neighbours untouched.
        self.assertEqual(db.session.get(VaAllocations, other.va_allocation_id).va_allocation_status, VaStatuses.active)
        self.assertEqual(get_submission_workflow_state(other_sid), WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self.assertEqual(
            db.session.get(VaAllocations, coder_allocation.va_allocation_id).va_allocation_status, VaStatuses.active
        )
        # A second release has nothing to release; the case is offered again.
        again = self._post(f"{_API}/allocation/release")
        self._flat(again, 409, "no_allocation")
        self.assertIn(sid, self._available_sids())

    def test_release_needs_csrf_for_a_cookie_session(self):
        sid = self._case()
        self._allocate(self.reviewer, sid)
        self._as(self.reviewer)
        refused = self.client.post(f"{_API}/allocation/release")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "csrf_failed"))
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

    def test_release_without_an_allocation_is_a_409(self):
        self._as(self.reviewer)
        self._flat(self._post(f"{_API}/allocation/release"), 409, "no_allocation")

    def test_a_case_no_longer_in_session_is_a_409_wrong_state_and_nothing_changes(self):
        sid = self._case()
        allocation = self._allocate(self.reviewer, sid, state=WORKFLOW_REVIEWER_ELIGIBLE)
        allocation_id = allocation.va_allocation_id
        self._as(self.reviewer)
        self._flat(self._post(f"{_API}/allocation/release"), 409, "wrong_state")
        db.session.expire_all()
        self.assertEqual(db.session.get(VaAllocations, allocation_id).va_allocation_status, VaStatuses.active)

    def test_a_reviewer_may_release_an_allocation_that_left_their_scope(self):
        sid = self._case(WORKFLOW_REVIEWER_CODING_IN_PROGRESS, form_id=self.OTHER_FORM_ID)
        self._allocate(self.reviewer, sid, state=None)
        self._as(self.reviewer)
        response = self._post(f"{_API}/allocation/release")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["workflow_state"], WORKFLOW_REVIEWER_ELIGIBLE)

    def test_the_timeout_release_stays_the_systems_and_keeps_step_one(self):
        sid = self._case()
        allocation = self._allocate(self.reviewer, sid)
        step_one, _review, nqa, _social = self._session_work(sid, self.reviewer)
        allocation.va_allocation_createdat = datetime.now(UTC) - timedelta(hours=2)
        db.session.commit()

        self.assertGreaterEqual(release_stale_reviewer_allocations(timeout_hours=1), 1)

        db.session.expire_all()
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_REVIEWER_ELIGIBLE)
        self.assertEqual(db.session.get(type(step_one), step_one.va_riniassess_id).va_riniassess_status, VaStatuses.active)
        self.assertEqual(db.session.get(VaNarrativeAssessment, nqa.va_nqa_id).va_nqa_status, VaStatuses.deactive)
        row = db.session.scalar(db.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == sid,
            VaSubmissionsAuditlog.va_audit_action == "reviewer_allocation_released_due_to_timeout",
        ))
        self.assertIsNotNone(row)
        self.assertEqual((row.va_audit_byrole, row.va_audit_by), ("vasystem", None))


_DEV = device_tests.DeviceApiTests.__dict__


class ReviewerReleaseBearerTests(BaseTestCase):
    """The release over a device bearer token: no CSRF header, no cookie.

    Device helpers are reused from tests/routes/test_device_api.py, as in
    tests/routes/test_coding_cod_api.py. The reviewer signs the device in
    through an interviewer grant of their own.
    """

    PROJECT_ID = "XL43R"
    SITE_ID = "XR43"
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}R3"

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
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
            odk_form_id="R3_BEARER_FORM", odk_project_id="45", form_type="WHO_2022_VA",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        cls._make_project(cls.PROJECT_ID, cls.SITE_ID, now)
        cls.reviewer = cls._make_user("r3b.bearer.reviewer@test.local", "BearerReviewer123")
        cls._grant(cls.reviewer, cls.PROJECT_ID)
        db.session.add(VaUserAccessGrants(
            user_id=cls.reviewer.user_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.BASE_PROJECT_ID,
            notes="r3b bearer", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}

    def test_a_bearer_token_releases_without_a_csrf_header(self):
        sid = f"uuid:r3b-bearer-{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now, va_odk_updatedat=now,
            va_data_collector="tester", va_instance_name=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English", va_deceased_age=42,
            va_deceased_gender="male", va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(submission, payload_data={}, source_updated_at=now)
        set_submission_workflow_state(
            sid, WORKFLOW_REVIEWER_CODING_IN_PROGRESS, reason="test_setup", by_role="vasystem"
        )
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=self.reviewer.user_id,
            va_allocation_for=VaAllocation.reviewing,
        ))
        db.session.commit()
        _device, tokens = self._session(email=self.reviewer.email, password="BearerReviewer123")

        # No credential at all: refused, nothing released.
        anonymous = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        # (a signed-out POST meets the CSRF check before the login gate)
        self.assertIn(anonymous.post(f"{_API}/allocation/release").status_code, (400, 401))
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

        response = self.client.post(f"{_API}/allocation/release", headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json(), {"va_sid": sid, "workflow_state": WORKFLOW_REVIEWER_ELIGIBLE}
        )
        db.session.expire_all()
        released = db.session.scalar(db.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == sid,
            VaSubmissionsAuditlog.va_audit_action == "reviewer_allocation_released_by_reviewer",
        ))
        self.assertEqual(released.va_audit_by, self.reviewer.user_id)
        again = self.client.post(f"{_API}/allocation/release", headers=self._bearer(tokens))
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "no_allocation"))
