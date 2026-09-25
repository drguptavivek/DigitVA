from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    CodSearchTelemetry,
    MasIcd11Mms,
    MasIcd1020192,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
)
from tests.base import BaseTestCase


class TestCodingSearchDemoApi(BaseTestCase):
    URL = "/api/v1/coding-search-demo/search"
    FORM_ID = "BASE01BS01CD"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # is_coder() only resolves through a VaForms row under the granted
        # project/site (app/models/va_users.py::_get_granted_va_forms); the
        # base coder grant alone is not enough. VaForms FKs to VaResearchProjects
        # / VaSites, distinct from the VaProjectMaster / VaSiteMaster rows
        # BaseTestCase._seed_base_fixtures already creates for BASE_PROJECT_ID.
        now = datetime.now(UTC)
        if db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID) is None:
            db.session.add(
                VaResearchProjects(
                    project_id=cls.BASE_PROJECT_ID,
                    project_code=cls.BASE_PROJECT_ID,
                    project_name="Base Test Project",
                    project_nickname="BaseTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaSites, cls.BASE_SITE_ID) is None:
            db.session.add(
                VaSites(
                    site_id=cls.BASE_SITE_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_name="Base Test Site",
                    site_abbr=cls.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_id=cls.BASE_SITE_ID,
                    odk_form_id="CODING_SEARCH_DEMO_FORM",
                    odk_project_id="1",
                    form_type="WHO 2022 VA",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.execute(sa.delete(MasIcd11Mms))
        db.session.flush()

        now = datetime.now(UTC)
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
                    has_children=False,
                    is_leaf=True,
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
                    code="P07",
                    title="Disorders related to short gestation and low birth weight",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=2,
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
                MasIcd11Mms(
                    release="2026-01",
                    linearization_uri="lin:1A00",
                    foundation_uri="f:1A00",
                    code="1A00",
                    title="Cholera",
                    class_kind="category",
                    depth_in_kind=1,
                    chapter_no="01",
                    is_residual=False,
                    is_leaf=True,
                    sort_order=1,
                    parent_foundation_uri="f:chapter1",
                    parent_linearization_uri="lin:chapter1",
                    is_coding_selectable=True,
                    sex_selectable="both",
                    age_group_selectable="all",
                    source_version="ICD-11-MMS-2026-01",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.session.commit()

    def _telemetry_count(self):
        return db.session.scalar(sa.select(sa.func.count()).select_from(CodSearchTelemetry))

    # ── Auth ──────────────────────────────────────────────────────────────

    def test_anonymous_gets_401(self):
        response = self.client.get(
            f"{self.URL}?classification=icd10&q=A0&age_group=adult&sex=female"
        )
        self.assertEqual(response.status_code, 401)

    def test_role_without_access_gets_403(self):
        self._login(self.base_project_pi_id)

        response = self.client.get(
            f"{self.URL}?classification=icd10&q=A0&age_group=adult&sex=female"
        )

        self.assertEqual(response.status_code, 403)

    # ── Validation ───────────────────────────────────────────────────────

    def test_unknown_classification_is_rejected(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"{self.URL}?classification=icd9&q=A0&age_group=adult&sex=female"
        )

        self.assertEqual(response.status_code, 400)

    def test_unknown_age_group_is_rejected(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"{self.URL}?classification=icd10&q=A0&age_group=toddler&sex=female"
        )

        self.assertEqual(response.status_code, 400)

    def test_unknown_sex_is_rejected(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"{self.URL}?classification=icd10&q=A0&age_group=adult&sex=unknown"
        )

        self.assertEqual(response.status_code, 400)

    # ── Results ──────────────────────────────────────────────────────────

    def test_icd10_search_returns_selectable_codes_with_tier(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"{self.URL}?classification=icd10&q=A0&age_group=adult&sex=female"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["A00"])
        self.assertIn("tier", payload[0])

    def test_icd11_search_returns_selectable_codes_with_tier(self):
        self._login(self.base_coder_id)

        response = self.client.get(
            f"{self.URL}?classification=icd11&q=Cholera&age_group=adult&sex=female"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["icd_code"] for row in payload], ["1A00"])
        self.assertIn("tier", payload[0])

    def test_age_group_policy_applies_neonate_code_present_before_absent(self):
        self._login(self.base_coder_id)

        # Present for neonate.
        response = self.client.get(
            f"{self.URL}?classification=icd10&q=P0&age_group=neonate&sex=female"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["icd_code"] for row in response.get_json()], ["P07"])

        # Absent for adult.
        response = self.client.get(
            f"{self.URL}?classification=icd10&q=P0&age_group=adult&sex=female"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_search_is_not_recorded_in_telemetry(self):
        self._login(self.base_coder_id)
        before = self._telemetry_count()

        response = self.client.get(
            f"{self.URL}?classification=icd10&q=A0&age_group=adult&sex=female"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Search-Id", response.headers)
        self.assertEqual(self._telemetry_count(), before)

    def test_va_sid_coding_search_path_is_unchanged(self):
        # Regression guard: the refactor of search_icd10_2019_2_coding_choices
        # must not alter the real coding-screen path. Full coverage lives in
        # tests/routes/test_icd10_coding_api.py; this is a smoke check that
        # the split still wires va_sid -> submission context correctly.
        from app.services.icd10_2019_2_service import get_icd10_2019_2_coding_context

        self.assertIsNone(get_icd10_2019_2_coding_context("uuid:does-not-exist"))
