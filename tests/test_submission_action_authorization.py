"""Who may start a recode, a review, or save coder Step 1 on one submission.

Audit 2026-10-02 (.tasks/digitva-0wc-access-matrix-current.md):
- digitva-ch8 (F1): recode start had no form, scope or ownership check.
- digitva-44d (F6): reviewer start, allocation and finalize skipped unit scope;
  ``reviewing.start`` was a state-changing GET.
- digitva-bfw (F9, F10): the ``vainitialasses``, ``vacoderreview`` and
  ``vareviewform`` POST partials wrote without holding an allocation.

Policy: docs/policy/access-control-model.md ("Authorization Rule"),
docs/policy/organization-model.md ("Coding scope").
"""
import uuid
from datetime import UTC, datetime, timedelta

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
    VaReviewerReview,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.coder_workflow_service import AllocationError, start_recode_allocation
from app.services.final_cod_authority_service import upsert_final_cod_authority
from app.services.reviewer_coding_service import ReviewerCodingError, start_reviewer_coding
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin

_SFX = uuid.uuid4().hex[:4].upper()
ICD10_VALUE = "I24 Other acute ischaemic heart diseases"


def _submission(sid, form_id, unit=None):
    now = datetime.now(UTC)
    submission = VaSubmissions(
        va_sid=sid, va_form_id=form_id, va_submission_date=now,
        va_odk_updatedat=now, va_data_collector="Collector",
        va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
        va_consent="yes", va_narration_language="English",
        va_deceased_age=42, va_deceased_gender="male",
        va_summary=[], va_catcount={}, va_category_list=[],
        org_unit_id=unit.org_unit_id if unit else None,
    )
    db.session.add(submission)
    db.session.flush()
    return submission


def _set_state(sid, state):
    set_submission_workflow_state(sid, state, reason="test_seed", by_role="vasystem")
    db.session.commit()


def _finalize(sid, coder, age=timedelta(minutes=5)):
    """Make *coder* the author of the authoritative final COD of *sid*."""
    final = VaFinalAssessments(
        va_sid=sid, va_finassess_by=coder.user_id, va_conclusive_cod="R99",
        va_finassess_status=VaStatuses.active,
        va_finassess_createdat=datetime.now(UTC) - age,
    )
    db.session.add(final)
    db.session.flush()
    upsert_final_cod_authority(
        sid, final, reason="final_cod_submitted", source_role="vacoder",
        updated_by=coder.user_id,
    )
    _set_state(sid, WORKFLOW_CODER_FINALIZED)


def _active_allocation(sid, purpose):
    return db.session.scalar(sa.select(VaAllocations.va_sid).where(
        VaAllocations.va_sid == sid,
        VaAllocations.va_allocation_for == purpose,
        VaAllocations.va_allocation_status == VaStatuses.active,
    ))


def _allocate(sid, user, purpose):
    db.session.add(VaAllocations(
        va_allocation_id=uuid.uuid4(), va_sid=sid,
        va_allocated_to=user.user_id, va_allocation_for=purpose,
        va_allocation_status=VaStatuses.active,
    ))
    db.session.commit()


