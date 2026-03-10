---
title: Phase 1 - Database Schema Creation
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 1
estimated_duration: 1 day
risk_level: low
---

# Phase 1: Database Schema Creation

## Objective

Create database tables for the field mapping system **without affecting existing data**.

## Prerequisites

- [ ] Database backup completed
- [ ] All tests passing on current codebase
- [ ] No active data collection in progress

## Deliverables

1. New database tables created
2. SQLAlchemy models created
3. Migration script tested
4. No existing data affected

---

## Step 1.1: Create Migration File

**File**: `migrations/versions/{timestamp}_add_field_mapping_tables.py`

```python
"""add field mapping tables

Revision ID: field_mapping_001
Revises: {previous_revision}
Create Date: 2026-03-10

This migration ONLY creates new tables. It does NOT:
- Modify existing tables (except adding nullable column)
- Migrate data from Excel
- Change existing functionality

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'field_mapping_001'
down_revision = '{previous_revision}'  # UPDATE THIS
branch_labels = None
depends_on = None


def upgrade():
    # ============================================================
    # 1. FORM TYPE REGISTRY
    # ============================================================
    op.create_table(
        'mas_form_types',
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('form_type_code', sa.String(32), unique=True, nullable=False),
        sa.Column('form_type_name', sa.String(128), nullable=False),
        sa.Column('form_type_description', sa.Text),
        sa.Column('base_template_path', sa.String(256)),
        sa.Column('mapping_version', sa.Integer, default=1),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_mas_form_types_code', 'mas_form_types', ['form_type_code'])

    # ============================================================
    # 2. CATEGORY ORDER (per form type)
    # ============================================================
    op.create_table(
        'mas_category_order',
        sa.Column('category_order_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('mas_form_types.form_type_id'), nullable=False),
        sa.Column('category_code', sa.String(64), nullable=False),
        sa.Column('category_name', sa.String(128)),
        sa.Column('display_order', sa.Integer, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.UniqueConstraint('form_type_id', 'category_code', name='uq_category_form_type'),
    )
    op.create_index('idx_mas_category_order_form_type', 'mas_category_order', ['form_type_id'])

    # ============================================================
    # 3. SUB-CATEGORY ORDER (per form type)
    # ============================================================
    op.create_table(
        'mas_subcategory_order',
        sa.Column('subcategory_order_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('mas_form_types.form_type_id'), nullable=False),
        sa.Column('category_code', sa.String(64), nullable=False),
        sa.Column('subcategory_code', sa.String(64), nullable=False),
        sa.Column('subcategory_name', sa.String(128)),
        sa.Column('display_order', sa.Integer, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.UniqueConstraint('form_type_id', 'category_code', 'subcategory_code',
                           name='uq_subcategory_form_type'),
    )
    op.create_index('idx_mas_subcategory_order_form_type', 'mas_subcategory_order', ['form_type_id'])

    # ============================================================
    # 4. FIELD DISPLAY CONFIGURATION
    # ============================================================
    op.create_table(
        'mas_field_display_config',
        sa.Column('config_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('mas_form_types.form_type_id'), nullable=False),

        # Field identification
        sa.Column('field_id', sa.String(64), nullable=False),

        # Category assignment
        sa.Column('category_code', sa.String(64)),
        sa.Column('subcategory_code', sa.String(64)),

        # Display labels
        sa.Column('short_label', sa.String(256)),
        sa.Column('full_label', sa.Text),
        sa.Column('summary_label', sa.String(256)),

        # Field metadata (from ODK or manual)
        sa.Column('field_type', sa.String(32)),  # string, int, date, select_one, etc.
        sa.Column('age_group', sa.String(16)),   # ALL, NEONATE, CHILD, ADULT

        # Display options
        sa.Column('flip_color', sa.Boolean, default=False),
        sa.Column('is_info', sa.Boolean, default=False),
        sa.Column('summary_include', sa.Boolean, default=False),

        # PII handling
        sa.Column('is_pii', sa.Boolean, default=False),
        sa.Column('pii_type', sa.String(32)),  # name, location, identifier, date

        # Order within sub-category
        sa.Column('display_order', sa.Integer, default=0),

        # Status
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_custom', sa.Boolean, default=False),  # True if project-specific

        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),

        sa.UniqueConstraint('form_type_id', 'field_id', name='uq_field_config_form_type'),
    )
    op.create_index('idx_mas_field_display_config_form_type',
                   'mas_field_display_config', ['form_type_id'])
    op.create_index('idx_mas_field_display_config_category',
                   'mas_field_display_config', ['form_type_id', 'category_code'])

    # ============================================================
    # 5. CHOICE MAPPINGS (auto-synced from ODK)
    # ============================================================
    op.create_table(
        'mas_choice_mappings',
        sa.Column('choice_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('mas_form_types.form_type_id'), nullable=False),

        # Field and choice identification
        sa.Column('field_id', sa.String(64), nullable=False),
        sa.Column('choice_value', sa.String(128), nullable=False),
        sa.Column('choice_label', sa.String(256), nullable=False),

        # Order within field choices
        sa.Column('display_order', sa.Integer, default=0),

        # Metadata
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('synced_at', sa.DateTime, server_default=sa.func.now()),

        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),

        sa.UniqueConstraint('form_type_id', 'field_id', 'choice_value',
                           name='uq_choice_form_type_field'),
    )
    op.create_index('idx_mas_choice_mappings_form_type',
                   'mas_choice_mappings', ['form_type_id'])
    op.create_index('idx_mas_choice_mappings_field',
                   'mas_choice_mappings', ['form_type_id', 'field_id'])

    # ============================================================
    # 6. PII ACCESS LOG (for audit trail)
    # ============================================================
    op.create_table(
        'mas_pii_access_log',
        sa.Column('log_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True)),
        sa.Column('field_id', sa.String(64), nullable=False),
        sa.Column('submission_id', sa.String(64), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),  # view, export
        sa.Column('accessed_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('idx_mas_pii_access_log_user', 'mas_pii_access_log', ['user_id'])
    op.create_index('idx_mas_pii_access_log_timestamp', 'mas_pii_access_log', ['accessed_at'])

    # ============================================================
    # 7. Add form_type_id to va_forms (NULLABLE - will be populated later)
    # ============================================================
    op.add_column('va_forms',
        sa.Column('form_type_id', postgresql.UUID(as_uuid=True),
                 sa.ForeignKey('mas_form_types.form_type_id'), nullable=True)
    )
    op.create_index('idx_va_forms_form_type', 'va_forms', ['form_type_id'])


def downgrade():
    """Rollback: Remove all new tables and columns."""
    # Drop in reverse order
    op.drop_index('idx_va_forms_form_type', 'va_forms')
    op.drop_column('va_forms', 'form_type_id')

    op.drop_table('mas_pii_access_log')
    op.drop_table('mas_choice_mappings')
    op.drop_table('mas_field_display_config')
    op.drop_table('mas_subcategory_order')
    op.drop_table('mas_category_order')
    op.drop_table('mas_form_types')
```

