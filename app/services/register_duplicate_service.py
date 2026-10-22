"""Possible-duplicate matching over the (possibly sealed) death register.

Policy: docs/policy/pii-encryption-at-rest.md, "Register design" (duplicate
matching, option (a)); notes: docs/kb/pii-slice-2.md, "T3". Rules of the hint:
``possible_duplicate_rows``.

Postgres cannot score ciphertext, so the SQL stage keeps every non-name gate and
selects no name; the names of the (capped) candidates are opened here and
scored with a Python port of the old query: the name normalisation of
``_normalised_name`` and pg_trgm's ``similarity()``. Names are never sent back
to Postgres. Phone and ABHA hints compare stored blind indexes in SQL.

Character classes (word, punctuation, space) come from the database itself,
probed once per process by code point (no name is involved), so the port
follows the DB locale; see ``_classes`` for what is approximated.
"""

from __future__ import annotations

import logging
import string
import struct
import unicodedata
import uuid
from typing import NamedTuple

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.orm import aliased, load_only

from app import db
from app.models import (
    MapDeathIdentifier,
    MasDeathIdentifierType,
    MasOrgUnit,
    VaDeathRegister,
    VaUsers,
)
from app.services import register_pii_accessor as register_pii

log = logging.getLogger(__name__)

#: Dates of death this many days apart or less may be the same death.
DUPLICATE_DAYS = 3
#: pg_trgm ``similarity()`` of the normalised names at or above this matches.
DUPLICATE_NAME_SIMILARITY = 0.5
#: Most candidates the case API returns.
DUPLICATE_CANDIDATES_MAX = 50
#: Most sealed name candidates one subject gets opened (config ``DUPLICATE_PREFILTER_MAX``).
DUPLICATE_PREFILTER_MAX = 50
#: Most candidates one subject takes from each score-1 branch (config ``DUPLICATE_STRONG_MAX``).
DUPLICATE_STRONG_MAX = 50
_UNKNOWN_SEX = ("undetermined", "unknown")
#: Honorifics dropped before comparing names ("Late Smt. Kamla Devi").
_NAME_TITLES = frozenset(
    ("late", "lt", "mr", "mrs", "ms", "miss", "smt", "shrimati", "shri", "sri", "dr", "master", "baby",
     "kumari", "km")
)
_OPEN_FIELDS = ("deceased_name",)
_SURVIVOR_FIELDS = ("deceased_name", "informant_name", "address_village_ward")


class DuplicateRow(NamedTuple):
    """One candidate for one subject (the shape the callers read)."""

    subject_id: uuid.UUID
    death_id: uuid.UUID
    unique_id: str
    status: str
    unit_name: str | None
    score: float
    deceased_name: str | None
    date_of_death: object
    deceased_sex: str | None
    age_years: int | None
    informant_name: str | None
    address_village_ward: str | None
    interviewer_name: str | None
    registrant_name: str | None


# ---------------------------------------------------------------------------
# Python port of the name normalisation and pg_trgm similarity()
# ---------------------------------------------------------------------------

_classes_cache: tuple[frozenset, frozenset, frozenset] | None = None


def _classes() -> tuple[frozenset, frozenset, frozenset]:
    """``(word, punct, space)``: the BMP code points from 128 up that the
    database's locale counts as alphanumeric (what pg_trgm and the regex
    ``\\m`` / ``\\M`` call a word character), ``[[:punct:]]`` and ``\\s``.
    Probed once per process with code points only. ASCII is fixed (letters
    and digits; ``string.punctuation``; the six ASCII spaces). Above the BMP
    the Python ``str`` methods stand in (punctuation or symbol categories;
    an approximation, residual). In a
    glibc ``en_US.utf8`` database many combining marks (Devanagari virama,
    nukta, some vowel signs) are punctuation or non-word, which is why this is
    read from the database rather than from ``unicodedata``."""
    global _classes_cache
    if _classes_cache is None:
        rows = db.session.execute(
            sa.text(
                "SELECT i, show_trgm(chr(i)) = ARRAY[]::text[] AS nonword, chr(i) ~ :punct AS punct, "
                "chr(i) ~ :space AS space FROM generate_series(128, 65535) AS i "
                "WHERE i NOT BETWEEN 55296 AND 57343"
            ),
            {"punct": "[[:punct:]]", "space": r"\s"},
        ).all()
        _classes_cache = (
            frozenset(r.i for r in rows if not r.nonword),
            frozenset(r.i for r in rows if r.punct),
            frozenset(r.i for r in rows if r.space),
        )
    return _classes_cache


