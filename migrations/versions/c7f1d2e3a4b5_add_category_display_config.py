"""add category display config

Revision ID: c7f1d2e3a4b5
Revises: b6d9f3c4e1a2
Create Date: 2026-03-12 18:35:00.000000

"""
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c7f1d2e3a4b5"
down_revision = "b6d9f3c4e1a2"
branch_labels = None
depends_on = None


CATEGORY_DISPLAY_ROWS = {
    "WHO_2022_VA": [
        ("vainterviewdetails", "Interview Details", "Interview Details", "fa-info-circle", 1, "table_sections", False, False, True, False, False),
        ("vademographicdetails", "Demographic / Risk Factors", "Demographic / Risk Factors", "fa-user", 2, "table_sections", True, True, True, False, True),
        ("vaneonatalperioddetails", "Neonatal Period", "Neonatal Period", "fa-baby", 3, "table_sections", True, True, True, False, False),
        ("vainjuriesdetails", "Injuries", "Injuries", "fa-first-aid", 4, "table_sections", True, True, True, False, False),
        ("vahealthhistorydetails", "Disease / Co-morbidity", "Disease/Co-morbidity", "fa-history", 5, "health_history_summary", True, True, True, False, False),
        ("vageneralsymptoms", "General Symptoms", "General Symptoms", "fa-thermometer", 6, "table_sections", True, True, True, False, False),
        ("varespiratorycardiacsymptoms", "Respiratory / Cardiac", "Respiratory / Cardiac", "fa-lungs", 7, "table_sections", True, True, True, False, False),
        ("vaabdominalsymptoms", "Abdominal", "Abdominal", "fa-capsules", 8, "table_sections", True, True, True, False, False),
        ("vaneurologicalsymptoms", "Neurological", "Neurological", "fa-brain", 9, "table_sections", True, True, True, False, False),
        ("vaskinmucosalsymptoms", "Skin / Mucosal / Others", "Skin / Mucosal / Others", "fa-allergies", 10, "table_sections", True, True, True, False, False),
        ("vaneonatalfeedingsymptoms", "Neonatal Specific", "Neonatal Specific", "fa-baby-carriage", 11, "table_sections", True, True, True, False, False),
        ("vamaternalsymptoms", "Maternal", "Maternal", "fa-female", 12, "table_sections", True, True, True, False, False),
        ("vahealthserviceutilisation", "Health Service Utilization", "Health Service Utilization", "fa-hospital-alt", 13, "table_sections", True, True, True, False, False),
        ("vanarrationanddocuments", "Narration / Documents / COD", "Narration / Documents / COD", "fa-file-medical-alt", 14, "attachments", True, True, True, True, False),
    ],
    "WHO_2022_VA_SOCIAL": [
        ("vainterviewdetails", "Interview Details", "Interview Details", "fa-info-circle", 1, "table_sections", False, False, True, False, False),
        ("vademographicdetails", "Demographic / Risk Factors", "Demographic / Risk Factors", "fa-user", 2, "table_sections", True, True, True, False, True),
        ("vaneonatalperioddetails", "Neonatal Period", "Neonatal Period", "fa-baby", 3, "table_sections", True, True, True, False, False),
        ("vainjuriesdetails", "Injuries", "Injuries", "fa-first-aid", 4, "table_sections", True, True, True, False, False),
        ("vahealthhistorydetails", "Disease / Co-morbidity", "Disease/Co-morbidity", "fa-history", 5, "health_history_summary", True, True, True, False, False),
        ("vageneralsymptoms", "General Symptoms", "General Symptoms", "fa-thermometer", 6, "table_sections", True, True, True, False, False),
        ("varespiratorycardiacsymptoms", "Respiratory / Cardiac", "Respiratory / Cardiac", "fa-lungs", 7, "table_sections", True, True, True, False, False),
        ("vaabdominalsymptoms", "Abdominal", "Abdominal", "fa-capsules", 8, "table_sections", True, True, True, False, False),
        ("vaneurologicalsymptoms", "Neurological", "Neurological", "fa-brain", 9, "table_sections", True, True, True, False, False),
        ("vaskinmucosalsymptoms", "Skin / Mucosal / Others", "Skin / Mucosal / Others", "fa-allergies", 10, "table_sections", True, True, True, False, False),
        ("vaneonatalfeedingsymptoms", "Neonatal Specific", "Neonatal Specific", "fa-baby-carriage", 11, "table_sections", True, True, True, False, False),
        ("vamaternalsymptoms", "Maternal", "Maternal", "fa-female", 12, "table_sections", True, True, True, False, False),
        ("vahealthserviceutilisation", "Health Service Utilization", "Health Service Utilization", "fa-hospital-alt", 13, "table_sections", True, True, True, False, False),
        ("vanarrationanddocuments", "Narration / Documents / COD", "Narration / Documents / COD", "fa-file-medical-alt", 14, "attachments", True, True, True, True, False),
        ("social_autopsy", "Social Autopsy", "Social Autopsy", "fa-users", 15, "table_sections", True, True, True, False, False),
    ],
}


