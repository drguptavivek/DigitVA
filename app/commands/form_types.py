"""
CLI commands for form type management.

Usage:
  flask form-types list
  flask form-types register --code=BALLABGARH_VA --name="Ballabgarh VA Form"
  flask form-types stats --code=WHO_2022_VA
  flask form-types deactivate --code=TEST_FORM
"""
import click
from app.services.form_type_service import get_form_type_service


@click.group("form-types")
def form_types_group():
    """Form type management commands."""
    pass


@form_types_group.command("list")
def list_form_types():
    """List all registered active form types."""
    service = get_form_type_service()
    form_types = service.list_form_types()

    if not form_types:
        click.echo("No form types registered.")
        return

    click.echo("\nRegistered Form Types:")
    click.echo("=" * 60)
    for ft in form_types:
        stats = service.get_form_type_stats(ft.form_type_code)
        click.echo(f"\n{ft.form_type_code}")
        click.echo(f"  Name:       {ft.form_type_name}")
        click.echo(f"  Categories: {stats['category_count']}")
        click.echo(f"  Fields:     {stats['field_count']}")
        click.echo(f"  Choices:    {stats['choice_count']}")
        click.echo(f"  Forms:      {stats['form_count']}")


@form_types_group.command("register")
@click.option("--code", required=True, help="Form type code (e.g., BALLABGARH_VA)")
@click.option("--name", required=True, help="Display name")
@click.option("--description", help="Optional description")
@click.option("--template", help="Path to base Excel template file")
def register_form_type(code, name, description, template):
    """Register a new form type.

    Example:
        flask form-types register --code=BALLABGARH_VA --name="Ballabgarh VA Form"
    """
    service = get_form_type_service()
    try:
        ft = service.register_form_type(
            form_type_code=code,
            form_type_name=name,
            description=description,
            base_template_path=template,
        )
        click.echo(f"\nForm type registered: {ft.form_type_code}")
        click.echo(f"  ID:   {ft.form_type_id}")
        click.echo(f"  Name: {ft.form_type_name}")
    except ValueError as exc:
        click.echo(f"Error: {exc}")
        raise SystemExit(1)


@form_types_group.command("stats")
@click.option("--code", required=True, help="Form type code")
def form_type_stats(code):
    """Show statistics for a form type.

    Example:
        flask form-types stats --code=WHO_2022_VA
    """
    service = get_form_type_service()
    stats = service.get_form_type_stats(code)
    if not stats:
        click.echo(f"Form type not found: {code}")
        raise SystemExit(1)

    click.echo(f"\nStatistics for {code}:")
    click.echo("=" * 40)
    click.echo(f"  Name:       {stats['form_type_name']}")
    click.echo(f"  Active:     {stats['is_active']}")
    click.echo(f"  Forms:      {stats['form_count']}")
    click.echo(f"  Categories: {stats['category_count']}")
    click.echo(f"  Fields:     {stats['field_count']}")
    click.echo(f"  Choices:    {stats['choice_count']}")


@form_types_group.command("deactivate")
@click.option("--code", required=True, help="Form type code to deactivate")
@click.confirmation_option(prompt="Are you sure you want to deactivate this form type?")
def deactivate_form_type(code):
    """Deactivate a form type (soft delete, only if no forms use it).

    Example:
        flask form-types deactivate --code=TEST_FORM
    """
    service = get_form_type_service()
    try:
        result = service.deactivate_form_type(code)
        if result:
            click.echo(f"Form type deactivated: {code}")
        else:
            click.echo(f"Form type not found: {code}")
            raise SystemExit(1)
    except ValueError as exc:
        click.echo(f"Error: {exc}")
        raise SystemExit(1)


def init_app(app):
    """Register form-types CLI commands with the Flask app."""
    app.cli.add_command(form_types_group)
