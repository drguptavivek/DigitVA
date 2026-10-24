"""``flask ui-strings`` — Expo UI string maintenance (digitva-cqw9)."""

import click

from app.services import ui_string_machine_job as job
from app.services.ui_string_service import UiStringError


@click.group("ui-strings")
def ui_strings_group():
    """Expo UI string commands."""


@ui_strings_group.command("machine-translate")
@click.option("--locale", "locales", multiple=True, help="Limit to a locale; repeatable.")
@click.option("--dry-run", is_flag=True, help="Count what would be created; call no provider.")
@click.option("--limit", type=click.IntRange(min=1), default=None, help="At most N strings per locale.")
def machine_translate(locales, dry_run, limit):
    """Create machine candidates for missing strings (never served until accepted)."""
    try:
        status = job.run(locales or None, dry_run=dry_run, limit=limit)
    except UiStringError as exc:
        raise click.ClickException(str(exc))
    except job.azure.NotConfigured as exc:
        raise click.ClickException(str(exc))
    for code, counts in status["results"].items():
        click.echo(f"{code}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


@ui_strings_group.command("bake")
@click.option("--locale", required=True, help="Locale to bake, e.g. hi.")
@click.option("--out", "out_dir", required=True, type=click.Path(file_okay=False))
def bake_cmd(locale, out_dir):
    """Write <out>/<locale>.json: bundled strings plus accepted corrections (no machine drafts)."""
    from pathlib import Path

    from app.services.ui_string_bake import bake

    try:
        text, changed = bake(locale)
    except (UiStringError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{locale}.json").write_text(text, encoding="utf-8")
    click.echo(f"wrote {out / (locale + '.json')}: {changed} string(s) changed from the bundle")


def init_app(app):
    app.cli.add_command(ui_strings_group)
