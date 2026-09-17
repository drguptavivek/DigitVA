"""Tests for classification-aware ICD coding value helpers.

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/services/test_icd_coding_value.py -v
"""
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.services.icd_coding_value import (
    ICD_CLASSIFICATIONS,
    extract_icd_code,
    get_icd_classification_for_submission,
)
from tests.base import BaseTestCase


class TestExtractIcdCode(BaseTestCase):
    def test_icd10_extracts_letter_digit_digit_optional_decimal(self):
        self.assertEqual(extract_icd_code("A00 Cholera", "icd10"), "A00")
        self.assertEqual(extract_icd_code("a00.1 Cholera", "icd10"), "A00.1")
        self.assertIsNone(extract_icd_code("1A00 Cholera", "icd10"))
        self.assertIsNone(extract_icd_code(None, "icd10"))
        self.assertIsNone(extract_icd_code("", "icd10"))

    def test_icd11_extracts_stem_codes(self):
        self.assertEqual(extract_icd_code("1A00 Cholera", "icd11"), "1A00")
        self.assertEqual(extract_icd_code("BA00.1 Something", "icd11"), "BA00.1")
        self.assertEqual(extract_icd_code("2C25.Z Unspecified", "icd11"), "2C25.Z")
        self.assertIsNone(extract_icd_code("A00 Cholera", "icd11"))
        self.assertIsNone(extract_icd_code(None, "icd11"))

    def test_unknown_classification_raises(self):
        with self.assertRaises(ValueError):
            extract_icd_code("A00 Cholera", "icd9")

    def test_icd_classifications_constant(self):
        self.assertEqual(ICD_CLASSIFICATIONS, ("icd10", "icd11"))


class TestGetIcdClassificationForSubmission(BaseTestCase):
    FORM_ID = "BASE01BS0102"
    SID = "uuid:test-icd-classification-base01bs0102"

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(VaSubmissions).where(VaSubmissions.va_sid == self.SID))
        db.session.execute(sa.delete(VaForms).where(VaForms.form_id == self.FORM_ID))
        db.session.execute(
            sa.delete(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.BASE_PROJECT_ID,
                MapProjectSiteOdk.site_id == self.BASE_SITE_ID,
            )
        )
        db.session.flush()

        now = datetime.now(UTC)
        # VaForms.project_id/site_id are FKs into the legacy va_research_projects
        # and va_sites tables, not va_project_master/va_site_master.
        if db.session.get(VaResearchProjects, self.BASE_PROJECT_ID) is None:
            db.session.add(
                VaResearchProjects(
                    project_id=self.BASE_PROJECT_ID,
                    project_code=self.BASE_PROJECT_ID,
                    project_name="Base Test Project",
                    project_nickname="BaseTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaSites, self.BASE_SITE_ID) is None:
            db.session.add(
                VaSites(
                    site_id=self.BASE_SITE_ID,
                    project_id=self.BASE_PROJECT_ID,
                    site_name="Base Test Site",
                    site_abbr=self.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
        db.session.add(
            VaForms(
                form_id=self.FORM_ID,
                project_id=self.BASE_PROJECT_ID,
                site_id=self.BASE_SITE_ID,
                odk_form_id="ICD_CLASSIFICATION_FORM",
                odk_project_id="1",
                form_type="WHO 2022 VA",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaSubmissions(
                va_sid=self.SID,
                va_form_id=self.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="tester",
                va_odk_reviewstate=None,
                va_instance_name="ICD-CLASSIFICATION-1",
                va_uniqueid_real="ICD-CLASSIFICATION-1",
                va_uniqueid_masked="ICD-CLASSIFICATION-1",
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
        )
        db.session.flush()

    def test_defaults_to_icd10_when_unmapped(self):
        self.assertEqual(get_icd_classification_for_submission(self.SID), "icd10")

    def test_defaults_to_icd10_for_unknown_submission(self):
        self.assertEqual(get_icd_classification_for_submission("uuid:does-not-exist"), "icd10")

    def test_resolves_icd11_from_project_site_mapping(self):
        db.session.add(
            MapProjectSiteOdk(
                project_id=self.BASE_PROJECT_ID,
                site_id=self.BASE_SITE_ID,
                odk_project_id=1,
                odk_form_id="ICD_CLASSIFICATION_FORM",
                icd_classification="icd11",
            )
        )
        db.session.flush()

        self.assertEqual(get_icd_classification_for_submission(self.SID), "icd11")
