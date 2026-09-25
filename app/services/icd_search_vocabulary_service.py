"""COD search vocabulary service (digitva-zpe.1).

Central, admin-managed table of clinician shorthand and diagnosis synonyms
(`MI`, `CVA`, `CCF`, `Kochs`) wired into the coding-search endpoints.
Policy: docs/policy/icd-coding-search-vocabulary.md.

Matching is exact on ``term_normalized`` only — no prefix or fuzzy matching,
so `MI` cannot hijack `miliary`. A vocabulary hit never bypasses coding
policy: the search endpoints resolve targets through the same filters they
already apply, and a filtered-out target contributes nothing.
"""

from __future__ import annotations

import logging
import re
import uuid

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms, MasIcd1020192, MasIcdSearchTerms

log = logging.getLogger(__name__)

CLASSIFICATION_ICD10 = "icd10"
CLASSIFICATION_ICD11 = "icd11"
CLASSIFICATIONS = (CLASSIFICATION_ICD10, CLASSIFICATION_ICD11)
SOURCES = ("seed_used_cod", "who_inclusion", "admin", "telemetry")
DEFAULT_SOURCE = "admin"

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_TERM_LENGTH = 500
MAX_NOTE_LENGTH = 2000

# Everything that is not a lowercase alphanumeric or a hyphen is a word
# boundary; hyphens survive wherever they sit ("adult-onset", "I50.-" ->
# "i50 -"). Must reproduce the seed CSV's `term_normalized` column.
_NON_TERM_CHARS = re.compile(r"[^a-z0-9-]+")

_LIKE_ESCAPE = "\\"


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so a search for ``%`` or ``_`` matches literally."""
    return (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )

# ponytail: one table per process, rebuilt on a key change; a multi-worker
# server builds it once per worker. Move to the shared cache if that hurts.
_cache: dict = {"key": None, "links": ()}


def normalize_term(text: str) -> str:
    """Lowercase, turn punctuation into spaces (hyphens survive), collapse
    whitespace. ``Koch's disease`` -> ``koch s disease``."""
    return " ".join(_NON_TERM_CHARS.sub(" ", (text or "").lower()).split())


def _cache_key() -> tuple[int, object]:
    """``(row count, latest updated_at)``: changes whenever a row is added,
    removed or edited. One aggregate query."""
    return db.session.execute(
        sa.select(
            sa.func.count(MasIcdSearchTerms.term_id),
            sa.func.max(MasIcdSearchTerms.updated_at),
        )
    ).one()


def clear_cache() -> None:
    """Drop the cached vocabulary; called after every admin write so the next
    search in this worker sees the change."""
    _cache["key"] = None
    _cache["links"] = ()


def _load_links() -> tuple[dict, ...]:
    rows = db.session.scalars(
        sa.select(MasIcdSearchTerms)
        .where(MasIcdSearchTerms.is_active.is_(True))
        .order_by(
            MasIcdSearchTerms.term_normalized,
            MasIcdSearchTerms.icd_classification,
            MasIcdSearchTerms.icd_code,
        )
    ).all()
    return tuple(
        {
            "term_id": row.term_id,
            "term": row.term,
            "term_normalized": row.term_normalized,
            "icd_classification": row.icd_classification,
            "icd_code": row.icd_code,
            "source": row.source,
            "note": row.note,
        }
        for row in rows
    )


def vocabulary_matches(query: str, classification: str | None = None) -> list[dict]:
    """Active links whose ``term_normalized`` equals the normalized ``query``.

    ``classification`` optionally narrows to one catalogue. Returns links in
    table order; several rows per term is the mechanism for multi-code
    targets (`TB` -> A15 and A16).
    """
    normalized_query = normalize_term(query)
    if not normalized_query:
        return []
    key = _cache_key()
    if _cache["key"] != key:
        _cache["key"] = key
        _cache["links"] = _load_links()
    return [
        link
        for link in _cache["links"]
        if link["term_normalized"] == normalized_query
        and (classification is None or link["icd_classification"] == classification)
    ]