class ConventionalProjectMixin:
    """A project with no organization tree: one site, one form, a second site."""

    BASE_PROJECT_ID = f"AZ{_SFX}"
    BASE_SITE_ID = f"Z{_SFX[:3]}"
    OTHER_SITE_ID = f"Y{_SFX[:3]}"
    FORM_ID = f"AZ{_SFX}FORM01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID, odk_form_id="AUTHZ_FORM",
            odk_project_id="1", form_type="WHO_2022_VA",
            form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.OTHER_SITE_ID, site_abbr=cls.OTHER_SITE_ID,
            site_name="Other Site", site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.BASE_PROJECT_ID, site_id=cls.OTHER_SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        cls.home_pair = cls._pair(cls.BASE_SITE_ID)
        cls.other_pair = cls._pair(cls.OTHER_SITE_ID)
        db.session.commit()

    @classmethod
    def _pair(cls, site_id):
        return db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == cls.BASE_PROJECT_ID,
            VaProjectSites.site_id == site_id,
        ))

    @classmethod
    def _user(cls, name, role, project_site_id):
        user = cls._make_user(f"{name}.{_SFX.lower()}@test.local", "AuthzUser123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user


# ---------------------------------------------------------------------------
# digitva-ch8: recode start
# ---------------------------------------------------------------------------


class RecodeStartAuthorizationTests(ConventionalProjectMixin, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls._user("recode.owner", VaAccessRoles.coder, cls.home_pair)
        cls.peer = cls._user("recode.peer", VaAccessRoles.coder, cls.home_pair)
        cls.moved = cls._user("recode.moved", VaAccessRoles.coder, cls.other_pair)

    def _finalized_by(self, coder, age=timedelta(minutes=5)):
        sid = f"uuid:authz-recode-{uuid.uuid4()}"
        _submission(sid, self.FORM_ID)
        _finalize(sid, coder, age=age)
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_CODER_FINALIZED)
        self.assertIsNone(_active_allocation(sid, VaAllocation.coding))
        return sid

    def test_another_coder_of_the_same_form_is_refused(self):
        sid = self._finalized_by(self.owner)
        self.assertTrue(self.peer.is_coder(self.FORM_ID))

        with self.assertRaises(AllocationError) as ctx:
            start_recode_allocation(self.peer, sid)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsNone(_active_allocation(sid, VaAllocation.coding))
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_CODER_FINALIZED)

    def test_the_coder_who_now_codes_another_site_is_refused(self):
        # Coded it, but the grant is now on another site of the project.
        sid = self._finalized_by(self.moved)
        self.assertFalse(self.moved.is_coder(self.FORM_ID))

        with self.assertRaises(AllocationError):
            start_recode_allocation(self.moved, sid)

        self.assertIsNone(_active_allocation(sid, VaAllocation.coding))

    def test_the_owner_may_recode_within_the_window(self):
        sid = self._finalized_by(self.owner)

        result = start_recode_allocation(self.owner, sid)

        self.assertEqual(result.va_sid, sid)
        self.assertEqual(_active_allocation(sid, VaAllocation.coding), sid)

    def test_the_owner_is_refused_after_the_window(self):
        sid = self._finalized_by(self.owner, age=timedelta(hours=25))

        with self.assertRaises(AllocationError):
            start_recode_allocation(self.owner, sid)

        self.assertIsNone(_active_allocation(sid, VaAllocation.coding))

    def test_both_recode_routes_refuse_a_non_owner(self):
        sid = self._finalized_by(self.owner)
        self._login(str(self.peer.user_id))

        api = self.client.post(
            f"/api/v1/coding/recode/{sid}", headers=self._csrf_headers()
        )
        html = self.client.post(f"/coding/recode/{sid}", headers=self._csrf_headers())

        self.assertEqual(api.status_code, 403)
        self.assertEqual(html.status_code, 403)
        self.assertIsNone(_active_allocation(sid, VaAllocation.coding))


class RecodeStartOrgScopeTests(CodingScopeFixtureMixin, BaseTestCase):
    def test_the_owner_is_refused_once_the_submission_leaves_their_unit(self):
        _, _, _, phc_a, phc_b = self._tree()
        self._grant(phc_a)
        # Keeps the form granted, so the refusal is the unit check's.
        self._submission("csc-anchor", unit=phc_a)
        submission = self._submission("csc-recode", unit=phc_a)
        _finalize("csc-recode", self.base_coder_user)
        submission.org_unit_id = phc_b.org_unit_id
        db.session.commit()
        self.assertTrue(self.base_coder_user.is_coder(self.FORM_ID))

        with self.assertRaises(AllocationError) as ctx:
            start_recode_allocation(self.base_coder_user, "csc-recode")

        self.assertIn("outside your coding scope", ctx.exception.message)
        self.assertIsNone(_active_allocation("csc-recode", VaAllocation.coding))

    def test_the_owner_inside_their_unit_may_recode(self):
        _, _, _, phc_a, _ = self._tree()
        self._grant(phc_a)
        self._submission("csc-recode-in", unit=phc_a)
        _finalize("csc-recode-in", self.base_coder_user)

        start_recode_allocation(self.base_coder_user, "csc-recode-in")

        self.assertEqual(
            _active_allocation("csc-recode-in", VaAllocation.coding), "csc-recode-in"
        )


