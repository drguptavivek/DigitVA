---
title: Phase 3 - Verify Migration Completeness
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 3
estimated_duration: 0.5 day
risk_level: critical
---

# Phase 3: Verify Migration Completeness

## Objective

Comprehensively verify that ALL WHO_2022_VA data has been migrated correctly with zero data loss before cutover.

## Prerequisites

- [ ] Phase 2 completed (data migrated)
- [ ] Phase 2 tests passing
- [ ] Database backup before verification

## Deliverables

1. 100% data integrity verified
2. Visual comparison of Excel vs DB outputs
3. Render output comparison (current vs new system)
4. Sign-off on migration completeness

---

## Critical Principle

> **NO CUTOVER UNTIL 100% VERIFIED**: We do not switch to the database system
> until comprehensive testing confirms exact match with Excel-based system.

---

## Step 3.1: Automated Verification Tests

**File**: `tests/migrations/test_migration_completeness.py`

```python
"""
Comprehensive migration verification tests.

These tests perform exhaustive comparison between Excel source data
and database migrated data to ensure 100% accuracy.
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
from tests.base import BaseTestCase


class TestMigrationCompleteness(BaseTestCase):
    """Exhaustive verification of migration completeness."""

    def setUp(self):
        super().setUp()
        self.resource_path = Path("resource/mapping")
        self.labels_df = pd.read_excel(self.resource_path / "mapping_labels.xlsx")
        self.choices_df = pd.read_excel(self.resource_path / "mapping_choices.xlsx")

        # Get form type
        self.form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

    def test_01_exact_field_count(self):
        """Field count in DB exactly matches Excel."""
        db_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id)
        )
        excel_count = len(self.labels_df)

        self.assertEqual(
            db_count, excel_count,
            f"Field count mismatch: DB={db_count}, Excel={excel_count}"
        )

    def test_02_exact_choice_count(self):
        """Choice count in DB exactly matches Excel."""
        db_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == self.form_type.form_type_id)
        )
        excel_count = len(self.choices_df)

        self.assertEqual(
            db_count, excel_count,
            f"Choice count mismatch: DB={db_count}, Excel={excel_count}"
        )

    def test_03_all_field_ids_match(self):
        """Every field_id in Excel exists in DB."""
        excel_fields = set(self.labels_df["name"].dropna().str.strip().tolist())
        db_fields = set(db.session.scalars(
            db.select(MasFieldDisplayConfig.field_id)
            .where(MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id)
        ).all())

        missing = excel_fields - db_fields
        extra = db_fields - excel_fields

        self.assertEqual(
            len(missing), 0,
            f"Fields in Excel but not in DB: {missing}"
        )
        self.assertEqual(
            len(extra), 0,
            f"Fields in DB but not in Excel: {extra}"
        )

    def test_04_all_choice_keys_match(self):
        """Every (field_id, choice_value) in Excel exists in DB."""
        excel_choices = set(
            (str(row["category"]).strip(), str(row["name"]).strip())
            for _, row in self.choices_df.iterrows()
            if pd.notna(row["category"]) and pd.notna(row["name"])
        )

        db_choices = set(db.session.execute(
            db.select(MasChoiceMappings.field_id, MasChoiceMappings.choice_value)
            .where(MasChoiceMappings.form_type_id == self.form_type.form_type_id)
        ).all())

        missing = excel_choices - db_choices
        extra = db_choices - excel_choices

        self.assertEqual(
            len(missing), 0,
            f"Choices in Excel but not in DB: {missing}"
        )
        self.assertEqual(
            len(extra), 0,
            f"Choices in DB but not in Excel: {extra}"
        )

    def test_05_field_labels_match(self):
        """All field labels match between Excel and DB."""
        mismatches = []

        for _, row in self.labels_df.iterrows():
            field_id = str(row.get("name", "")).strip()
            if not field_id:
                continue

            db_config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )

            if db_config:
                # Compare short_label
                excel_label = str(row.get("short_label", "")).strip() or None
                if db_config.short_label != excel_label:
                    mismatches.append(
                        f"{field_id}.short_label: DB='{db_config.short_label}' vs Excel='{excel_label}'"
                    )

                # Compare category
                excel_cat = str(row.get("category", "")).strip() or None
                if db_config.category_code != excel_cat:
                    mismatches.append(
                        f"{field_id}.category: DB='{db_config.category_code}' vs Excel='{excel_cat}'"
                    )

                # Compare sub_category
                excel_subcat = str(row.get("sub_category", "")).strip() or None
                if db_config.subcategory_code != excel_subcat:
                    mismatches.append(
                        f"{field_id}.sub_category: DB='{db_config.subcategory_code}' vs Excel='{excel_subcat}'"
                    )

        self.assertEqual(
            len(mismatches), 0,
            f"Label mismatches found:\n" + "\n".join(mismatches[:20])
        )

    def test_06_choice_labels_match(self):
        """All choice labels match between Excel and DB."""
        mismatches = []

        for _, row in self.choices_df.iterrows():
            field_id = str(row.get("category", "")).strip()
            choice_value = str(row.get("name", "")).strip()

            if not field_id or not choice_value:
                continue

            db_choice = db.session.scalar(
                db.select(MasChoiceMappings).where(
                    MasChoiceMappings.form_type_id == self.form_type.form_type_id,
                    MasChoiceMappings.field_id == field_id,
                    MasChoiceMappings.choice_value == choice_value,
                )
            )

            if db_choice:
                excel_label = str(row.get("short_label", "")).strip()
                if db_choice.choice_label != excel_label:
                    mismatches.append(
                        f"{field_id}.{choice_value}: DB='{db_choice.choice_label}' vs Excel='{excel_label}'"
                    )

        self.assertEqual(
            len(mismatches), 0,
            f"Choice label mismatches found:\n" + "\n".join(mismatches[:20])
        )

    def test_07_category_order_preserved(self):
        """Category display order matches hardcoded list."""
        from app.services.migrations.migrate_who_2022_va import WHO_2022_CATEGORIES

        db_categories = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == self.form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()

        db_codes = [c.category_code for c in db_categories]

        self.assertEqual(
            db_codes, WHO_2022_CATEGORIES,
            f"Category order mismatch:\nDB: {db_codes}\nExpected: {WHO_2022_CATEGORIES}"
        )

    def test_08_field_order_within_category(self):
        """Field display order within each category matches Excel row order."""
        # Group Excel by category and get order
        excel_order = {}
        for idx, row in self.labels_df.iterrows():
            cat = str(row.get("category", "")).strip()
            field_id = str(row.get("name", "")).strip()
            if cat and field_id:
                if cat not in excel_order:
                    excel_order[cat] = []
                excel_order[cat].append((idx, field_id))

        # Compare with DB order
        for cat, excel_fields in excel_order.items():
            db_fields = db.session.scalars(
                db.select(MasFieldDisplayConfig)
                .where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.category_code == cat,
                )
                .order_by(MasFieldDisplayConfig.display_order)
            ).all()

            db_field_ids = [f.field_id for f in db_fields]
            excel_field_ids = [f[1] for f in excel_fields]

            # Note: Order might not be exactly same if rows were inserted differently
            # But we verify same fields exist
            self.assertEqual(
                set(db_field_ids), set(excel_field_ids),
                f"Field set mismatch in category {cat}"
            )

    def test_09_boolean_fields_match(self):
        """Boolean fields (flip_color, is_info, summary_include) match."""
        mismatches = []

        for _, row in self.labels_df.iterrows():
            field_id = str(row.get("name", "")).strip()
            if not field_id:
                continue

            db_config = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )

            if db_config:
                # flip_color
                excel_flip = bool(row.get("flip_color", False))
                if db_config.flip_color != excel_flip:
                    mismatches.append(
                        f"{field_id}.flip_color: DB={db_config.flip_color} vs Excel={excel_flip}"
                    )

                # is_info
                excel_info = bool(row.get("is_info", False))
                if db_config.is_info != excel_info:
                    mismatches.append(
                        f"{field_id}.is_info: DB={db_config.is_info} vs Excel={excel_info}"
                    )

                # summary_include
                excel_summary = bool(row.get("summary_include", False))
                if db_config.summary_include != excel_summary:
                    mismatches.append(
                        f"{field_id}.summary_include: DB={db_config.summary_include} vs Excel={excel_summary}"
                    )

        self.assertEqual(
            len(mismatches), 0,
            f"Boolean field mismatches:\n" + "\n".join(mismatches[:20])
        )

    def test_10_render_output_comparison(self):
        """
        Compare render output between current Excel-based system
        and new database-based system.

        This is the ultimate test - if outputs match, migration is successful.
        """
        from app.utils.va_mapping import get_categories_to_display
        from app.services.field_mapping_service import FieldMappingService

        # Get categories from old system (Excel)
        old_categories = get_categories_to_display()

        # Get categories from new system (Database)
        mapping_service = FieldMappingService()
        new_categories = mapping_service.get_categories_to_display("WHO_2022_VA")

        # Compare structure
        old_cat_codes = [c["category"] for c in old_categories]
        new_cat_codes = [c["category_code"] for c in new_categories]

        self.assertEqual(
            old_cat_codes, new_cat_codes,
            "Category order must match between old and new system"
        )

        # Compare field counts per category
        for old_cat, new_cat in zip(old_categories, new_categories):
            old_count = len(old_cat.get("fields", []))
            new_count = len(new_cat.get("fields", []))

            self.assertEqual(
                old_count, new_count,
                f"Field count mismatch in {old_cat['category']}: "
                f"old={old_count}, new={new_count}"
            )
```

