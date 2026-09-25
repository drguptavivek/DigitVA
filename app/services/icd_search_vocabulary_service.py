"""COD search vocabulary service (digitva-zpe.1).

Central, admin-managed table of clinician shorthand and diagnosis synonyms
(`MI`, `CVA`, `CCF`, `Kochs`) wired into the coding-search endpoints.
Policy: docs/policy/icd-coding-search-vocabulary.md.

Matching is exact on ``term_normalized`` first, then — for a query of
:data:`PREFIX_MIN_QUERY_LEN` characters or more — by prefix against a longer
stored key (``dysen`` -> ``dysentery``); a short query like `MI` never
prefix-matches and cannot become a prefix hit of its own, so it cannot
hijack `miliary`. A vocabulary hit never bypasses coding policy: the search
endpoints resolve targets through the same filters they already apply, and a
filtered-out target contributes nothing.
"""

from __future__ import annotations

import difflib
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
DEFAULT_SORT_ORDER = 100
MAX_SORT_ORDER = 32767

# digitva-wqc: shared two-stage-picker tier labels. Used to be duplicated
# in icd10_2019_2_service.py and icd11_mms_service.py.
RESULT_TIER_FOCUSED = "focused"
RESULT_TIER_EXPANDED = "expanded"

# digitva-wqc: normalized query >= this many characters also matches a
# vocabulary key by PREFIX ("dysen" -> "dysentery"), on top of the
# existing exact match. Shorter queries stay exact-only ("MI" must not
# prefix-match into unrelated longer keys).
PREFIX_MIN_QUERY_LEN = 3
_PREFIX_VOCAB_MAX_CODES = 10

# digitva-1ht: typo-tolerant fallback, run only when the normal lexical +
# vocabulary search for a query returns nothing.
FUZZY_MIN_QUERY_LEN = 4
_FUZZY_VOCAB_CUTOFF = 0.8
_FUZZY_VOCAB_MAX_CODES = 10

# digitva-wqc: WHO qualifier boilerplate stripped from a title (and query)
# before tier classification, ranking and fuzzy comparison — "unspecified"
# and friends carry no search signal and only push the actual diagnosis
# word away from the title's start. Longest phrase first so "other and
# unspecified" is removed as one unit rather than leaving a stray "and".
_QUALIFIER_PHRASES = tuple(
    sorted(
        {
            "other and unspecified",
            "other",
            "not otherwise specified",
            "nos",
            "not elsewhere classified",
            "nec",
            "of unspecified origin",
            "unspecified origin",
            "unspecified",
            "not confirmed bacteriologically or histologically",
            "not confirmed",
            "without mention of bacteriological or histological confirmation",
            "in diseases classified elsewhere",
            "classified elsewhere",
        },
        key=len,
        reverse=True,
    )
)

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
    coding-search queries, ``normalize_term``, ``result_tier`` and the admin
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
            MasIcdSearchTerms.sort_order,
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
            "sort_order": row.sort_order,
        }
        for row in rows
    )


def _cached_links() -> tuple[dict, ...]:
    """The active-link cache, rebuilt when a row was added, removed or
    edited since the last read (see :func:`_cache_key`)."""
    key = _cache_key()
    if _cache["key"] != key:
        _cache["key"] = key
        _cache["links"] = _load_links()
    return _cache["links"]


