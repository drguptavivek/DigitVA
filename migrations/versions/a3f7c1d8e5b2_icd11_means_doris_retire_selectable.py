"""ICD-11 means DORIS; retire the 'selectable' classification.

Revision ID: a3f7c1d8e5b2
Revises: c7a4e2d9f1b6
Create Date: 2026-09-27 00:00:00.000000

digitva-0n3 phase 1. Owner decision in
docs/policy/doris-cod-workflow.md ("Decided 2026-09-27, not yet
implemented"); design record .tasks/2026-09-27-icd11-means-doris.md.

Choosing `icd_classification='icd11'` now always means
`cod_entry_mode='doris'`; ICD-10 always means simple entry. The
`selectable` classification (coder picks ICD-10 or ICD-11 per death) is
retired. Masked + DORIS becomes legal at the settings level (its own UI is
a later phase; nothing here builds it).

Upgrade drops the three old CHECKs, rewrites data (every 'selectable'
project to 'icd10', then every 'icd11' project to 'doris'), and adds the
new combined CHECK. Every project changed is logged, as migration
33dea3ea3303 does.

Downgrade is lossy: 'selectable' projects are not restored (DigitVA is not
deployed, dev data only). It drops the new CHECK, moves a masked
'doris' project back to 'simple' (the only combination the old
cod_entry_mode_masking CHECK allowed), and recreates the three old CHECKs.
"""

import logging

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f7c1d8e5b2"
down_revision = "c7a4e2d9f1b6"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

OLD_ICD_CLASSIFICATION_CHECK = "ck_va_project_master_icd_classification"
OLD_COD_ENTRY_MODE_MASKING_CHECK = "ck_va_project_master_cod_entry_mode_masking"
OLD_DORIS_REQUIRES_ICD11_CHECK = "ck_va_project_master_doris_requires_icd11"
NEW_CHECK = "ck_va_project_master_cod_entry_mode_classification"


def upgrade():
    op.drop_constraint(
        op.f(OLD_COD_ENTRY_MODE_MASKING_CHECK), "va_project_master", type_="check"
    )
    op.drop_constraint(
        op.f(OLD_DORIS_REQUIRES_ICD11_CHECK), "va_project_master", type_="check"
    )
    op.drop_constraint(
        op.f(OLD_ICD_CLASSIFICATION_CHECK), "va_project_master", type_="check"
    )

    bind = op.get_bind()

    selectable_changed = bind.execute(
        sa.text(
            "UPDATE va_project_master SET icd_classification = 'icd10' "
            "WHERE icd_classification = 'selectable' "
            "RETURNING project_id"
        )
    ).all()
    for (project_id,) in selectable_changed:
        log.warning(
            "va_project_master.icd_classification: project %s moved from "
            "'selectable' to 'icd10' (icd11_means_doris_retire_selectable)",
            project_id,
        )

    doris_changed = bind.execute(
        sa.text(
            "UPDATE va_project_master SET cod_entry_mode = 'doris' "
            "WHERE icd_classification = 'icd11' AND cod_entry_mode <> 'doris' "
            "RETURNING project_id"
        )
    ).all()
    for (project_id,) in doris_changed:
        log.warning(
            "va_project_master.cod_entry_mode: project %s moved to 'doris' "
            "(icd_classification='icd11', icd11_means_doris_retire_selectable)",
            project_id,
        )

    op.create_check_constraint(
        op.f("ck_va_project_master_icd_classification"),
        "va_project_master",
        "icd_classification IN ('icd10', 'icd11')",
    )
    op.create_check_constraint(
        op.f(NEW_CHECK),
        "va_project_master",
        "(icd_classification = 'icd11') = (cod_entry_mode = 'doris')",
    )


def downgrade():
    op.drop_constraint(op.f(NEW_CHECK), "va_project_master", type_="check")
    op.drop_constraint(
        op.f(OLD_ICD_CLASSIFICATION_CHECK), "va_project_master", type_="check"
    )

    # The old cod_entry_mode_masking CHECK forbade masked + doris; a project
    # this phase made masked + doris legal for has no home under the old
    # rules, so it moves to simple entry rather than reinstating an invalid
    # row. 'selectable' classifications are not restored (lossy, dev only).
    op.execute(
        "UPDATE va_project_master SET cod_entry_mode = 'simple' "
        "WHERE masked_cod_required AND cod_entry_mode = 'doris'"
    )

    op.create_check_constraint(
        op.f(OLD_ICD_CLASSIFICATION_CHECK),
        "va_project_master",
        "icd_classification IN ('icd10', 'icd11', 'selectable')",
    )
    op.create_check_constraint(
        op.f(OLD_DORIS_REQUIRES_ICD11_CHECK),
        "va_project_master",
        "cod_entry_mode <> 'doris' OR icd_classification = 'icd11'",
    )
    op.create_check_constraint(
        op.f(OLD_COD_ENTRY_MODE_MASKING_CHECK),
        "va_project_master",
        "NOT (masked_cod_required AND cod_entry_mode = 'doris')",
    )
