---
title: Phase 5 - ODK Schema Sync Service
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 5
estimated_duration: 1 day
risk_level: medium
---

# Phase 5: ODK Schema Sync Service

## Objective

Implement automatic synchronization of choice mappings from ODK Central form schemas to the database.

## Prerequisites

- [ ] Phase 4 completed (render integration working)
- [ ] System stable on database-backed mapping
- [ ] ODK Central API access configured

## Deliverables

1. ODK schema sync service
2. Choice mapping sync from ODK XLSX/fields endpoint
3. Sync scheduling (manual or Celery)
4. Sync status tracking
5. Admin command to trigger sync

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ ODK SCHEMA SYNC                                                     │
│                                                                      │
│  ODK Central API                                                    │
│       │                                                              │
│       ├── GET /projects/{id}/forms/{id}/fields                     │
│       │   Returns form field definitions with choices              │
│       │                                                              │
│       └── GET /projects/{id}/forms/{id}.xlsx                       │
│           Returns full XLSX with choices sheet                     │
│                                                                      │
│  Sync Service                                                       │
│       │                                                              │
│       ├── Fetch schema from ODK                                    │
│       ├── Parse field definitions                                  │
│       ├── Extract choice lists                                    │
│       └── Update mas_choice_mappings table                        │
│                                                                      │
│  Benefits                                                           │
│       ├── Automatic choice sync when ODK form updated            │
│       ├── No manual Excel maintenance                             │
│       └── Detect new/removed fields                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step 5.1: Create ODK Schema Sync Service

**File**: `app/services/odk_schema_sync_service.py`

