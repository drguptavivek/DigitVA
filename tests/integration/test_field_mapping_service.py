"""
Integration tests for FieldMappingService (Phase 4 TDD).

These tests verify that FieldMappingService produces data structures
identical in format and content to the old Excel-based static mapping dicts.

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/integration/test_field_mapping_service.py -v
"""
import pandas as pd
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    MasCategoryDisplayConfig,
    MasFormTypes,
    MasSubcategoryOrder,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator, WHO_2022_CATEGORIES
from app.services.field_mapping_service import FieldMappingService
from tests.base import BaseTestCase


LABELS_PATH = Path("resource/mapping/mapping_labels.xlsx")
CHOICES_PATH = Path("resource/mapping/mapping_choices.xlsx")


class TestFieldMappingServiceStructure(BaseTestCase):
    """Test that FieldMappingService returns correctly structured data."""

    def setUp(self):
        super().setUp()
        # Run migration to populate test DB
        Who2022VaMigrator().run()
        self.service = FieldMappingService()
        self.form_type_code = "WHO_2022_VA"

    # ------------------------------------------------------------------ #
    # fieldsitepi dict structure                                           #
    # ------------------------------------------------------------------ #

    def test_01_fieldsitepi_returns_dict(self):
        """get_fieldsitepi returns a dict."""
        result = self.service.get_fieldsitepi(self.form_type_code)
        self.assertIsInstance(result, dict)

    def test_02_fieldsitepi_has_all_categories(self):
        """fieldsitepi contains all 14 category codes as top-level keys."""
        result = self.service.get_fieldsitepi(self.form_type_code)
        for cat_code in WHO_2022_CATEGORIES:
            self.assertIn(cat_code, result,
                         f"Category {cat_code} missing from fieldsitepi")

    def test_03_fieldsitepi_has_subcategory_nesting(self):
        """Each category value is a dict of {subcategory: {field_id: label}}."""
        result = self.service.get_fieldsitepi(self.form_type_code)
        # Check first category
        first_cat = result[WHO_2022_CATEGORIES[0]]
        self.assertIsInstance(first_cat, dict)
        # Each subcategory should be a dict
        for subcat, fields in first_cat.items():
            self.assertIsInstance(subcat, str)
            self.assertIsInstance(fields, dict)

    def test_04_fieldsitepi_field_values_are_strings(self):
        """Each field entry value is the short_label string."""
        result = self.service.get_fieldsitepi(self.form_type_code)
        for cat_code, subcats in result.items():
            for subcat, fields in subcats.items():
                for field_id, label in fields.items():
                    self.assertIsInstance(field_id, str,
                                         f"field_id must be str, got {type(field_id)}")
                    self.assertIsInstance(label, str,
                                         f"label for {field_id} must be str, got {type(label)}")

    def test_05_fieldsitepi_matches_excel_field_ids(self):
        """All Excel field_ids (with subcategories) appear in fieldsitepi.

        For duplicate field_ids, only the last occurrence wins (matching
        the migration's update-on-duplicate behaviour).
        """
        labels_df = pd.read_excel(LABELS_PATH)
        valid = labels_df[
            labels_df["name"].notna() &
            labels_df["sub_category"].notna()
        ]
        # Keep last occurrence for duplicate field_ids (mirrors migration)
        valid = valid.drop_duplicates(subset=["name"], keep="last")

        result = self.service.get_fieldsitepi(self.form_type_code)

        missing = []
        for _, row in valid.iterrows():
            field_id = str(row["name"]).strip()
            cat = str(row["category"]).strip()
            subcat = str(row["sub_category"]).strip()

            if cat not in result:
                missing.append(f"category missing: {cat}")
            elif subcat not in result.get(cat, {}):
                missing.append(f"subcat missing: {cat}/{subcat}")
            elif field_id not in result.get(cat, {}).get(subcat, {}):
                missing.append(f"field missing: {cat}/{subcat}/{field_id}")

        self.assertEqual(len(missing), 0,
                         f"Missing from fieldsitepi:\n" + "\n".join(missing[:10]))

    def test_06_fieldsitepi_labels_match_excel(self):
        """Labels in fieldsitepi match short_label column in Excel."""
        labels_df = pd.read_excel(LABELS_PATH)
        valid = labels_df[
            labels_df["name"].notna() &
            labels_df["sub_category"].notna()
        ].drop_duplicates(subset=["name"], keep="last")

        result = self.service.get_fieldsitepi(self.form_type_code)

        mismatches = []
        for _, row in valid.head(50).iterrows():
            field_id = str(row["name"]).strip()
            cat = str(row["category"]).strip()
            subcat = str(row["sub_category"]).strip()
            expected_label = str(row.get("short_label", "") or "").strip()

            actual_label = result.get(cat, {}).get(subcat, {}).get(field_id)
            if actual_label != expected_label:
                mismatches.append(
                    f"{field_id}: expected={expected_label!r}, got={actual_label!r}"
                )

        self.assertEqual(len(mismatches), 0,
                         f"Label mismatches:\n" + "\n".join(mismatches))

    # ------------------------------------------------------------------ #
    # choice dict structure                                                #
    # ------------------------------------------------------------------ #

    def test_07_choices_returns_dict(self):
        """get_choices returns a dict."""
        result = self.service.get_choices(self.form_type_code)
        self.assertIsInstance(result, dict)

    def test_08_choices_has_correct_structure(self):
        """choices is {field_id: {choice_value: choice_label}}."""
        result = self.service.get_choices(self.form_type_code)
        for field_id, choices in result.items():
            self.assertIsInstance(field_id, str)
            self.assertIsInstance(choices, dict)
            for value, label in choices.items():
                self.assertIsInstance(value, str)
                self.assertIsInstance(label, str)

    def test_09_choices_matches_excel(self):
        """All Excel choice rows appear in choices dict."""
        choices_df = pd.read_excel(CHOICES_PATH)
        valid = choices_df[
            choices_df["category"].notna() & choices_df["name"].notna()
        ]
        result = self.service.get_choices(self.form_type_code)

        missing = []
        for _, row in valid.iterrows():
            field_id = str(row["category"]).strip()
            choice_value = str(row["name"]).strip()
            expected_label = str(row.get("short_label", "") or "").strip()

            actual = result.get(field_id, {}).get(choice_value)
            if actual is None:
                missing.append(f"MISSING: {field_id}/{choice_value}")
            elif actual != expected_label:
                missing.append(f"MISMATCH {field_id}/{choice_value}: {actual!r} != {expected_label!r}")

        self.assertEqual(len(missing), 0,
                         f"Choice mismatches:\n" + "\n".join(missing[:10]))

    # ------------------------------------------------------------------ #
    # flip and info lists                                                  #
    # ------------------------------------------------------------------ #

    def test_10_flip_labels_is_list(self):
        """get_flip_labels returns a list of strings."""
        result = self.service.get_flip_labels(self.form_type_code)
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIsInstance(item, str)

    def test_11_info_labels_is_list(self):
        """get_info_labels returns a list of strings."""
        result = self.service.get_info_labels(self.form_type_code)
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIsInstance(item, str)

    def test_12_flip_labels_match_excel(self):
        """Flip labels come from rows where flip_color=True in Excel."""
        labels_df = pd.read_excel(LABELS_PATH)
        excel_flip_fields = set(
            str(row["name"]).strip()
            for _, row in labels_df.iterrows()
            if pd.notna(row.get("name")) and pd.notna(row.get("flip_color")) and bool(row["flip_color"])
        )

        result_labels = self.service.get_flip_labels(self.form_type_code)
        # Build set of field_ids from result by mapping back via fieldsitepi
        fieldsitepi = self.service.get_fieldsitepi(self.form_type_code)
        label_to_fieldid = {}
        for cat, subcats in fieldsitepi.items():
            for subcat, fields in subcats.items():
                for fid, lbl in fields.items():
                    label_to_fieldid[lbl] = fid

        result_field_ids = set(
            label_to_fieldid[lbl]
            for lbl in result_labels
            if lbl in label_to_fieldid
        )
        self.assertEqual(result_field_ids, excel_flip_fields,
                         f"Flip field_id mismatch")

    def test_13_invalid_form_type_returns_empty(self):
        """Unknown form type returns empty structures."""
        self.assertEqual(self.service.get_fieldsitepi("UNKNOWN"), {})
        self.assertEqual(self.service.get_choices("UNKNOWN"), {})
        self.assertEqual(self.service.get_flip_labels("UNKNOWN"), [])
        self.assertEqual(self.service.get_info_labels("UNKNOWN"), [])

    # ------------------------------------------------------------------ #
    # Render compatibility                                                 #
    # ------------------------------------------------------------------ #

    def test_14_render_processcategorydata_works_with_service_data(self):
        """va_render_processcategorydata produces output using service data."""
        from app.utils.va_render.va_render_06_processcategorydata import va_render_processcategorydata

        fieldsitepi = self.service.get_fieldsitepi(self.form_type_code)
        choices = self.service.get_choices(self.form_type_code)

        # Sample VA data for first category
        first_cat = WHO_2022_CATEGORIES[0]
        sample_data = {"Id10010": "Test Interviewer"}

        result = va_render_processcategorydata(
            va_data=sample_data,
            va_form_id="TEST001",
            va_datalevel=fieldsitepi,
            va_mapping_choice=choices,
            va_partial=first_cat,
        )

        # Result should be a dict (may be empty if no matching fields in sample)
        self.assertIsInstance(result, dict)

    def test_14b_render_processcategorydata_maps_numeric_choice_values(self):
        """Numeric JSON select values still map to field choice labels."""
        from app.utils.va_render.va_render_06_processcategorydata import va_render_processcategorydata

        datalevel = {
            "social_autopsy": {
                "social-autopsy": {
                    "sa05": "5. If yes, type of first consultation",
                }
            }
        }
        choices = {
            "sa05": {
                "1": "Home visit by physician",
                "2": "Individual Practitioner",
                "3": "Small hospital",
            }
        }

        result = va_render_processcategorydata(
            va_data={"sa05": 3.0},
            va_form_id="TEST001",
            va_datalevel=datalevel,
            va_mapping_choice=choices,
            va_partial="social_autopsy",
        )

        self.assertEqual(
            result["social-autopsy"]["5. If yes, type of first consultation"],
            "Small hospital",
        )

    def test_15_fieldsitepi_category_order_matches_source(self):
        """Categories in fieldsitepi are in the correct display order."""
        result = self.service.get_fieldsitepi(self.form_type_code)
        cat_keys = list(result.keys())

        # Should match WHO_2022_CATEGORIES order (may have fewer if some empty)
        expected_order = [c for c in WHO_2022_CATEGORIES if c in cat_keys]
        self.assertEqual(cat_keys, expected_order,
                         "Category order in fieldsitepi does not match source")

    def test_15b_fieldsitepi_uses_category_display_config_order(self):
        """Runtime category order follows MasCategoryDisplayConfig, not legacy order."""
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == self.form_type_code)
        )
        first = db.session.scalar(
            db.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.category_code == "vanarrationanddocuments",
            )
        )
        second = db.session.scalar(
            db.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.category_code == "vahealthserviceutilisation",
            )
        )
        first.display_order = 20
        second.display_order = 19
        db.session.commit()

        self.service.clear_cache()
        result = self.service.get_fieldsitepi(self.form_type_code)
        cat_keys = list(result.keys())

        self.assertLess(
            cat_keys.index("vahealthserviceutilisation"),
            cat_keys.index("vanarrationanddocuments"),
        )


