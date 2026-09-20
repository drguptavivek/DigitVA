"""``flask instrument-translations`` — manage a standard instrument's languages.

Importing a language's questionnaire source is an **operator step**, not a
migration: it is a reviewed one-time activity, the import is re-runnable
against any readable workbook, and a migration that read one would pin a
historical revision to today's files. See docs/current-state/cli-reference.md.
"""

import json
import uuid

import click
import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import LIFECYCLE_APPROVED, SOURCE_EDITED, SOURCE_IMPORTED
from app.models.va_users import VaUsers
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    LIFECYCLE_STATES,
    InstrumentTranslationError,
    export_translations,
    export_xliff,
    import_translations,
    import_xliff,
    locale_status,
    set_locale_active,
    set_locale_lifecycle_state,
)


@click.group("instrument-translations")
def instrument_translations_group():
    """Instrument display-language commands."""


def _fail(exc: InstrumentTranslationError) -> None:
    raise click.ClickException(str(exc))


def _resolve_approver(raw: str) -> uuid.UUID:
    """A CLI-supplied user id or email, resolved to a ``va_users.user_id``.

    The CLI has no logged-in session, so approving from here requires the
    operator to name who is approving -- ``--approved-by`` is required for the
    'approved' transition (not optional/NULL): an approval with no recorded
    approver would defeat the point of the approval gate this bead adds.
    """
    value = (raw or "").strip()
    if not value:
        raise click.ClickException(
            "--approved-by is required to approve a locale: name the "
            "approving administrator by user id or email."
        )
    try:
        user_id = uuid.UUID(value)
        user = db.session.get(VaUsers, user_id)
    except ValueError:
        user = db.session.scalar(
            sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == value.lower())
        )
    if user is None:
        raise click.ClickException(f"No DigitVA user found for --approved-by {value!r}.")
    return user.user_id


@instrument_translations_group.command("import")
@click.argument("instrument_code")
@click.argument("locale")
@click.argument("workbook")
@click.option(
    "--cross-check",
    is_flag=True,
    default=False,
    help="Dry run: read the workbook and report, writing nothing.",
)
@click.option(
    "--language-name",
    default=None,
    help="Display name for a locale imported for the first time, when the "
    "workbook's own language column does not carry one.",
)
def import_workbook(instrument_code, locale, workbook, cross_check, language_name):
    """Import LOCALE for INSTRUMENT_CODE from WORKBOOK.

    Importing a questionnaire source is a reviewed one-time activity: any
    readable workbook is accepted for any locale. This never activates or
    deactivates the locale -- coverage is reported here but decides nothing;
    run ``activate`` explicitly once you are ready to serve it. Changing a
    translation already served is the admin string editor's job, not a
    re-import.
    """
    try:
        report = import_translations(
            instrument_code, locale, workbook,
            cross_check=cross_check, language_name=language_name,
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
        f"({report.translated_items}/{report.reference_items} translatable items), "
        f"written={report.written}, kept_edited={report.kept_edited}, "
        f"missing={len(report.missing_from_workbook)}, "
        f"unknown={len(report.unknown_in_workbook)}"
    )
    click.echo(
        f"  labels={report.label_coverage:.1%} "
        f"({report.translated_labels}/{report.reference_labels} survey labels)"
    )
    for name, counts in sorted(report.extension_coverage.items()):
        total = counts["total"]
        pct = (counts["translated"] / total) if total else 0.0
        label_total = counts["label_total"]
        label_pct = (counts["label_translated"] / label_total) if label_total else 0.0
        click.echo(
            f"  {name}: {pct:.1%} ({counts['translated']}/{total}) -- "
            f"labels {label_pct:.1%} ({counts['label_translated']}/{label_total})"
        )
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


@instrument_translations_group.command("lifecycle")
@click.argument("instrument_code")
@click.argument("locale")
@click.argument("state", type=click.Choice(LIFECYCLE_STATES))
@click.option(
    "--approved-by", default=None,
    help="Required when STATE is 'approved': the approving administrator, "
    "by user id or email. Not recorded for 'draft' or 'in_review'.",
)
def lifecycle(instrument_code, locale, state, approved_by):
    """Move LOCALE to STATE (draft, in_review or approved).

    Only an 'approved' locale may be activated (see 'activate'). Leaving
    'approved' while a locale is still active is refused -- deactivate first.
    """
    actor_id = _resolve_approver(approved_by) if state == LIFECYCLE_APPROVED else None
    try:
        result = set_locale_lifecycle_state(
            instrument_code, locale, state, actor_id=actor_id,
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        _fail(exc)
    db.session.commit()
    click.echo(
        f"{result['locale_code']} lifecycle_state={result['lifecycle_state']} "
        f"approved_by={result['approved_by_user_id']} approved_at={result['approved_at']}"
    )


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
    except InstrumentTranslationError as exc:
        _fail(exc)
    click.echo(
        f"{'locale':<8}{'active':<8}{'lifecycle':<11}{'ver':<5}{'coverage':>9}  source"
    )
    for row in rows:
        coverage = f"{row['coverage']:.1%}"
        click.echo(
            f"{row['locale_code']:<8}"
            f"{('yes' if row['is_active'] else 'no'):<8}"
            f"{row['lifecycle_state']:<11}"
            f"{row['version']:<5}"
            f"{coverage:>9}  "
            f"labels {row['label_coverage']:.1%}  "
            f"{row['source_document'] or '-'}"
        )
        if extensions:
            for name, counts in sorted(row.get("extension_coverage", {}).items()):
                click.echo(
                    f"    {name}: {counts['coverage']:.1%} "
                    f"({counts['translated']}/{counts['total']}) -- "
                    f"labels {counts['label_coverage']:.1%} "
                    f"({counts['label_translated']}/{counts['label_total']})"
                )


def init_app(app):
    app.cli.add_command(instrument_translations_group)