```python
"""
ODK Schema Sync Service

Synchronizes form field choices from ODK Central to the database.

Uses ODK Central API endpoints:
- /projects/{id}/forms/{id}/fields - Field definitions with choices
- /projects/{id}/forms/{id}.xlsx - Full form XLSX (fallback)
"""
import uuid
import io
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from flask import current_app
from app import db
from app.models import (
    MasFormTypes,
    MasChoiceMappings,
    MasFieldDisplayConfig,
)
from app.services.odk_service import OdkCentralService


class OdkSchemaSyncService:
    """
    Synchronizes choice mappings from ODK Central form schemas.
    """

    def __init__(self):
        self.stats = {
            "fields_processed": 0,
            "choices_added": 0,
            "choices_updated": 0,
            "choices_deactivated": 0,
            "errors": [],
        }

    def sync_form_choices(self, form_type_code: str,
                         odk_project_id: int,
                         odk_form_id: str) -> dict:
        """
        Sync choice mappings for a form from ODK Central.

        Args:
            form_type_code: Form type code (e.g., "WHO_2022_VA")
            odk_project_id: ODK Central project ID
            odk_form_id: ODK Central form ID (XML form ID)

        Returns:
            Dict with sync statistics
        """
        self.stats = {
            "fields_processed": 0,
            "choices_added": 0,
            "choices_updated": 0,
            "choices_deactivated": 0,
            "errors": [],
        }

        # Get form type
        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )

        if not form_type:
            self.stats["errors"].append(f"Form type not found: {form_type_code}")
            return self.stats

        try:
            # Fetch fields from ODK
            odk_service = OdkCentralService()
            fields = odk_service.get_form_fields(odk_project_id, odk_form_id)

            if not fields:
                # Fallback to XLSX if fields endpoint fails
                fields = self._fetch_from_xlsx(odk_service, odk_project_id, odk_form_id)

            if not fields:
                self.stats["errors"].append("Failed to fetch form schema from ODK")
                return self.stats

            # Get existing choices for comparison
            existing_choices = self._get_existing_choices(form_type.form_type_id)

            # Track which choices we see from ODK
            seen_choice_keys = set()

            # Process each field with choices
            for field in fields:
                field_name = field.get("name")
                field_type = field.get("type", "")

                # Only process select fields
                if not field_type.startswith("select"):
                    continue

                choices = field.get("choice_list", [])
                if not choices:
                    continue

                self.stats["fields_processed"] += 1

                # Process each choice
                for order, choice in enumerate(choices, start=1):
                    choice_value = choice.get("name") or choice.get("value")
                    choice_label = choice.get("label") or choice_value

                    if not choice_value:
                        continue

                    choice_key = (field_name, choice_value)
                    seen_choice_keys.add(choice_key)

                    # Update or create choice mapping
                    self._upsert_choice(
                        form_type.form_type_id,
                        field_name,
                        choice_value,
                        choice_label,
                        order
                    )

            # Deactivate choices not in ODK schema
            self._deactivate_missing_choices(
                form_type.form_type_id,
                seen_choice_keys
            )

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            self.stats["errors"].append(str(e))

        return self.stats

    def _fetch_from_xlsx(self, odk_service: OdkCentralService,
                        project_id: int, form_id: str) -> list[dict]:
        """Fetch field definitions from XLSX attachment."""
        try:
            xlsx_content = odk_service.get_form_xlsx(project_id, form_id)
            if not xlsx_content:
                return []

            # Parse XLSX choices sheet
            xlsx = pd.read_excel(io.BytesIO(xlsx_content), sheet_name="choices")

            fields = {}
            for _, row in xlsx.iterrows():
                list_name = row.get("list_name")
                name = row.get("name")
                label = row.get("label")

                if not list_name or not name:
                    continue

                if list_name not in fields:
                    fields[list_name] = {
                        "name": list_name,
                        "type": "select_one",
                        "choice_list": [],
                    }

                fields[list_name]["choice_list"].append({
                    "name": str(name),
                    "label": str(label) if pd.notna(label) else str(name),
                })

            return list(fields.values())

        except Exception as e:
            current_app.logger.error(f"Failed to parse XLSX: {e}")
            return []

    def _get_existing_choices(self, form_type_id: uuid.UUID) -> dict:
        """Get existing choices as dict for comparison."""
        choices = db.session.scalars(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type_id
            )
        ).all()

        return {
            (c.field_id, c.choice_value): c
            for c in choices
        }

    def _upsert_choice(self, form_type_id: uuid.UUID, field_id: str,
                      choice_value: str, choice_label: str, order: int):
        """Create or update a choice mapping."""
        existing = db.session.scalar(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type_id,
                MasChoiceMappings.field_id == field_id,
                MasChoiceMappings.choice_value == choice_value,
            )
        )

        if existing:
            # Update existing
            if existing.choice_label != choice_label:
                existing.choice_label = choice_label
                existing.display_order = order
                existing.synced_at = datetime.now(timezone.utc)
                existing.is_active = True
                self.stats["choices_updated"] += 1
        else:
            # Create new
            choice = MasChoiceMappings(
                choice_id=uuid.uuid4(),
                form_type_id=form_type_id,
                field_id=field_id,
                choice_value=choice_value,
                choice_label=choice_label,
                display_order=order,
                is_active=True,
            )
            db.session.add(choice)
            self.stats["choices_added"] += 1

    def _deactivate_missing_choices(self, form_type_id: uuid.UUID,
                                    seen_keys: set):
        """Deactivate choices that are no longer in ODK schema."""
        existing = db.session.scalars(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type_id,
                MasChoiceMappings.is_active == True,
            )
        ).all()

        for choice in existing:
            key = (choice.field_id, choice.choice_value)
            if key not in seen_keys:
                choice.is_active = False
                self.stats["choices_deactivated"] += 1

    def detect_schema_changes(self, form_type_code: str,
                             odk_project_id: int,
                             odk_form_id: str) -> dict:
        """
        Detect changes in ODK schema compared to database.

        Returns dict with:
        - new_fields: Fields in ODK but not in DB
        - removed_fields: Fields in DB but not in ODK
        - new_choices: Choices in ODK but not in DB
        - removed_choices: Choices in DB but not in ODK
        """
        # Get form type
        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )

        if not form_type:
            return {"error": "Form type not found"}

        # Get ODK fields
        odk_service = OdkCentralService()
        odk_fields = odk_service.get_form_fields(odk_project_id, odk_form_id)

        if not odk_fields:
            odk_fields = self._fetch_from_xlsx(odk_service, odk_project_id, odk_form_id)

        # Get DB fields
        db_fields = db.session.scalars(
            select(MasFieldDisplayConfig.field_id).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id
            )
        ).all()

        db_field_set = set(db_fields)
        odk_field_set = {f["name"] for f in odk_fields}

        # Get DB choices
        db_choices = db.session.scalars(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.is_active == True,
            )
        ).all()

        db_choice_set = {(c.field_id, c.choice_value) for c in db_choices}

        # Get ODK choices
        odk_choice_set = set()
        for field in odk_fields:
            if field.get("type", "").startswith("select"):
                for choice in field.get("choice_list", []):
                    odk_choice_set.add((field["name"], choice.get("name")))

        return {
            "new_fields": list(odk_field_set - db_field_set),
            "removed_fields": list(db_field_set - odk_field_set),
            "new_choices": list(odk_choice_set - db_choice_set),
            "removed_choices": list(db_choice_set - odk_choice_set),
        }


# Singleton
_sync_service = None

def get_sync_service() -> OdkSchemaSyncService:
    """Get the ODK schema sync service instance."""
    global _sync_service
    if _sync_service is None:
        _sync_service = OdkSchemaSyncService()
    return _sync_service
```

