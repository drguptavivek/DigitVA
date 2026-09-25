"""Tests for classification-aware ICD coding value helpers.

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/services/test_icd_coding_value.py -v
"""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    MasIcd11Mms,
    MasIcd1020192,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.icd_coding_value import (
    ICD_CLASSIFICATIONS,
    PROJECT_ICD_CLASSIFICATIONS,
    build_icd11_provenance_for_values,
    classification_of_value,
    extract_icd11_code_expression,
    extract_icd_code,
    get_icd_classification_for_submission,
    has_icd11_cluster_marker,
    validate_coding_value_for_submission,
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

    def test_icd11_extracts_complete_code_expression(self):
        expression = "1G40.0&XN8Q/1G41"
        self.assertEqual(
            extract_icd11_code_expression(f"{expression} Post-coordinated sepsis"),
            expression,
        )
        self.assertEqual(extract_icd11_code_expression("1A00 Cholera"), "1A00")
        self.assertIsNone(extract_icd11_code_expression("1A00&"))
        self.assertTrue(has_icd11_cluster_marker(f"{expression} title"))
        self.assertFalse(has_icd11_cluster_marker("1A00 Cholera"))

    def test_unknown_classification_raises(self):
        with self.assertRaises(ValueError):
            extract_icd_code("A00 Cholera", "icd9")

    def test_icd_classifications_constant(self):
        self.assertEqual(ICD_CLASSIFICATIONS, ("icd10", "icd11"))
        self.assertEqual(PROJECT_ICD_CLASSIFICATIONS, ("icd10", "icd11", "selectable"))

    def test_classification_of_value_reads_the_code_shape(self):
        self.assertEqual(classification_of_value("A00.1 Cholera"), "icd10")
        self.assertEqual(classification_of_value("I24-Other acute ischaemic"), "icd10")
        self.assertEqual(classification_of_value("1A00 Cholera"), "icd11")
        self.assertEqual(classification_of_value("BA00.1 Something"), "icd11")
        self.assertEqual(classification_of_value("2C25.Z Unspecified"), "icd11")
        self.assertIsNone(classification_of_value(None))
        self.assertIsNone(classification_of_value(""))
        self.assertIsNone(classification_of_value("not a code"))


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

    def _set_project(self, value):
        db.session.get(VaProjectMaster, self.BASE_PROJECT_ID).icd_classification = value
        db.session.flush()

    def test_defaults_to_icd10(self):
        self.assertEqual(get_icd_classification_for_submission(self.SID), "icd10")

    def test_defaults_to_icd10_for_unknown_submission(self):
        self.assertEqual(get_icd_classification_for_submission("uuid:does-not-exist"), "icd10")

    def test_resolves_every_project_setting(self):
        # The form has no ODK mapping row, exactly like a web-form submission:
        # the project setting still applies.
        for value in ("icd11", "selectable", "icd10"):
            self._set_project(value)
            self.assertEqual(get_icd_classification_for_submission(self.SID), value)

    def test_ignores_the_deprecated_per_form_setting(self):
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
        self.assertEqual(get_icd_classification_for_submission(self.SID), "icd10")


class TestValidateCodingValueForSubmission(TestGetIcdClassificationForSubmission):
    """Save validation dispatches on the project setting (and, for a
    selectable project, on the value's code shape)."""

    ICD10 = "I24 Other acute ischaemic heart diseases"
    ICD11 = "BA41 Acute myocardial infarction"

    def setUp(self):
        super().setUp()
        now = datetime.now(UTC)
        db.session.merge(
            MasIcd1020192(
                code="I24",
                title="Other acute ischaemic heart diseases",
                node_type="category",
                semantic_level="three_character",
                sort_order=1,
                chapter_code="IX",
                chapter_title="Diseases of the circulatory system",
                block_code="I20-I25",
                block_title="Ischaemic heart diseases",
                three_character_code="I24",
                three_character_title="Other acute ischaemic heart diseases",
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
            )
        )
        for code, sex in (("BA41", "both"), ("JA00", "female"), ("MB23", "male")):
            db.session.merge(
                MasIcd11Mms(
                    release=DEFAULT_ICD11_RELEASE,
                    linearization_uri=f"http://id.who.int/icd/test/{code}",
                    code=code,
                    title=f"Test {code}",
                    class_kind="category",
                    is_coding_selectable=True,
                    sex_selectable=sex,
                    age_group_selectable="all",
                    source_version="test",
                )
            )
        db.session.flush()

    def test_icd10_project_accepts_icd10_and_rejects_icd11(self):
        self.assertEqual(validate_coding_value_for_submission(self.SID, self.ICD10), "icd10")
        with self.assertRaisesRegex(ValueError, "ICD-10"):
            validate_coding_value_for_submission(self.SID, self.ICD11)

    def test_icd11_project_accepts_icd11_and_rejects_icd10(self):
        self._set_project("icd11")
        self.assertEqual(validate_coding_value_for_submission(self.SID, self.ICD11), "icd11")
        with self.assertRaisesRegex(ValueError, "ICD-11"):
            validate_coding_value_for_submission(self.SID, self.ICD10)

    def test_selectable_project_accepts_both_by_shape(self):
        self._set_project("selectable")
        self.assertEqual(validate_coding_value_for_submission(self.SID, self.ICD10), "icd10")
        self.assertEqual(validate_coding_value_for_submission(self.SID, self.ICD11), "icd11")
        for bad in (None, "", "not a code"):
            with self.assertRaisesRegex(ValueError, "ICD-10 or ICD-11"):
                validate_coding_value_for_submission(self.SID, bad)

    def test_icd11_applies_catalogue_and_sex_policy(self):
        self._set_project("icd11")
        # The submission is female.
        self.assertEqual(validate_coding_value_for_submission(self.SID, "JA00 Test"), "icd11")
        with self.assertRaisesRegex(ValueError, "not selectable"):
            validate_coding_value_for_submission(self.SID, "MB23 Test")
        # Well-shaped but not in the catalogue.
        with self.assertRaisesRegex(ValueError, "not selectable"):
            validate_coding_value_for_submission(self.SID, "1A00 Cholera")

    def test_icd11_accepts_a_who_verified_cluster_and_checks_its_stem(self):
        self._set_project("icd11")
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/1G40.0",
                code="1G40.0",
                title="Test cluster stem",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.flush()
        expression = "1G40.0&XN8Q/1G41"
        with patch(
            "app.services.who_icd_api.get_icd11_codeinfo",
            return_value={"code": expression, "stemCode": "1G40.0"},
        ) as codeinfo:
            self.assertEqual(
                validate_coding_value_for_submission(
                    self.SID, f"{expression} Post-coordinated sepsis"
                ),
                "icd11",
            )
        codeinfo.assert_called_once_with(expression, release=DEFAULT_ICD11_RELEASE)

    def test_icd11_provenance_uses_versioned_who_stem_uri_and_local_title(self):
        self._set_project("icd11")
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/release/11/mms/412389819/unspecified",
                foundation_uri="http://id.who.int/icd/entity/412389819",
                code="GB61.Z",
                title="Chronic kidney disease, stage unspecified",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.flush()
        with patch(
            "app.services.who_icd_api.get_icd11_codeinfo",
            return_value={
                "@id": "http://id.who.int/icd/release/11/2026-01/mms/codeinfo/GB61.Z",
                "code": "GB61.Z",
                "stemId": "http://id.who.int/icd/release/11/2026-01/mms/412389819/unspecified",
            },
        ) as codeinfo:
            provenance = build_icd11_provenance_for_values(
                self.SID, {"conclusive": "GB61.Z Diabetic nephropathy"}
            )

        self.assertEqual(provenance["conclusive"]["code"], "GB61.Z")
        self.assertEqual(
            provenance["conclusive"]["selected_text"], "Diabetic nephropathy"
        )
        self.assertEqual(
            provenance["conclusive"]["title"],
            "Chronic kidney disease, stage unspecified",
        )
        self.assertEqual(
            provenance["conclusive"]["linearization_uri"],
            "http://id.who.int/icd/release/11/2026-01/mms/412389819/unspecified",
        )
        codeinfo.assert_called_once_with("GB61.Z", release=DEFAULT_ICD11_RELEASE)

    def test_icd10_provenance_is_null(self):
        self.assertIsNone(
            build_icd11_provenance_for_values(
                self.SID, {"conclusive": "I21 Acute myocardial infarction"}
            )
        )

    def test_icd11_rejects_a_cluster_with_a_noncanonical_suffix(self):
        self._set_project("icd11")
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/1G40.0-invalid",
                code="1G40.0",
                title="Test cluster stem",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.flush()
        expression = "1G40.0&XN8Q&ARBITRARY"
        with patch(
            "app.services.who_icd_api.get_icd11_codeinfo",
            return_value={"code": "1G40.0&XN8Q", "stemCode": "1G40.0"},
        ):
            with self.assertRaisesRegex(ValueError, "expression is not valid"):
                validate_coding_value_for_submission(self.SID, f"{expression} title")

    def test_icd11_rejects_a_malformed_cluster_before_local_stem_fallback(self):
        self._set_project("icd11")
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/1G40.0-malformed",
                code="1G40.0",
                title="Test cluster stem",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.flush()
        with patch("app.services.who_icd_api.get_icd11_codeinfo") as codeinfo:
            with self.assertRaisesRegex(ValueError, "valid ICD-11 code"):
                validate_coding_value_for_submission(self.SID, "1G40.0& title")
        codeinfo.assert_not_called()

    def test_icd11_cluster_fails_closed_when_who_api_is_unavailable(self):
        self._set_project("icd11")
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/1G40.0-outage",
                code="1G40.0",
                title="Test cluster stem",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.flush()
        from app.services.who_icd_api import WhoIcdApiUnavailable

        expression = "1G40.0&XN8Q/1G41"
        with patch(
            "app.services.who_icd_api.get_icd11_codeinfo",
            side_effect=WhoIcdApiUnavailable("test outage"),
        ):
            with self.assertRaisesRegex(ValueError, "service unavailable"):
                validate_coding_value_for_submission(self.SID, f"{expression} title")

    def test_unknown_submission_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            validate_coding_value_for_submission("uuid:does-not-exist", self.ICD10)


class TestValidateCodingValueThreeCharacterTransport(TestGetIcdClassificationForSubmission):
    """Owner decision 15 (digitva-g2n): three-character V01-V89/Y85 are not
    selectable, but their detailed subcodes are. The submission here is an
    adult, so age/sex policy never masks the check."""

    def setUp(self):
        super().setUp()
        now = datetime.now(UTC)
        db.session.merge(
            MasIcd1020192(
                code="V89",
                title="Other and unspecified transport accidents",
                node_type="category",
                semantic_level="three_character",
                sort_order=1,
                chapter_code="XX",
                chapter_title="External causes of morbidity and mortality",
                block_code="V01-X59",
                block_title="Accidents",
                three_character_code="V89",
                three_character_title="Other and unspecified transport accidents",
                has_children=True,
                is_leaf=False,
                is_three_character_code=True,
                is_detailed_code=False,
                is_coding_selectable=False,
                sex_selectable="both",
                age_group_selectable="all",
                policy_status="unreviewed",
                source_version="ICD-10-2019",
                source_path="test",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        db.session.merge(
            MasIcd1020192(
                code="V89.2",
                title="Person injured in unspecified traffic accident",
                node_type="detail",
                semantic_level="detailed_code",
                sort_order=1,
                chapter_code="XX",
                chapter_title="External causes of morbidity and mortality",
                block_code="V01-X59",
                block_title="Accidents",
                three_character_code="V89",
                three_character_title="Other and unspecified transport accidents",
                has_children=False,
                is_leaf=True,
                is_three_character_code=False,
                is_detailed_code=True,
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                policy_status="unreviewed",
                source_version="ICD-10-2019",
                source_path="test",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        db.session.flush()

    def test_three_character_code_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not selectable"):
            validate_coding_value_for_submission(self.SID, "V89 Other and unspecified transport accidents")

    def test_detailed_subcode_is_accepted(self):
        self.assertEqual(
            validate_coding_value_for_submission(
                self.SID, "V89.2 Person injured in unspecified traffic accident"
            ),
            "icd10",
        )
