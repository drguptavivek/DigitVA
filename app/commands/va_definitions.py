"""`flask va-definitions` — WHO VA cause definitions master data.

See docs/policy/va-cause-definitions.md.
"""

from pathlib import Path

import click

from app.services.va_cause_definition_service import (
    DEFAULT_SEED_JSON_PATH,
    DEFAULT_SOURCE_HTML_PATH,
    import_va_definitions,
    parse_va_definitions_html,
    write_seed_json,
)


@click.group("va-definitions")
def va_definitions_group():
    """WHO VA cause definitions commands."""


def _parse(path: str) -> list[dict]:
    source = Path(path)
    if not source.is_file():
        raise click.ClickException(f"Definitions file not found: {source}")
    try:
        return parse_va_definitions_html(source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@va_definitions_group.command("import")
@click.argument("path", required=False, default=str(DEFAULT_SOURCE_HTML_PATH))
@click.option("--force", is_flag=True, default=False,
              help="Also overwrite rows an admin has edited.")
def import_command(path: str, force: bool) -> None:
    """Upsert definitions from the WHO definitions HTML table at PATH."""
    rows = _parse(path)
    result = import_va_definitions(rows, force=force)
    click.echo(
        f"VA definitions rows={len(rows)} inserted={result.inserted} "
        f"updated={result.updated} unchanged={result.unchanged} "
        f"skipped_edited={result.skipped_edited}"
    )


@va_definitions_group.command("generate-seed-json")
@click.argument("path", required=False, default=str(DEFAULT_SOURCE_HTML_PATH))
@click.option("--json-path", default=str(DEFAULT_SEED_JSON_PATH), show_default=True)
def generate_seed_json(path: str, json_path: str) -> None:
    """Freeze the parsed HTML table into the shipped seed JSON."""
    rows = _parse(path)
    write_seed_json(rows, json_path)
    click.echo(f"Wrote {len(rows)} rows to {json_path}")


def init_app(app):
    app.cli.add_command(va_definitions_group)