---

## Step 1.2: Create SQLAlchemy Models

**File**: `app/models/va_field_mapping.py`

```python
"""
Field Mapping System Models

These models support multi-form-type field display configuration.
Data is migrated from resource/mapping/*.xlsx files.
"""
import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from datetime import datetime, timezone
from app import db
from app.models.va_selectives import VaStatuses


class MasFormTypes(db.Model):
    """Registry of supported VA form types."""
    __tablename__ = "mas_form_types"

    form_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_type_code: so.Mapped[str] = so.mapped_column(
        sa.String(32), unique=True, nullable=False, index=True
    )
    form_type_name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    form_type_description: so.Mapped[str | None] = so.mapped_column(sa.Text)
    base_template_path: so.Mapped[str | None] = so.mapped_column(sa.String(256))
    mapping_version: so.Mapped[int] = so.mapped_column(sa.Integer, default=1)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    categories: so.Mapped[list["MasCategoryOrder"]] = so.relationship(
        "MasCategoryOrder", back_populates="form_type", lazy="dynamic"
    )
    field_configs: so.Mapped[list["MasFieldDisplayConfig"]] = so.relationship(
        "MasFieldDisplayConfig", back_populates="form_type", lazy="dynamic"
    )
    choices: so.Mapped[list["MasChoiceMappings"]] = so.relationship(
        "MasChoiceMappings", back_populates="form_type", lazy="dynamic"
    )

    def __repr__(self):
        return f"<FormType: {self.form_type_code}>"


class MasCategoryOrder(db.Model):
    """Category display order per form type."""
    __tablename__ = "mas_category_order"

    category_order_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_form_types.form_type_id"), nullable=False
    )
    category_code: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    category_name: so.Mapped[str | None] = so.mapped_column(sa.String(128))
    display_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)

    # Relationships
    form_type: so.Mapped["MasFormTypes"] = so.relationship(
        "MasFormTypes", back_populates="categories"
    )
    subcategories: so.Mapped[list["MasSubcategoryOrder"]] = so.relationship(
        "MasSubcategoryOrder", back_populates="category", lazy="dynamic"
    )

    __table_args__ = (
        sa.UniqueConstraint("form_type_id", "category_code", name="uq_category_form_type"),
    )

    def __repr__(self):
        return f"<Category: {self.category_code} (order={self.display_order})>"


class MasSubcategoryOrder(db.Model):
    """Sub-category display order per form type and category."""
    __tablename__ = "mas_subcategory_order"

    subcategory_order_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_form_types.form_type_id"), nullable=False
    )
    category_code: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    subcategory_code: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    subcategory_name: so.Mapped[str | None] = so.mapped_column(sa.String(128))
    display_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)

    # Relationships
    form_type: so.Mapped["MasFormTypes"] = so.relationship("MasFormTypes")
    category: so.Mapped["MasCategoryOrder"] = so.relationship(
        "MasCategoryOrder", back_populates="subcategories"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "form_type_id", "category_code", "subcategory_code",
            name="uq_subcategory_form_type"
        ),
    )

    def __repr__(self):
        return f"<SubCategory: {self.category_code}/{self.subcategory_code}>"


class MasFieldDisplayConfig(db.Model):
    """Field display configuration per form type."""
    __tablename__ = "mas_field_display_config"

    config_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_form_types.form_type_id"), nullable=False
    )

    # Field identification
    field_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)

    # Category assignment
    category_code: so.Mapped[str | None] = so.mapped_column(sa.String(64))
    subcategory_code: so.Mapped[str | None] = so.mapped_column(sa.String(64))

    # Display labels
    short_label: so.Mapped[str | None] = so.mapped_column(sa.String(256))
    full_label: so.Mapped[str | None] = so.mapped_column(sa.Text)
    summary_label: so.Mapped[str | None] = so.mapped_column(sa.String(256))

    # Field metadata
    field_type: so.Mapped[str | None] = so.mapped_column(sa.String(32))
    age_group: so.Mapped[str | None] = so.mapped_column(sa.String(16))

    # Display options
    flip_color: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)
    is_info: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)
    summary_include: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)

    # PII handling
    is_pii: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)
    pii_type: so.Mapped[str | None] = so.mapped_column(sa.String(32))

    # Order within sub-category
    display_order: so.Mapped[int] = so.mapped_column(sa.Integer, default=0)

    # Status
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    is_custom: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    form_type: so.Mapped["MasFormTypes"] = so.relationship(
        "MasFormTypes", back_populates="field_configs"
    )

    __table_args__ = (
        sa.UniqueConstraint("form_type_id", "field_id", name="uq_field_config_form_type"),
    )

    def __repr__(self):
        return f"<FieldConfig: {self.field_id}>"


class MasChoiceMappings(db.Model):
    """Choice value-to-label mappings per form type (auto-synced from ODK)."""
    __tablename__ = "mas_choice_mappings"

    choice_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_form_types.form_type_id"), nullable=False
    )

    # Field and choice identification
    field_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    choice_value: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    choice_label: so.Mapped[str] = so.mapped_column(sa.String(256), nullable=False)

    # Order within field choices
    display_order: so.Mapped[int] = so.mapped_column(sa.Integer, default=0)

    # Metadata
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    synced_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    form_type: so.Mapped["MasFormTypes"] = so.relationship(
        "MasFormTypes", back_populates="choices"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "form_type_id", "field_id", "choice_value",
            name="uq_choice_form_type_field"
        ),
    )

    def __repr__(self):
        return f"<Choice: {self.field_id}={self.choice_value}>"


class MasPiiAccessLog(db.Model):
    """Audit log for PII field access."""
    __tablename__ = "mas_pii_access_log"

    log_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    form_type_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_form_types.form_type_id")
    )
    field_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    submission_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    action: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    accessed_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<PIIAccess: {self.user_id} -> {self.field_id}>"
```

