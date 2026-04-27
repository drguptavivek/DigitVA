from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    MasIcd1020192,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from tests.base import BaseTestCase


class TestIcd10CodingApi(BaseTestCase):
    FORM_ID = "BASE01BS0101"
    SID = "uuid:test-icd10-coding-base01bs0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        research_project = db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID)
        if research_project is None:
            db.session.add(
                VaResearchProjects(
                    project_id=cls.BASE_PROJECT_ID,
                    project_code=cls.BASE_PROJECT_ID,
                    project_name="Base Test Project",
                    project_nickname="BaseTest",
                    project_status=VaStatuses.active,
                    project_registered_at=datetime.now(UTC),
                    project_updated_at=datetime.now(UTC),
                )
            )
            db.session.flush()

        site = db.session.get(VaSites, cls.BASE_SITE_ID)
        if site is None:
            db.session.add(
                VaSites(
                    site_id=cls.BASE_SITE_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_name="Base Test Site",
                    site_abbr=cls.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=datetime.now(UTC),
                    site_updated_at=datetime.now(UTC),
                )
            )
            db.session.flush()

        form = db.session.get(VaForms, cls.FORM_ID)
        if form is None:
            db.session.add(
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_id=cls.BASE_SITE_ID,
                    odk_form_id="ICD_FORM",
                    odk_project_id="1",
                    form_type="WHO 2022 VA",
                    form_status=VaStatuses.active,
                    form_registered_at=datetime.now(UTC),
                    form_updated_at=datetime.now(UTC),
                )
            )
            db.session.flush()
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(VaAllocations).where(VaAllocations.va_sid == self.SID))
        db.session.execute(sa.delete(VaSubmissions).where(VaSubmissions.va_sid == self.SID))
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.flush()

        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=self.SID,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="ICD-CODING-1",
            va_uniqueid_real="ICD-CODING-1",
            va_uniqueid_masked="ICD-CODING-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_age_normalized_days=Decimal("15340"),
            va_deceased_age_normalized_years=Decimal("42"),
            va_deceased_gender="female",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.add(
            VaAllocations(
                va_sid=self.SID,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
                va_allocation_createdat=now,
                va_allocation_updatedat=now,
            )
        )
        db.session.add_all(
            [
                MasIcd1020192(
                    code="A00",
                    title="Cholera",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=1,
                    parent_code="A00-A09",
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    block_code="A00-A09",
                    block_title="Intestinal infectious diseases",
                    three_character_code="A00",
                    three_character_title="Cholera",
                    has_children=True,
                    is_leaf=False,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    is_coding_selectable=True,
                    sex_selectable="both",
                    age_group_selectable="all",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="A00.0",
                    title="Cholera due to Vibrio cholerae 01, biovar cholerae",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=2,
                    parent_code="A00",
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    block_code="A00-A09",
                    block_title="Intestinal infectious diseases",
                    three_character_code="A00",
                    three_character_title="Cholera",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=False,
                    is_detailed_code=True,
                    is_coding_selectable=True,
                    sex_selectable="female",
                    age_group_selectable="adult",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="B50",
                    title="Plasmodium falciparum malaria",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=3,
                    parent_code="B50-B54",
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    block_code="B50-B54",
                    block_title="Protozoal diseases",
                    three_character_code="B50",
                    three_character_title="Plasmodium falciparum malaria",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    is_coding_selectable=True,
                    sex_selectable="male",
                    age_group_selectable="adult",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="P07",
                    title="Disorders related to short gestation and low birth weight",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=4,
                    parent_code="P05-P08",
                    chapter_code="XVI",
                    chapter_title="Certain conditions originating in the perinatal period",
                    block_code="P05-P08",
                    block_title="Disorders of newborn related to gestation",
                    three_character_code="P07",
                    three_character_title="Disorders related to short gestation and low birth weight",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    is_coding_selectable=True,
                    sex_selectable="both",
                    age_group_selectable="neonate",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="R95",
                    title="Sudden infant death syndrome",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=5,
                    parent_code="R95-R99",
                    chapter_code="XVIII",
                    chapter_title="Symptoms, signs and abnormal clinical findings",
                    block_code="R95-R99",
                    block_title="Ill-defined and unknown cause of mortality",
                    three_character_code="R95",
                    three_character_title="Sudden infant death syndrome",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    is_coding_selectable=True,
                    sex_selectable="both",
                    age_group_selectable="infant",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="C51",
                    title="Malignant neoplasm of vulva",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=6,
                    parent_code="C51-C58",
                    chapter_code="II",
                    chapter_title="Neoplasms",
                    block_code="C51-C58",
                    block_title="Malignant neoplasms of female genital organs",
                    three_character_code="C51",
                    three_character_title="Malignant neoplasm of vulva",
                    has_children=True,
                    is_leaf=False,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    is_coding_selectable=True,
                    sex_selectable="female",
                    age_group_selectable="all",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="C51.0",
                    title="Labium majus",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=7,
                    parent_code="C51",
                    chapter_code="II",
                    chapter_title="Neoplasms",
                    block_code="C51-C58",
                    block_title="Malignant neoplasms of female genital organs",
                    three_character_code="C51",
                    three_character_title="Malignant neoplasm of vulva",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=False,
                    is_detailed_code=True,
                    is_coding_selectable=False,
                    sex_selectable=None,
                    age_group_selectable=None,
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="C60",
                    title="Malignant neoplasm of penis",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=8,
                    parent_code="C60-C63",
                    chapter_code="II",
                    chapter_title="Neoplasms",
                    block_code="C60-C63",
                    block_title="Malignant neoplasms of male genital organs",
                    three_character_code="C60",
                    three_character_title="Malignant neoplasm of penis",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    is_coding_selectable=True,
                    sex_selectable="male",
                    age_group_selectable="all",
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.session.commit()

    def _set_submission_demographics(
        self,
        *,
        normalized_days: Decimal | None = None,
        normalized_years: Decimal | None = None,
        age_years: int | None = None,
        gender: str | None = None,
    ):
        submission = db.session.get(VaSubmissions, self.SID)
        if normalized_days is not None:
            submission.va_deceased_age_normalized_days = normalized_days
        if normalized_years is not None:
            submission.va_deceased_age_normalized_years = normalized_years
        if age_years is not None:
            submission.va_deceased_age = age_years
        if gender is not None:
            submission.va_deceased_gender = gender
        db.session.commit()

    def test_coder_can_search_available_icd_codes_for_submission_context(self):
        self._login(self.base_coder_id)

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=A0")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["A00", "A00.0"])

    def test_coding_search_applies_submission_age_and_sex_filters(self):
        self._login(self.base_coder_id)

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=B5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_coding_search_allows_neonate_code_before_28_day_boundary(self):
        self._login(self.base_coder_id)
        self._set_submission_demographics(
            normalized_days=Decimal("27.999"),
            normalized_years=Decimal("0.08"),
            age_years=0,
        )

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=P0")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["P07"])

    def test_coding_search_excludes_neonate_code_at_infant_boundary(self):
        self._login(self.base_coder_id)
        self._set_submission_demographics(
            normalized_days=Decimal("28"),
            normalized_years=Decimal("1"),
            age_years=1,
        )

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=P0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_coding_search_allows_infant_only_code_for_infant_submission(self):
        self._login(self.base_coder_id)
        self._set_submission_demographics(
            normalized_days=Decimal("28"),
            normalized_years=Decimal("0.08"),
            age_years=0,
        )

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=R95")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["R95"])

    def test_coding_search_excludes_infant_only_code_for_adult_submission(self):
        self._login(self.base_coder_id)

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=R95")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_coding_search_uses_sex_filter_but_keeps_both_codes(self):
        self._login(self.base_coder_id)
        self._set_submission_demographics(gender="Male")

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=A0")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["A00"])

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=B5")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["B50"])

    def test_coding_search_applies_sex_specific_neoplasm_rules(self):
        self._login(self.base_coder_id)

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=C51")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["C51"])

        self._set_submission_demographics(gender="Male")
        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=C51")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=C60")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["C60"])

    def test_coding_detailed_children_exclude_disabled_who_granularity_children(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"/api/v1/icd10/2019-2/coding-children/{self.SID}?parent_code=C51"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["parent_code"], "C51")
        self.assertEqual(payload["children"], [])

    def test_coding_search_treats_submission_under_12_years_as_child(self):
        self._login(self.base_coder_id)
        self._set_submission_demographics(
            normalized_days=Decimal("3650"),
            normalized_years=Decimal("10"),
            age_years=10,
        )

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=A0")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["A00"])

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=B5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=P0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_coder_can_fetch_available_detailed_children(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"/api/v1/icd10/2019-2/coding-children/{self.SID}?parent_code=A00"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["parent_code"], "A00")
        self.assertEqual([row["icd_code"] for row in payload["children"]], ["A00.0"])

    def test_coding_helpers_require_active_coding_allocation(self):
        self._login(self.base_coder_id)
        db.session.execute(sa.delete(VaAllocations).where(VaAllocations.va_sid == self.SID))
        db.session.commit()

        response = self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.SID}?q=A0")

        self.assertEqual(response.status_code, 403)
        self.assertIn("Active coding allocation required.", response.get_json()["error"])
