"""Machine-draft the missing questionnaire translations (digitva-m2ve).

Policy: docs/policy/va-form-project-configuration.md ("Azure machine drafts for
missing questionnaire strings"). For each locale the job finds the reference
items with no ``map_instrument_translations`` row and no pending suggestion,
asks Azure Translator and inserts ``source='machine'`` rows with
``ON CONFLICT DO NOTHING``: an existing row is never touched and nothing it
writes is served until an administrator accepts or edits it.

One run at a time (a Redis lock); the last run's counts are kept in Redis for
the admin page. Shared by the Celery task, the admin route and the CLI.
"""

import json
import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import db
from app.models.map_instrument_translation_suggestions import (
    SUGGESTION_PENDING,
    MapInstrumentTranslationSuggestions as Suggestions,
)
from app.models.mas_instrument_locales import (
    SOURCE_MACHINE,
    MapInstrumentTranslations as Translations,
    MasInstrumentLocales,
)
from app.services import machine_translation_service as azure
from app.services import ui_string_machine_job as ui_job
from app.services import ui_string_service as uis
from app.services.instrument_translation_service import (
    _REFERENCE_RE,
    _TAG_RE,
    BASE_INSTRUMENT_CODE,
    MAX_TRANSLATION_TEXT_CHARS,
    InstrumentTranslationError,
    InvalidTranslationText,
    reference_items,
    validate_translation_text,
)

log = logging.getLogger(__name__)

LOCK_KEY = "digitva_instrument_machine_translate:lock"
STATUS_KEY = "digitva_instrument_machine_translate:status"
AlreadyRunning = ui_job.AlreadyRunning


def _redis():
    return ui_job._redis()


def last_run() -> dict | None:
    """The running or last-finished run, or ``None`` (also without Redis)."""
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(STATUS_KEY)
    except Exception:  # noqa: BLE001 - status is informational
        return None
    return json.loads(raw) if raw else None


def is_running() -> bool:
    client = _redis()
    try:
        return bool(client is not None and client.exists(LOCK_KEY))
    except Exception:  # noqa: BLE001 - the run itself will meet the lock
        return False


def _acceptable(candidate: str, english: str) -> bool:
    """Valid text whose references, placeholders and tags are the English's."""
    candidate = (candidate or "").strip()
    if not candidate or len(candidate) > MAX_TRANSLATION_TEXT_CHARS:
        return False
    try:
        validate_translation_text(candidate, english)
    except InvalidTranslationText:
        return False
    return (
        sorted(_REFERENCE_RE.findall(candidate)) == sorted(_REFERENCE_RE.findall(english))
        and uis._placeholders(candidate) == uis._placeholders(english)
        and sorted(_TAG_RE.findall(candidate)) == sorted(_TAG_RE.findall(english))
    )


def _missing(instrument_code: str, locale: str, reference: dict) -> list[tuple]:
    """Reference keys with no translation row and no pending suggestion."""
    held = set(
        db.session.execute(
            sa.select(Translations.item_kind, Translations.item_key, Translations.field)
            .where(
                Translations.instrument_code == instrument_code,
                Translations.locale_code == locale,
            )
        ).tuples()
    )
    held |= set(
        db.session.execute(
            sa.select(Suggestions.item_kind, Suggestions.item_key, Suggestions.field)
            .where(
                Suggestions.instrument_code == instrument_code,
                Suggestions.locale_code == locale,
                Suggestions.status == SUGGESTION_PENDING,
            )
        ).tuples()
    )
    return sorted(k for k, text in reference.items() if k not in held and (text or "").strip())


def _run_locale(instrument_code, locale, reference, dry_run, limit, client=None, token="") -> dict:
    result = {"created": 0, "rejected": 0, "skipped": 0, "errors": 0}
    if db.session.get(MasInstrumentLocales, (instrument_code, locale)) is None:
        result.update(errors=1, error=f"No {locale!r} translation exists for {instrument_code}.")
        return result
    todo = _missing(instrument_code, locale, reference)
    result["skipped"] = len(reference) - len(todo)
    if limit is not None:
        todo = todo[:limit]
    if dry_run:
        result["would_create"] = len(todo)
        return result
    if not todo:
        return result
    # Each request's drafts are committed before the next is sent, so a later
    # failure keeps them and a rerun drafts only what is still missing.
    now, pos = datetime.now(UTC), 0
    try:
        for translated in azure.translate_chunks([reference[k] for k in todo], locale):
            keys, pos = todo[pos:pos + len(translated)], pos + len(translated)
            for key, text in zip(keys, translated):
                if not _acceptable(text, reference[key]):
                    result["rejected"] += 1
                    continue
                kind, item_key, field = key
                inserted = db.session.execute(
                    pg_insert(Translations)
                    .values(
                        instrument_code=instrument_code, locale_code=locale,
                        item_kind=kind, item_key=item_key, field=field,
                        text=text.strip(), source=SOURCE_MACHINE,
                        updated_by=None, updated_at=now,
                    )
                    .on_conflict_do_nothing()
                )
                if inserted.rowcount:
                    result["created"] += 1
                else:
                    result["skipped"] += 1
            db.session.commit()
            ui_job._refresh(client, token, LOCK_KEY)
    except azure.MachineTranslationError as exc:
        db.session.rollback()
        log.warning("machine translation of %s failed: %s", locale, exc)
        result.update(errors=1, error=str(exc))
    return result


def run(locales=None, dry_run: bool = False, limit: int | None = None,
        instrument_code: str = BASE_INSTRUMENT_CODE) -> dict:
    """Create machine drafts; per-locale counts are under ``results``.

    Raises :class:`~app.services.machine_translation_service.NotConfigured`
    (unless ``dry_run``), :class:`AlreadyRunning`, or ``InstrumentTranslationError``
    for a locale outside the machine set.
    """
    chosen = list(locales) if locales else list(uis.MACHINE_LOCALES)
    for code in chosen:
        if code not in uis.MACHINE_LOCALES:
            raise InstrumentTranslationError(f"{code!r} is not a machine-translation locale.")
    if not dry_run and not azure.is_configured():
        raise azure.NotConfigured("Azure Translator is not configured.")
    reference = reference_items(instrument_code)
    if not locales:  # default: every machine language the instrument already has
        have = set(db.session.scalars(
            sa.select(MasInstrumentLocales.locale_code)
            .where(MasInstrumentLocales.instrument_code == instrument_code)
        ))
        chosen = [c for c in chosen if c in have]

    client = _redis()
    token = ui_job._acquire(client, LOCK_KEY)
    if token is None:
        raise AlreadyRunning("A machine-translation run is already in progress.")
    status = {
        "state": "running", "dry_run": dry_run, "instrument_code": instrument_code,
        "started_at": datetime.now(UTC).isoformat(), "results": {},
    }
    if not dry_run:
        ui_job._save(client, status, STATUS_KEY)
    try:
        for code in chosen:
            status["results"][code] = _run_locale(instrument_code, code, reference, dry_run, limit, client, token)
            if not dry_run:
                ui_job._save(client, status, STATUS_KEY)
        status["state"] = "done"
    except Exception:
        db.session.rollback()
        status["state"] = "failed"
        raise
    finally:
        status["finished_at"] = datetime.now(UTC).isoformat()
        if not dry_run:
            ui_job._save(client, status, STATUS_KEY)
        ui_job._release(client, token, LOCK_KEY)
    return status