def _tidy_title(text: str) -> str:
    """Collapse whitespace and repeated commas left behind by qualifier
    removal, then trim stray leading/trailing commas and spaces."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\s*,\s*)+", ", ", text)
    return text.strip(" ,")


def core_title(text: str) -> str:
    """``text`` with WHO qualifier boilerplate removed (case-insensitive,
    whole word/phrase, longest phrase first), then tidied.

    Falls back to the tidied original when stripping empties it out — a
    query or title that IS "other" must still be searchable as "other".
    Used for tier classification, the Python re-rank of already-fetched
    rows and fuzzy comparison; never to change which rows SQL fetches.
    """
    stripped = text or ""
    for phrase in _QUALIFIER_PHRASES:
        stripped = re.sub(
            rf"\b{re.escape(phrase)}\b", "", stripped, flags=re.IGNORECASE
        )
    tidied = _tidy_title(stripped)
    return tidied or _tidy_title(text or "")


def _title_word_starts_with(lowered_text: str, variant: str) -> bool:
    """Whether ``variant`` matches the start of ``lowered_text`` or of any
    word inside it — a word boundary is the start of the string or the
    position right after a non-alphanumeric character. Mid-word ("art" in
    "heart") never matches."""
    if not variant:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(variant), lowered_text) is not None


def result_tier(*, code: str | None, title: str, normalized_query: str) -> str:
    """``focused`` for an exact-code match or a query that starts the title
    (or any word inside it), ``expanded`` otherwise — compared over the
    query's spelling/hyphen variants AND its qualifier-stripped
    (:func:`core_title`) form against both the raw and qualifier-stripped
    title, so "gastroenteritis" reaches "Other gastroenteritis and
    colitis..." and "respiratory tuberculosis" still reaches both A15 and
    A16. Vocabulary hits are always focused (assigned at their result
    dicts). The picker's two-stage grouping reads this field. Shared by
    both catalogue search services (used to be duplicated per-service)."""
    query_variants = spelling_variants(normalized_query)
    core_query = core_title(normalized_query)
    if core_query != normalized_query:
        query_variants = list(query_variants) + [
            v for v in spelling_variants(core_query) if v not in query_variants
        ]

    stripped_code = _compact_key(code.lower()) if code is not None else None
    lowered_title = title.lower()
    stripped_title = _compact_key(lowered_title)
    core_lowered_title = core_title(title).lower()

    for variant in query_variants:
        stripped_variant = _compact_key(variant)
        if code is not None and (
            code.lower() == variant or stripped_code == stripped_variant
        ):
            return RESULT_TIER_FOCUSED
        if stripped_title.startswith(stripped_variant):
            return RESULT_TIER_FOCUSED
        if _title_word_starts_with(lowered_title, variant):
            return RESULT_TIER_FOCUSED
        if _title_word_starts_with(core_lowered_title, variant):
            return RESULT_TIER_FOCUSED
    return RESULT_TIER_EXPANDED


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


def _is_exact_link(link: dict, lookup_keys: set[str]) -> bool:
    return (
        link["term_normalized"] in lookup_keys
        or link["term_normalized_compact"] in lookup_keys
    )


def vocabulary_matches(query: str, classification: str | None = None) -> list[dict]:
    """Active links whose normalized key equals any spelling/hyphen variant
    of the ``query`` (exact), plus — for a query of
    :data:`PREFIX_MIN_QUERY_LEN` characters or more — links whose key
    STARTS WITH a variant ("dysen" -> "dysentery") that the exact pass
    did not already return.

    ``classification`` optionally narrows to one catalogue. Exact matches
    come first, in table order (several rows per term is the mechanism for
    multi-code targets like "head injury"); prefix matches follow, ranked
    by ``sort_order`` then ``icd_code`` and capped at
    :data:`_PREFIX_VOCAB_MAX_CODES` distinct codes so one short prefix
    cannot flood the picker.
    """
    lookup_keys = _query_lookup_keys(query)
    if not any(key for key in lookup_keys):
        return []
    links = tuple(
        link
        for link in _cached_links()
        if classification is None or link["icd_classification"] == classification
    )
    exact = [link for link in links if _is_exact_link(link, lookup_keys)]

    normalized_query = " ".join((query or "").lower().split())
    if len(normalized_query) < PREFIX_MIN_QUERY_LEN:
        return exact

    exact_codes = {link["icd_code"] for link in exact}
    prefix_candidates: list[dict] = []
    seen_codes: set[str] = set(exact_codes)
    for link in links:
        code = link["icd_code"]
        if code in seen_codes or _is_exact_link(link, lookup_keys):
            continue
        if any(
            link["term_normalized"].startswith(key)
            or link["term_normalized_compact"].startswith(_compact_key(key))
            for key in lookup_keys
            if key
        ):
            prefix_candidates.append(link)
            seen_codes.add(code)
    prefix_candidates.sort(key=lambda link: (link["sort_order"], link["icd_code"]))
    return exact + prefix_candidates[:_PREFIX_VOCAB_MAX_CODES]


def fuzzy_vocabulary_matches(query: str, classification: str | None = None) -> list[dict]:
    """Typo-tolerant vocabulary fallback (digitva-1ht): active links whose
    normalized key is a close match (``difflib`` ratio) of ``query``.

    Runs only when the caller's normal lexical + vocabulary search for this
    query is empty — never as part of ordinary matching, so it cannot hijack
    an exact-match query the way prefix matching would. No DB round trip:
    candidates come from the same in-memory cache ``vocabulary_matches``
    uses. Queries under :data:`FUZZY_MIN_QUERY_LEN` characters never match
    (a 2-3 character typo is not distinguishable from a different word).
    Capped at :data:`_FUZZY_VOCAB_MAX_CODES` distinct codes so one loose
    typo cannot flood the picker; ties broken by ratio then key so the
    result is deterministic.
    """
    normalized_query = " ".join((query or "").lower().split())
    if len(normalized_query) < FUZZY_MIN_QUERY_LEN:
        return []
    core_query = core_title(normalized_query)
    links = _cached_links()
    if classification is not None:
        links = tuple(link for link in links if link["icd_classification"] == classification)
    candidate_keys = {link["term_normalized"] for link in links}

    def ratio(key: str) -> float:
        # digitva-wqc: also compare the qualifier-stripped forms, so a
        # typo against a vocabulary term carrying WHO boilerplate is not
        # penalised for boilerplate the query never typed.
        return max(
            difflib.SequenceMatcher(None, normalized_query, key).ratio(),
            difflib.SequenceMatcher(None, core_query, core_title(key)).ratio(),
        )

    ranked_keys = sorted(
        ((ratio(key), key) for key in candidate_keys),
        key=lambda pair: (-pair[0], pair[1]),
    )
    matched_keys = [key for ratio, key in ranked_keys if ratio >= _FUZZY_VOCAB_CUTOFF]
    if not matched_keys:
        return []
    selected: list[dict] = []
    seen_codes: set[str] = set()
    for matched_key in matched_keys:
        for link in links:
            if link["term_normalized"] != matched_key or link["icd_code"] in seen_codes:
                continue
            seen_codes.add(link["icd_code"])
            selected.append(link)
            if len(seen_codes) >= _FUZZY_VOCAB_MAX_CODES:
                return selected
    return selected


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


def _validated_sort_order(value) -> int:
    """Positive int, optional (``None``/blank falls back to the default)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_SORT_ORDER
    try:
        sort_order = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("sort_order must be an integer.") from exc
    if not (1 <= sort_order <= MAX_SORT_ORDER):
        raise ValueError(f"sort_order must be between 1 and {MAX_SORT_ORDER}.")
    return sort_order


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
        "sort_order": row.sort_order,
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
            MasIcdSearchTerms.sort_order,
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
    sort_order: int | None = None,
) -> MasIcdSearchTerms:
    """Insert one term-code link. The normalized lookup key is derived from
    ``term``, never taken from input. ``sort_order`` defaults to
    :data:`DEFAULT_SORT_ORDER` when omitted or blank."""
    classification = _validated_classification(icd_classification)
    validated_term = _validated_term(term)
    validated_code = _validated_code(icd_code)
    row = MasIcdSearchTerms(
        term=validated_term,
        term_normalized=normalize_term(validated_term),
        icd_classification=classification,
        icd_code=validated_code,
        source=_validated_source(source),
        sort_order=_validated_sort_order(sort_order),
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
    sort_order: int | None = None,
) -> MasIcdSearchTerms:
    """Edit one link's display term, target, sort order or note.
    ``sort_order`` defaults to :data:`DEFAULT_SORT_ORDER` when omitted or
    blank, same as :func:`create_term`. Deactivation state is owned by
    :func:`set_active` and left untouched here."""
    row = get_term(term_id)
    classification = _validated_classification(icd_classification)
    validated_term = _validated_term(term)
    row.term = validated_term
    row.term_normalized = normalize_term(validated_term)
    row.icd_classification = classification
    row.icd_code = _validated_code(icd_code)
    row.sort_order = _validated_sort_order(sort_order)
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
