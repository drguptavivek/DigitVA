---
title: Phase 2 - Migrate Existing WHO_2022_VA Data
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 2
estimated_duration: 1 day
risk_level: critical
---

# Phase 2: Migrate Existing WHO_2022_VA Data

## Objective

Migrate all existing WHO_2022_VA mappings from Excel files to database tables **with zero data loss**.

## Prerequisites

- [ ] Phase 1 completed (tables exist)
- [ ] Phase 1 verification passed
- [ ] Database backup before migration
- [ ] Original Excel files preserved (`resource/mapping/*.xlsx`)

## Deliverables

1. WHO_2022_VA form type created in database
2. All 14 categories migrated with correct order
3. All 35+ sub-categories migrated with correct order
4. All 427 field display configs migrated
5. All 1199 choice mappings migrated
6. Migration verification tests passing

---

## Critical Principle

> **NO DATA LOSS**: Every row in the Excel files must have a corresponding database record.
> Migration is only complete when verification confirms 100% match.

---

## Step 2.1: Create Migration Script

**File**: `app/services/migrations/migrate_who_2022_va.py`

```python
"""
WHO_2022_VA Data Migration Script

Migrates data from:
- resource/mapping/mapping_labels.xlsx (427 rows)
- resource/mapping/mapping_choices.xlsx (1199 rows)
- Hardcoded category list (14 categories)

To database tables:
- mas_form_types
- mas_category_order
- mas_subcategory_order
- mas_field_display_config
- mas_choice_mappings

This script is IDEMPOTENT - safe to run multiple times.
"""
import uuid
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import text
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


# Hardcoded category order from va_preprocess_03_categoriestodisplay.py
WHO_2022_CATEGORIES = [
    "Id10007",      # 1. Identification
    "Id10011",      # 2. Demographics
    "Id10058",      # 3. Household
    "Id10008",      # 4. Neighbourhood
    "Id10010",      # 5. Neighbourhood (Environmental)
    "Id10022",      # 6. Family History
    "Id10018",      # 7. Pregnancy History
    "Id10021",      # 8. Birth History
    "Id10023",      # 9. Neonatal History
    "Id10025",      # 10. Child History
    "Id10026",      # 11. Adult History
    "Id10009",      # 12. Symptoms
    "Id10006",      # 13. Cause of Death
    "Id10012",      # 14. Final Notes
]

# Category display names (derived from Excel category column)
CATEGORY_NAMES = {
    "Id10007": "Identification",
    "Id10011": "Demographics",
    "Id10058": "Household",
    "Id10008": "Neighbourhood",
    "Id10010": "Neighbourhood (Environmental)",
    "Id10022": "Family History",
    "Id10018": "Pregnancy History",
    "Id10021": "Birth History",
    "Id10023": "Neonatal History",
    "Id10025": "Child History",
    "Id10026": "Adult History",
    "Id10009": "Symptoms",
    "Id10006": "Cause of Death",
    "Id10012": "Final Notes",
}


class Who2022VaMigrator:
    """Handles migration of WHO_2022_VA data from Excel to database."""

    FORM_TYPE_CODE = "WHO_2022_VA"
    FORM_TYPE_NAME = "WHO 2022 VA Form"

    def __init__(self):
        self.resource_path = Path("resource/mapping")
        self.stats = {
            "categories": 0,
            "subcategories": 0,
            "fields": 0,
            "choices": 0,
            "errors": [],
        }

    def run(self):
        """Execute full migration."""
        print(f"\n{'='*60}")
        print("WHO_2022_VA Data Migration")
        print(f"{'='*60}\n")

        try:
            # Step 1: Create form type
            form_type = self._create_form_type()
            print(f"[OK] Form type: {form_type.form_type_code}")

            # Step 2: Migrate categories
            self._migrate_categories(form_type)
            print(f"[OK] Categories: {self.stats['categories']}")

            # Step 3: Migrate field configs (includes sub-categories)
            self._migrate_field_configs(form_type)
            print(f"[OK] Sub-categories: {self.stats['subcategories']}")
            print(f"[OK] Field configs: {self.stats['fields']}")

            # Step 4: Migrate choice mappings
            self._migrate_choices(form_type)
            print(f"[OK] Choice mappings: {self.stats['choices']}")

            # Commit all changes
            db.session.commit()
            print(f"\n{'='*60}")
            print("Migration completed successfully!")
            print(f"{'='*60}\n")

            return True

        except Exception as e:
            db.session.rollback()
            print(f"\n[ERROR] Migration failed: {e}")
            self.stats["errors"].append(str(e))
            return False

    def _create_form_type(self) -> MasFormTypes:
        """Create or get WHO_2022_VA form type."""
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == self.FORM_TYPE_CODE
            )
        )

        if form_type:
            print(f"[INFO] Form type already exists, updating...")
            form_type.updated_at = datetime.now(timezone.utc)
        else:
            form_type = MasFormTypes(
                form_type_id=uuid.uuid4(),
                form_type_code=self.FORM_TYPE_CODE,
                form_type_name=self.FORM_TYPE_NAME,
                form_type_description="World Health Organization 2022 Verbal Autopsy Form",
                base_template_path="resource/mapping/mapping_labels.xlsx",
                mapping_version=1,
                is_active=True,
            )
            db.session.add(form_type)

        db.session.flush()
        return form_type

    def _migrate_categories(self, form_type: MasFormTypes):
        """Migrate category order from hardcoded list."""
        for order, category_code in enumerate(WHO_2022_CATEGORIES, start=1):
            existing = db.session.scalar(
                db.select(MasCategoryOrder).where(
                    MasCategoryOrder.form_type_id == form_type.form_type_id,
                    MasCategoryOrder.category_code == category_code,
                )
            )

            if existing:
                existing.display_order = order
                existing.category_name = CATEGORY_NAMES.get(category_code, category_code)
                existing.is_active = True
            else:
                category = MasCategoryOrder(
                    category_order_id=uuid.uuid4(),
                    form_type_id=form_type.form_type_id,
                    category_code=category_code,
                    category_name=CATEGORY_NAMES.get(category_code, category_code),
                    display_order=order,
                    is_active=True,
                )
                db.session.add(category)

            self.stats["categories"] += 1

        db.session.flush()

    def _migrate_field_configs(self, form_type: MasFormTypes):
        """Migrate field display configurations from mapping_labels.xlsx."""
        labels_path = self.resource_path / "mapping_labels.xlsx"

        if not labels_path.exists():
            raise FileNotFoundError(f"Labels file not found: {labels_path}")

        df = pd.read_excel(labels_path)

        # Track unique sub-categories
        seen_subcategories = set()

        for idx, row in df.iterrows():
            field_id = str(row.get("name", "")).strip()

            if not field_id:
                continue

            category_code = str(row.get("category", "")).strip() or None
            subcategory_code = str(row.get("sub_category", "")).strip() or None

            # Create sub-category if needed
            if category_code and subcategory_code:
                subcat_key = (category_code, subcategory_code)
                if subcat_key not in seen_subcategories:
                    self._create_subcategory(form_type, category_code, subcategory_code)
                    seen_subcategories.add(subcat_key)

            # Create or update field config
            existing = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )

            if existing:
                # Update existing
                existing.category_code = category_code
                existing.subcategory_code = subcategory_code
                existing.short_label = str(row.get("short_label", "")).strip() or None
                existing.full_label = str(row.get("full_label", "")).strip() or None
                existing.summary_label = str(row.get("summary_label", "")).strip() or None
                existing.flip_color = bool(row.get("flip_color", False))
                existing.is_info = bool(row.get("is_info", False))
                existing.summary_include = bool(row.get("summary_include", False))
                existing.display_order = idx + 1
                existing.updated_at = datetime.now(timezone.utc)
            else:
                # Create new
                config = MasFieldDisplayConfig(
                    config_id=uuid.uuid4(),
                    form_type_id=form_type.form_type_id,
                    field_id=field_id,
                    category_code=category_code,
                    subcategory_code=subcategory_code,
                    short_label=str(row.get("short_label", "")).strip() or None,
                    full_label=str(row.get("full_label", "")).strip() or None,
                    summary_label=str(row.get("summary_label", "")).strip() or None,
                    flip_color=bool(row.get("flip_color", False)),
                    is_info=bool(row.get("is_info", False)),
                    summary_include=bool(row.get("summary_include", False)),
                    display_order=idx + 1,
                    is_active=True,
                    is_custom=False,
                )
                db.session.add(config)

            self.stats["fields"] += 1

        db.session.flush()

    def _create_subcategory(self, form_type: MasFormTypes,
                            category_code: str, subcategory_code: str):
        """Create sub-category if it doesn't exist."""
        existing = db.session.scalar(
            db.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == subcategory_code,
            )
        )

        if not existing:
            # Calculate order based on when we see it (Excel row order)
            max_order = db.session.scalar(
                db.select(db.func.max(MasSubcategoryOrder.display_order)).where(
                    MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                    MasSubcategoryOrder.category_code == category_code,
                )
            ) or 0

            subcategory = MasSubcategoryOrder(
                subcategory_order_id=uuid.uuid4(),
                form_type_id=form_type.form_type_id,
                category_code=category_code,
                subcategory_code=subcategory_code,
                subcategory_name=subcategory_code,  # Use code as name initially
                display_order=max_order + 1,
                is_active=True,
            )
            db.session.add(subcategory)

        self.stats["subcategories"] += 1

    def _migrate_choices(self, form_type: MasFormTypes):
        """Migrate choice mappings from mapping_choices.xlsx."""
        choices_path = self.resource_path / "mapping_choices.xlsx"

        if not choices_path.exists():
            raise FileNotFoundError(f"Choices file not found: {choices_path}")

        df = pd.read_excel(choices_path)

        # Track order per field
        field_order = {}

        for idx, row in df.iterrows():
            field_id = str(row.get("category", "")).strip()  # 'category' is field_id
            choice_value = str(row.get("name", "")).strip()
            choice_label = str(row.get("short_label", "")).strip()

            if not field_id or not choice_value:
                continue

            # Track display order per field
            if field_id not in field_order:
                field_order[field_id] = 0
            field_order[field_id] += 1

            # Create or update choice mapping
            existing = db.session.scalar(
                db.select(MasChoiceMappings).where(
                    MasChoiceMappings.form_type_id == form_type.form_type_id,
                    MasChoiceMappings.field_id == field_id,
                    MasChoiceMappings.choice_value == choice_value,
                )
            )

            if existing:
                existing.choice_label = choice_label
                existing.display_order = field_order[field_id]
                existing.is_active = True
                existing.synced_at = datetime.now(timezone.utc)
            else:
                choice = MasChoiceMappings(
                    choice_id=uuid.uuid4(),
                    form_type_id=form_type.form_type_id,
                    field_id=field_id,
                    choice_value=choice_value,
                    choice_label=choice_label,
                    display_order=field_order[field_id],
                    is_active=True,
                )
                db.session.add(choice)

            self.stats["choices"] += 1

        db.session.flush()


def run_migration():
    """Entry point for migration script."""
    from app import create_app

    app = create_app()
    with app.app_context():
        migrator = Who2022VaMigrator()
        success = migrator.run()

        if not success:
            print("\nMigration errors:")
            for error in migrator.stats["errors"]:
                print(f"  - {error}")

        return success


if __name__ == "__main__":
    run_migration()
```

