"""Phase-0 coding-search telemetry service (digitva-zpe.3).

Evidence before build: record what clinicians actually type into the COD
coding search (docs/policy/coding-search-telemetry.md). The one hard rule:
telemetry must never break or slow the search path — the routes call it only
after the response payload is built, and every entry point the request path
touches swallows its own failures behind a warning log. Deliberately
synchronous and cheap: one insert, no celery task in the request path.

No PII: query text, coarse role, counts. No user id, no va_sid, no IP.
"""

import csv
import io
import logging
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import CodSearchTelemetry

log = logging.getLogger(__name__)

SURFACE_ICD10 = "icd10_coding"
SURFACE_ICD11 = "icd11_coding"
SURFACES = (SURFACE_ICD10, SURFACE_ICD11)
MAX_QUERY_LENGTH = 128
DEFAULT_RETENTION_DAYS = 90
_CODE_MAX_LENGTH = 16

CSV_HEADERS = (
    "search_id",
    "surface",
    "query_text",
    "result_count",
    "zero_results",
    "vocabulary_hit",
    "latency_ms",
    "role",
    "chosen_code",
    "chosen_rank",
    "chosen_at",
    "created_at",
)


def normalize_query_text(raw_query: str | None) -> str:
    """Whitespace-collapse the typed query and hard-truncate at 128 chars.

    The typed casing is kept: case is part of the evidence (SHORTHAND vs
    prose), and matching lowercases elsewhere.
    """
    collapsed = " ".join((raw_query or "").split())
    return collapsed[:MAX_QUERY_LENGTH]


def resolve_search_id(raw_value: object) -> uuid.UUID:
    """Parse the client's search_id; anything else becomes a fresh UUID.

    The query param is optional and client-controlled: an absent or invalid
    value must never fail the search, so it degrades to a server-generated id
    which the ``X-Search-Id`` response header echoes back.
    """
    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid4()


def role_label(user) -> str | None:
    """The coarse telemetry role among the four the coding screens gate on.

    The role_required decorator checks these same predicates, so this names
    the role the search was authorized through (coder wins if a user holds
    several).
    """
    for role in ("coder", "coding_tester", "reviewer", "admin"):
        check = getattr(user, f"is_{role}", None)
        if check is not None and check():
            return role
    return None


def record_query(  # noqa: PLR0913 - one row's fields, all meaningful
    *,
    search_id: uuid.UUID,
    surface: str,
    query_text: str,
    result_count: int = 0,
    zero_results: bool = False,
    vocabulary_hit: bool = False,
    latency_ms: int | None = None,
    role: str | None = None,
) -> None:
    """Insert one search row. Called after the response payload is built.

    Never raises: a telemetry failure is logged and dropped, because no
    search may be refused, deferred or altered by the log keeping itself
    (docs/policy/coding-search-telemetry.md).
    """
    try:
        if surface not in SURFACES:
            raise ValueError(f"unknown telemetry surface: {surface!r}")
        db.session.add(
            CodSearchTelemetry(
                search_id=search_id,
                surface=surface,
                query_text=normalize_query_text(query_text),
                result_count=int(result_count or 0),
                zero_results=bool(zero_results),
                vocabulary_hit=bool(vocabulary_hit),
                latency_ms=latency_ms,
                role=role,
            )
        )
        db.session.commit()
    except Exception:  # noqa: BLE001 - telemetry must never break the search path
        db.session.rollback()
        log.warning("coding search telemetry: could not record query", exc_info=True)


def record_search_request(
    *,
    search_id: uuid.UUID,
    surface: str,
    query_text: str,
    payload: list,
    latency_ms: int | None,
    user,
) -> None:
    """Derive the row's flags from a built search payload and record it.

    The route-side seam: if anything here goes wrong the search response is
    already built, so the failure is swallowed with a warning instead of
    turning a finished search into a 500.
    """
    try:
        record_query(
            search_id=search_id,
            surface=surface,
            query_text=query_text,
            result_count=len(payload),
            zero_results=not payload,
            vocabulary_hit=any(bool(item.get("vocabulary")) for item in payload),
            latency_ms=latency_ms,
            role=role_label(user),
        )
    except Exception:  # noqa: BLE001 - same rule, one level up
        log.warning("coding search telemetry: recording the search failed", exc_info=True)


def record_choice(
    *,
    search_id: object,
    chosen_code: str | None,
    chosen_rank: object = None,
    role: str | None = None,
) -> None:
    """Attach the chosen code to the search the browser forwards on save.

    The client only ever forwards a code it picked from that search's result
    list, so the code is trusted and the rank recorded with it. An unknown
    search_id (never searched, or already pruned) is a silent no-op; a
    malformed field is dropped, not fatal to the save. Never raises.
    """
    try:
        key = uuid.UUID(str(search_id))
    except (TypeError, ValueError, AttributeError):
        return
    code = (chosen_code or "").strip()
    if not code:
        return
    try:
        rank = None if chosen_rank in (None, "") else int(chosen_rank)
    except (TypeError, ValueError):
        rank = None
    try:
        rows = db.session.scalars(
            sa.select(CodSearchTelemetry).where(CodSearchTelemetry.search_id == key)
        ).all()
        if not rows:
            return
        for row in rows:
            row.chosen_code = code[:_CODE_MAX_LENGTH]
            row.chosen_rank = rank
            row.chosen_at = datetime.now(UTC)
            if role:
                row.role = role
        db.session.commit()
    except Exception:  # noqa: BLE001 - a save must not fail on its telemetry
        db.session.rollback()
        log.warning("coding search telemetry: could not record choice", exc_info=True)


def prune_expired(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete rows older than the retention window. Returns the count."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = db.session.execute(
        sa.delete(CodSearchTelemetry).where(CodSearchTelemetry.created_at < cutoff)
    )
    db.session.commit()
    return result.rowcount or 0


def export_csv_rows() -> list[dict]:
    """All rows, newest first, as plain values for the admin CSV export."""
    rows = db.session.scalars(
        sa.select(CodSearchTelemetry).order_by(
            CodSearchTelemetry.created_at.desc(),
            CodSearchTelemetry.id.desc(),
        )
    ).all()
    return [
        {
            "search_id": str(row.search_id),
            "surface": row.surface,
            "query_text": row.query_text,
            "result_count": row.result_count,
            "zero_results": "true" if row.zero_results else "false",
            "vocabulary_hit": "true" if row.vocabulary_hit else "false",
            "latency_ms": row.latency_ms,
            "role": row.role or "",
            "chosen_code": row.chosen_code or "",
            "chosen_rank": row.chosen_rank,
            "chosen_at": row.chosen_at.isoformat() if row.chosen_at else "",
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]


def iter_csv_lines():
    """Yield the export line by line, newest first, formula-neutralised like
    the vocabulary export (query text is free-typed clinician input)."""
    from app.services.va_code_mapping_public_service import csv_cell

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    yield buffer.getvalue()
    for values in export_csv_rows():
        buffer.seek(0)
        buffer.truncate()
        writer.writerow([csv_cell(str(values[header])) for header in CSV_HEADERS])
        yield buffer.getvalue()
