"""District suggestions for instrument translation strings (digitva-5op).

Policy: docs/policy/va-form-project-configuration.md ("District review and
suggestions"). Any user with an active grant in a project reads the
questionnaire translations of the locales the project serves, side by side
with the English, and suggests a wording for one string. An administrator, or
the PI of the project the suggestion was made in, accepts or rejects it.

There is exactly one write path to a translation: an accept calls
``instrument_translation_service.update_string`` (source ``edited``). This
module only decides *who may* and records the audit on the suggestion row.

Translations are instrument-level, so an accept changes the string for every
project using that locale; that is why a PI is limited to the locales their
own project serves.

Every public function that takes a user is an authz decision and marks the
request consulted (``authz.consulted``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes, VaProjectMaster, VaStatuses, VaUsers
from app.models.map_instrument_translation_suggestions import (
    SUGGESTION_ACCEPTED,
    SUGGESTION_PENDING,
    SUGGESTION_REJECTED,
    MapInstrumentTranslationSuggestions as Suggestion,
)
from app.models.mas_instrument_locales import (
    SOURCE_MACHINE,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services import instrument_translation_service as translations
from app.services.authz import resolve_grants
from app.services.authz.consulted import mark_consulted

log = logging.getLogger(__name__)

#: Reader page size ceiling (questions per page); lower than the editor's.
MAX_READ_PAGE_SIZE = 50
DEFAULT_READ_PAGE_SIZE = 25
MAX_QUEUE_LIMIT = 100
DEFAULT_QUEUE_LIMIT = 25
#: The reason and the decision note.
MAX_NOTE_CHARS = 1000
#: Open suggestions one user may hold at once.
MAX_PENDING_PER_USER = 50

_ITEM_KINDS = (translations.ITEM_KIND_QUESTION, translations.ITEM_KIND_CHOICE)


class SuggestionError(Exception):
    """A refusal that maps to an HTTP status; the message is safe to return."""

    def __init__(self, message: str, status: int = 400, code: str | None = None, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra


@dataclass(frozen=True)
class Standing:
    """What one user may do about one project's translations."""

    project: VaProjectMaster
    instrument_code: str
    locales: dict[str, str]  # served, non-base locale code -> language name
    can_decide: bool


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def _served(project: VaProjectMaster) -> tuple[str, dict[str, str]]:
    """The instrument code and ``{locale: language name}`` the project serves.

    The one definition the form-options payload and the translation download
    use (``served_instrument_locales``): the route module owns it, so it is
    imported late, as ``routes/api/instruments.py`` does. ``en`` is the
    instrument's own language and has nothing to suggest.
    """
    from app.routes.api.organization import served_instrument_locales

    code, offered = served_instrument_locales(project)
    offered = offered - {translations.BASE_LOCALE}
    if not offered:
        return code, {}
    rows = db.session.execute(
        sa.select(MasInstrumentLocales.locale_code, MasInstrumentLocales.language_name).where(
            MasInstrumentLocales.instrument_code == code,
            MasInstrumentLocales.locale_code.in_(offered),
        )
    ).all()
    return code, {row.locale_code: row.language_name for row in rows}


def _pi_projects(grants) -> set[str]:
    """Projects the user is PI of: a real project-scope ``project_pi`` grant."""
    return {
        g.project_id
        for g in grants.of((VaAccessRoles.project_pi,), scope_types=(VaAccessScopeTypes.project,), virtual=False)
    }


def project_standing(user, project_id: str) -> Standing:
    """Read-and-suggest standing in *project_id*; 404 unless the user holds an
    active grant there (any role, scope or level) or is an administrator, and
    the project is active, alike whether it exists or not."""
    mark_consulted()
    project_id = (project_id or "").strip().upper()
    grants = resolve_grants(user)
    holds = grants.is_admin or any(
        g.project_id == project_id and not g.virtual and g.source == "assigned"
        for g in grants.grants
    )
    project = db.session.get(VaProjectMaster, project_id) if holds else None
    if project is None or project.project_status != VaStatuses.active:
        raise SuggestionError("Project not found.", 404, "not_found")
    code, locales = _served(project)
    return Standing(
        project=project,
        instrument_code=code,
        locales=locales,
        can_decide=grants.is_admin or project_id in _pi_projects(grants),
    )


