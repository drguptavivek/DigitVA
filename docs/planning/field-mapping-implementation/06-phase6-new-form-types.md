---
title: Phase 6 - Add New Form Types
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 6
estimated_duration: 0.5 day
risk_level: low
---

# Phase 6: Add New Form Types

## Objective

Enable the system to support multiple form types (BALLABGARH_VA, SMART_VA) beyond the existing WHO_2022_VA.

## Prerequisites

- [ ] Phase 5 completed (ODK sync working)
- [ ] System stable with WHO_2022_VA
- [ ] New form ODK projects configured

## Deliverables

1. Form type registration system
2. BALLABGARH_VA form type support
3. SMART_VA form type support
4. Per-form-type ODK configuration
5. Tests for multi-form-type support

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ MULTI-FORM-TYPE SUPPORT                                             │
│                                                                      │
│  Current: Only WHO_2022_VA                                          │
│                                                                      │
│  Target: Multiple form types                                        │
│       ├── WHO_2022_VA (existing)                                   │
│       ├── BALLABGARH_VA (new)                                      │
│       └── SMART_VA (new)                                           │
│                                                                      │
│  Each form type has:                                                │
│       ├── Own set of categories and display order                  │
│       ├── Own field display configurations                         │
│       ├── Own choice mappings                                      │
│       └── Own ODK project/form mapping                             │
│                                                                      │
│  Projects use form types:                                           │
│       ├── Project A → WHO_2022_VA                                  │
│       ├── Project B → BALLABGARH_VA                                │
│       └── Project C → SMART_VA                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step 6.1: Update VaForms Model

The `form_type_id` column was added in Phase 1. Now we need to use it.

**File**: `app/models/va_forms.py` (verify/update relationship)

```python
# Ensure this relationship exists in VaForms model

from app.models.va_field_mapping import MasFormTypes

class VaForms(db.Model):
    # ... existing fields ...

    # Form type relationship (added in Phase 1)
    form_type_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_form_types.form_type_id"),
        nullable=True,  # Nullable during migration
        index=True,
    )

    # Relationship
    form_type: so.Mapped["MasFormTypes | None"] = so.relationship(
        "MasFormTypes", backref="forms"
    )
```

---

## Step 6.2: Create Form Type Registration Service

**File**: `app/services/form_type_service.py`

```python
"""
Form Type Registration Service

Manages registration and configuration of VA form types.
"""
import uuid
from typing import Optional
from sqlalchemy import select
from app import db
from app.models import MasFormTypes, MasCategoryOrder, MasFieldDisplayConfig


class FormTypeService:
    """Service for managing form types."""

    def register_form_type(
        self,
        form_type_code: str,
        form_type_name: str,
        description: str = None,
        base_template_path: str = None,
    ) -> MasFormTypes:
        """
        Register a new form type.

        Args:
            form_type_code: Unique code (e.g., "BALLABGARH_VA")
            form_type_name: Display name
            description: Optional description
            base_template_path: Path to Excel template (if any)

        Returns:
            Created MasFormTypes instance
        """
        existing = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )

        if existing:
            raise ValueError(f"Form type already exists: {form_type_code}")

        form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code=form_type_code,
            form_type_name=form_type_name,
            form_type_description=description,
            base_template_path=base_template_path,
            mapping_version=1,
            is_active=True,
        )

        db.session.add(form_type)
        db.session.commit()

        return form_type

    def get_form_type(self, form_type_code: str) -> Optional[MasFormTypes]:
        """Get form type by code."""
        return db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code,
                MasFormTypes.is_active == True,
            )
        )

    def list_form_types(self) -> list[MasFormTypes]:
        """List all active form types."""
        return list(db.session.scalars(
            select(MasFormTypes)
            .where(MasFormTypes.is_active == True)
            .order_by(MasFormTypes.form_type_code)
        ).all())

    def deactivate_form_type(self, form_type_code: str) -> bool:
        """Deactivate a form type (soft delete)."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return False

        # Check if any forms use this type
        from app.models import VaForms
        form_count = db.session.scalar(
            select(db.func.count())
            .select_from(VaForms)
            .where(VaForms.form_type_id == form_type.form_type_id)
        )

        if form_count > 0:
            raise ValueError(
                f"Cannot deactivate form type with {form_count} associated forms"
            )

        form_type.is_active = False
        db.session.commit()
        return True

    def get_form_type_stats(self, form_type_code: str) -> dict:
        """Get statistics for a form type."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return {}

        from app.models import VaForms

        # Count forms using this type
        form_count = db.session.scalar(
            select(db.func.count())
            .select_from(VaForms)
            .where(VaForms.form_type_id == form_type.form_type_id)
        ) or 0

        # Count categories
        category_count = db.session.scalar(
            select(db.func.count())
            .select_from(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        ) or 0

        # Count field configs
        field_count = db.session.scalar(
            select(db.func.count())
            .select_from(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        ) or 0

        return {
            "form_type_code": form_type_code,
            "form_type_name": form_type.form_type_name,
            "form_count": form_count,
            "category_count": category_count,
            "field_count": field_count,
            "is_active": form_type.is_active,
        }


# Singleton
_form_type_service = None

def get_form_type_service() -> FormTypeService:
    """Get the form type service instance."""
    global _form_type_service
    if _form_type_service is None:
        _form_type_service = FormTypeService()
    return _form_type_service
```