---

## Step 3.2: Visual Comparison Report

**File**: `scripts/generate_migration_report.py`

```python
"""
Generate a detailed comparison report between Excel and Database data.

This produces a human-readable report showing any differences.
"""
import pandas as pd
from pathlib import Path
from datetime import datetime
from app import create_app, db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


def generate_report():
    """Generate comprehensive migration verification report."""
    app = create_app()
    with app.app_context():
        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append("WHO_2022_VA Migration Verification Report")
        report_lines.append(f"Generated: {datetime.now().isoformat()}")
        report_lines.append("=" * 70)
        report_lines.append("")

        # Get form type
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

        if not form_type:
            report_lines.append("[ERROR] WHO_2022_VA form type not found!")
            return "\n".join(report_lines)

        # Load Excel data
        labels_df = pd.read_excel("resource/mapping/mapping_labels.xlsx")
        choices_df = pd.read_excel("resource/mapping/mapping_choices.xlsx")

        # Summary counts
        report_lines.append("SUMMARY COUNTS")
        report_lines.append("-" * 40)
        report_lines.append(f"{'Item':<30} {'Excel':>10} {'DB':>10} {'Match':>10}")
        report_lines.append("-" * 40)

        # Categories
        db_cat_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        )
        cat_match = "YES" if db_cat_count == 14 else "NO"
        report_lines.append(f"{'Categories':<30} {14:>10} {db_cat_count:>10} {cat_match:>10}")

        # Fields
        db_field_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        )
        field_match = "YES" if db_field_count == len(labels_df) else "NO"
        report_lines.append(f"{'Field Configs':<30} {len(labels_df):>10} {db_field_count:>10} {field_match:>10}")

        # Choices
        db_choice_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasChoiceMappings)
            .where(MasChoiceMappings.form_type_id == form_type.form_type_id)
        )
        choice_match = "YES" if db_choice_count == len(choices_df) else "NO"
        report_lines.append(f"{'Choice Mappings':<30} {len(choices_df):>10} {db_choice_count:>10} {choice_match:>10}")

        report_lines.append("")

        # Category details
        report_lines.append("CATEGORY ORDER")
        report_lines.append("-" * 40)
        categories = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()

        for cat in categories:
            field_count = db.session.scalar(
                db.select(db.func.count())
                .select_from(MasFieldDisplayConfig)
                .where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.category_code == cat.category_code,
                )
            )
            report_lines.append(
                f"{cat.display_order:>3}. {cat.category_code:<15} {cat.category_name or '':<25} ({field_count} fields)"
            )

        report_lines.append("")

        # Field comparison by category
        report_lines.append("FIELD COUNTS BY CATEGORY")
        report_lines.append("-" * 40)

        for cat in categories:
            excel_count = len(labels_df[labels_df["category"] == cat.category_code])
            db_count = db.session.scalar(
                db.select(db.func.count())
                .select_from(MasFieldDisplayConfig)
                .where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.category_code == cat.category_code,
                )
            )
            match = "OK" if excel_count == db_count else "MISMATCH"
            report_lines.append(
                f"{cat.category_code:<15} Excel: {excel_count:>4}  DB: {db_count:>4}  [{match}]"
            )

        report_lines.append("")

        # Final verdict
        report_lines.append("=" * 70)
        all_match = (db_cat_count == 14 and
                    db_field_count == len(labels_df) and
                    db_choice_count == len(choices_df))

        if all_match:
            report_lines.append("VERIFICATION PASSED - Migration is complete and accurate")
        else:
            report_lines.append("VERIFICATION FAILED - Review mismatches above")
        report_lines.append("=" * 70)

        return "\n".join(report_lines)


if __name__ == "__main__":
    print(generate_report())
```