def upgrade():
    op.create_table(
        "mas_category_display_config",
        sa.Column("category_display_config_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("form_type_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=False),
        sa.Column("display_label", sa.String(length=128), nullable=False),
        sa.Column("nav_label", sa.String(length=128), nullable=False),
        sa.Column("icon_name", sa.String(length=64), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("render_mode", sa.String(length=32), nullable=False),
        sa.Column("show_to_coder", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_to_reviewer", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_to_site_pi", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("always_include", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default_start", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["form_type_id"], ["mas_form_types.form_type_id"]),
        sa.PrimaryKeyConstraint("category_display_config_id"),
        sa.UniqueConstraint(
            "form_type_id",
            "category_code",
            name="uq_category_display_config_form_type",
        ),
    )
    op.create_index(
        "idx_mas_category_display_config_form_type",
        "mas_category_display_config",
        ["form_type_id"],
        unique=False,
    )

    bind = op.get_bind()
    form_types = sa.table(
        "mas_form_types",
        sa.column("form_type_id", postgresql.UUID(as_uuid=True)),
        sa.column("form_type_code", sa.String()),
    )
    category_display = sa.table(
        "mas_category_display_config",
        sa.column("category_display_config_id", postgresql.UUID(as_uuid=True)),
        sa.column("form_type_id", postgresql.UUID(as_uuid=True)),
        sa.column("category_code", sa.String()),
        sa.column("display_label", sa.String()),
        sa.column("nav_label", sa.String()),
        sa.column("icon_name", sa.String()),
        sa.column("display_order", sa.Integer()),
        sa.column("render_mode", sa.String()),
        sa.column("show_to_coder", sa.Boolean()),
        sa.column("show_to_reviewer", sa.Boolean()),
        sa.column("show_to_site_pi", sa.Boolean()),
        sa.column("always_include", sa.Boolean()),
        sa.column("is_default_start", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )

    now = datetime.now(timezone.utc)
    for form_type_code, rows in CATEGORY_DISPLAY_ROWS.items():
        form_type_id = bind.execute(
            sa.select(form_types.c.form_type_id).where(
                form_types.c.form_type_code == form_type_code
            )
        ).scalar_one_or_none()
        if not form_type_id:
            continue

        op.bulk_insert(
            category_display,
            [
                {
                    "category_display_config_id": uuid.uuid4(),
                    "form_type_id": form_type_id,
                    "category_code": category_code,
                    "display_label": display_label,
                    "nav_label": nav_label,
                    "icon_name": icon_name,
                    "display_order": display_order,
                    "render_mode": render_mode,
                    "show_to_coder": show_to_coder,
                    "show_to_reviewer": show_to_reviewer,
                    "show_to_site_pi": show_to_site_pi,
                    "always_include": always_include,
                    "is_default_start": is_default_start,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }
                for (
                    category_code,
                    display_label,
                    nav_label,
                    icon_name,
                    display_order,
                    render_mode,
                    show_to_coder,
                    show_to_reviewer,
                    show_to_site_pi,
                    always_include,
                    is_default_start,
                ) in rows
            ],
        )


def downgrade():
    op.drop_index(
        "idx_mas_category_display_config_form_type",
        table_name="mas_category_display_config",
    )
    op.drop_table("mas_category_display_config")
