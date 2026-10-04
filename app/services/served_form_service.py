"""The composed WHO VA 2022 form definition, served per project.

Policy: docs/policy/field-data-collection.md ("Form version", "Form definition
from the server"). ``app/data/who-va-2022.composed.json`` is built by
``tooling/who-va-2022/build-composed-instrument.mjs``: the complete definition
(every DigitVA extension on) with each section/question a conditional
extension contributes tagged ``extensions: [..]``. A project's definition is
that file minus the items whose tags are all disabled for the project -- no
Node process in the request path, and the build proves the result equals the
package's own ``createWhoVa2022Instrument`` for all 2^5 extension subsets.

Speed: the file is parsed once per process; each distinct set of enabled
conditional extensions (at most 32) is filtered and serialized once, and the
request path is a dict lookup plus the cached bytes. The ETag is the bytes'
SHA-256, so a client revalidates for free.

``version`` identifies the composed (all-extensions) definition, not a
project's slice of it: every project's body carries the same ``version`` and a
different ``sha256``. The slice is identified by (``version``, ``extensions``),
the body's top-level ``extensions`` (the sorted conditional extensions it
contains); a client keeps that pair with its sha256 and can fetch the exact
slice again later with :func:`historical_definition`, from the full definition
recorded for that version, whatever the project enables today.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import db
from app.models.mas_instrument_versions import MasInstrumentVersions
from app.services.web_form_instruments import FALLBACK_INSTRUMENT_CODE

log = logging.getLogger(__name__)

#: The one instrument a composed definition exists for.
INSTRUMENT_CODE = FALLBACK_INSTRUMENT_CODE
COMPOSED_PATH = Path(__file__).resolve().parents[1] / "data" / "who-va-2022.composed.json"

#: Versions listed by :func:`list_versions`, newest first. History grows by one
#: row per form change; a client wants the recent ones.
VERSIONS_LIMIT = 200


class ServedFormUnavailable(RuntimeError):
    """The composed definition file is missing or unreadable."""


class UnknownVersion(LookupError):
    """No such version is recorded for the instrument."""


class InvalidExtensions(ValueError):
    """Extensions outside the version's tag vocabulary."""


@dataclass(frozen=True)
class ServedDefinition:
    body: bytes
    sha256: str
    version: str
    # The same body gzipped once (about 1 MB -> a fraction): field phones are
    # on slow links, and the proxy's compression is not guaranteed.
    gzip_body: bytes


