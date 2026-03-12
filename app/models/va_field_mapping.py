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
    category_display_configs: so.Mapped[list["MasCategoryDisplayConfig"]] = so.relationship(
        "MasCategoryDisplayConfig", back_populates="form_type", lazy="dynamic"
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

    __table_args__ = (
        sa.UniqueConstraint("form_type_id", "category_code", name="uq_category_form_type"),
        sa.Index("idx_mas_category_order_form_type", "form_type_id"),
    )

    def __repr__(self):
        return f"<Category: {self.category_code} (order={self.display_order})>"


class MasCategoryDisplayConfig(db.Model):
    """Category-level display metadata per form type."""
    __tablename__ = "mas_category_display_config"

    category_display_config_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_form_types.form_type_id"), nullable=False
    )
    category_code: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    display_label: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    nav_label: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    icon_name: so.Mapped[str | None] = so.mapped_column(sa.String(64))
    display_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    render_mode: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, default="table_sections"
    )
    show_to_coder: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    show_to_reviewer: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    show_to_site_pi: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    always_include: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)
    is_default_start: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    form_type: so.Mapped["MasFormTypes"] = so.relationship(
        "MasFormTypes", back_populates="category_display_configs"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "form_type_id",
            "category_code",
            name="uq_category_display_config_form_type",
        ),
        sa.Index(
            "idx_mas_category_display_config_form_type",
            "form_type_id",
        ),
    )

    def __repr__(self):
        return (
            f"<CategoryDisplayConfig: {self.category_code} "
            f"(mode={self.render_mode}, order={self.display_order})>"
        )


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

    __table_args__ = (
        sa.UniqueConstraint(
            "form_type_id", "category_code", "subcategory_code",
            name="uq_subcategory_form_type"
        ),
        sa.Index("idx_mas_subcategory_order_form_type", "form_type_id"),
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
    odk_label: so.Mapped[str | None] = so.mapped_column(sa.Text)  # synced from ODK XLSForm
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

    # Order within sub-category. Decimal values allow quick inserts like 2.1, 2.2.
    display_order: so.Mapped[float] = so.mapped_column(sa.Numeric(10, 2), default=0)

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
        sa.Index("idx_mas_field_display_config_form_type", "form_type_id"),
        sa.Index("idx_mas_field_display_config_category", "form_type_id", "category_code"),
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
        sa.Index("idx_mas_choice_mappings_form_type", "form_type_id"),
        sa.Index("idx_mas_choice_mappings_field", "form_type_id", "field_id"),
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

    __table_args__ = (
        sa.Index("idx_mas_pii_access_log_user", "user_id"),
        sa.Index("idx_mas_pii_access_log_timestamp", "accessed_at"),
    )

    def __repr__(self):
        return f"<PIIAccess: {self.user_id} -> {self.field_id}>"
