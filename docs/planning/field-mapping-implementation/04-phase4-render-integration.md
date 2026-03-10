---
title: Phase 4 - Render Integration
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 4
estimated_duration: 1 day
risk_level: medium
---

# Phase 4: Render Integration

## Objective

Update the render functions to use the database-backed field mapping system instead of Excel files. This is the **cutover phase**.

## Prerequisites

- [ ] Phase 3 completed (100% verification passed)
- [ ] All verification tests passing
- [ ] Migration report signed off
- [ ] Database backup before cutover

## Deliverables

1. Field mapping service created
2. Render functions updated to use service
3. Excel-based code deprecated (not deleted)
4. All existing functionality works with database
5. Tests confirm identical output

---

## Cutover Approach

```
┌─────────────────────────────────────────────────────────────────────┐
│ CUTOVER PHASE                                                       │
│                                                                      │
│  Before: Excel files → Python modules → Render                      │
│  After:  Database → Field Mapping Service → Render                  │
│                                                                      │
│  This is a CLEAN CUTOVER - no parallel operation.                   │
│  We verified in Phase 3 that outputs match exactly.                 │
│                                                                      │
│  Rollback: Revert code changes, continue with Excel                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step 4.1: Create Field Mapping Service

**File**: `app/services/field_mapping_service.py`

```python
"""
Field Mapping Service

Provides unified access to field display configuration and choice mappings
from the database. Replaces the Excel-based mapping system.
"""
import uuid
from typing import Optional
from sqlalchemy import select
from flask import current_app
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


class FieldMappingService:
    """
    Service for accessing field mapping configuration from database.

    This service replaces the Excel-based mapping system and provides:
    - Category/sub-category ordering
    - Field display configuration
    - Choice value-to-label mappings
    - PII field identification
    """

    def get_form_type(self, form_type_code: str) -> Optional[MasFormTypes]:
        """Get form type by code."""
        return db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code,
                MasFormTypes.is_active == True,
            )
        )

    def get_categories(self, form_type_code: str) -> list[dict]:
        """
        Get ordered categories for a form type.

        Returns list of dicts with:
        - category_code
        - category_name
        - display_order
        """
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return []

        categories = db.session.scalars(
            select(MasCategoryOrder)
            .where(
                MasCategoryOrder.form_type_id == form_type.form_type_id,
                MasCategoryOrder.is_active == True,
            )
            .order_by(MasCategoryOrder.display_order)
        ).all()

        return [
            {
                "category_code": cat.category_code,
                "category_name": cat.category_name or cat.category_code,
                "display_order": cat.display_order,
            }
            for cat in categories
        ]

    def get_categories_to_display(self, form_type_code: str) -> list[dict]:
        """
        Get categories with fields for display rendering.

        This replaces the old get_categories_to_display() function
        from va_preprocess_03_categoriestodisplay.py.

        Returns list of dicts with:
        - category_code
        - category_name
        - display_order
        - fields: list of field configs
        - subcategories: list of subcategory dicts
        """
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return []

        categories = db.session.scalars(
            select(MasCategoryOrder)
            .where(
                MasCategoryOrder.form_type_id == form_type.form_type_id,
                MasCategoryOrder.is_active == True,
            )
            .order_by(MasCategoryOrder.display_order)
        ).all()

        result = []
        for cat in categories:
            # Get fields for this category
            fields = self._get_category_fields(form_type.form_type_id, cat.category_code)

            # Get subcategories for this category
            subcategories = self._get_subcategories(form_type.form_type_id, cat.category_code)

            result.append({
                "category_code": cat.category_code,
                "category_name": cat.category_name or cat.category_code,
                "display_order": cat.display_order,
                "fields": fields,
                "subcategories": subcategories,
            })

        return result

    def _get_category_fields(self, form_type_id: uuid.UUID,
                             category_code: str) -> list[dict]:
        """Get all fields for a category."""
        fields = db.session.scalars(
            select(MasFieldDisplayConfig)
            .where(
                MasFieldDisplayConfig.form_type_id == form_type_id,
                MasFieldDisplayConfig.category_code == category_code,
                MasFieldDisplayConfig.is_active == True,
            )
            .order_by(MasFieldDisplayConfig.display_order)
        ).all()

        return [
            {
                "field_id": f.field_id,
                "short_label": f.short_label,
                "full_label": f.full_label,
                "summary_label": f.summary_label,
                "flip_color": f.flip_color,
                "is_info": f.is_info,
                "summary_include": f.summary_include,
                "is_pii": f.is_pii,
                "pii_type": f.pii_type,
                "subcategory_code": f.subcategory_code,
            }
            for f in fields
        ]

    def _get_subcategories(self, form_type_id: uuid.UUID,
                          category_code: str) -> list[dict]:
        """Get subcategories for a category."""
        subcategories = db.session.scalars(
            select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

        return [
            {
                "subcategory_code": sub.subcategory_code,
                "subcategory_name": sub.subcategory_name or sub.subcategory_code,
                "display_order": sub.display_order,
            }
            for sub in subcategories
        ]

    def get_field_config(self, form_type_code: str, field_id: str) -> Optional[dict]:
        """Get configuration for a specific field."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return None

        field = db.session.scalar(
            select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.field_id == field_id,
                MasFieldDisplayConfig.is_active == True,
            )
        )

        if not field:
            return None

        return {
            "field_id": field.field_id,
            "short_label": field.short_label,
            "full_label": field.full_label,
            "summary_label": field.summary_label,
            "flip_color": field.flip_color,
            "is_info": field.is_info,
            "summary_include": field.summary_include,
            "is_pii": field.is_pii,
            "pii_type": field.pii_type,
            "category_code": field.category_code,
            "subcategory_code": field.subcategory_code,
        }

    def get_choice_label(self, form_type_code: str, field_id: str,
                        choice_value: str) -> Optional[str]:
        """Get display label for a choice value."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return None

        choice = db.session.scalar(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.field_id == field_id,
                MasChoiceMappings.choice_value == choice_value,
                MasChoiceMappings.is_active == True,
            )
        )

        return choice.choice_label if choice else None

    def get_choices_for_field(self, form_type_code: str, field_id: str) -> list[dict]:
        """Get all choices for a field, ordered by display_order."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return []

        choices = db.session.scalars(
            select(MasChoiceMappings)
            .where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.field_id == field_id,
                MasChoiceMappings.is_active == True,
            )
            .order_by(MasChoiceMappings.display_order)
        ).all()

        return [
            {
                "value": c.choice_value,
                "label": c.choice_label,
                "display_order": c.display_order,
            }
            for c in choices
        ]

    def get_pii_fields(self, form_type_code: str) -> list[str]:
        """Get list of field_ids marked as PII for a form type."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return []

        fields = db.session.scalars(
            select(MasFieldDisplayConfig.field_id).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.is_pii == True,
                MasFieldDisplayConfig.is_active == True,
            )
        ).all()

        return list(fields)


