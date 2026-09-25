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
from localspelling import convert_spelling

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
    whitespace, then fold to the US spelling: UK and US variants of a term
    share one lookup key (``septicaemia`` and ``septicemia`` normalize
    alike). Idempotent — an already-US term is returned unchanged.
    ``Koch's disease`` -> ``koch s disease``.

    Stored ``term_normalized`` values are never rewritten (no migration);
    ``_load_links`` recomputes this key over the stored value at cache-build
    time, so rows keyed before the fold still collide with their US spelling.
    """
    normalized = " ".join(_NON_TERM_CHARS.sub(" ", (text or "").lower()).split())
    if not normalized:
        return ""
    return _phrase_form(normalized, "us")


# localspelling 0.94 (MIT, Fast Data Science) carries the general UK/US word
# map but misses a measured set of medical words (34/54 of the owner's
# taxonomy). These run token-wise before its conversion, in the direction
# being produced; all are upstreamable to the library. "angio-oedema" rides
# the hyphen-insensitive arm as well, so "angio oedema" and "angioedema"
# queries reach the same titles.
_MEDICAL_SPELLING_SUPPLEMENT = {
    "ischaemic": "ischemic",
    "caesarean": "cesarean",
    "septicaemia": "septicemia",
    "septicaemic": "septicemic",
    "uraemia": "uremia",
    "uraemic": "uremic",
    "anaemias": "anemias",
    "leukaemic": "leukemic",
    "diarrhoeal": "diarrheal",
    "dyspnoea": "dyspnea",
    "oesophageal": "esophageal",
    "menorrhoea": "menorrhea",
    "haemoptysis": "hemoptysis",
    "haematemesis": "hematemesis",
    "angio-oedema": "angioedema",
    "titre": "titer",
    "catalogue": "catalog",
    "catalyse": "catalyze",
    "disc": "disk",
    "leucocyte": "leukocyte",
    "leucopenia": "leukopenia",
    "leucocytosis": "leukocytosis",
}
_SUPPLEMENT_TO_US = _MEDICAL_SPELLING_SUPPLEMENT
_SUPPLEMENT_TO_UK = {us: uk for uk, us in _MEDICAL_SPELLING_SUPPLEMENT.items()}


def _phrase_form(normalized: str, direction: str) -> str:
    """The phrase rewritten in one spelling convention (``"us"``/``"gb"``).

    The supplement word is substituted first in the target direction — it is
    exactly the set localspelling's own conversion leaves unchanged — then
    the library converts the rest word-level.
    """
    supplement = _SUPPLEMENT_TO_US if direction == "us" else _SUPPLEMENT_TO_UK
    preconverted = " ".join(
        supplement.get(token, token) for token in normalized.split(" ")
    )
    return convert_spelling(preconverted, direction)


def spelling_variants(text: str) -> list[str]:
    """``[normalized, us form, gb form]``, deduped and order-stable.

    Normalized = lowercase + whitespace collapse (every caller works on
    normalized text, so case shape is not preserved). The original always
    comes first and is never removed, so a conversion can only ADD matches,
    never take the original's away. One helper for the whole fold feature:
    coding-search queries, ``normalize_term``, ``_result_tier`` and the admin
    panel search all go through this.
    """
    normalized = " ".join((text or "").lower().split())
    if not normalized:
        return []
    variants = [normalized]
    for form in (_phrase_form(normalized, "us"), _phrase_form(normalized, "gb")):
        if form not in variants:
            variants.append(form)
    return variants


def spelling_like_clauses(lower_columns, variants, *, escape=None):
    """LIKE clauses for the coding searches over spelling and hyphen variants.

    Returns ``(where, rank)``. Every spelling variant matches two ways —
    plain ``ILIKE %v%`` and, with hyphens translated out of both sides, the
    hyphen-stripped form — so hyphen placement is irrelevant on both sides
    (query "cat scratch" finds "Cat-scratch disease" and vice versa).
    ``rank`` keeps the four bands (exact code, code prefix, title prefix,
    title substring) with every variant scored at the same band as the
    original, folded and hyphen-stripped forms included, so the tier the
    picker groups by stays consistent with what matched. ``lower_columns[0]``
    is the code column and ``lower_columns[1]`` the title column; further
    columns only feed the WHERE. ``escape`` is forwarded to ``.like`` for
    callers whose queries escape LIKE wildcards.
    """
    def like(column, pattern):
        if escape is None:
            return column.like(pattern)
        return column.like(pattern, escape=escape)

    def strip_separators(expression):
        # Hyphens AND spaces leave the haystack: "cat scratch" must reach
        # "Cat-scratch disease" whichever side carries the hyphen.
        return sa.func.translate(expression, "- ", "")

    def compact(variant):
        return variant.replace("-", "").replace(" ", "")

    def escaped(text: str) -> str:
        # With an escape marker configured, the variant's own % and _ are
        # literals ("1_00" must not wildcard-match "1A00"); the wrapping %
        # wildcards below stay intentional.
        if escape is None:
            return text
        return (
            text.replace(escape, escape * 2)
            .replace("%", f"{escape}%")
            .replace("_", f"{escape}_")
        )

    def match_arm(column, variant):
        # Both arms always fire: the query may be separator-free while the
        # title still carries hyphens ("catscratch" vs "Cat-scratch"). When
        # the variant itself has no separators the two arms coincide for
        # separator-free titles and the planner folds the extra work away.
        return sa.or_(
            like(column, f"%{escaped(variant)}%"),
            like(strip_separators(column), f"%{escaped(compact(variant))}%"),
        )

    lower_code, lower_title = lower_columns[0], lower_columns[1]
    where = sa.or_(
        *(
            sa.or_(*(match_arm(column, variant) for column in lower_columns))
            for variant in variants
        )
    )

    def exact_arm(column, variant):
        stripped_variant = compact(variant)
        return sa.or_(
            column == variant,
            strip_separators(column) == stripped_variant,
        )

    def prefix_arm(column, variant):
        return sa.or_(
            like(column, f"{escaped(variant)}%"),
            like(strip_separators(column), f"{escaped(compact(variant))}%"),
        )

    rank = sa.case(
        (sa.or_(*[exact_arm(lower_code, variant) for variant in variants]), 0),
        (sa.or_(*[prefix_arm(lower_code, variant) for variant in variants]), 1),
        (sa.or_(*[prefix_arm(lower_title, variant) for variant in variants]), 2),
        (sa.or_(*[match_arm(lower_title, variant) for variant in variants]), 3),
        else_=4,
    )
    return where, rank


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
            # Recomputed through the current normalize_term (which folds), so
            # a row keyed before the fold — seed rows like septicaemia —
            # collides with its US spelling. Stored values stay untouched.
            "term_normalized": normalize_term(row.term_normalized),
            # Separator-stripped: "self harm" must reach a stored "self-harm"
            # through the query's lookup keys without a data migration.
            "term_normalized_compact": _compact_key(
                normalize_term(row.term_normalized)
            ),
            "icd_classification": row.icd_classification,
            "icd_code": row.icd_code,
            "source": row.source,
            "note": row.note,
        }
        for row in rows
    )


def _compact_key(value: str) -> str:
    """The value with separators (hyphens and spaces) removed: the shared
    shape of "self harm", "self-harm" and "selfharm"."""
    return value.replace("-", "").replace(" ", "")


def _query_lookup_keys(query: str) -> set[str]:
    """Every exact-key form a query may match a stored ``term_normalized``:
    the spelling variants (original/US/GB), each raw and separator-stripped,
    so ``self harm`` reaches ``self-harm`` and ``septicemia`` reaches a
    stored ``septicaemia`` without rewriting stored rows."""
    keys: set[str] = set()
    for variant in spelling_variants(query):
        keys.add(variant)
        keys.add(_compact_key(variant))
    return keys


def vocabulary_matches(query: str, classification: str | None = None) -> list[dict]:
    """Active links whose normalized key equals any spelling/hyphen variant
    of the ``query``.

    ``classification`` optionally narrows to one catalogue. Returns links in
    table order; several rows per term is the mechanism for multi-code
    targets (`TB` -> A15 and A16).
    """
    lookup_keys = _query_lookup_keys(query)
    if not any(key for key in lookup_keys):
        return []
    key = _cache_key()
    if _cache["key"] != key:
        _cache["key"] = key
        _cache["links"] = _load_links()
    return [
        link
        for link in _cache["links"]
        if (
            link["term_normalized"] in lookup_keys
            or link["term_normalized_compact"] in lookup_keys
        )
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
        # A promoted row is now a vocabulary hit: the picker groups it
        # with the focused matches regardless of how the lexical pass
        # tiered it (spec: vocabulary hits are always focused).
        promoted["tier"] = "focused"
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
        # Spelling and hyphen variants OR-ed in: a search for septicaemia
        # also finds septicemia rows and vice versa; "self harm" finds
        # "self-harm" — same helper behaviour as the coding searches.
        def text_arm(column, variant):
            compact = _compact_key(variant)
            return sa.or_(
                sa.func.lower(column).like(
                    f"%{_escape_like(variant)}%", escape=_LIKE_ESCAPE
                ),
                sa.func.lower(sa.func.translate(column, "- ", "")).like(
                    f"%{_escape_like(compact)}%", escape=_LIKE_ESCAPE
                ),
            )

        clause = sa.or_(
            *(
                sa.or_(
                    text_arm(MasIcdSearchTerms.term, variant),
                    text_arm(MasIcdSearchTerms.term_normalized, variant),
                    text_arm(MasIcdSearchTerms.icd_code, variant),
                    text_arm(sa.func.coalesce(MasIcdSearchTerms.note, ""), variant),
                )
                for variant in spelling_variants(text)
            )
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
