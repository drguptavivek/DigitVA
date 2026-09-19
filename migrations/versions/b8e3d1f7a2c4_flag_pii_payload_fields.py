"""Flag the payload fields that carry personal data

``mas_field_display_config.is_pii`` is read by
``FieldMappingService.get_pii_field_ids()`` to redact the data-manager CSV
export. Eleven WHO_2022_VA fields already carried the flag, set by hand
through the admin field-mapping panel.

Two gaps remained. Four fields were never flagged at all: ``Id10010c``,
``Id10073`` (national identification number), and web intake's
``abha_number`` and ``abha_address``. And none of it was reproducible: the
rows are seeded from ``mapping_labels.xlsx``, which has no ``is_pii`` column,
so a fresh install or a mapping reseed starts with no flags and the export
falls back entirely to the hardcoded ``CSV_EXPORT_OMIT_PAYLOAD_FIELDS`` list,
which does not cover the questionnaire's name fields.

This migration flags those fields on every registered form type, not just
WHO_2022_VA. These are WHO instrument field ids that mean the same thing in
any WHO-derived form type; a form type such as WHO_2022_VA_SOCIAL has its own
``mas_field_display_config`` rows (cloned once from WHO_2022_VA and never
resynced) and needs the same flags applied to its own copies, or its export
stays unredacted. Of the fifteen fields below, twelve (Id10007, Id10010,
Id10010c, Id10017, Id10018, Id10055, Id10057, Id10061, Id10062, Id10070,
Id10071, Id10072) are real coder-mapped rows with a category and subcategory
already set; only Id10073, abha_number and abha_address are genuinely
unmapped, and those get a row created here with
``category_code``/``subcategory_code`` NULL. The NULL subcategory matters:
``_build_fieldsitepi`` requires a non-NULL subcategory to render a field,
while ``_build_pii_field_ids`` does not consult ``is_active`` at all — it
keys on ``is_pii`` alone — so these rows are visible to redaction and
invisible to the coding screen regardless of ``is_active``. Nothing a coder
sees changes, and this migration never touches ``is_active`` on a row it
updates (only on a row it creates, where the field has no category/
subcategory to render anyway) — forcing it true would resurrect a field an
operator had deliberately deactivated.

The list below is frozen at this revision. The living source is
``app/services/pii_field_registry.py``, which reapplies it after a mapping
reseed.

Revision ID: b8e3d1f7a2c4
Revises: f1c6a9d3e7b5
"""

import sqlalchemy as sa
from alembic import op


revision = "b8e3d1f7a2c4"
down_revision = "c5f2a8d1e9b3"
branch_labels = None
depends_on = None


# field_id -> pii_type
PII_FIELDS = {
    # Already flagged by hand in the live database; listed so a fresh install
    # or a mapping reseed reproduces the same set.
    "Id10007": "name",  # full name of VA respondent
    "Id10010": "name",  # name of VA interviewer
    "Id10017": "name",  # first/given name(s) of the deceased
    "Id10018": "name",  # surname(s) of the deceased
    "Id10061": "name",  # full name of the father
    "Id10062": "name",  # full name of the mother
    "Id10055": "location",  # place of death, free text
    "Id10057": "location",  # where the death occurred, free text to village
    "Id10070": "identifier",  # death registration number
    "Id10071": "date",  # date of death registration
    "Id10072": "identifier",  # death certificate identifier
    # Missing until now.
    "Id10010c": "identifier",  # ID of VA interviewer
    "Id10073": "identifier",  # national identification number of deceased
    "abha_number": "identifier",
    "abha_address": "identifier",
}


def upgrade():
    connection = op.get_bind()
    form_type_ids = connection.execute(
        sa.text("SELECT form_type_id FROM mas_form_types WHERE is_active = true")
    ).scalars().all()
    if not form_type_ids:
        # A database that has not seeded any form type yet (a fresh install
        # seeds after migrating). pii_field_registry applies the same rows at
        # seed time, so there is nothing to do here.
        return

    for form_type_id in form_type_ids:
        for field_id, pii_type in PII_FIELDS.items():
            connection.execute(
                sa.text(
                    """
                    INSERT INTO mas_field_display_config (
                        config_id, form_type_id, field_id,
                        category_code, subcategory_code,
                        flip_color, is_info, summary_include,
                        is_pii, pii_type, display_order,
                        is_active, is_custom, created_at, updated_at
                    )
                    VALUES (
                        gen_random_uuid(), :form_type_id, :field_id,
                        NULL, NULL,
                        false, false, false,
                        true, :pii_type, 0,
                        true, true, NOW(), NOW()
                    )
                    ON CONFLICT ON CONSTRAINT uq_field_config_form_type
                    DO UPDATE SET
                        is_pii = true,
                        -- An operator's own classification, set from the admin
                        -- panel, is never replaced: the registry decides whether a
                        -- field is PII, not how someone chose to label it.
                        pii_type = COALESCE(
                            mas_field_display_config.pii_type, EXCLUDED.pii_type
                        ),
                        -- is_active is a display flag, not a redaction one:
                        -- leave it as the operator set it. Redaction keys on
                        -- is_pii alone, so it does not need is_active touched.
                        updated_at = NOW()
                    WHERE mas_field_display_config.is_pii IS DISTINCT FROM true
                       OR mas_field_display_config.pii_type IS NULL
                    """
                ),
                {"form_type_id": form_type_id, "field_id": field_id, "pii_type": pii_type},
            )


def downgrade():
    connection = op.get_bind()
    form_type_ids = connection.execute(
        sa.text("SELECT form_type_id FROM mas_form_types")
    ).scalars().all()
    if not form_type_ids:
        return

    # Only the redaction-only rows this migration created are removed. Flags on
    # rows that already existed are deliberately left in place: most of them
    # predate this migration (they were set by hand in the admin field-mapping
    # panel) and there is no record of which ones did, so clearing them would
    # silently widen what the data-manager CSV export emits.
    connection.execute(
        sa.text(
            """
            DELETE FROM mas_field_display_config
            WHERE form_type_id = ANY(:form_type_ids)
              AND field_id = ANY(:field_ids)
              AND is_custom = true
              AND category_code IS NULL
              AND subcategory_code IS NULL
            """
        ),
        {"form_type_ids": form_type_ids, "field_ids": list(PII_FIELDS)},
    )
