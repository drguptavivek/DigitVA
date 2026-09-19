"""``flask instrument-translations`` — manage a standard instrument's languages.

Importing the documented source workbook for each language is an **operator
step**, not a migration: the workbooks are reference material, the import is
re-runnable, and a migration that read them would pin a historical revision to
today's files. See docs/current-state/cli-reference.md.
"""

import json

import click

from app import db
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    TRANSLATION_COVERAGE_THRESHOLD,
    InstrumentTranslationError,
    documented_sources,
    export_translations,
    import_translations,
    locale_status,
    set_locale_active,
)


@click.group("instrument-translations")
def instrument_translations_group():
    """Instrument display-language commands."""


def _fail(exc: InstrumentTranslationError) -> None:
    raise click.ClickException(str(exc))


@instrument_translations_group.command("import")
@click.argument("instrument_code")
@click.argument("locale")
@click.argument("workbook")
@click.option(
    "--cross-check",
    is_flag=True,
    default=False,
    help="Report differences against a workbook that is not the documented source; writes nothing.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Activate the locale even when coverage is below the threshold (logged).",
)
def import_workbook(instrument_code, locale, workbook, cross_check, force):
    """Import LOCALE for INSTRUMENT_CODE from WORKBOOK."""
    try:
        report = import_translations(
            instrument_code, locale, workbook, cross_check=cross_check, force=force
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        _fail(exc)
    if cross_check:
        db.session.rollback()
    else:
        db.session.commit()
    click.echo(
        f"{report.instrument_code}/{report.locale_code} from {report.workbook}: "
        f"coverage={report.coverage:.1%} "
        f"({report.translated_labels}/{report.reference_labels} survey labels), "
        f"written={report.written}, kept_edited={report.kept_edited}, "
        f"missing={len(report.missing_from_workbook)}, "
        f"unknown={len(report.unknown_in_workbook)}"
    )
    if report.cross_check:
        click.echo("Cross-check only: nothing was written.")
    elif report.activated:
        click.echo("Locale is active." + (" (forced below threshold)" if report.forced else ""))
    else:
        click.echo(
            "Locale is NOT active: coverage is below "
            f"{TRANSLATION_COVERAGE_THRESHOLD:.0%}. Re-run with --force to activate anyway."
        )


@instrument_translations_group.command("export")
@click.argument("instrument_code")
@click.argument("locale")
@click.option("--output", "output_path", default=None, help="Write to this file instead of stdout.")
def export(instrument_code, locale, output_path):
    """Write LOCALE's strings as the JSON the panel and the form read."""
    try:
        payload = export_translations(instrument_code, locale)
    except InstrumentTranslationError as exc:
        _fail(exc)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        click.echo(f"Wrote {locale} version {payload['version']} to {output_path}")
    else:
        click.echo(text)


@instrument_translations_group.command("activate")
@click.argument("instrument_code")
@click.argument("locale")
@click.option("--force", is_flag=True, default=False, help="Activate below the coverage threshold.")
def activate(instrument_code, locale, force):
    """Serve LOCALE to forms."""
    try:
        result = set_locale_active(instrument_code, locale, True, force=force)
    except InstrumentTranslationError as exc:
        db.session.rollback()
        _fail(exc)
    db.session.commit()
    click.echo(f"{locale} active (coverage {result['coverage']:.1%}, version {result['version']}).")


@instrument_translations_group.command("deactivate")
@click.argument("instrument_code")
@click.argument("locale")
def deactivate(instrument_code, locale):
    """Stop serving LOCALE to forms."""
    try:
        set_locale_active(instrument_code, locale, False)
    except InstrumentTranslationError as exc:
        db.session.rollback()
        _fail(exc)
    db.session.commit()
    click.echo(f"{locale} deactivated.")


@instrument_translations_group.command("status")
@click.option("--instrument-code", default=BASE_INSTRUMENT_CODE, show_default=True)
def status(instrument_code):
    """Coverage, version, source and active flag for every locale."""
    try:
        rows = locale_status(instrument_code)
        documented = documented_sources()
    except InstrumentTranslationError as exc:
        _fail(exc)
    click.echo(
        f"{'locale':<8}{'active':<8}{'ver':<5}{'coverage':>9}  "
        f"{'source':<34}documented"
    )
    for row in rows:
        expected = documented.get(row["locale_code"])
        coverage = f"{row['coverage']:.1%}"
        click.echo(
            f"{row['locale_code']:<8}"
            f"{('yes' if row['is_active'] else 'no'):<8}"
            f"{row['version']:<5}"
            f"{coverage:>9}  "
            f"{(row['source_document'] or '-'):<34}"
            f"{expected.workbook if expected else '-'}"
        )


def init_app(app):
    app.cli.add_command(instrument_translations_group)