---

## Step 1.3: Register Models in `__init__.py`

**File**: `app/models/__init__.py` (add to existing exports)

```python
# Add to imports section
from app.models.va_field_mapping import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
    MasPiiAccessLog,
)

# Add to __all__ list
    "MasFormTypes",
    "MasCategoryOrder",
    "MasSubcategoryOrder",
    "MasFieldDisplayConfig",
    "MasChoiceMappings",
    "MasPiiAccessLog",
```

---

## Step 1.4: Run Migration

```bash
# Inside Docker
docker compose exec minerva_app_service uv run flask db migrate -m "add field mapping tables"
docker compose exec minerva_app_service uv run flask db upgrade
```

---

## Verification Checklist

After completing Phase 1:

```bash
# 1. Verify tables exist
docker compose exec minerva_db_service psql -U minerva -d minerva -c "\dt mas_*"

# Expected output:
#  mas_category_order
#  mas_choice_mappings
#  mas_field_display_config
#  mas_form_types
#  mas_pii_access_log
#  mas_subcategory_order

# 2. Verify indexes exist
docker compose exec minerva_db_service psql -U minerva -d minerva -c "\di idx_mas_*"

# 3. Verify va_forms has new column (should be nullable)
docker compose exec minerva_db_service psql -U minerva -d minerva -c "\d va_forms" | grep form_type_id

# 4. Verify NO data was affected
docker compose exec minerva_db_service psql -U minerva -d minerva -c "SELECT COUNT(*) FROM va_forms;"
# Should return same count as before migration

# 5. Test SQLAlchemy models load
docker compose exec minerva_app_service uv run python -c "
from app import create_app, db
from app.models import MasFormTypes
app = create_app()
with app.app_context():
    print('Models loaded successfully')
    print(f'Table: {MasFormTypes.__tablename__}')
"
```

---

## Rollback Procedure

If Phase 1 fails:

```bash
# Rollback migration
docker compose exec minerva_app_service uv run flask db downgrade -1

# Or manually
docker compose exec minerva_db_service psql -U minerva -d minerva -c "
DROP TABLE IF EXISTS mas_pii_access_log CASCADE;
DROP TABLE IF EXISTS mas_choice_mappings CASCADE;
DROP TABLE IF EXISTS mas_field_display_config CASCADE;
DROP TABLE IF EXISTS mas_subcategory_order CASCADE;
DROP TABLE IF EXISTS mas_category_order CASCADE;
DROP TABLE IF EXISTS mas_form_types CASCADE;
ALTER TABLE va_forms DROP COLUMN IF EXISTS form_type_id;
"
```

---

## Next Phase

After Phase 1 verification passes, proceed to:
**[Phase 2: Migrate Existing WHO_2022_VA Data](02-phase2-migrate-existing.md)**