def _is_word(char: str) -> bool:
    code = ord(char)
    if code < 128:
        return char.isalnum()
    return code in _classes()[0] if code <= 0xFFFF else char.isalnum()


def _is_punct(char: str) -> bool:
    code = ord(char)
    if code < 128:
        return char in string.punctuation
    return code in _classes()[1] if code <= 0xFFFF else unicodedata.category(char)[0] in "PS"


def _is_space(char: str) -> bool:
    code = ord(char)
    if code < 128:
        return char in " \t\n\r\x0b\x0c"
    return code in _classes()[2] if code <= 0xFFFF else char.isspace()


def _lower(char: str) -> str:
    # Postgres lower() maps one character to one ("İ" -> "i"); Python may emit two.
    return char.lower()[0]


def normalised_name(name: str) -> str:
    """Port of the old SQL ``_normalised_name``: lowercase, punctuation to
    spaces, whole-word titles dropped, whitespace collapsed, trimmed."""
    chars = [" " if _is_punct(c) else c for c in map(_lower, name)]
    out: list[str] = []
    word: list[str] = []

    def flush():
        text = "".join(word)
        out.append(" " if text in _NAME_TITLES else text)
        word.clear()

    for c in chars:
        if _is_word(c):
            word.append(c)
            continue
        if word:
            flush()
        out.append(" " if _is_space(c) else c)
    if word:
        flush()
    collapsed, previous_space = [], False
    for c in "".join(out):
        is_space = c == " "
        if not (is_space and previous_space):
            collapsed.append(c)
        previous_space = is_space
    return "".join(collapsed).strip(" ")


def trigrams(text: str) -> frozenset:
    """pg_trgm's trigram set: each run of word characters padded with two
    spaces before and one after, every three-character window. Postgres
    stores a trigram of non-ASCII characters as a 24-bit hash, so two
    different ones can collide there and not here (residual, documented in
    docs/kb/pii-slice-2.md)."""
    keys, word = set(), []

    def add():
        padded = "  " + "".join(word) + " "
        keys.update(padded[i:i + 3] for i in range(len(padded) - 2))
        word.clear()

    for c in text:
        if _is_word(c):
            word.append(c)
        elif word:
            add()
    if word:
        add()
    return frozenset(keys)


def similarity(a: frozenset, b: frozenset) -> float:
    """pg_trgm ``similarity()`` of two trigram sets (0 when either is empty),
    rounded to float4 as Postgres returns it."""
    if not a or not b:
        return 0.0
    common = len(a & b)
    return _float4(common / (len(a) + len(b) - common))


