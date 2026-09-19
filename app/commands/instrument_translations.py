"""``flask instrument-translations`` — manage a standard instrument's languages.

Importing the documented source workbook for each language is an **operator
step**, not a migration: the workbooks are reference material, the import is
re-runnable, and a migration that read them would pin a historical revision to
today's files. See docs/current-state/cli-reference.md.
"""

import json

import click

from app import db
from app.models.mas_instrument_locales import SOURCE_EDITED, SOURCE_IMPORTED
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    InstrumentTranslationError,
    documented_sources,
    export_translations,
    export_xliff,
    import_translations,
    import_xliff,
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
def import_workbook(instrument_code, locale, workbook, cross_check):
    """Import LOCALE for INSTRUMENT_CODE from WORKBOOK.

    This never activates or deactivates the locale -- coverage is reported
    here but decides nothing; run ``activate`` explicitly once you are ready
    to serve it.
    """
    try:
        report = import_translations(instrument_code, locale, workbook, cross_check=cross_check)
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
    for name, counts in sorted(report.extension_coverage.items()):
        total = counts["total"]
        pct = (counts["translated"] / total) if total else 0.0
        click.echo(f"  {name}: {pct:.1%} ({counts['translated']}/{total} labels)")
    if report.cross_check:
        click.echo("Cross-check only: nothing was written.")
    else:
        click.echo(
            "Locale is not activated by an import. Run "
            f"'instrument-translations activate {instrument_code} {locale}' "
            "when ready to serve it."
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


@instrument_translations_group.command("export-xliff")
@click.argument("instrument_code")
@click.argument("locale")
@click.option("--output", "output_path", default=None, help="Write to this file instead of stdout.")
def export_xliff_command(instrument_code, locale, output_path):
    """Write LOCALE as an XLIFF 2.0 document for a translator's CAT tool."""
    try:
        document = export_xliff(instrument_code, locale)
    except InstrumentTranslationError as exc:
        _fail(exc)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(document)
        click.echo(f"Wrote {locale} XLIFF to {output_path}")
    else:
        click.echo(document)


@instrument_translations_group.command("import-xliff")
@click.argument("instrument_code")
@click.argument("locale")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--as",
    "mark_as",
    type=click.Choice([SOURCE_IMPORTED, SOURCE_EDITED]),
    default=SOURCE_IMPORTED,
    show_default=True,
    help="How the written rows are marked. 'edited' outranks a later workbook re-import.",
)
def import_xliff_command(instrument_code, locale, path, mark_as):
    """Write the targets of the XLIFF 2.0 document at PATH back into LOCALE."""
    with open(path, encoding="utf-8") as handle:
        document = handle.read()
    try:
        report = import_xliff(instrument_code, locale, document, mark_as=mark_as)
    except InstrumentTranslationError as exc:
        db.session.rollback()
        _fail(exc)
    db.session.commit()
    click.echo(
        f"{report['instrument_code']}/{report['locale_code']} as {report['mark_as']}: "
        f"units={report['units']}, written={report['written']}, "
        f"unchanged={report['unchanged']}, kept_edited={report['kept_edited']}, "
        f"empty={report['skipped_empty']}, unknown={report['skipped_unknown_count']}, "
        f"too_long={report['skipped_too_long_count']}, version={report['version']}"
    )


@instrument_translations_group.command("activate")
@click.argument("instrument_code")
@click.argument("locale")
def activate(instrument_code, locale):
    """Serve LOCALE to forms."""
    try:
        result = set_locale_active(instrument_code, locale, True)
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
@click.option(
    "--extensions", is_flag=True, default=False,
    help="Also print each locale's per-extension (layer) coverage.",
)
def status(instrument_code, extensions):
    """Coverage, version, source and active flag for every locale.

    Coverage is informational: activation (the 'active' column) is a separate
    administrative action and is never decided by it.
    """
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
        if extensions:
            for name, counts in sorted(row.get("extension_coverage", {}).items()):
                click.echo(
                    f"    {name}: {counts['coverage']:.1%} "
                    f"({counts['translated']}/{counts['total']})"
                )


def init_app(app):
    app.cli.add_command(instrument_translations_group)
