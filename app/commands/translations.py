"""``flask translations`` — carry UI-string and questionnaire translations across servers."""

import json

import click

from app import db
from app.services import translation_transfer_service as svc


@click.group("translations")
def translations_group():
    """Dump and load translation rows (digitva-3b65)."""


@translations_group.command("dump")
@click.argument("path", type=click.Path(dir_okay=False, writable=True))
@click.option("--ui-strings/--no-ui-strings", default=True)
@click.option("--questionnaire/--no-questionnaire", default=True)
@click.option("--locale", "locales", multiple=True, help="Limit to a locale; repeatable.")
def dump_cmd(path, ui_strings, questionnaire, locales):
    """Write every row (all sources, machine included) to a JSON file."""
    data = svc.dump(ui_strings=ui_strings, questionnaire=questionnaire, locales=locales)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    n_ui = len(data.get("ui_strings", []))
    n_q = len(data.get("questionnaire", {}).get("translations", []))
    click.echo(f"wrote {path}: ui_strings={n_ui}, questionnaire={n_q}")


@translations_group.command("load")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Count only; write nothing.")
def load_cmd(path, dry_run):
    """Insert the file's rows the target lacks. Never overwrites an existing row."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        counts = svc.load(data, dry_run=dry_run)
    except (svc.TransferError, ValueError) as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    for store in ("ui_strings", "questionnaire"):
        for (scope, source), tally in sorted(counts[store].items()):
            click.echo(f"{store} {scope} {source}: " + ", ".join(f"{k}={tally[k]}" for k in svc.RESULT_KEYS))
    for store, n in sorted(counts["unknown_authors"].items()):
        click.echo(f"{store}: unknown_authors={n}")
    for name in counts["locales_created"]:
        click.echo(f"{'would create' if dry_run else 'created'} locale {name}")
    for name in counts["versions_bumped"]:
        click.echo(f"{'would bump' if dry_run else 'bumped'} version {name}")
    if dry_run:
        click.echo("dry run: nothing written")


def init_app(app):
    app.cli.add_command(translations_group)