# Singleton instance
_mapping_service = None

def get_mapping_service() -> FieldMappingService:
    """Get the field mapping service instance."""
    global _mapping_service
    if _mapping_service is None:
        _mapping_service = FieldMappingService()
    return _mapping_service
```

---

## Step 4.2: Update Render Functions

**File**: `app/utils/va_render_01_displayselected.py` (modify existing)

```python
"""
Display selected fields for VA review.

UPDATED: Now uses database-backed field mapping service instead of Excel.
"""
from app.services.field_mapping_service import get_mapping_service


def display_selected_fields(submission_data: dict, form_type_code: str = "WHO_2022_VA") -> dict:
    """
    Prepare submission data for display using field mapping configuration.

    Args:
        submission_data: Raw submission data from ODK
        form_type_code: Form type to use for mapping (default: WHO_2022_VA)

    Returns:
        Dict with categories and fields for display
    """
    mapping_service = get_mapping_service()

    # Get category structure with fields
    categories = mapping_service.get_categories_to_display(form_type_code)

    # Process each category
    result = []
    for cat in categories:
        category_data = {
            "category": cat["category_code"],
            "category_name": cat["category_name"],
            "display_order": cat["display_order"],
            "subcategories": [],
        }

        # Group fields by subcategory
        subcategory_fields = {}
        for field in cat["fields"]:
            subcat_code = field.get("subcategory_code") or "default"
            if subcat_code not in subcategory_fields:
                subcategory_fields[subcat_code] = {
                    "subcategory_code": subcat_code,
                    "fields": [],
                }

            # Get value from submission
            field_value = submission_data.get(field["field_id"])

            # Map choice values to labels if applicable
            if field_value is not None:
                choices = mapping_service.get_choices_for_field(form_type_code, field["field_id"])
                if choices:
                    choice_map = {c["value"]: c["label"] for c in choices}
                    if field_value in choice_map:
                        field_value = choice_map[field_value]

            field_data = {
                **field,
                "value": field_value,
            }
            subcategory_fields[subcat_code]["fields"].append(field_data)

        # Add subcategories in order
        for subcat in cat["subcategories"]:
            if subcat["subcategory_code"] in subcategory_fields:
                category_data["subcategories"].append(
                    subcategory_fields[subcat["subcategory_code"]]
                )

        result.append(category_data)

    return result
```

---

## Step 4.3: Create Integration Tests

**File**: `tests/integration/test_field_mapping_render.py`

```python
"""
Integration tests for field mapping render integration.

These tests verify that the database-backed system produces
identical output to the old Excel-based system.
"""
import pytest
from app import db
from app.models import MasFormTypes, MasFieldDisplayConfig, MasChoiceMappings
from app.services.field_mapping_service import get_mapping_service, FieldMappingService
from tests.base import BaseTestCase