def _decider_scope(user) -> tuple[bool, set[str]]:
    """``(is_admin, PI project ids)``; 403 for a user who may decide nothing."""
    mark_consulted()
    grants = resolve_grants(user)
    pi_projects = _pi_projects(grants)
    if not grants.is_admin and not pi_projects:
        raise SuggestionError("Only an administrator or a project PI may review suggestions.", 403, "forbidden")
    return grants.is_admin, pi_projects


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _hide_machine(node) -> None:
    """Blank every ``machine`` draft in a ``list_questions`` payload: a draft
    is not a served translation, so a reader sees it as untranslated."""
    if isinstance(node, dict):
        if node.get("source") == SOURCE_MACHINE:
            for key in ("translated", "translated_label"):
                if key in node:
                    node[key] = None
            node["source"] = None
        for value in node.values():
            _hide_machine(value)
    elif isinstance(node, list):
        for value in node:
            _hide_machine(value)


def project_locales(user, project_id: str) -> dict:
    """The locales *project_id* serves, and whether the viewer may decide."""
    standing = project_standing(user, project_id)
    return {
        "project_id": standing.project.project_id,
        "instrument_code": standing.instrument_code,
        "can_decide": standing.can_decide,
        "locales": [{"code": c, "label": n} for c, n in sorted(standing.locales.items())],
    }


def read_questions(
    user, project_id: str, locale: str, *, search: str | None = None, page: int = 1,
    page_size: int = DEFAULT_READ_PAGE_SIZE,
) -> dict:
    """One page of the project's locale in form order, English beside the
    served translation, never a machine draft. 404 for a locale the project
    does not serve."""
    standing = project_standing(user, project_id)
    locale = (locale or "").strip()
    if locale not in standing.locales:
        raise SuggestionError("Language not found.", 404, "not_found")
    try:
        payload = translations.list_questions(
            standing.instrument_code, locale, search=search, page=page,
            page_size=min(max(1, page_size), MAX_READ_PAGE_SIZE),
        )
    except translations.InstrumentTranslationError:
        raise SuggestionError("Instrument not found.", 404, "not_found") from None
    _hide_machine(payload["items"])
    payload["project_id"] = standing.project.project_id
    payload["can_decide"] = standing.can_decide
    return payload


def _reference(code: str) -> dict:
    """The instrument's reference items; an instrument the app has no
    reference form for is a 404, never a 500."""
    try:
        return translations.reference_items(code)
    except translations.InstrumentTranslationError:
        raise SuggestionError("Instrument not found.", 404, "not_found") from None


def _served_text(
    code: str, locale: str, item_kind: str, item_key: str, field: str, *, lock: bool = False
) -> str | None:
    """The translation a reader is shown: the stored text unless it is a
    machine draft or absent. ``lock`` takes the row ``FOR UPDATE``."""
    row = db.session.get(
        MapInstrumentTranslations, (code, locale, item_kind, item_key, field), with_for_update=lock
    )
    return row.text if row is not None and row.source != SOURCE_MACHINE else None


# ---------------------------------------------------------------------------
# Suggesting
# ---------------------------------------------------------------------------


def _text(body: dict, name: str, limit: int) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SuggestionError(f"{name} is required.", 400, "invalid_request")
    value = value.strip()
    if len(value) > limit:
        raise SuggestionError(f"{name} may not exceed {limit} characters.", 400, "invalid_request")
    return value


def suggest(user, project_id: str, locale: str, body: dict) -> dict:
    """Store a suggestion for one string. The translation the suggester saw is
    read here, never taken from the client. 409 when the user already has a
    pending suggestion for the string."""
    standing = project_standing(user, project_id)
    locale = (locale or "").strip()
    if locale not in standing.locales:
        raise SuggestionError("Language not found.", 404, "not_found")
    kind = body.get("item_kind")
    key = body.get("item_key")
    fld = body.get("field")
    if not all(isinstance(v, str) for v in (kind, key, fld)) or kind not in _ITEM_KINDS:
        raise SuggestionError("item_kind, item_key and field are required.", 400, "invalid_request")
    proposed = _text(body, "proposed_text", translations.MAX_TRANSLATION_TEXT_CHARS)
    reason = _text(body, "reason", MAX_NOTE_CHARS)
    code = standing.instrument_code
    reference = _reference(code)
    if (kind, key, fld) not in reference:
        raise SuggestionError(f"{kind} {key!r} has no {fld} in the reference form.", 400, "invalid_request")
    try:
        translations.validate_translation_text(proposed, reference[(kind, key, fld)])
    except translations.InvalidTranslationText as exc:
        raise SuggestionError(str(exc), 422, exc.code) from None
    seen = _served_text(code, locale, kind, key, fld)
    if proposed == seen:
        raise SuggestionError("That is already the current wording.", 400, "invalid_request")

    pending = db.session.scalar(
        sa.select(sa.func.count()).select_from(Suggestion).where(
            Suggestion.suggested_by == user.user_id, Suggestion.status == SUGGESTION_PENDING
        )
    )
    if pending >= MAX_PENDING_PER_USER:
        raise SuggestionError(
            f"You already have {MAX_PENDING_PER_USER} suggestions waiting for review.",
            409, "too_many_pending",
        )
    row = Suggestion(
        instrument_code=code, locale_code=locale, item_kind=kind, item_key=key, field=fld,
        proposed_text=proposed, seen_text=seen, reason=reason,
        project_id=standing.project.project_id, suggested_by=user.user_id,
    )
    try:
        with db.session.begin_nested():
            db.session.add(row)
            db.session.flush()
    except sa.exc.IntegrityError:
        raise SuggestionError(
            "You already have a pending suggestion for this string.", 409, "already_pending"
        ) from None
    log.info(
        "instrument translation suggested | id=%s | %s/%s | item=%s:%s:%s | project=%s | by=%s",
        row.id, code, locale, kind, key, fld, row.project_id, user.user_id,
    )
    return {"id": row.id, "status": row.status}


