"""Machine-translate the missing Expo UI strings into candidates (digitva-cqw9).

Policy: docs/policy/ui-strings.md ("Machine candidates"). For each target locale
the job finds the English keys the bundled file lacks (or holds only whitespace)
and that have no override row of any source, asks Azure Translator, and inserts
``source='machine'`` rows with ``ON CONFLICT DO NOTHING``. It never updates a
row, so an edit, an accepted text or an earlier candidate is never overwritten,
and nothing it writes is served until an administrator accepts it.

One run at a time (a Redis lock); the last run's result is kept in Redis for the
admin page. Shared by the Celery task and ``flask ui-strings machine-translate``.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import db
from app.models.mas_ui_string_override import MasUiStringOverride
from app.services import machine_translation_service as azure
from app.services import ui_string_service as uis
from app.services.instrument_translation_service import (
    BASE_LOCALE,
    MAX_TRANSLATION_TEXT_CHARS,
    InvalidTranslationText,
    validate_translation_text,
)

log = logging.getLogger(__name__)

LOCK_KEY = "digitva_ui_string_machine_translate:lock"
STATUS_KEY = "digitva_ui_string_machine_translate:status"
LOCK_TTL_SECONDS = 1800
STATUS_TTL_SECONDS = 7 * 24 * 3600


class AlreadyRunning(uis.UiStringError):
    """Another machine-translation run holds the lock."""


def _redis():
    from app.tasks.sync_tasks import _lock_client

    return _lock_client()


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


def _save(client, status: dict, key: str = STATUS_KEY) -> None:
    if client is None:
        return
    try:
        client.set(key, json.dumps(status), ex=STATUS_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - status is informational
        log.warning("could not record machine-translation status", exc_info=True)


def _acquire(client, key: str = LOCK_KEY) -> str | None:
    """A lock token, or ``None`` when another run holds it."""
    import uuid

    token = uuid.uuid4().hex
    if client is None:
        return token  # ponytail: no Redis, no mutual exclusion; runs are idempotent
    return token if client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS) else None


def _release(client, token: str, key: str = LOCK_KEY) -> None:
    if client is None:
        return
    try:
        if client.get(key) in (token, token.encode()):
            client.delete(key)
    except Exception:  # noqa: BLE001 - the TTL releases it either way
        log.warning("machine-translation lock could not be released", exc_info=True)


def _refresh(client, token: str, key: str = LOCK_KEY) -> None:
    """Restart the lock's TTL; a paced run outlives the first TTL."""
    if client is None:
        return
    try:
        if client.get(key) in (token, token.encode()):
            client.expire(key, LOCK_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - the TTL is only a safety net
        log.warning("machine-translation lock could not be refreshed", exc_info=True)


def _acceptable(candidate: str, english: str) -> bool:
    candidate = (candidate or "").strip()
    if not candidate or len(candidate) > MAX_TRANSLATION_TEXT_CHARS:
        return False
    try:
        validate_translation_text(candidate, english)
    except InvalidTranslationText:
        return False
    return uis._placeholders(candidate) == uis._placeholders(english)


def _missing(locale: str, english: dict) -> list[str]:
    """Keys with no usable bundled text and no override row of any source."""
    bundled = uis._bundle(locale)
    rows = db.session.execute(
        db.select(MasUiStringOverride.string_key).where(
            MasUiStringOverride.locale_code == locale
        )
    ).scalars()
    held = set(rows)
    return [
        k for k in english
        if k not in held and not (bundled.get(k) or "").strip()
    ]


def _run_locale(locale: str, english: dict, dry_run: bool, limit: int | None,
                client=None, token: str = "") -> dict:
    result = {"created": 0, "rejected": 0, "skipped": 0, "errors": 0}
    todo = _missing(locale, english)
    result["skipped"] = len(english) - len(todo)
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
        for translated in azure.translate_chunks([english[k] for k in todo], locale):
            keys, pos = todo[pos:pos + len(translated)], pos + len(translated)
            for key, text in zip(keys, translated):
                if not _acceptable(text, english[key]):
                    result["rejected"] += 1
                    continue
                inserted = db.session.execute(
                    pg_insert(MasUiStringOverride)
                    .values(
                        locale_code=locale,
                        string_key=key,
                        text=text.strip(),
                        source=uis.SOURCE_MACHINE,
                        updated_by=None,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["locale_code", "string_key"])
                )
                if inserted.rowcount:
                    result["created"] += 1
                else:
                    result["skipped"] += 1
            db.session.commit()
            _refresh(client, token)
    except azure.MachineTranslationError as exc:
        db.session.rollback()
        log.warning("machine translation of %s failed: %s", locale, exc)
        result["errors"] = 1
        result["error"] = str(exc)
    return result


def run(locales=None, dry_run: bool = False, limit: int | None = None) -> dict:
    """Create machine candidates; returns ``{locale: counts}`` under ``results``.

    Raises :class:`~app.services.machine_translation_service.NotConfigured`
    (unless ``dry_run``), :class:`AlreadyRunning`, or ``UiStringError`` for a
    locale outside the allow-list.
    """
    chosen = list(locales) if locales else list(uis.MACHINE_LOCALES)
    for code in chosen:
        if code not in uis.MACHINE_LOCALES:
            raise uis.UiStringError(f"{code!r} is not a machine-translation locale.")
    if not dry_run and not azure.is_configured():
        raise azure.NotConfigured("Azure Translator is not configured.")
    english = uis._bundle(BASE_LOCALE)

    client = _redis()
    token = _acquire(client)
    if token is None:
        raise AlreadyRunning("A machine-translation run is already in progress.")
    status = {
        "state": "running",
        "dry_run": dry_run,
        "started_at": datetime.now(UTC).isoformat(),
        "results": {},
    }
    if not dry_run:
        _save(client, status)
    try:
        for code in chosen:
            status["results"][code] = _run_locale(code, english, dry_run, limit, client, token)
            if not dry_run:
                _save(client, status)
        status["state"] = "done"
    except Exception:
        db.session.rollback()
        status["state"] = "failed"
        raise
    finally:
        status["finished_at"] = datetime.now(UTC).isoformat()
        if not dry_run:
            _save(client, status)
        _release(client, token)
    return status