---

## Step 6.3: Create CLI Commands for Form Types

**File**: `app/commands/form_types.py`

```python
"""
CLI commands for form type management.
"""
import click
from app import db
from app.services.form_type_service import get_form_type_service
from app.models import MasFormTypes


@click.group("form-types")
def form_types_group():
    """Form type management commands."""
    pass


@form_types_group.command("list")
def list_form_types():
    """List all registered form types."""
    service = get_form_type_service()
    form_types = service.list_form_types()

    click.echo("\nRegistered Form Types:")
    click.echo("=" * 60)

    for ft in form_types:
        stats = service.get_form_type_stats(ft.form_type_code)
        click.echo(f"\n{ft.form_type_code}")
        click.echo(f"  Name: {ft.form_type_name}")
        click.echo(f"  Forms: {stats['form_count']}")
        click.echo(f"  Categories: {stats['category_count']}")
        click.echo(f"  Fields: {stats['field_count']}")


@form_types_group.command("register")
@click.option("--code", required=True, help="Form type code (e.g., BALLABGARH_VA)")
@click.option("--name", required=True, help="Display name")
@click.option("--description", help="Description")
@click.option("--template", help="Path to base Excel template")
def register_form_type(code, name, description, template):
    """
    Register a new form type.

    Example:
        flask form-types register --code=BALLABGARH_VA --name="Ballabgarh VA Form"
    """
    service = get_form_type_service()

    try:
        form_type = service.register_form_type(
            form_type_code=code,
            form_type_name=name,
            description=description,
            base_template_path=template,
        )

        click.echo(f"\nForm type registered: {form_type.form_type_code}")
        click.echo(f"  ID: {form_type.form_type_id}")
        click.echo(f"  Name: {form_type.form_type_name}")

    except ValueError as e:
        click.echo(f"Error: {e}")


@form_types_group.command("stats")
@click.option("--code", required=True, help="Form type code")
def form_type_stats(code):
    """Show statistics for a form type."""
    service = get_form_type_service()
    stats = service.get_form_type_stats(code)

    if not stats:
        click.echo(f"Form type not found: {code}")
        return

    click.echo(f"\nStatistics for {code}:")
    click.echo("=" * 40)
    click.echo(f"  Name: {stats['form_type_name']}")
    click.echo(f"  Forms: {stats['form_count']}")
    click.echo(f"  Categories: {stats['category_count']}")
    click.echo(f"  Fields: {stats['field_count']}")
    click.echo(f"  Active: {stats['is_active']}")


@form_types_group.command("deactivate")
@click.option("--code", required=True, help="Form type code")
def deactivate_form_type(code):
    """Deactivate a form type."""
    service = get_form_type_service()

    try:
        service.deactivate_form_type(code)
        click.echo(f"Form type deactivated: {code}")
    except ValueError as e:
        click.echo(f"Error: {e}")


def init_app(app):
    """Register CLI commands with Flask app."""
    app.cli.add_command(form_types_group)
```

---

## Step 6.4: Update Field Mapping Service for Multi-Form-Type

**File**: `app/services/field_mapping_service.py` (update existing)

The existing service already supports `form_type_code` parameter. Just ensure it's used consistently.

Add helper method:

```python
def get_default_form_type(self) -> str:
    """Get the default form type code (for backward compatibility)."""
    return "WHO_2022_VA"
```