---

## Step 2.2: Create Migration Tests (TDD)

**File**: `tests/migrations/test_migrate_who_2022_va.py`

```python
"""
Tests for WHO_2022_VA data migration.

These tests verify:
1. All Excel data is migrated
2. No data is lost
3. Order is preserved
4. Migration is idempotent
"""
import pytest
import pandas as pd
from pathlib import Path
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)
from app.services.migrations.migrate_who_2022_va import (
    Who2022VaMigrator,
    WHO_2022_CATEGORIES,
)
from tests.base import BaseTestCase


class TestWho2022VaMigration(BaseTestCase):
    """Test WHO_2022_VA data migration."""

    def setUp(self):
        super().setUp()
        self.resource_path = Path("resource/mapping")
        self.labels_path = self.resource_path / "mapping_labels.xlsx"
        self.choices_path = self.resource_path / "mapping_choices.xlsx"

    def test_01_excel_files_exist(self):
        """Verify source Excel files exist."""
        self.assertTrue(self.labels_path.exists(),
                       f"Labels file missing: {self.labels_path}")
        self.assertTrue(self.choices_path.exists(),
                       f"Choices file missing: {self.choices_path}")

    def test_02_excel_row_counts(self):
        """Verify Excel file row counts match expectations."""
        labels_df = pd.read_excel(self.labels_path)
        choices_df = pd.read_excel(self.choices_path)

        # Expected: 427 field configs, 1199 choices
        self.assertEqual(len(labels_df), 427,
                        f"Expected 427 labels, got {len(labels_df)}")
        self.assertEqual(len(choices_df), 1199,
                        f"Expected 1199 choices, got {len(choices_df)}")

    def test_03_migration_creates_form_type(self):
        """Migration creates WHO_2022_VA form type."""
        migrator = Who2022VaMigrator()
        success = migrator.run()

        self.assertTrue(success, "Migration should succeed")

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        self.assertIsNotNone(form_type)
        self.assertEqual(form_type.form_type_name, "WHO 2022 VA Form")
        self.assertTrue(form_type.is_active)

    def test_04_all_categories_migrated(self):
        """All 14 categories are migrated with correct order."""
        migrator = Who2022VaMigrator()
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        categories = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()

        self.assertEqual(len(categories), 14, "Should have 14 categories")

        # Verify order matches hardcoded list
        for i, cat in enumerate(categories):
            expected_code = WHO_2022_CATEGORIES[i]
            self.assertEqual(cat.category_code, expected_code,
                           f"Category {i+1} should be {expected_code}, got {cat.category_code}")
            self.assertEqual(cat.display_order, i + 1)

    def test_05_all_field_configs_migrated(self):
        """All 427 field configs are migrated."""
        migrator = Who2022VaMigrator()
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        )

        self.assertEqual(count, 427, "Should have 427 field configs")

    def test_06_all_choices_migrated(self):
        """All 1199 choice mappings are migrated."""
        migrator = Who2022VaMigrator()
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        )

        self.assertEqual(count, 1199, "Should have 1199 choice mappings")

    def test_07_no_data_loss_field_configs(self):
        """Verify no field configs lost - compare Excel to DB."""
        migrator = Who2022VaMigrator()
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        # Load Excel data
        labels_df = pd.read_excel(self.labels_path)
        excel_fields = set(labels_df["name"].dropna().str.strip().tolist())

        # Load DB data
        db_fields = set(db.session.scalars(
            db.select(MasFieldDisplayConfig.field_id)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        ).all())

        # Compare
        missing_in_db = excel_fields - db_fields
        extra_in_db = db_fields - excel_fields

        self.assertEqual(len(missing_in_db), 0,
                        f"Fields missing in DB: {missing_in_db}")
        self.assertEqual(len(extra_in_db), 0,
                        f"Extra fields in DB: {extra_in_db}")

    def test_08_no_data_loss_choices(self):
        """Verify no choice mappings lost - compare Excel to DB."""
        migrator = Who2022VaMigrator()
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        # Load Excel data
        choices_df = pd.read_excel(self.choices_path)
        excel_choices = set(
            (row["category"], row["name"])  # (field_id, choice_value)
            for _, row in choices_df.iterrows()
            if pd.notna(row["category"]) and pd.notna(row["name"])
        )

        # Load DB data
        db_choices = set(db.session.execute(
            db.select(MasChoiceMappings.field_id, MasChoiceMappings.choice_value)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        ).all())

        # Compare
        missing_in_db = excel_choices - db_choices
        extra_in_db = db_choices - excel_choices

        self.assertEqual(len(missing_in_db), 0,
                        f"Choices missing in DB: {missing_in_db}")
        self.assertEqual(len(extra_in_db), 0,
                        f"Extra choices in DB: {extra_in_db}")

    def test_09_migration_is_idempotent(self):
        """Running migration twice doesn't duplicate data."""
        migrator = Who2022VaMigrator()

        # First run
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        field_count_1 = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        )

        choice_count_1 = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        )

        # Second run
        migrator.run()

        field_count_2 = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        )

        choice_count_2 = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        )

        # Counts should be identical
        self.assertEqual(field_count_1, field_count_2,
                        "Field count should not change on re-run")
        self.assertEqual(choice_count_1, choice_count_2,
                        "Choice count should not change on re-run")

    def test_10_subcategories_created(self):
        """Sub-categories are created from field configs."""
        migrator = Who2022VaMigrator()
        migrator.run()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        # Load Excel to count unique sub-categories
        labels_df = pd.read_excel(self.labels_path)
        excel_subcats = set(
            (row["category"], row["sub_category"])
            for _, row in labels_df.iterrows()
            if pd.notna(row["category"]) and pd.notna(row["sub_category"])
        )

        # Count DB sub-categories
        db_subcat_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasSubcategoryOrder)
            .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
        )

        self.assertEqual(db_subcat_count, len(excel_subcats),
                        f"Expected {len(excel_subcats)} sub-categories, got {db_subcat_count}")
```