def _float4(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _prefilter_max() -> int:
    return int(current_app.config.get("DUPLICATE_PREFILTER_MAX", DUPLICATE_PREFILTER_MAX))


def _strong_max() -> int:
    return int(current_app.config.get("DUPLICATE_STRONG_MAX", DUPLICATE_STRONG_MAX))


def _candidates_query(subject_ids, scope, prefilter_max, strong_max):
    """ONE statement: every (subject, candidate) pair the gates let through,
    with the columns the hint shows that are not sealed. ``score`` is NULL
    for the name branch (scored in Python; at most *prefilter_max* sealed
    candidates per subject, every plaintext one) and 1.0 for a registration
    number, phone or ABHA match (at most *strong_max* per subject and branch)."""
    subject = aliased(VaDeathRegister)
    subject_unit = aliased(MasOrgUnit)
    unit = aliased(MasOrgUnit)
    interviewer = aliased(VaUsers)
    registrant = aliased(VaUsers)
    closed = ("cancelled", "duplicate")
    days = sa.literal_column(str(DUPLICATE_DAYS), sa.Integer)  # a constant, never input
    candidate = VaDeathRegister

    def columns(score_column, rank_column, total_column):
        return (
            subject.death_id.label("subject_id"),
            candidate.death_id,
            candidate.unique_id,
            candidate.status,
            unit.unit_name,
            candidate.date_of_death,
            candidate.deceased_sex,
            candidate.age_years,
            interviewer.name.label("interviewer_name"),
            registrant.name.label("registrant_name"),
            score_column.label("score"),
            rank_column.label("rn"),
            total_column.label("total"),
            sealed.label("sealed"),
        )

    def people(stmt):
        return (
            stmt.outerjoin(unit, unit.org_unit_id == candidate.org_unit_id)
            .outerjoin(interviewer, interviewer.user_id == candidate.started_by_user_id)
            .outerjoin(registrant, registrant.user_id == candidate.registered_by)
        )

    one = sa.literal(1, sa.Integer)
    unscored = sa.cast(sa.null(), sa.Float)
    # Nearer first when a subject has more candidates than the cap: the same
    # unit, then the closest date of death, then the id (a stable cut).
    nearness = (
        sa.case((sa.and_(subject.org_unit_id.is_not(None), candidate.org_unit_id == subject.org_unit_id), 0),
                else_=1),
        sa.func.abs(candidate.date_of_death - subject.date_of_death),
        candidate.death_id,
    )
    # Only a sealed candidate costs a decrypt, so only those are capped; a
    # plaintext name (flag off, not yet sealed) is scored as the old query did.
    sealed = candidate.pii_sealed.is_not(None)
    by_name = people(
        sa.select(*columns(
            unscored,
            sa.func.row_number().over(partition_by=(subject.death_id, sealed), order_by=nearness),
            sa.func.count().over(partition_by=(subject.death_id, sealed)),
        ))
        .select_from(subject)
        .join(
            candidate,
            sa.and_(
                candidate.project_id == subject.project_id,
                candidate.death_id != subject.death_id,
                candidate.date_of_death.between(
                    subject.date_of_death - days, subject.date_of_death + days
                ),
                candidate.status.not_in(closed),
                candidate.has_deceased_name.is_(True),
            ),
        )
        .outerjoin(subject_unit, subject_unit.org_unit_id == subject.org_unit_id)
    ).where(
        subject.death_id.in_(subject_ids),
        subject.status.not_in(closed),
        subject.pending_flag.is_(None),
        subject.has_deceased_name.is_(True),
        subject.date_of_death.is_not(None),
        sa.or_(
            subject.deceased_sex.is_(None),
            subject.deceased_sex.in_(_UNKNOWN_SEX),
            candidate.deceased_sex.is_(None),
            candidate.deceased_sex.in_(_UNKNOWN_SEX),
            candidate.deceased_sex == subject.deceased_sex,
        ),
        sa.or_(
            subject.org_unit_id.is_(None),
            candidate.org_unit_id.is_(None),
            candidate.org_unit_id == subject.org_unit_id,
            candidate.org_unit_id == subject_unit.parent_org_unit_id,
            unit.parent_org_unit_id == subject.org_unit_id,
            unit.parent_org_unit_id == subject_unit.parent_org_unit_id,
        ),
        scope,
    ).subquery()
    capped = sa.select(by_name).where(
        sa.or_(by_name.c.rn <= prefilter_max, by_name.c.sealed.is_(False)))

    def strong(join_candidate, *joins_before):
        """A score-1 branch: the subject's gates (open, no flag) and the
        candidate's (same project, open, inside *scope*); no date, sex, unit or name rule.
        Ranked per subject by ``nearness`` and cut at *strong_max* before any
        entity is loaded, so one shared phone cannot fan out."""
        stmt = sa.select(*columns(
            sa.literal(1.0, sa.Float),
            sa.func.row_number().over(partition_by=subject.death_id, order_by=nearness),
            sa.func.count().over(partition_by=subject.death_id),
        )).select_from(subject)
        for target, on in joins_before:
            stmt = stmt.join(target, on)
        stmt = people(stmt.join(candidate, join_candidate))
        ranked = stmt.where(
            subject.death_id.in_(subject_ids),
            subject.status.not_in(closed),
            subject.pending_flag.is_(None),
            scope,
        ).subquery()
        return sa.select(ranked).where(ranked.c.rn <= strong_max)

    # The same registration number (blind index, one project-scoped type); the
    # lookup is ix_map_death_identifier_type_bidx.
    mine = aliased(MapDeathIdentifier)
    theirs = aliased(MapDeathIdentifier)
    by_number = strong(
        sa.and_(
            candidate.death_id == theirs.death_id,
            candidate.project_id == subject.project_id,
            candidate.status.not_in(closed),
        ),
        (mine, mine.death_id == subject.death_id),
        (MasDeathIdentifierType, sa.and_(
            MasDeathIdentifierType.identifier_type_id == mine.identifier_type_id,
            MasDeathIdentifierType.uniqueness_scope == "project",
        )),
        (theirs, sa.and_(
            theirs.identifier_type_id == mine.identifier_type_id,
            theirs.value_blind_index == mine.value_blind_index,
            theirs.death_id != mine.death_id,
        )),
    )

    def bidx(mine_column, their_column):
        """Equality of one blind index pair, inside the project: each is its
        own branch (a UNION, not an OR) so the (project_id, index) partial
        index serves it. A subject without the index (unsealed, legacy) has
        NULL, which equals nothing."""
        return strong(sa.and_(
            their_column(candidate) == mine_column(subject),
            candidate.project_id == subject.project_id,
            candidate.death_id != subject.death_id,
            candidate.status.not_in(closed),
        ))

    phone_1, phone_2 = (lambda r: r.informant_phone_bidx), (lambda r: r.informant_phone_2_bidx)
    branches = [capped, by_number]
    branches += [bidx(mine, theirs) for mine in (phone_1, phone_2) for theirs in (phone_1, phone_2)]
    for column in (lambda r: r.abha_number_bidx, lambda r: r.abha_address_bidx):
        branches.append(bidx(column, column))
    return sa.union_all(*branches)


def possible_duplicate_rows(subject_ids: list[uuid.UUID], scope, *, per_case: int) -> list[DuplicateRow]:
    """Other cases that may be the same death as each subject: two statements
    for any number of subjects, a sealed register or not.

    A candidate is in the subject's project, not the subject, not cancelled
    and not itself a confirmed duplicate (neither can be named as the kept
    case), inside *scope* (the caller's worklist reach, so no name leaves it),
    with a date of death within ``DUPLICATE_DAYS``, the same sex unless either
    is unknown, a normalised-name similarity (pg_trgm's, ported) of at least
    ``DUPLICATE_NAME_SIMILARITY``, and a neighbouring unit: the same unit, its
    parent, a child, or a sibling (same parent), or either case has no unit.
    Two top-level units are not neighbours. Subjects without a name or date of
    death get no name match; a closed subject, or one with a flag waiting for a
    supervisor, gets none. Only the ``DUPLICATE_PREFILTER_MAX`` nearest
    sealed candidates of a subject (same unit, then closest date) are opened and
    scored, so a crowded window costs a bounded number of decryptions; a
    candidate whose name is still a plaintext column costs none and is always
    scored. Each score-1 branch keeps the ``DUPLICATE_STRONG_MAX`` nearest per
    subject (same ordering). A warning with counts only is logged when a cap cuts. A case holding the
    same registration number (blind index of a project-scoped type,
    ``death_identifier_service``), informant phone (either column against
    either) or ABHA number or address (stored blind indexes, so only sealed
    rows carry them) is also a candidate, score 1, whatever its name, date or
    unit says (still inside *scope*, still open). At most *per_case*
    candidates per subject, highest score first, then by id. Opens, for the
    scored candidates and their subjects, the deceased's name only; for the
    survivors also the informant's name and the village or ward. Rows:
    ``DuplicateRow`` (``subject_id``, ``death_id``, ``unique_id``, ``status``,
    ``unit_name``, ``score``, and the candidate's ``deceased_name``,
    ``date_of_death``, ``deceased_sex``, ``age_years``, ``informant_name``,
    ``address_village_ward``, ``interviewer_name`` (who started its
    interview, None when nobody did: a registrant may not be an interviewer)
    and ``registrant_name`` (who registered the death)), ordered by subject
    then rank.
    """
    if not subject_ids or scope is None:
        return []
    cap = _prefilter_max()
    strong_cap = _strong_max()
    pairs = db.session.execute(_candidates_query(subject_ids, scope, cap, strong_cap)).all()
    if not pairs:
        return []
    capped = {p.subject_id: p.total for p in pairs if p.score is None and p.sealed and p.total > cap}
    if capped:
        log.warning(
            "duplicate prefilter cap hit | subjects=%d | max_candidates=%d | cap=%d",
            len(capped), max(capped.values()), cap,
        )
    strong_capped = {p.subject_id: p.total for p in pairs if p.score is not None and p.total > strong_cap}
    if strong_capped:
        log.warning(
            "duplicate strong cap hit | subjects=%d | max_candidates=%d | cap=%d",
            len(strong_capped), max(strong_capped.values()), strong_cap,
        )

    needed = {p.death_id for p in pairs} | {p.subject_id for p in pairs if p.score is None}
    entities = {
        row.death_id: row
        for row in db.session.scalars(
            sa.select(VaDeathRegister)
            .where(VaDeathRegister.death_id.in_(needed))
            .options(load_only(
                VaDeathRegister.death_id, VaDeathRegister.pii_sealed, VaDeathRegister.pii_dek_wrapped,
                *(getattr(VaDeathRegister, field) for field in _SURVIVOR_FIELDS),
            ))
        )
    }

    # Name stage: one open per distinct row (subjects and name candidates),
    # kept as trigram sets, never as names. The DEK cache evicts oldest-first
    # past DEK_CACHE_MAX, so memory stays bounded for any page size.
    name_ids = {p.death_id for p in pairs if p.score is None} | {p.subject_id for p in pairs if p.score is None}
    opened = register_pii.open_register_pii([entities[i] for i in name_ids], only=_OPEN_FIELDS)
    grams = {i: trigrams(normalised_name(opened[i]["deceased_name"] or "")) for i in name_ids}

    best: dict[tuple, tuple[float, object]] = {}
    for p in pairs:
        score = (
            similarity(grams[p.subject_id], grams[p.death_id]) if p.score is None else float(p.score)
        )
        if p.score is None and score < DUPLICATE_NAME_SIMILARITY:
            continue
        key = (p.subject_id, p.death_id)
        if key not in best or score > best[key][0]:
            best[key] = (score, p)

    per_subject: dict[uuid.UUID, list] = {}
    for (subject_id, death_id), (score, p) in best.items():
        per_subject.setdefault(subject_id, []).append((score, death_id, p))
    survivors = []
    for subject_id in sorted(per_subject):
        ranked = sorted(per_subject[subject_id], key=lambda item: (-item[0], item[1]))
        survivors += [(subject_id, *item) for item in ranked[:per_case]]

    details = register_pii.open_register_pii(
        [entities[death_id] for _, _, death_id, _ in survivors], only=_SURVIVOR_FIELDS
    )
    return [
        DuplicateRow(
            subject_id=subject_id, death_id=death_id, unique_id=p.unique_id, status=p.status,
            unit_name=p.unit_name, score=score, deceased_name=details[death_id]["deceased_name"],
            date_of_death=p.date_of_death, deceased_sex=p.deceased_sex, age_years=p.age_years,
            informant_name=details[death_id]["informant_name"],
            address_village_ward=details[death_id]["address_village_ward"],
            interviewer_name=p.interviewer_name, registrant_name=p.registrant_name,
        )
        for subject_id, score, death_id, p in survivors
    ]