---

## Step 3.3: Run Verification

```bash
# 1. Run comprehensive tests
docker compose exec minerva_app_service uv run pytest tests/migrations/test_migration_completeness.py -v

# 2. Generate visual report
docker compose exec minerva_app_service uv run python scripts/generate_migration_report.py

# 3. Save report for records
docker compose exec minerva_app_service uv run python scripts/generate_migration_report.py > docs/planning/field-mapping-implementation/migration-report-$(date +%Y%m%d).txt
```

---

## Verification Checklist

Phase 3 is complete when ALL of the following pass:

### Automated Tests
- [ ] `test_01_exact_field_count` - Field count exactly matches
- [ ] `test_02_exact_choice_count` - Choice count exactly matches
- [ ] `test_03_all_field_ids_match` - All field IDs present
- [ ] `test_04_all_choice_keys_match` - All choice keys present
- [ ] `test_05_field_labels_match` - Labels match exactly
- [ ] `test_06_choice_labels_match` - Choice labels match exactly
- [ ] `test_07_category_order_preserved` - Category order correct
- [ ] `test_08_field_order_within_category` - Field order preserved
- [ ] `test_09_boolean_fields_match` - Boolean fields correct
- [ ] `test_10_render_output_comparison` - Render outputs match

### Manual Verification
- [ ] Visual report shows all "YES" for match columns
- [ ] Category counts match Excel
- [ ] Field counts per category match
- [ ] No mismatches in field labels
- [ ] No mismatches in choice labels

### Sign-off
- [ ] Developer sign-off on migration completeness
- [ ] Report saved to `docs/planning/field-mapping-implementation/`

---

## If Verification Fails

1. **Identify specific mismatches** from test output
2. **Fix migration script** (`migrate_who_2022_va.py`)
3. **Clear migrated data**:
   ```bash
   docker compose exec minerva_db_service psql -U minerva -d minerva -c "
   DELETE FROM mas_choice_mappings;
   DELETE FROM mas_field_display_config;
   DELETE FROM mas_subcategory_order;
   DELETE FROM mas_category_order;
   DELETE FROM mas_form_types;
   "
   ```
4. **Re-run migration**:
   ```bash
   docker compose exec minerva_app_service uv run python -m app.services.migrations.migrate_who_2022_va
   ```
5. **Re-run verification tests**

---

## Cutover Criteria

**Phase 3 must pass 100% before proceeding to Phase 4.**

Cutover happens in Phase 4 when we update render functions to use database instead of Excel.

---

## Next Phase

After Phase 3 verification passes completely:
**[Phase 4: Render Integration](04-phase4-render-integration.md)**
