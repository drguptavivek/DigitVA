"""
Tests for WHO_2022_VA data migration.

TDD tests that verify:
1. Migration creates all expected records
2. No data loss (Excel vs DB)
3. Category order is preserved
4. Migration is idempotent (safe to re-run)

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/migrations/test_migrate_who_2022_va.py -v
"""
import pandas as pd
from pathlib import Path

from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasCategoryDisplayConfig,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)
from app.services.migrations.migrate_who_2022_va import (
    Who2022VaMigrator,
    WHO_2022_CATEGORIES,
)
from tests.base import BaseTestCase


LABELS_PATH = Path("resource/mapping/mapping_labels.xlsx")
CHOICES_PATH = Path("resource/mapping/mapping_choices.xlsx")


class TestWho2022VaMigration(BaseTestCase):
    """Test WHO_2022_VA data migration from Excel to database."""

    def _run_migration(self) -> MasFormTypes:
        """Helper: run migration and return the form type."""
        migrator = Who2022VaMigrator()
        migrator.run()
        return db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

    # ------------------------------------------------------------------ #
    # Preconditions                                                        #
    # ------------------------------------------------------------------ #

    def test_01_excel_files_exist(self):
        """Source Excel files must exist before migration can run."""
        self.assertTrue(LABELS_PATH.exists(), f"Labels file missing: {LABELS_PATH}")
        self.assertTrue(CHOICES_PATH.exists(), f"Choices file missing: {CHOICES_PATH}")

    def test_02_excel_has_expected_structure(self):
        """Excel files have expected columns."""
        labels_df = pd.read_excel(LABELS_PATH)
        choices_df = pd.read_excel(CHOICES_PATH)

        required_labels_cols = {"category", "sub_category", "name", "short_label", "label"}
        required_choices_cols = {"category", "name", "short_label"}

        self.assertTrue(
            required_labels_cols.issubset(set(labels_df.columns)),
            f"Missing columns in labels: {required_labels_cols - set(labels_df.columns)}"
        )
        self.assertTrue(
            required_choices_cols.issubset(set(choices_df.columns)),
            f"Missing columns in choices: {required_choices_cols - set(choices_df.columns)}"
        )

    # ------------------------------------------------------------------ #
    # Core migration results                                               #
    # ------------------------------------------------------------------ #

    def test_03_migration_creates_form_type(self):
        """Migration creates WHO_2022_VA form type record."""
        form_type = self._run_migration()

        self.assertIsNotNone(form_type)
        self.assertEqual(form_type.form_type_code, "WHO_2022_VA")
        self.assertEqual(form_type.form_type_name, "WHO 2022 VA Form")
        self.assertTrue(form_type.is_active)

    def test_04_all_14_categories_migrated(self):
        """All 14 categories are migrated with correct count."""
        form_type = self._run_migration()

        count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        )
        self.assertEqual(count, 14, f"Expected 14 categories, got {count}")

    def test_05_category_order_matches_source(self):
        """Categories are stored in exact order from va_preprocess_03."""
        form_type = self._run_migration()

        categories = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()

        self.assertEqual(len(categories), len(WHO_2022_CATEGORIES))
        for i, cat in enumerate(categories):
            self.assertEqual(
                cat.category_code, WHO_2022_CATEGORIES[i],
                f"Position {i+1}: expected {WHO_2022_CATEGORIES[i]}, got {cat.category_code}"
            )
            self.assertEqual(cat.display_order, i + 1)

    def test_05b_category_display_configs_created(self):
        """Migration creates one category display config per WHO category."""
        form_type = self._run_migration()

        count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasCategoryDisplayConfig)
            .where(MasCategoryDisplayConfig.form_type_id == form_type.form_type_id)
        )
        self.assertEqual(count, 14)

    def test_05c_category_display_config_preserves_special_modes(self):
        """Seeded category display metadata captures current special behaviors."""
        form_type = self._run_migration()

        health_history = db.session.scalar(
            db.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.category_code == "vahealthhistorydetails",
            )
        )
        narration = db.session.scalar(
            db.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.category_code == "vanarrationanddocuments",
            )
        )
        interview = db.session.scalar(
            db.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.category_code == "vainterviewdetails",
            )
        )

        self.assertEqual(health_history.render_mode, "health_history_summary")
        self.assertEqual(narration.render_mode, "attachments")
        self.assertTrue(narration.always_include)
        self.assertFalse(interview.show_to_coder)
        self.assertFalse(interview.show_to_reviewer)
        self.assertTrue(interview.show_to_site_pi)

    def test_06_all_field_configs_migrated(self):
        """All unique field configs from Excel are migrated.

        The Excel may contain duplicate field_ids (e.g., Id10233-Id10236 appear
        twice each). The DB stores one row per unique field_id, so we compare
        against the unique count.
        """
        labels_df = pd.read_excel(LABELS_PATH)
        # Unique non-NaN, non-empty field names
        expected_count = int(
            labels_df["name"].dropna().astype(str).str.strip()
            .replace("", pd.NA).dropna().nunique()
        )

        form_type = self._run_migration()

        db_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        )
        self.assertEqual(db_count, expected_count,
                         f"Expected {expected_count} unique field configs, got {db_count}")

    def test_07_all_choices_migrated(self):
        """All 1199 choice mappings from Excel are migrated."""
        choices_df = pd.read_excel(CHOICES_PATH)
        expected_count = len(choices_df[
            choices_df["category"].notna() & choices_df["name"].notna()
        ])

        form_type = self._run_migration()

        db_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        )
        self.assertEqual(db_count, expected_count,
                         f"Expected {expected_count} choices, got {db_count}")

    # ------------------------------------------------------------------ #
    # Data integrity: no loss                                              #
    # ------------------------------------------------------------------ #

    def test_08_no_field_ids_lost(self):
        """Every field_id from Excel exists in DB (using unique set comparison)."""
        labels_df = pd.read_excel(LABELS_PATH)
        excel_fields = set(
            labels_df["name"].dropna().astype(str).str.strip()
            .replace("", pd.NA).dropna().unique()
        )

        form_type = self._run_migration()

        db_fields = set(db.session.scalars(
            db.select(MasFieldDisplayConfig.field_id)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        ).all())

        missing = excel_fields - db_fields
        extra = db_fields - excel_fields

        self.assertEqual(len(missing), 0, f"Fields missing in DB: {missing}")
        self.assertEqual(len(extra), 0, f"Extra fields in DB (not in Excel): {extra}")

    def test_09_no_choices_lost(self):
        """Every (field_id, choice_value) pair from Excel exists in DB."""
        choices_df = pd.read_excel(CHOICES_PATH)
        excel_choices = set(
            (str(row["category"]).strip(), str(row["name"]).strip())
            for _, row in choices_df.iterrows()
            if pd.notna(row["category"]) and pd.notna(row["name"])
        )

        form_type = self._run_migration()

        db_choices = set(db.session.execute(
            db.select(MasChoiceMappings.field_id, MasChoiceMappings.choice_value)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        ).all())

        missing = excel_choices - db_choices
        extra = db_choices - excel_choices

        self.assertEqual(len(missing), 0, f"Choices missing in DB: {list(missing)[:10]}")
        self.assertEqual(len(extra), 0, f"Extra choices in DB: {list(extra)[:10]}")

    def test_10_field_labels_preserved(self):
        """short_label and full_label values match Excel for sampled fields."""
        labels_df = pd.read_excel(LABELS_PATH)
        form_type = self._run_migration()

        # Sample first 20 rows that have valid (non-NaN) field_ids
        valid_rows = labels_df[labels_df["name"].notna()].head(20)
        for _, row in valid_rows.iterrows():
            field_id = str(row.get("name")).strip()
            if not field_id:
                continue

            db_config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )
            self.assertIsNotNone(db_config, f"Field {field_id} not found in DB")

            expected_short = str(row.get("short_label", "") or "").strip() or None
            expected_full = str(row.get("label", "") or "").strip() or None

            self.assertEqual(db_config.short_label, expected_short,
                             f"short_label mismatch for {field_id}")
            self.assertEqual(db_config.full_label, expected_full,
                             f"full_label mismatch for {field_id}")

    def test_11_subcategories_created_from_excel(self):
        """Sub-categories are created from unique (category, sub_category) pairs in Excel."""
        labels_df = pd.read_excel(LABELS_PATH)
        excel_subcats = set(
            (str(row["category"]).strip(), str(row["sub_category"]).strip())
            for _, row in labels_df.iterrows()
            if pd.notna(row["category"]) and pd.notna(row["sub_category"])
        )

        form_type = self._run_migration()

        db_subcat_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasSubcategoryOrder)
            .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
        )
        self.assertEqual(
            db_subcat_count, len(excel_subcats),
            f"Expected {len(excel_subcats)} sub-categories, got {db_subcat_count}"
        )

    # ------------------------------------------------------------------ #
    # Idempotency                                                          #
    # ------------------------------------------------------------------ #

    def test_12_migration_is_idempotent(self):
        """Running migration twice does not duplicate any data."""
        # First run
        form_type = self._run_migration()

        ft_id = form_type.form_type_id

        field_count_1 = db.session.scalar(
            db.select(db.func.count()).select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == ft_id)
        )
        choice_count_1 = db.session.scalar(
            db.select(db.func.count()).select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == ft_id)
        )
        cat_count_1 = db.session.scalar(
            db.select(db.func.count()).select_from(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == ft_id)
        )

        # Second run
        migrator2 = Who2022VaMigrator()
        migrator2.run()

        # Refresh form type (same code = same record)
        form_type2 = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        ft_id2 = form_type2.form_type_id
        self.assertEqual(ft_id, ft_id2, "Second run should not create a new form type")

        field_count_2 = db.session.scalar(
            db.select(db.func.count()).select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == ft_id2)
        )
        choice_count_2 = db.session.scalar(
            db.select(db.func.count()).select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == ft_id2)
        )
        cat_count_2 = db.session.scalar(
            db.select(db.func.count()).select_from(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == ft_id2)
        )

        self.assertEqual(field_count_1, field_count_2,
                         "Field count must not change on re-run")
        self.assertEqual(choice_count_1, choice_count_2,
                         "Choice count must not change on re-run")
        self.assertEqual(cat_count_1, cat_count_2,
                         "Category count must not change on re-run")