class TestRenderProcessCategoryDataLegacyAttachmentFallback(BaseTestCase):
    FORM_ID = "LEGACYATT01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        if not db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Research Project",
                project_nickname="BaseResearch",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
            db.session.flush()

        if not db.session.scalar(
            sa.select(VaSites).where(VaSites.site_id == cls.BASE_SITE_ID)
        ):
            db.session.add(VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
            db.session.flush()

        if not db.session.get(VaForms, cls.FORM_ID):
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="LEGACYATT_ODK",
                odk_project_id="99",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
            db.session.flush()

        cls.submission = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=cls.FORM_ID,
            va_data_collector="Legacy Collector",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_uniqueid_masked="LEGACY001",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(cls.submission)
        db.session.commit()

    def test_legacy_attachment_without_storage_name_uses_media_fallback(self):
        from app.utils.va_render.va_render_06_processcategorydata import (
            va_render_processcategorydata,
        )

        filename = f"legacy_{uuid.uuid4().hex[:8]}.jpg"
        db.session.add(VaSubmissionAttachments(
            va_sid=self.submission.va_sid,
            filename=filename,
            local_path=f"/app/data/{self.FORM_ID}/media/{filename}",
            mime_type="image/jpeg",
            storage_name=None,
            exists_on_odk=True,
            etag=None,
            last_downloaded_at=datetime.now(timezone.utc),
        ))
        db.session.flush()

        datalevel = {
            "vanarrationanddocuments": {
                "narration": {
                    "imagenarr": "(imagenarr) Narration image",
                }
            }
        }

        with self.app.test_request_context():
            result = va_render_processcategorydata(
                va_data={"imagenarr": filename},
                va_form_id=self.FORM_ID,
                va_datalevel=datalevel,
                va_mapping_choice={},
                va_partial="vanarrationanddocuments",
                va_sid=self.submission.va_sid,
            )

        self.assertEqual(
            result["narration"]["(imagenarr) Narration image"],
            f"/vaform/media/{self.FORM_ID}/{filename}",
        )

    def test_16_fieldsitepi_uses_explicit_subcategory_order(self):
        """Subcategories are ordered by MasSubcategoryOrder, not first field order."""
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == self.form_type_code)
        )
        category_code = "vademographicdetails"

        first = db.session.scalar(
            db.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == "general",
            )
        )
        second = db.session.scalar(
            db.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == "risk_factors",
            )
        )

        first.display_order = 2
        second.display_order = 1
        db.session.commit()

        self.service.clear_cache()
        result = self.service.get_fieldsitepi(self.form_type_code)

        self.assertEqual(
            list(result[category_code].keys())[:2],
            ["risk_factors", "general"],
        )
