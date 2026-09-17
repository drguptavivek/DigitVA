"""CLI commands for auditing and repairing ODK form mappings.

An ODK form may be mapped to at most one project-site pair per ODK connection
(see ``app/services/odk_form_mapping_service.py``). Historical data predates that
rule, so this command reports the duplicates and can remove the stale ones.
"""

import click

from app import db
from app.models import MapProjectSiteOdk
from app.services.odk_form_mapping_service import find_duplicate_odk_form_mappings


@click.group("odk-mappings")
def odk_mappings_group():
    """ODK form mapping audit commands."""
    pass


@odk_mappings_group.command("audit")
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Delete stale duplicate mappings. Dry-run is the default.",
)
def audit(fix):
    """Report ODK forms mapped to more than one project-site.

    ``--fix`` deletes only a mapping that shares its ODK form with another mapping
    on the same connection, sits on a deactivated project-site pair, and leaves at
    least one mapping on an active pair behind. When two conflicting mappings are
    both active the command changes nothing and exits non-zero: choosing which one
    survives is a human decision.
    """
    conflicts = find_duplicate_odk_form_mappings()
    if not conflicts:
        click.echo("No ODK form mapping conflicts found.")
        return

    for conflict in conflicts:
        click.echo(
            f"\nconnection={conflict.connection_name} "
            f"odk_project={conflict.odk_project_id} "
            f"odk_form={conflict.odk_form_id}"
        )
        for target in conflict.targets:
            status = "active" if target.project_site_active else "deactive"
            click.echo(
                f"  {target.project_id}/{target.site_id} "
                f"pair={status} submissions={target.submission_count}"
            )

    unresolvable = [c for c in conflicts if len(c.active_targets) > 1]
    if unresolvable:
        for conflict in unresolvable:
            pairs = ", ".join(
                f"{t.project_id}/{t.site_id}" for t in conflict.active_targets
            )
            click.echo(
                f"\nREFUSED: ODK form {conflict.odk_form_id} in ODK project "
                f"{conflict.odk_project_id} is mapped to more than one ACTIVE "
                f"project-site ({pairs}). Decide which mapping survives and remove "
                "the other through the admin panel."
            )
        raise SystemExit(1)

    if not fix:
        click.echo("\nDry-run: nothing deleted. Re-run with --fix to remove stale mappings.")
        return

    deleted = 0
    for conflict in conflicts:
        for target in conflict.stale_targets:
            mapping = db.session.get(MapProjectSiteOdk, target.mapping_id)
            if mapping is None:
                continue
            db.session.delete(mapping)
            deleted += 1
            click.echo(
                f"Deleted mapping {target.project_id}/{target.site_id} → "
                f"odk_project={conflict.odk_project_id} form={conflict.odk_form_id} "
                f"(deactivated pair, submissions={target.submission_count})"
            )

    db.session.commit()
    click.echo(f"\nSummary: deleted={deleted} conflicts_inspected={len(conflicts)}")


def init_app(app):
    """Register ODK mapping CLI commands with the Flask app."""
    app.cli.add_command(odk_mappings_group)