---

## Step 5.2: Add ODK Service Methods

**File**: `app/services/odk_service.py` (add to existing)

```python
# Add these methods to the existing OdkCentralService class

def get_form_fields(self, project_id: int, form_id: str) -> list[dict]:
    """
    Get form field definitions from ODK Central.

    Args:
        project_id: ODK Central project ID
        form_id: ODK form ID (XML form ID)

    Returns:
        List of field dicts with name, type, and choices
    """
    try:
        response = self.session.get(
            f"{self.base_url}/projects/{project_id}/forms/{form_id}/fields"
        )
        response.raise_for_status()

        fields = response.json()

        # Transform ODK fields to our format
        result = []
        for field in fields:
            field_data = {
                "name": field.get("name"),
                "type": field.get("type"),
                "path": field.get("path"),
            }

            # Extract choices if select field
            if field.get("type", "").startswith("select"):
                choices = []
                for choice in field.get("choices", []):
                    choices.append({
                        "name": choice.get("name"),
                        "value": choice.get("value"),
                        "label": choice.get("label", {}).get("en", choice.get("name")),
                    })
                field_data["choice_list"] = choices

            result.append(field_data)

        return result

    except Exception as e:
        current_app.logger.error(f"Failed to get form fields: {e}")
        return []

def get_form_xlsx(self, project_id: int, form_id: str) -> Optional[bytes]:
    """
    Get form XLSX file from ODK Central.

    Args:
        project_id: ODK Central project ID
        form_id: ODK form ID

    Returns:
        XLSX file content as bytes, or None on error
    """
    try:
        response = self.session.get(
            f"{self.base_url}/projects/{project_id}/forms/{form_id}.xlsx"
        )
        response.raise_for_status()
        return response.content

    except Exception as e:
        current_app.logger.error(f"Failed to get form XLSX: {e}")
        return None
```

---

## Step 5.3: Create Admin CLI Command

**File**: `app/commands/odk_sync.py`