class TestFieldMappingRenderIntegration(BaseTestCase):
    """Test render integration with database field mapping."""

    def setUp(self):
        super().setUp()
        self.service = get_mapping_service()
        self.form_type_code = "WHO_2022_VA"

    def test_01_service_returns_categories(self):
        """Service returns categories for WHO_2022_VA."""
        categories = self.service.get_categories(self.form_type_code)

        self.assertEqual(len(categories), 14)
        self.assertEqual(categories[0]["category_code"], "Id10007")

    def test_02_service_returns_category_structure(self):
        """Service returns full category structure with fields."""
        categories = self.service.get_categories_to_display(self.form_type_code)

        self.assertEqual(len(categories), 14)

        # First category should be Identification
        first_cat = categories[0]
        self.assertEqual(first_cat["category_code"], "Id10007")
        self.assertIn("fields", first_cat)
        self.assertIn("subcategories", first_cat)
        self.assertGreater(len(first_cat["fields"]), 0)

    def test_03_field_config_retrieval(self):
        """Individual field config can be retrieved."""
        # Get a known field (Id10007 is first category)
        config = self.service.get_field_config(self.form_type_code, "Id10007")

        self.assertIsNotNone(config)
        self.assertEqual(config["field_id"], "Id10007")
        self.assertIn("short_label", config)

    def test_04_choice_label_retrieval(self):
        """Choice labels can be retrieved."""
        # Get choices for a known field
        choices = self.service.get_choices_for_field(self.form_type_code, "Id10007")

        self.assertIsNotNone(choices)
        self.assertGreater(len(choices), 0)

        # Each choice should have value and label
        for choice in choices:
            self.assertIn("value", choice)
            self.assertIn("label", choice)

    def test_05_render_output_structure(self):
        """Render output has correct structure."""
        from app.utils.va_render_01_displayselected import display_selected_fields

        # Sample submission data
        submission_data = {
            "Id10007": "test_value",
        }

        result = display_selected_fields(submission_data, self.form_type_code)

        self.assertEqual(len(result), 14)

        # First category should have the test value
        first_cat = result[0]
        self.assertEqual(first_cat["category"], "Id10007")

    def test_06_pii_field_identification(self):
        """PII fields can be identified."""
        pii_fields = self.service.get_pii_fields(self.form_type_code)

        # Should return a list (may be empty if no PII marked yet)
        self.assertIsInstance(pii_fields, list)

    def test_07_form_type_not_found_returns_empty(self):
        """Invalid form type returns empty lists."""
        categories = self.service.get_categories("NONEXISTENT_FORM")
        self.assertEqual(categories, [])

        config = self.service.get_field_config("NONEXISTENT_FORM", "any_field")
        self.assertIsNone(config)

    def test_08_field_not_found_returns_none(self):
        """Invalid field returns None."""
        config = self.service.get_field_config(self.form_type_code, "NonExistentField123")
        self.assertIsNone(config)
```

---

## Step 4.4: Deprecate Excel-Based Code

Mark old Excel-based functions as deprecated but keep them for rollback:

**File**: `app/utils/va_mapping/__init__.py` (add deprecation warnings)

```python
"""
Field Mapping - DEPRECATED

This module is DEPRECATED. Use app.services.field_mapping_service instead.

The Excel-based mapping system is being replaced by the database-backed
FieldMappingService. This code is kept for rollback purposes only.
"""
import warnings

warnings.warn(
    "va_mapping module is deprecated. Use app.services.field_mapping_service instead.",
    DeprecationWarning,
    stacklevel=2
)

# ... rest of existing code unchanged ...
```

---

## Step 4.5: Run Tests and Verify

```bash
# 1. Run all existing tests to ensure nothing broke
docker compose exec minerva_app_service uv run pytest tests/ -v --tb=short

# 2. Run specific render integration tests
docker compose exec minerva_app_service uv run pytest tests/integration/test_field_mapping_render.py -v

# 3. Manual smoke test - load a VA review page
# Login as test user and navigate to a submission review page
# Verify all categories and fields display correctly
```

---

## Verification Checklist

After completing Phase 4:

### Automated Tests
- [ ] All existing tests still pass
- [ ] New integration tests pass
- [ ] Category retrieval works
- [ ] Field config retrieval works
- [ ] Choice mapping works
- [ ] Render output structure correct

### Manual Verification
- [ ] Login and navigate to VA review page
- [ ] All 14 categories display
- [ ] Fields display with correct labels
- [ ] Choice values show labels, not raw values
- [ ] Category order is correct
- [ ] No errors in browser console
- [ ] No errors in server logs

### Performance
- [ ] Page load time acceptable
- [ ] Database queries are efficient (check with EXPLAIN)

---

## Rollback Procedure

If Phase 4 causes issues:

```bash
# 1. Revert code changes
git revert HEAD  # Or revert specific commit

# 2. Restart app service
docker compose restart minerva_app_service

# 3. Verify old Excel-based system works
# The deprecated code is still available
```

---

## Post-Cutover

After successful cutover:

1. **Monitor** - Watch for any errors or issues in logs
2. **Performance** - Monitor query performance
3. **User feedback** - Check if users notice any differences
4. **Document** - Update documentation to reflect new system

After 1 week of stable operation:
- Remove deprecation warnings from old code
- Archive Excel-based mapping code (keep for reference)

---

## Next Phase

After Phase 4 cutover is stable:
**[Phase 5: ODK Schema Sync Service](05-phase5-odk-sync-service.md)**