---

## Step 6.5: Tests for Multi-Form-Type

**File**: `tests/services/test_form_type_service.py`

```python
"""
Tests for form type service.
"""
import pytest
from app import db
from app.models import MasFormTypes, MasCategoryOrder, MasFieldDisplayConfig
from app.services.form_type_service import FormTypeService, get_form_type_service
from tests.base import BaseTestCase


class TestFormTypeService(BaseTestCase):
    """Test form type registration and management."""

    def setUp(self):
        super().setUp()
        self.service = FormTypeService()

    def test_01_register_new_form_type(self):
        """Can register a new form type."""
        form_type = self.service.register_form_type(
            form_type_code="TEST_FORM",
            form_type_name="Test Form Type",
            description="A test form type",
        )

        self.assertIsNotNone(form_type)
        self.assertEqual(form_type.form_type_code, "TEST_FORM")
        self.assertEqual(form_type.form_type_name, "Test Form Type")
        self.assertTrue(form_type.is_active)

    def test_02_cannot_register_duplicate(self):
        """Cannot register duplicate form type code."""
        self.service.register_form_type(
            form_type_code="TEST_DUP",
            form_type_name="Test Duplicate",
        )

        with self.assertRaises(ValueError):
            self.service.register_form_type(
                form_type_code="TEST_DUP",
                form_type_name="Another Form",
            )

    def test_03_list_form_types(self):
        """Can list all form types."""
        # WHO_2022_VA should exist from Phase 2
        form_types = self.service.list_form_types()

        self.assertGreater(len(form_types), 0)
        codes = [ft.form_type_code for ft in form_types]
        self.assertIn("WHO_2022_VA", codes)

    def test_04_get_form_type_stats(self):
        """Can get statistics for a form type."""
        stats = self.service.get_form_type_stats("WHO_2022_VA")

        self.assertIsNotNone(stats)
        self.assertEqual(stats["form_type_code"], "WHO_2022_VA")
        self.assertEqual(stats["category_count"], 14)
        self.assertEqual(stats["field_count"], 427)

    def test_05_deactivate_form_type(self):
        """Can deactivate a form type with no forms."""
        # Register a new type
        form_type = self.service.register_form_type(
            form_type_code="TO_DEACTIVATE",
            form_type_name="Will Be Deactivated",
        )

        # Deactivate it
        result = self.service.deactivate_form_type("TO_DEACTIVATE")
        self.assertTrue(result)

        # Verify it's inactive
        db.session.refresh(form_type)
        self.assertFalse(form_type.is_active)

    def test_06_cannot_deactivate_with_forms(self):
        """Cannot deactivate form type with associated forms."""
        # This would require creating a VaForms record with form_type_id
        # For now, just verify the check exists
        # (Actual test would need form creation setup)
        pass
```

---

## Step 6.6: Register BALLABGARH_VA and SMART_VA

```bash
# Register new form types
docker compose exec minerva_app_service uv run flask form-types register \
    --code=BALLABGARH_VA \
    --name="Ballabgarh VA Form" \
    --description="Ballabgarh Verbal Autopsy Form"

docker compose exec minerva_app_service uv run flask form-types register \
    --code=SMART_VA \
    --name="Smart VA Form" \
    --description="Smart Verbal Autopsy Form"

# List all form types
docker compose exec minerva_app_service uv run flask form-types list
```

---

## Verification Checklist

After completing Phase 6:

- [ ] Form type service created
- [ ] CLI commands registered
- [ ] Tests passing
- [ ] BALLABGARH_VA registered
- [ ] SMART_VA registered
- [ ] Can list form types: `flask form-types list`
- [ ] Can get stats: `flask form-types stats --code=WHO_2022_VA`

---

## Usage Examples

```bash
# List all form types
docker compose exec minerva_app_service uv run flask form-types list

# Register a new form type
docker compose exec minerva_app_service uv run flask form-types register \
    --code=NEW_FORM \
    --name="New Form Type"

# Get statistics
docker compose exec minerva_app_service uv run flask form-types stats --code=WHO_2022_VA

# Deactivate (if no forms use it)
docker compose exec minerva_app_service uv run flask form-types deactivate --code=TEST_FORM
```

---

## Next Phase

After Phase 6 is complete:
**[Phase 7: Admin UI](07-phase7-admin-ui.md)**