def merge_vocabulary_results(
    lexical_results: list[dict], vocabulary_results: list[dict]
) -> list[dict]:
    """Rank vocabulary matches first, deduped against lexical hits.

    A target the lexical search already found moves to the top carrying the
    ``vocabulary`` flag; vocabulary-only targets are prepended. Lexical order
    is otherwise untouched. The caller applies its own result cap.
    """
    lexical_index_by_code: dict[str | None, int] = {}
    for index, result in enumerate(lexical_results):
        lexical_index_by_code.setdefault(result.get("icd_code"), index)

    promoted_codes: set[str | None] = set()
    merged: list[dict] = []
    for hit in vocabulary_results:
        code = hit.get("icd_code")
        if code in promoted_codes:
            continue
        promoted_codes.add(code)
        lexical_index = lexical_index_by_code.get(code)
        if lexical_index is None:
            merged.append(hit)
            continue
        promoted = dict(lexical_results[lexical_index])
        promoted["vocabulary"] = True
        merged.append(promoted)
    merged.extend(
        result for result in lexical_results if result.get("icd_code") not in promoted_codes
    )
    return merged


def _validated_classification(value) -> str:
    classification = (value or "").strip()
    if classification not in CLASSIFICATIONS:
        raise ValueError(
            f"icd_classification must be one of {', '.join(CLASSIFICATIONS)}."
        )
    return classification


def _validated_source(value) -> str:
    source = (value or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}.")
    return source


def _validated_term(value) -> str:
    term = (value or "").strip()
    if not term:
        raise ValueError("term is required.")
    if len(term) > MAX_TERM_LENGTH:
        raise ValueError(f"term must be at most {MAX_TERM_LENGTH} characters.")
    return term


def _validated_code(value) -> str:
    code = (value or "").strip().upper()
    if not code:
        raise ValueError("icd_code is required.")
    if len(code) > 16:
        raise ValueError("icd_code must be at most 16 characters.")
    return code


def _validated_note(value) -> str | None:
    note = (value or "").strip() or None
    if note is not None and len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"note must be at most {MAX_NOTE_LENGTH} characters.")
    return note