```python
"""
CLI commands for ODK schema synchronization.
"""
import click
from flask import current_app
from app import db
from app.services.odk_schema_sync_service import get_sync_service
from app.models import VaForms, MasFormTypes


@click.group("odk-sync")
def odk_sync_group():
    """ODK schema synchronization commands."""
    pass


@odk_sync_group.command("choices")
@click.option("--form-type", required=True, help="Form type code (e.g., WHO_2022_VA)")
@click.option("--project-id", type=int, help="ODK project ID (optional, uses configured)")
@click.option("--form-id", help="ODK form ID (optional, uses configured)")
@click.option("--dry-run", is_flag=True, help="Show changes without applying")
def sync_choices(form_type, project_id, form_id, dry_run):
    """
    Sync choice mappings from ODK Central.

    Example:
        flask odk-sync choices --form-type=WHO_2022_VA
    """
    sync_service = get_sync_service()

    # Get ODK project/form IDs from configuration if not specified
    if not project_id or not form_id:
        # Try to get from va_forms table
        form = db.session.scalar(
            db.select(VaForms).where(
                VaForms.form_type_id == db.select(MasFormTypes.form_type_id).where(
                    MasFormTypes.form_type_code == form_type
                )
            ).limit(1)
        )

        if form:
            project_id = project_id or form.project_id
            form_id = form_id or form.form_id

    if not project_id or not form_id:
        click.echo("Error: Must specify --project-id and --form-id, or have configured form in va_forms")
        return

    click.echo(f"Syncing choices for {form_type}...")
    click.echo(f"  ODK Project: {project_id}")
    click.echo(f"  ODK Form: {form_id}")

    if dry_run:
        # Just detect changes
        changes = sync_service.detect_schema_changes(form_type, project_id, form_id)

        click.echo("\nDetected changes:")
        click.echo(f"  New fields: {len(changes.get('new_fields', []))}")
        click.echo(f"  Removed fields: {len(changes.get('removed_fields', []))}")
        click.echo(f"  New choices: {len(changes.get('new_choices', []))}")
        click.echo(f"  Removed choices: {len(changes.get('removed_choices', []))}")

        if changes.get('new_choices'):
            click.echo("\n  Sample new choices:")
            for fc in list(changes['new_choices'])[:5]:
                click.echo(f"    - {fc[0]}.{fc[1]}")
    else:
        # Perform sync
        stats = sync_service.sync_form_choices(form_type, project_id, form_id)

        click.echo("\nSync complete:")
        click.echo(f"  Fields processed: {stats['fields_processed']}")
        click.echo(f"  Choices added: {stats['choices_added']}")
        click.echo(f"  Choices updated: {stats['choices_updated']}")
        click.echo(f"  Choices deactivated: {stats['choices_deactivated']}")

        if stats['errors']:
            click.echo("\nErrors:")
            for error in stats['errors']:
                click.echo(f"  - {error}")


@odk_sync_group.command("detect-changes")
@click.option("--form-type", required=True, help="Form type code")
@click.option("--project-id", type=int, help="ODK project ID")
@click.option("--form-id", help="ODK form ID")
def detect_changes(form_type, project_id, form_id):
    """
    Detect schema changes between ODK and database.

    Example:
        flask odk-sync detect-changes --form-type=WHO_2022_VA
    """
    sync_service = get_sync_service()

    # Similar logic to get project/form IDs
    if not project_id or not form_id:
        form = db.session.scalar(
            db.select(VaForms).where(
                VaForms.form_type_id == db.select(MasFormTypes.form_type_id).where(
                    MasFormTypes.form_type_code == form_type
                )
            ).limit(1)
        )

        if form:
            project_id = project_id or form.project_id
            form_id = form_id or form.form_id

    if not project_id or not form_id:
        click.echo("Error: Must specify project and form IDs")
        return

    changes = sync_service.detect_schema_changes(form_type, project_id, form_id)

    click.echo(f"\nSchema Changes for {form_type}:")
    click.echo("=" * 50)

    click.echo(f"\nNew Fields ({len(changes.get('new_fields', []))}):")
    for f in changes.get('new_fields', []):
        click.echo(f"  + {f}")

    click.echo(f"\nRemoved Fields ({len(changes.get('removed_fields', []))}):")
    for f in changes.get('removed_fields', []):
        click.echo(f"  - {f}")

    click.echo(f"\nNew Choices ({len(changes.get('new_choices', []))}):")
    for fc in changes.get('new_choices', []):
        click.echo(f"  + {fc[0]}.{fc[1]}")

    click.echo(f"\nRemoved Choices ({len(changes.get('removed_choices', []))}):")
    for fc in changes.get('removed_choices', []):
        click.echo(f"  - {fc[0]}.{fc[1]}")


def init_app(app):
    """Register CLI commands with Flask app."""
    app.cli.add_command(odk_sync_group)
```

---

## Step 5.4: Register Commands

**File**: `app/__init__.py` (add to create_app function)

```python
# Add near other CLI registrations
from app.commands.odk_sync import init_app as init_odk_sync
init_odk_sync(app)
```

---

## Step 5.5: Create Tests

**File**: `tests/services/test_odk_schema_sync.py`

