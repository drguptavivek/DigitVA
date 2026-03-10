"""
CLI commands for ODK schema synchronization.

Usage:
  flask odk-sync choices --form-type=WHO_2022_VA [--dry-run]
  flask odk-sync detect-changes --form-type=WHO_2022_VA
"""
import click
from app import db
from app.services.odk_schema_sync_service import get_sync_service


@click.group("odk-sync")
def odk_sync_group():
    """ODK schema synchronization commands."""
    pass


@odk_sync_group.command("choices")
@click.option("--form-type", required=True, help="Form type code (e.g., WHO_2022_VA)")
@click.option("--project-id", type=int, required=True, help="ODK Central project ID")
@click.option("--form-id", required=True, help="ODK form ID (XML form ID)")
@click.option("--dry-run", is_flag=True, help="Show changes without applying them")
def sync_choices(form_type, project_id, form_id, dry_run):
    """Sync choice mappings from ODK Central for a form type.

    Example:
        flask odk-sync choices --form-type=WHO_2022_VA --project-id=1 --form-id=WHO_VA
    """
    sync_service = get_sync_service()

    click.echo(f"Syncing choices for {form_type} (ODK project {project_id}, form {form_id})...")

    if dry_run:
        changes = sync_service.detect_schema_changes(form_type, project_id, form_id)
        if "error" in changes:
            click.echo(f"Error: {changes['error']}")
            return
        click.echo("\nDetected changes (dry run):")
        click.echo(f"  New choices:     {len(changes.get('new_choices', []))}")
        click.echo(f"  Removed choices: {len(changes.get('removed_choices', []))}")
        click.echo(f"  New fields:      {len(changes.get('new_fields', []))}")
        click.echo(f"  Removed fields:  {len(changes.get('removed_fields', []))}")
        if changes.get("new_choices"):
            click.echo("\n  Sample new choices:")
            for field_id, val in list(changes["new_choices"])[:5]:
                click.echo(f"    + {field_id}.{val}")
    else:
        stats = sync_service.sync_form_choices(form_type, project_id, form_id)
        click.echo("\nSync complete:")
        click.echo(f"  Fields processed:    {stats['fields_processed']}")
        click.echo(f"  Choices added:       {stats['choices_added']}")
        click.echo(f"  Choices updated:     {stats['choices_updated']}")
        click.echo(f"  Choices deactivated: {stats['choices_deactivated']}")
        if stats["errors"]:
            click.echo("\nErrors:")
            for err in stats["errors"]:
                click.echo(f"  - {err}")
            raise SystemExit(1)


@odk_sync_group.command("detect-changes")
@click.option("--form-type", required=True, help="Form type code")
@click.option("--project-id", type=int, required=True, help="ODK Central project ID")
@click.option("--form-id", required=True, help="ODK form ID")
def detect_changes(form_type, project_id, form_id):
    """Detect schema changes between ODK Central and the database.

    Example:
        flask odk-sync detect-changes --form-type=WHO_2022_VA --project-id=1 --form-id=WHO_VA
    """
    sync_service = get_sync_service()
    changes = sync_service.detect_schema_changes(form_type, project_id, form_id)

    if "error" in changes:
        click.echo(f"Error: {changes['error']}")
        raise SystemExit(1)

    click.echo(f"\nSchema changes for {form_type}:")
    click.echo("=" * 50)

    new_fields = changes.get("new_fields", [])
    removed_fields = changes.get("removed_fields", [])
    new_choices = changes.get("new_choices", [])
    removed_choices = changes.get("removed_choices", [])

    click.echo(f"\nNew fields ({len(new_fields)}):")
    for f in new_fields:
        click.echo(f"  + {f}")

    click.echo(f"\nRemoved fields ({len(removed_fields)}):")
    for f in removed_fields:
        click.echo(f"  - {f}")

    click.echo(f"\nNew choices ({len(new_choices)}):")
    for field_id, val in new_choices:
        click.echo(f"  + {field_id}.{val}")

    click.echo(f"\nRemoved choices ({len(removed_choices)}):")
    for field_id, val in removed_choices:
        click.echo(f"  - {field_id}.{val}")


def init_app(app):
    """Register ODK sync CLI commands with the Flask app."""
    app.cli.add_command(odk_sync_group)