def serialize_term(row: MasIcdSearchTerms) -> dict:
    return {
        "term_id": str(row.term_id),
        "term": row.term,
        "term_normalized": row.term_normalized,
        "icd_classification": row.icd_classification,
        "icd_code": row.icd_code,
        "source": row.source,
        "note": row.note,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def vocabulary_stats() -> dict:
    """Header counts for the admin panel: total, active and inactive links."""
    return {
        "total_terms": db.session.scalar(
            sa.select(sa.func.count()).select_from(MasIcdSearchTerms)
        )
        or 0,
        "active_terms": db.session.scalar(
            sa.select(sa.func.count())
            .select_from(MasIcdSearchTerms)
            .where(MasIcdSearchTerms.is_active.is_(True))
        )
        or 0,
    }


def get_term(term_id: str) -> MasIcdSearchTerms:
    """The vocabulary row, or ``LookupError`` for an unknown id."""
    try:
        key = uuid.UUID(str(term_id))
    except ValueError as exc:
        raise LookupError(f"Vocabulary term not found: {term_id}") from exc
    row = db.session.get(MasIcdSearchTerms, key)
    if row is None:
        raise LookupError(f"Vocabulary term not found: {term_id}")
    return row


def list_terms(
    *,
    search: str = "",
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> dict:
    """Paged admin listing over active and inactive rows, with optional
    substring search across term, code and note."""
    per_page = min(max(int(per_page or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
    page = max(int(page or 1), 1)

    query = sa.select(MasIcdSearchTerms)
    count_query = sa.select(sa.func.count()).select_from(MasIcdSearchTerms)
    text = (search or "").strip()
    if text:
        like = f"%{_escape_like(text.lower())}%"
        clause = sa.or_(
            sa.func.lower(MasIcdSearchTerms.term).like(like, escape=_LIKE_ESCAPE),
            sa.func.lower(MasIcdSearchTerms.term_normalized).like(like, escape=_LIKE_ESCAPE),
            sa.func.lower(MasIcdSearchTerms.icd_code).like(like, escape=_LIKE_ESCAPE),
            sa.func.lower(sa.func.coalesce(MasIcdSearchTerms.note, "")).like(
                like, escape=_LIKE_ESCAPE
            ),
        )
        query = query.where(clause)
        count_query = count_query.where(clause)

    total = db.session.scalar(count_query) or 0
    rows = db.session.scalars(
        query.order_by(
            MasIcdSearchTerms.term_normalized,
            MasIcdSearchTerms.icd_classification,
            MasIcdSearchTerms.icd_code,
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return {
        "rows": [serialize_term(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def create_term(
    *,
    term: str,
    icd_classification: str,
    icd_code: str,
    note: str | None = None,
    source: str = DEFAULT_SOURCE,
) -> MasIcdSearchTerms:
    """Insert one term-code link. The normalized lookup key is derived from
    ``term``, never taken from input."""
    classification = _validated_classification(icd_classification)
    validated_term = _validated_term(term)
    validated_code = _validated_code(icd_code)
    row = MasIcdSearchTerms(
        term=validated_term,
        term_normalized=normalize_term(validated_term),
        icd_classification=classification,
        icd_code=validated_code,
        source=_validated_source(source),
        note=_validated_note(note),
        is_active=True,
    )
    db.session.add(row)
    db.session.commit()
    clear_cache()
    log.info(
        "Vocabulary term created %s -> %s %s",
        row.term_normalized,
        classification,
        validated_code,
    )
    return row


def update_term(
    term_id: str,
    *,
    term: str,
    icd_classification: str,
    icd_code: str,
    note: str | None = None,
) -> MasIcdSearchTerms:
    """Edit one link's display term, target or note. Deactivation state is
    owned by :func:`set_active` and left untouched here."""
    row = get_term(term_id)
    classification = _validated_classification(icd_classification)
    validated_term = _validated_term(term)
    row.term = validated_term
    row.term_normalized = normalize_term(validated_term)
    row.icd_classification = classification
    row.icd_code = _validated_code(icd_code)
    row.note = _validated_note(note)
    db.session.commit()
    clear_cache()
    log.info(
        "Vocabulary term updated %s -> %s %s",
        row.term_normalized,
        classification,
        row.icd_code,
    )
    return row


def set_active(term_id: str, is_active: bool) -> MasIcdSearchTerms:
    """Activate or deactivate one link; deactivation keeps audit history."""
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be a boolean.")
    row = get_term(term_id)
    row.is_active = is_active
    db.session.commit()
    clear_cache()
    log.info(
        "Vocabulary term %s %s", row.term_normalized, "activated" if is_active else "deactivated"
    )
    return row


def code_in_catalogue(icd_classification: str, icd_code: str) -> bool:
    """Whether the target code resolves in its catalogue.

    Admin UI warns softly when it does not, but saving is still allowed —
    a code ahead of the next catalogue refresh must not be rejected.
    """
    classification = _validated_classification(icd_classification)
    code = _validated_code(icd_code)
    if classification == CLASSIFICATION_ICD10:
        return (
            db.session.scalar(
                sa.select(sa.literal(True)).where(
                    sa.exists(
                        sa.select(MasIcd1020192.code).where(
                            MasIcd1020192.code == code,
                            MasIcd1020192.is_active.is_(True),
                        )
                    )
                )
            )
            is True
        )
    # Lazy import: icd11_mms_service imports this module to wire vocabulary
    # expansion into its search, so the module-level edge is one-way.
    from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE

    return (
        db.session.scalar(
            sa.select(sa.literal(True)).where(
                sa.exists(
                    sa.select(MasIcd11Mms.linearization_uri).where(
                        MasIcd11Mms.release == DEFAULT_ICD11_RELEASE,
                        MasIcd11Mms.code == code,
                        MasIcd11Mms.is_active.is_(True),
                    )
                )
            )
        )
        is True
    )
