"""CLI commands for targeted administrative data repairs."""

import click
import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaInitialAssessments,
    VaStatuses,
    VaSubmissionsAuditlog,
)


@click.group("repair")
def repair_group():
    """Administrative repair commands."""
    pass


@repair_group.command("reactivate-step1-after-final")
@click.option("--sid", default=None, help="Optional submission SID to repair.")
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Optional maximum number of candidate rows to inspect.",
)
@click.option(
    "--apply/--dry-run",
    default=False,
    help="Apply the repair. Dry-run is the default.",
)
def reactivate_step1_after_final(sid, limit, apply):
    """Reactivate historical Step 1 rows deactivated by old final-COD behavior."""
    stmt = (
        sa.select(
            VaFinalAssessments.va_sid,
            VaFinalAssessments.source_initial_assessment_id,
            VaInitialAssessments.va_iniassess_id,
            VaInitialAssessments.va_iniassess_by,
            VaInitialAssessments.va_iniassess_status,
            VaInitialAssessments.va_immediate_cod,
            VaInitialAssessments.va_antecedent_cod,
        )
        .join(
            VaInitialAssessments,
            VaInitialAssessments.va_iniassess_id
            == VaFinalAssessments.source_initial_assessment_id,
        )
        .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        .where(VaFinalAssessments.source_initial_assessment_id.is_not(None))
        .order_by(
            VaFinalAssessments.va_sid.asc(),
            VaFinalAssessments.va_finassess_createdat.desc(),
            VaFinalAssessments.va_finassess_id.desc(),
        )
    )
    if sid:
        stmt = stmt.where(VaFinalAssessments.va_sid == sid.strip())
    if limit is not None:
        stmt = stmt.limit(limit)

    rows = db.session.execute(stmt).mappings().all()
    if not rows:
        click.echo("No candidate Step 1 rows found.")
        return

    inspected = 0
    repaired = 0
    already_active = 0
    skipped_conflict = 0

    for row in rows:
        inspected += 1
        if row["va_iniassess_status"] == VaStatuses.active:
            already_active += 1
            click.echo(f"KEEP active {row['va_sid']} initial={row['va_iniassess_id']}")
            continue

        conflicting_active = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaInitialAssessments)
            .where(VaInitialAssessments.va_sid == row["va_sid"])
            .where(VaInitialAssessments.va_iniassess_by == row["va_iniassess_by"])
            .where(VaInitialAssessments.va_iniassess_status == VaStatuses.active)
            .where(VaInitialAssessments.va_iniassess_id != row["va_iniassess_id"])
        )
        if conflicting_active:
            skipped_conflict += 1
            click.echo(
                f"SKIP conflict {row['va_sid']} initial={row['va_iniassess_id']} "
                f"active_by_same_user={conflicting_active}"
            )
            continue

        repaired += 1
        click.echo(
            f"{'REPAIR' if apply else 'WOULD REPAIR'} {row['va_sid']} "
            f"initial={row['va_iniassess_id']} "
            f"immediate={row['va_immediate_cod']} "
            f"antecedent={row['va_antecedent_cod']}"
        )
        if not apply:
            continue

        initial = db.session.get(VaInitialAssessments, row["va_iniassess_id"])
        if initial is None:
            skipped_conflict += 1
            click.echo(
                f"SKIP missing {row['va_sid']} initial={row['va_iniassess_id']}"
            )
            continue

        initial.va_iniassess_status = VaStatuses.active
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=row["va_sid"],
                va_audit_byrole="vaadmin",
                va_audit_by=None,
                va_audit_operation="u",
                va_audit_action="step1 reactivated after final cod repair",
                va_audit_entityid=initial.va_iniassess_id,
            )
        )

    if apply:
        db.session.commit()
    else:
        db.session.rollback()

    click.echo(
        "Summary: "
        f"inspected={inspected} "
        f"repaired={repaired} "
        f"already_active={already_active} "
        f"skipped_conflict={skipped_conflict} "
        f"mode={'apply' if apply else 'dry-run'}"
    )


def init_app(app):
    """Register repair CLI commands with the Flask app."""
    app.cli.add_command(repair_group)