```python
"""
Tests for ODK schema sync service.
"""
import pytest
from unittest.mock import Mock, patch
from app import db
from app.models import MasFormTypes, MasChoiceMappings
from app.services.odk_schema_sync_service import OdkSchemaSyncService
from tests.base import BaseTestCase


class TestOdkSchemaSync(BaseTestCase):
    """Test ODK schema synchronization."""

    def setUp(self):
        super().setUp()
        # Ensure WHO_2022_VA form type exists
        self.form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )

    @patch('app.services.odk_schema_sync_service.OdkCentralService')
    def test_01_sync_adds_new_choices(self, mock_odk_service):
        """Sync adds new choices from ODK."""
        # Mock ODK response
        mock_service = Mock()
        mock_service.get_form_fields.return_value = [
            {
                "name": "TestField",
                "type": "select_one",
                "choice_list": [
                    {"name": "choice1", "label": "Choice One"},
                    {"name": "choice2", "label": "Choice Two"},
                ]
            }
        ]
        mock_odk_service.return_value = mock_service

        sync_service = OdkSchemaSyncService()
        stats = sync_service.sync_form_choices("WHO_2022_VA", 1, "test_form")

        self.assertEqual(stats["choices_added"], 2)
        self.assertEqual(stats["errors"], [])

    @patch('app.services.odk_schema_sync_service.OdkCentralService')
    def test_02_sync_updates_existing_choices(self, mock_odk_service):
        """Sync updates existing choice labels."""
        # Create existing choice
        existing = MasChoiceMappings(
            choice_id=uuid.uuid4(),
            form_type_id=self.form_type.form_type_id,
            field_id="TestField",
            choice_value="choice1",
            choice_label="Old Label",
        )
        db.session.add(existing)
        db.session.commit()

        # Mock ODK response with updated label
        mock_service = Mock()
        mock_service.get_form_fields.return_value = [
            {
                "name": "TestField",
                "type": "select_one",
                "choice_list": [
                    {"name": "choice1", "label": "New Label"},
                ]
            }
        ]
        mock_odk_service.return_value = mock_service

        sync_service = OdkSchemaSyncService()
        stats = sync_service.sync_form_choices("WHO_2022_VA", 1, "test_form")

        # Verify label updated
        db.session.refresh(existing)
        self.assertEqual(existing.choice_label, "New Label")

    @patch('app.services.odk_schema_sync_service.OdkCentralService')
    def test_03_sync_deactivates_removed_choices(self, mock_odk_service):
        """Sync deactivates choices no longer in ODK."""
        # Create existing choice
        existing = MasChoiceMappings(
            choice_id=uuid.uuid4(),
            form_type_id=self.form_type.form_type_id,
            field_id="TestField",
            choice_value="old_choice",
            choice_label="Old Choice",
            is_active=True,
        )
        db.session.add(existing)
        db.session.commit()

        # Mock ODK response without this choice
        mock_service = Mock()
        mock_service.get_form_fields.return_value = [
            {
                "name": "TestField",
                "type": "select_one",
                "choice_list": [
                    {"name": "new_choice", "label": "New Choice"},
                ]
            }
        ]
        mock_odk_service.return_value = mock_service

        sync_service = OdkSchemaSyncService()
        stats = sync_service.sync_form_choices("WHO_2022_VA", 1, "test_form")

        # Verify old choice deactivated
        db.session.refresh(existing)
        self.assertFalse(existing.is_active)
        self.assertEqual(stats["choices_deactivated"], 1)
```

---

## Verification Checklist

After completing Phase 5:

- [ ] Sync service created
- [ ] ODK service methods added
- [ ] CLI commands registered
- [ ] Tests passing
- [ ] Manual sync works: `flask odk-sync choices --form-type=WHO_2022_VA --dry-run`
- [ ] Change detection works: `flask odk-sync detect-changes --form-type=WHO_2022_VA`

---

## Usage Examples

```bash
# Detect changes before syncing
docker compose exec minerva_app_service uv run flask odk-sync detect-changes --form-type=WHO_2022_VA

# Sync choices (dry run first)
docker compose exec minerva_app_service uv run flask odk-sync choices --form-type=WHO_2022_VA --dry-run

# Perform actual sync
docker compose exec minerva_app_service uv run flask odk-sync choices --form-type=WHO_2022_VA
```

---

## Next Phase

After Phase 5 is complete:
**[Phase 6: New Form Types](06-phase6-new-form-types.md)**