# ---------------------------------------------------------------------------
# Reviewing
# ---------------------------------------------------------------------------


def _queue_filter(is_admin: bool, pi_projects: set[str], project_id: str | None, locale: str | None):
    """The WHERE of the decider's pending queue. An admin sees every pending
    suggestion; a PI only those made in their projects, for a locale that
    project still serves."""
    clauses = [Suggestion.status == SUGGESTION_PENDING]
    if project_id:
        clauses.append(Suggestion.project_id == project_id)
    if locale:
        clauses.append(Suggestion.locale_code == locale)
    if not is_admin:
        wanted = pi_projects & {project_id} if project_id else pi_projects
        projects = db.session.scalars(
            sa.select(VaProjectMaster).where(
                VaProjectMaster.project_id.in_(wanted),
                VaProjectMaster.project_status == VaStatuses.active,
            )
        ).all()
        per_project = []
        for project in projects:
            _code, served = _served(project)
            if served:
                per_project.append(sa.and_(
                    Suggestion.project_id == project.project_id,
                    Suggestion.locale_code.in_(sorted(served)),
                ))
        clauses.append(sa.or_(*per_project) if per_project else sa.false())
    return clauses


def list_pending(
    user, *, project_id: str | None = None, locale: str | None = None,
    limit: int = DEFAULT_QUEUE_LIMIT, offset: int = 0,
) -> dict:
    """The pending queue the user may decide, oldest first, with the English,
    the current served text and whether it moved since the suggester looked
    (``stale``). ``total`` is the badge count."""
    is_admin, pi_projects = _decider_scope(user)
    project_id = (project_id or "").strip().upper() or None
    locale = (locale or "").strip() or None
    limit = min(max(1, limit), MAX_QUEUE_LIMIT)
    offset = max(0, offset)
    where = _queue_filter(is_admin, pi_projects, project_id, locale)

    total = db.session.scalar(sa.select(sa.func.count()).select_from(Suggestion).where(*where))
    rows = db.session.execute(
        sa.select(Suggestion, VaUsers.name)
        .join(VaUsers, VaUsers.user_id == Suggestion.suggested_by)
        .where(*where)
        .order_by(Suggestion.id)
        .limit(limit)
        .offset(offset)
    ).all()

    # One read for every current translation on the page, not one per row.
    current = {}
    if rows:
        keys = [
            (s.instrument_code, s.locale_code, s.item_kind, s.item_key, s.field) for s, _ in rows
        ]
        for tr in db.session.scalars(
            sa.select(MapInstrumentTranslations).where(
                sa.tuple_(
                    MapInstrumentTranslations.instrument_code,
                    MapInstrumentTranslations.locale_code,
                    MapInstrumentTranslations.item_kind,
                    MapInstrumentTranslations.item_key,
                    MapInstrumentTranslations.field,
                ).in_(keys)
            )
        ):
            if tr.source != SOURCE_MACHINE:
                current[(tr.instrument_code, tr.locale_code, tr.item_kind, tr.item_key, tr.field)] = tr.text
    names = {
        (c, l): n
        for c, l, n in db.session.execute(
            sa.select(
                MasInstrumentLocales.instrument_code,
                MasInstrumentLocales.locale_code,
                MasInstrumentLocales.language_name,
            ).where(MasInstrumentLocales.locale_code.in_({s.locale_code for s, _ in rows}))
        )
    }

    english_by_code = {}
    for code in {s.instrument_code for s, _ in rows}:
        try:
            english_by_code[code] = translations.reference_items(code)
        except translations.InstrumentTranslationError:
            english_by_code[code] = {}
    items = []
    for s, suggester in rows:
        key = (s.instrument_code, s.locale_code, s.item_kind, s.item_key, s.field)
        now_text = current.get(key)
        items.append({
            "id": s.id,
            "project_id": s.project_id,
            "instrument_code": s.instrument_code,
            "locale": s.locale_code,
            "language": names.get((s.instrument_code, s.locale_code), s.locale_code),
            "item_kind": s.item_kind,
            "item_key": s.item_key,
            "field": s.field,
            "english": english_by_code[s.instrument_code].get(key[2:]),
            "current_text": now_text,
            "proposed_text": s.proposed_text,
            "reason": s.reason,
            "suggested_by": suggester,
            "suggested_at": s.suggested_at.isoformat() if s.suggested_at else None,
            "stale": now_text != s.seen_text,
        })
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def decide(user, suggestion_id: int, *, accept: bool, note: str | None = None) -> dict:
    """Accept or reject one pending suggestion.

    Accept writes the proposed text through ``update_string`` (``edited``) as
    the deciding user, after re-checking that the served translation is still
    what the suggester saw (409 ``stale`` otherwise). The row is locked for the
    check and the write, so two deciders cannot both win. The caller commits.
    """
    is_admin, pi_projects = _decider_scope(user)
    note = (note or "").strip() or None
    if note and len(note) > MAX_NOTE_CHARS:
        raise SuggestionError(f"note may not exceed {MAX_NOTE_CHARS} characters.", 400, "invalid_request")

    row = db.session.get(Suggestion, suggestion_id, with_for_update=True)
    # A PI sees nothing of another project's suggestions, not even that they exist.
    if row is None or (not is_admin and row.project_id not in pi_projects):
        raise SuggestionError("Suggestion not found.", 404, "not_found")
    if not is_admin:
        project = db.session.get(VaProjectMaster, row.project_id)
        _code, served = _served(project)
        if row.locale_code not in served:
            raise SuggestionError(
                "Your project does not serve this language, so you cannot decide it.", 403, "forbidden"
            )
    if row.status != SUGGESTION_PENDING:
        raise SuggestionError("This suggestion has already been decided.", 409, "already_decided")
    if accept and not is_admin and row.suggested_by == user.user_id:
        raise SuggestionError(
            "You cannot accept your own suggestion; another PI or an administrator must.",
            403, "own_suggestion",
        )

    result = {}
    if accept:
        # Lock the locale (serialises accepts, covers a string with no row yet)
        # then the string, so nothing can change it between the staleness
        # check and the write.
        db.session.get(
            MasInstrumentLocales, (row.instrument_code, row.locale_code), with_for_update=True
        )
        now_text = _served_text(
            row.instrument_code, row.locale_code, row.item_kind, row.item_key, row.field, lock=True
        )
        if now_text != row.seen_text:
            raise SuggestionError(
                "The translation changed since this was suggested. Reject it and ask for a fresh suggestion.",
                409, "stale", current_text=now_text,
            )
        try:
            result = translations.update_string(
                row.instrument_code, row.locale_code, item_kind=row.item_kind,
                item_key=row.item_key, field=row.field, text=row.proposed_text,
                actor_id=user.user_id,
            )
        except translations.InvalidTranslationText as exc:
            raise SuggestionError(str(exc), 422, exc.code) from None
        except translations.InstrumentTranslationError as exc:
            raise SuggestionError(str(exc), 422, "unprocessable") from None

    row.status = SUGGESTION_ACCEPTED if accept else SUGGESTION_REJECTED
    row.decided_by = user.user_id
    row.decided_at = datetime.now(UTC)
    row.decision_note = note
    db.session.flush()
    log.info(
        "instrument translation suggestion %s | id=%s | %s/%s | item=%s:%s:%s | project=%s | "
        "suggested_by=%s | decided_by=%s",
        row.status, row.id, row.instrument_code, row.locale_code, row.item_kind, row.item_key,
        row.field, row.project_id, row.suggested_by, user.user_id,
    )
    return {
        "id": row.id,
        "status": row.status,
        "version": result.get("version"),
        # Instrument-level: every project using this locale now shows the text.
        "changes_all_projects": accept,
    }