# ---------------------------------------------------------------------------
# digitva-44d: reviewer unit scope
# ---------------------------------------------------------------------------


class ReviewerUnitScopeTests(CodingScopeFixtureMixin, BaseTestCase):
    def _setup_units(self):
        _, _, _, phc_a, phc_b = self._tree()
        self._grant(phc_a, role=VaAccessRoles.reviewer)
        self._submission("csc-rev-mine", unit=phc_a)
        self._submission("csc-rev-sibling", unit=phc_b)
        _set_state("csc-rev-mine", WORKFLOW_REVIEWER_ELIGIBLE)
        _set_state("csc-rev-sibling", WORKFLOW_REVIEWER_ELIGIBLE)
        user = self.base_coder_user
        self.assertTrue(user.is_reviewer(self.FORM_ID))
        self._login(str(user.user_id))
        return user

    def test_a_unit_reviewer_cannot_start_a_review_in_a_sibling_unit(self):
        user = self._setup_units()

        with self.assertRaises(ReviewerCodingError) as ctx:
            start_reviewer_coding(user, "csc-rev-sibling")
        self.assertEqual(ctx.exception.status_code, 403)

        page = self.client.post(
            "/reviewing/start/csc-rev-sibling", headers=self._csrf_headers()
        )
        api = self.client.post(
            "/api/v1/reviewing/allocation/csc-rev-sibling",
            headers=self._csrf_headers(),
        )
        self.assertEqual(page.status_code, 403)
        self.assertEqual(api.status_code, 403)
        self.assertIsNone(_active_allocation("csc-rev-sibling", VaAllocation.reviewing))
        self.assertEqual(
            get_submission_workflow_state("csc-rev-sibling"), WORKFLOW_REVIEWER_ELIGIBLE
        )

    def test_a_unit_reviewer_cannot_finalize_a_sibling_unit_review(self):
        user = self._setup_units()
        # An allocation obtained before the scope check (or before re-routing).
        _set_state("csc-rev-sibling", WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        _allocate("csc-rev-sibling", user, VaAllocation.reviewing)

        final = self.client.post(
            "/api/v1/reviewing/finalize/csc-rev-sibling",
            json={"conclusive_cod": ICD10_VALUE},
            headers=self._csrf_headers(),
        )
        initial = self.client.post(
            "/api/v1/reviewing/initial/csc-rev-sibling",
            json={"immediate_cod": ICD10_VALUE, "antecedent_cod": ICD10_VALUE},
            headers=self._csrf_headers(),
        )

        self.assertEqual(final.status_code, 403)
        self.assertEqual(initial.status_code, 403)
        self.assertEqual(
            get_submission_workflow_state("csc-rev-sibling"),
            WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
        )

    def test_a_unit_reviewer_may_start_a_review_in_their_unit(self):
        self._setup_units()

        response = self.client.post(
            "/api/v1/reviewing/allocation/csc-rev-mine", headers=self._csrf_headers()
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            _active_allocation("csc-rev-mine", VaAllocation.reviewing), "csc-rev-mine"
        )
        self.assertEqual(
            get_submission_workflow_state("csc-rev-mine"),
            WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
        )


# ---------------------------------------------------------------------------
# digitva-bfw: coder Step 1 and sibling POST partials
# ---------------------------------------------------------------------------


class StepOneSaveAuthorizationTests(ConventionalProjectMixin, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        project.masked_cod_required = True
        project.icd_classification = "icd10"
        project.cod_entry_mode = "simple"
        project.narrative_qa_enabled = False
        db.session.merge(MasIcd1020192(
            code="I24", title="Other acute ischaemic heart diseases",
            node_type="category", semantic_level="three_character", sort_order=1,
            chapter_code="IX", chapter_title="Diseases of the circulatory system",
            block_code="I20-I25", block_title="Ischaemic heart diseases",
            three_character_code="I24",
            three_character_title="Other acute ischaemic heart diseases",
            has_children=False, is_leaf=True, is_three_character_code=True,
            is_detailed_code=False, is_coding_selectable=True,
            sex_selectable="both", age_group_selectable="all",
            policy_status="unreviewed", source_version="ICD-10-2019",
            source_path="test", is_active=True, created_at=now, updated_at=now,
        ))
        cls.coder = cls._user("step1.coder", VaAccessRoles.coder, cls.home_pair)
        cls.reviewer = cls._user("step1.reviewer", VaAccessRoles.reviewer, cls.home_pair)

    def _ready(self, state=WORKFLOW_READY_FOR_CODING):
        sid = f"uuid:authz-step1-{uuid.uuid4()}"
        submission = _submission(sid, self.FORM_ID)
        ensure_active_payload_version(
            submission, payload_data={}, source_updated_at=submission.va_odk_updatedat,
        )
        _set_state(sid, state)
        self.assertEqual(get_submission_workflow_state(sid), state)
        return sid

    def _post(self, sid, partial, query, data):
        return self.client.post(
            f"/vaform/{sid}/{partial}?{query}",
            data=data,
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

    def _post_step1(self, sid, query):
        return self._post(sid, "vainitialasses", query, {
            "va_immediate_cod": ICD10_VALUE,
            "va_antecedent_cod": ICD10_VALUE,
            "va_save_assessment": "1",
        })

    def _initial_rows(self, sid):
        return db.session.scalars(sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == sid
        )).all()

    def test_a_reviewer_cannot_save_step1_on_a_pool_submission(self):
        sid = self._ready()
        self._login(str(self.reviewer.user_id))

        response = self._post_step1(sid, "action=vareview&actiontype=vaview")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._initial_rows(sid), [])
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_READY_FOR_CODING)

    def test_a_coder_without_the_allocation_cannot_save_step1(self):
        # The old "session expired" save: no allocation, case back in the pool.
        sid = self._ready()
        self._login(str(self.coder.user_id))

        response = self._post_step1(sid, "action=vacode&actiontype=vastartcoding")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._initial_rows(sid), [])
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_READY_FOR_CODING)

    def test_the_allocated_coder_saves_step1(self):
        sid = self._ready(WORKFLOW_CODING_IN_PROGRESS)
        _allocate(sid, self.coder, VaAllocation.coding)
        self._login(str(self.coder.user_id))

        response = self._post_step1(sid, "action=vacode&actiontype=vastartcoding")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(self._initial_rows(sid)), 1)
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_CODER_STEP1_SAVED)

    def test_not_codeable_needs_the_coding_allocation(self):
        sid = self._ready()
        self._login(str(self.reviewer.user_id))

        response = self._post(
            sid, "vacoderreview", "action=vareview&actiontype=vaview",
            {"va_creview_reason": "no_info"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(db.session.scalar(
            sa.select(VaCoderReview.va_sid).where(VaCoderReview.va_sid == sid)
        ))
        self.assertEqual(get_submission_workflow_state(sid), WORKFLOW_READY_FOR_CODING)

    def test_reviewer_review_form_needs_the_reviewing_allocation(self):
        sid = self._ready(WORKFLOW_REVIEWER_ELIGIBLE)
        self._login(str(self.reviewer.user_id))

        response = self._post(
            sid, "vareviewform", "action=vareview&actiontype=vaview",
            {
                "va_rreview_narrpos": "3_5_symptoms",
                "va_rreview_narrneg": "present",
                "va_rreview_narrchrono": "can_be_established",
                "va_rreview_narrdoc": "provides_data",
                "va_rreview_narrcomorb": "present",
                "va_rreview": "accepted",
                "va_rreview_fail": "",
                "va_rreview_remark": "ok",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(db.session.scalar(
            sa.select(VaReviewerReview.va_sid).where(VaReviewerReview.va_sid == sid)
        ))
