"""
Phase 3: Migration Completeness Verification Tests

These tests run against the test DB (using the base test framework) and verify
that the migration script produces data that is 100% accurate against the
Excel source files.

They are distinct from Phase 2 tests in that they verify:
- Boolean fields are correctly preserved (flip_color, is_info, summary_include)
- Field type and age group are preserved
- Category assignments match Excel exactly
- Choice labels match Excel exactly (spot checks)
- All data is queryable via SQLAlchemy models without errors

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/migrations/test_migration_completeness.py -v
"""
import pandas as pd
from pathlib import Path

from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)
from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator, WHO_2022_CATEGORIES
from tests.base import BaseTestCase


LABELS_PATH = Path("resource/mapping/mapping_labels.xlsx")
CHOICES_PATH = Path("resource/mapping/mapping_choices.xlsx")


class TestMigrationCompleteness(BaseTestCase):
    """Exhaustive verification of WHO_2022_VA migration completeness."""

    def setUp(self):
        super().setUp()
        self.labels_df = pd.read_excel(LABELS_PATH)
        self.choices_df = pd.read_excel(CHOICES_PATH)
        # Run migration fresh
        migrator = Who2022VaMigrator()
        migrator.run()
        self.form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )

    def _valid_labels(self):
        """Return Excel label rows with valid (non-NaN) field_ids, deduplicated."""
        df = self.labels_df
        valid = df[df["name"].notna()].copy()
        valid["name"] = valid["name"].astype(str).str.strip()
        valid = valid[valid["name"] != ""]
        # Keep last occurrence for duplicates (matches update-wins behavior)
        valid = valid.drop_duplicates(subset=["name"], keep="last")
        return valid

    # ------------------------------------------------------------------ #
    # test_01: Form type exists and is active                              #
    # ------------------------------------------------------------------ #

    def test_01_form_type_exists(self):
        """WHO_2022_VA form type is in database and active."""
        self.assertIsNotNone(self.form_type)
        self.assertTrue(self.form_type.is_active)
        self.assertEqual(self.form_type.form_type_code, "WHO_2022_VA")

    # ------------------------------------------------------------------ #
    # test_02: Exact field count                                           #
    # ------------------------------------------------------------------ #

    def test_02_exact_field_count(self):
        """DB field count matches unique valid field_ids in Excel."""
        expected = int(
            self.labels_df["name"].dropna().astype(str).str.strip()
            .replace("", pd.NA).dropna().nunique()
        )
        actual = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id)
        )
        self.assertEqual(actual, expected, f"Expected {expected} fields, got {actual}")

    # ------------------------------------------------------------------ #
    # test_03: Exact choice count                                          #
    # ------------------------------------------------------------------ #

    def test_03_exact_choice_count(self):
        """DB choice count matches valid (non-NaN) rows in choices Excel."""
        expected = int(len(self.choices_df[
            self.choices_df["category"].notna() & self.choices_df["name"].notna()
        ]))
        actual = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == self.form_type.form_type_id)
        )
        self.assertEqual(actual, expected, f"Expected {expected} choices, got {actual}")

    # ------------------------------------------------------------------ #
    # test_04: Category order matches source exactly                       #
    # ------------------------------------------------------------------ #

    def test_04_category_order_exact(self):
        """14 categories match WHO_2022_CATEGORIES in exact order."""
        cats = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == self.form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()
        self.assertEqual(len(cats), 14)
        for i, cat in enumerate(cats):
            self.assertEqual(cat.category_code, WHO_2022_CATEGORIES[i])
            self.assertEqual(cat.display_order, i + 1)

    # ------------------------------------------------------------------ #
    # test_05: Category assignments match Excel                            #
    # ------------------------------------------------------------------ #

    def test_05_category_assignments_match(self):
        """Every field's category_code matches Excel."""
        valid = self._valid_labels()

        mismatches = []
        for _, row in valid.iterrows():
            field_id = str(row["name"])
            expected_cat = str(row.get("category", "") or "").strip() or None

            config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )
            if config and config.category_code != expected_cat:
                mismatches.append(
                    f"{field_id}: expected={expected_cat}, got={config.category_code}"
                )

        self.assertEqual(len(mismatches), 0,
                         f"Category mismatches:\n" + "\n".join(mismatches[:10]))

    # ------------------------------------------------------------------ #
    # test_06: Boolean fields preserved                                     #
    # ------------------------------------------------------------------ #

    def test_06_boolean_fields_match(self):
        """flip_color, is_info, summary_include match Excel for all fields."""
        valid = self._valid_labels()

        mismatches = []
        for _, row in valid.iterrows():
            field_id = str(row["name"])

            expected_flip = bool(row.get("flip_color")) if pd.notna(row.get("flip_color")) else False
            expected_info = bool(row.get("is_info")) if pd.notna(row.get("is_info")) else False
            expected_sum = bool(row.get("summary_include")) if pd.notna(row.get("summary_include")) else False

            config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )
            if config is None:
                continue

            if config.flip_color != expected_flip:
                mismatches.append(f"{field_id} flip_color: {config.flip_color} != {expected_flip}")
            if config.is_info != expected_info:
                mismatches.append(f"{field_id} is_info: {config.is_info} != {expected_info}")
            if config.summary_include != expected_sum:
                mismatches.append(f"{field_id} summary_include: {config.summary_include} != {expected_sum}")

        self.assertEqual(len(mismatches), 0,
                         f"Boolean mismatches:\n" + "\n".join(mismatches[:10]))

    # ------------------------------------------------------------------ #
    # test_07: Choice labels match Excel                                   #
    # ------------------------------------------------------------------ #

    def test_07_choice_labels_match(self):
        """choice_label matches Excel short_label for all valid choices."""
        valid_choices = self.choices_df[
            self.choices_df["category"].notna() & self.choices_df["name"].notna()
        ]

        mismatches = []
        sample = valid_choices.head(50)  # spot-check first 50
        for _, row in sample.iterrows():
            field_id = str(row["category"]).strip()
            choice_value = str(row["name"]).strip()
            expected_label = str(row.get("short_label", "") or "").strip()

            choice = db.session.scalar(
                db.select(MasChoiceMappings).where(
                    MasChoiceMappings.form_type_id == self.form_type.form_type_id,
                    MasChoiceMappings.field_id == field_id,
                    MasChoiceMappings.choice_value == choice_value,
                )
            )
            if choice is None:
                mismatches.append(f"MISSING: {field_id}/{choice_value}")
            elif choice.choice_label != expected_label:
                mismatches.append(
                    f"{field_id}/{choice_value}: expected={expected_label!r}, got={choice.choice_label!r}"
                )

        self.assertEqual(len(mismatches), 0,
                         f"Choice label mismatches:\n" + "\n".join(mismatches))

    # ------------------------------------------------------------------ #
    # test_08: Field type and age_group preserved                          #
    # ------------------------------------------------------------------ #

    def test_08_field_type_and_age_group_match(self):
        """field_type and age_group match Excel for all fields."""
        valid = self._valid_labels()

        mismatches = []
        for _, row in valid.iterrows():
            field_id = str(row["name"])
            expected_type = str(row.get("type", "") or "").strip() or None
            expected_age = str(row.get("agegroup", "") or "").strip() or None

            config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )
            if config is None:
                continue

            if config.field_type != expected_type:
                mismatches.append(f"{field_id} field_type: {config.field_type!r} != {expected_type!r}")
            if config.age_group != expected_age:
                mismatches.append(f"{field_id} age_group: {config.age_group!r} != {expected_age!r}")

        self.assertEqual(len(mismatches), 0,
                         f"Field type/age_group mismatches:\n" + "\n".join(mismatches[:10]))

    # ------------------------------------------------------------------ #
    # test_09: Models queryable without errors                             #
    # ------------------------------------------------------------------ #

    def test_09_all_models_queryable(self):
        """All field mapping models can be queried without errors."""
        from app.models import MasSubcategoryOrder, MasPiiAccessLog

        # Query each model
        ft_count = db.session.scalar(db.select(db.func.count()).select_from(MasFormTypes))
        self.assertGreater(ft_count, 0)

        cat_count = db.session.scalar(db.select(db.func.count()).select_from(MasCategoryOrder))
        self.assertGreater(cat_count, 0)

        subcat_count = db.session.scalar(db.select(db.func.count()).select_from(MasSubcategoryOrder))
        self.assertGreater(subcat_count, 0)

        field_count = db.session.scalar(db.select(db.func.count()).select_from(MasFieldDisplayConfig))
        self.assertGreater(field_count, 0)

        choice_count = db.session.scalar(db.select(db.func.count()).select_from(MasChoiceMappings))
        self.assertGreater(choice_count, 0)

        # PII log is empty (no access yet) - just check table exists
        pii_count = db.session.scalar(db.select(db.func.count()).select_from(MasPiiAccessLog))
        self.assertGreaterEqual(pii_count, 0)

    # ------------------------------------------------------------------ #
    # test_10: Subcategory assignments match Excel                         #
    # ------------------------------------------------------------------ #

    def test_10_subcategory_assignments_match(self):
        """Every field's subcategory_code matches Excel sub_category."""
        valid = self._valid_labels()

        mismatches = []
        for _, row in valid.iterrows():
            field_id = str(row["name"])
            expected_sub = str(row.get("sub_category", "") or "").strip() or None
            if pd.isna(row.get("sub_category")):
                expected_sub = None

            config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )
            if config and config.subcategory_code != expected_sub:
                mismatches.append(
                    f"{field_id}: expected={expected_sub!r}, got={config.subcategory_code!r}"
                )

        self.assertEqual(len(mismatches), 0,
                         f"Subcategory mismatches:\n" + "\n".join(mismatches[:10]))