---

## Step 2.3: Run Migration

```bash
# 1. Run tests first (TDD - should fail initially)
docker compose exec minerva_app_service uv run pytest tests/migrations/test_migrate_who_2022_va.py -v

# 2. Create migrations directory if needed
mkdir -p app/services/migrations
touch app/services/migrations/__init__.py

# 3. Run migration script
docker compose exec minerva_app_service uv run python -m app.services.migrations.migrate_who_2022_va

# 4. Re-run tests (should pass now)
docker compose exec minerva_app_service uv run pytest tests/migrations/test_migrate_who_2022_va.py -v
```

---

## Step 2.4: Manual Verification

After migration, verify counts manually:

```bash
# Check all tables have data
docker compose exec minerva_db_service psql -U minerva -d minerva -c "
SELECT
    'Form Types' as table_name, COUNT(*) as count FROM mas_form_types
UNION ALL
SELECT 'Categories', COUNT(*) FROM mas_category_order
UNION ALL
SELECT 'Sub-Categories', COUNT(*) FROM mas_subcategory_order
UNION ALL
SELECT 'Field Configs', COUNT(*) FROM mas_field_display_config
UNION ALL
SELECT 'Choice Mappings', COUNT(*) FROM mas_choice_mappings;
"

# Expected output:
#      table_name     | count
# --------------------+-------
#  Form Types         |     1
#  Categories         |    14
#  Sub-Categories     |    35+ (depends on Excel)
#  Field Configs      |   427
#  Choice Mappings    |  1199

# Verify category order
docker compose exec minerva_db_service psql -U minerva -d minerva -c "
SELECT category_code, category_name, display_order
FROM mas_category_order
ORDER BY display_order;
"

# Sample field configs
docker compose exec minerva_db_service psql -U minerva -d minerva -c "
SELECT field_id, category_code, short_label, display_order
FROM mas_field_display_config
WHERE category_code = 'Id10007'
ORDER BY display_order
LIMIT 5;
"

# Sample choice mappings
docker compose exec minerva_db_service psql -U minerva -d minerva -c "
SELECT field_id, choice_value, choice_label, display_order
FROM mas_choice_mappings
WHERE field_id = 'Id10007'
ORDER BY display_order
LIMIT 5;
"
```