@lru_cache(maxsize=1)
def composed_definition() -> dict:
    """The full tagged definition, loaded once per process."""
    try:
        return json.loads(COMPOSED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServedFormUnavailable(
            f"{COMPOSED_PATH} could not be read: {exc}; run "
            "`cd tooling/who-va-2022 && npm run build:composed-instrument`."
        ) from exc


def composed_version() -> str:
    return composed_definition()["version"]


def _vocabulary(definition: dict) -> frozenset[str]:
    return frozenset(
        tag for kind in ("sections", "questions") for item in definition[kind] for tag in item.get("extensions", ())
    )


@lru_cache(maxsize=1)
def _tag_vocabulary() -> frozenset[str]:
    return _vocabulary(composed_definition())


def filter_definition(composed: dict, enabled: Iterable[str]) -> dict:
    """*composed* without the items only disabled extensions contribute.

    An item stays when it carries no tag or any of its tags is enabled; the
    ``extensions`` tags are dropped from what is returned (a client has no use
    for them). Pure: used by the cache below and by the tests.
    """
    on = set(enabled)

    def keep(item: dict) -> bool:
        tags = item.get("extensions")
        return not tags or any(tag in on for tag in tags)

    def bare(item: dict) -> dict:
        return {k: v for k, v in item.items() if k != "extensions"} if "extensions" in item else item

    return {
        **composed,
        "sections": [bare(i) for i in composed["sections"] if keep(i)],
        "questions": [bare(i) for i in composed["questions"] if keep(i)],
    }


@lru_cache(maxsize=4)
def _stored_definition(version: str) -> tuple[dict, frozenset[str]]:
    """The full tagged definition recorded for an older *version* and its tag
    vocabulary, read from the database once per process. Rows are insert-only,
    so the copy never goes stale; a miss raises (and so is never cached: the
    version may be recorded a moment later)."""
    try:
        definition = db.session.scalar(
            sa.select(MasInstrumentVersions.definition).where(
                MasInstrumentVersions.instrument_code == INSTRUMENT_CODE, MasInstrumentVersions.version == version
            )
        )
    except sa.exc.SQLAlchemyError as exc:
        db.session.rollback()
        raise ServedFormUnavailable(f"recorded versions could not be read: {exc}") from exc
    if definition is None:
        raise UnknownVersion(version)
    return definition, _vocabulary(definition)


def _served(full: dict, enabled: frozenset[str]) -> ServedDefinition:
    definition = {**filter_definition(full, enabled), "extensions": sorted(enabled)}
    # Canonical bytes (sorted keys): an older version is re-served from its
    # JSONB copy, which does not keep key order, and must hash exactly as it
    # did when first served from the file.
    body = json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return ServedDefinition(
        body=body, sha256=hashlib.sha256(body).hexdigest(), version=definition["version"],
        gzip_body=gzip.compress(body, compresslevel=9, mtime=0),
    )


@lru_cache(maxsize=32)  # at most 2^5 conditional-extension sets
def _serve_current(enabled: frozenset[str]) -> ServedDefinition:
    return _served(composed_definition(), enabled)


@lru_cache(maxsize=8)  # separate and small: recovery fetches cannot evict the hot entries
def _serve_historical(version: str, enabled: frozenset[str]) -> ServedDefinition:
    return _served(_stored_definition(version)[0], enabled)


def served_definition(enabled_extensions: Iterable[str]) -> ServedDefinition:
    """Bytes, SHA-256 and version of a project's definition, built once per
    distinct set of enabled conditional extensions."""
    return _serve_current(frozenset(enabled_extensions) & _tag_vocabulary())


def historical_definition(version: str, extensions: Iterable[str]) -> ServedDefinition:
    """The slice (*version*, *extensions*) exactly as it was served, for a
    client that lost its copy. Raises :class:`UnknownVersion` for a version not
    recorded and :class:`InvalidExtensions` for extensions the version does not
    contain. The current version is served from the file (the same cache entry
    as :func:`served_definition`), older ones from their recorded definition."""
    chosen = frozenset(extensions)
    vocabulary = _tag_vocabulary() if version == composed_version() else _stored_definition(version)[1]
    if not chosen <= vocabulary:
        raise InvalidExtensions(", ".join(sorted(chosen - vocabulary)))
    if version == composed_version():
        return _serve_current(chosen)
    return _serve_historical(version, chosen)


# (instrument_code, version) pairs this process has already written; the table
# is touched once per process per version, never per request.
_recorded: set[tuple[str, str]] = set()
# After a failed write (e.g. the table's migration not run yet), wait before
# retrying, so a broken table costs one logged attempt a minute, not one per
# request. ponytail: per-process monotonic backoff, fixed 60 s.
_RECORD_RETRY_SECONDS = 60.0
_retry_at = 0.0


def record_served_version() -> None:
    """Record the current composed version (and its full definition) the first
    time this server serves it. Idempotent across processes
    (``ON CONFLICT DO NOTHING``); a failure is logged, not raised -- serving the
    form must not depend on its bookkeeping, and the next request retries."""
    global _retry_at
    key = (INSTRUMENT_CODE, composed_version())
    if key in _recorded or time.monotonic() < _retry_at:
        return
    try:
        with db.session.begin_nested():
            db.session.execute(
                pg_insert(MasInstrumentVersions)
                .values(instrument_code=key[0], version=key[1], definition=composed_definition())
                .on_conflict_do_nothing(constraint="uq_mas_instrument_versions_code_version")
            )
        db.session.commit()
    except Exception:
        log.exception("served_form: could not record instrument version %s", key[1])
        _retry_at = time.monotonic() + _RECORD_RETRY_SECONDS
        return
    _recorded.add(key)


def list_versions() -> list[dict]:
    """Recorded versions of the instrument, newest first (at most
    ``VERSIONS_LIMIT``): ``[{"version", "activated_at"}]``."""
    rows = db.session.execute(
        sa.select(MasInstrumentVersions.version, MasInstrumentVersions.activated_at)
        .where(MasInstrumentVersions.instrument_code == INSTRUMENT_CODE)
        .order_by(MasInstrumentVersions.activated_at.desc(), MasInstrumentVersions.id.desc())
        .limit(VERSIONS_LIMIT)
    ).all()
    return [{"version": version, "activated_at": activated_at.isoformat()} for version, activated_at in rows]