---

## Verification Checklist

After completing Phase 2:

- [ ] All tests in `test_migrate_who_2022_va.py` pass
- [ ] Form type count: 1
- [ ] Category count: 14
- [ ] Sub-category count: matches Excel unique values
- [ ] Field config count: 427
- [ ] Choice mapping count: 1199
- [ ] Category order matches hardcoded list
- [ ] No data loss (Excel to DB comparison passes)
- [ ] Migration is idempotent (re-run doesn't duplicate)

---

## Data Comparison Script

**File**: `scripts/verify_migration.py`

```python
"""
Verify migration by comparing Excel data to database data.
Run this after migration to ensure 100% match.
"""
import pandas as pd
from pathlib import Path
from app import create_app, db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


def verify_migration():
    """Compare Excel data to database and report differences."""
    app = create_app()
    with app.app_context():
        print("\n" + "="*60)
        print("Migration Verification Report")
        print("="*60 + "\n")

        # Get form type
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        if not form_type:
            print("[ERROR] WHO_2022_VA form type not found!")
            return False

        errors = []

        # 1. Verify categories
        print("1. Verifying categories...")
        db_categories = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()

        if len(db_categories) != 14:
            errors.append(f"Category count: expected 14, got {len(db_categories)}")
        print(f"   Categories: {len(db_categories)} (expected 14)")

        # 2. Verify field configs
        print("2. Verifying field configs...")
        labels_df = pd.read_excel("resource/mapping/mapping_labels.xlsx")
        excel_field_count = len(labels_df)

        db_field_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        )

        if db_field_count != excel_field_count:
            errors.append(f"Field count: expected {excel_field_count}, got {db_field_count}")
        print(f"   Field configs: {db_field_count} (expected {excel_field_count})")

        # 3. Verify choices
        print("3. Verifying choice mappings...")
        choices_df = pd.read_excel("resource/mapping/mapping_choices.xlsx")
        excel_choice_count = len(choices_df)

        db_choice_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        )

        if db_choice_count != excel_choice_count:
            errors.append(f"Choice count: expected {excel_choice_count}, got {db_choice_count}")
        print(f"   Choice mappings: {db_choice_count} (expected {excel_choice_count})")

        # 4. Verify field-level data
        print("4. Verifying field-level data...")
        excel_fields = set(labels_df["name"].dropna().str.strip().tolist())
        db_fields = set(db.session.scalars(
            db.select(MasFieldDisplayConfig.field_id)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        ).all())

        missing = excel_fields - db_fields
        if missing:
            errors.append(f"Fields missing in DB: {missing}")
        print(f"   Missing fields: {len(missing)}")

        # Summary
        print("\n" + "="*60)
        if errors:
            print("VERIFICATION FAILED")
            print("="*60 + "\n")
            for error in errors:
                print(f"  [ERROR] {error}")
            return False
        else:
            print("VERIFICATION PASSED")
            print("="*60 + "\n")
            print("  All data migrated successfully!")
            return True


if __name__ == "__main__":
    verify_migration()
```

---

## Rollback Procedure

If Phase 2 fails or verification fails:

```bash
# 1. Delete migrated data (keep tables)
docker compose exec minerva_db_service psql -U minerva -d minerva -c "
DELETE FROM mas_choice_mappings;
DELETE FROM mas_field_display_config;
DELETE FROM mas_subcategory_order;
DELETE FROM mas_category_order;
DELETE FROM mas_form_types;
"

# 2. Re-run migration after fixing issues
docker compose exec minerva_app_service uv run python -m app.services.migrations.migrate_who_2022_va
```

---

## Next Phase

After Phase 2 verification passes, proceed to:
**[Phase 3: Verify Migration Completeness](03-phase3-verify-migration.md)**
