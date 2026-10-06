"""Questionnaire translations for district staff — /api/v1/translations/

Read the translations of the languages a project serves beside the English,
suggest a wording for one string, and (administrator or that project's PI)
accept or reject suggestions. Policy: docs/policy/va-form-project-configuration.md
("District review and suggestions", digitva-5op).

Cookie session; the writes carry the CSRF token like every browser-originated
write. Authorization is decided in the service from the caller's grants, before
any parameter is looked at: no grant in the project is a 404 whether it exists
or not. An accept changes the string for every project using that locale.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.routes.api.request_helpers import error as api_error
from app.routes.api.request_helpers import parse_body
from app.services import instrument_translation_suggestion_service as service

bp = Blueprint("translation_suggestions_api", __name__)

_MAX_SEARCH_CHARS = 64


def _refusal(exc: service.SuggestionError):
    return api_error(str(exc), exc.code, exc.status, **exc.extra)


def _no_store(payload: dict):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/<project_id>")
@login_required
@limiter.limit("120 per minute")
def project_locales(project_id: str):
    """The locales the project serves and whether the caller may decide."""
    try:
        return _no_store(service.project_locales(current_user, project_id))
    except service.SuggestionError as exc:
        return _refusal(exc)


@bp.get("/<project_id>/<locale>/questions")
@login_required
@limiter.limit("120 per minute")
def questions(project_id: str, locale: str):
    """One page of questions in form order, English beside the served
    translation. Query: ``q`` (search), ``page``, ``page_size`` (clamped)."""
    try:
        payload = service.read_questions(
            current_user, project_id, locale,
            search=(request.args.get("q") or "")[:_MAX_SEARCH_CHARS],
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", service.DEFAULT_READ_PAGE_SIZE, type=int),
        )
    except service.SuggestionError as exc:
        return _refusal(exc)
    return _no_store(payload)


@bp.post("/<project_id>/<locale>/suggestions")
@login_required
@limiter.limit("30 per hour")
def suggest(project_id: str, locale: str):
    """Body: ``item_kind``, ``item_key``, ``field``, ``proposed_text``,
    ``reason``. Rate-limited per user."""
    try:
        result = service.suggest(current_user, project_id, locale, parse_body())
        db.session.commit()
    except service.SuggestionError as exc:
        db.session.rollback()
        return _refusal(exc)
    return jsonify(result), 201


@bp.get("/suggestions")
@login_required
@limiter.limit("120 per minute")
def pending():
    """The pending queue the caller may decide (administrator: all; project
    PI: suggestions made in their projects for a locale the project serves).
    ``total`` is the badge count. Query: ``project_id``, ``locale``, ``limit``
    (clamped), ``offset``."""
    try:
        payload = service.list_pending(
            current_user,
            project_id=request.args.get("project_id"),
            locale=request.args.get("locale"),
            limit=request.args.get("limit", service.DEFAULT_QUEUE_LIMIT, type=int),
            offset=request.args.get("offset", 0, type=int),
        )
    except service.SuggestionError as exc:
        return _refusal(exc)
    return _no_store(payload)


def _decide(suggestion_id: int, accept: bool):
    note = parse_body().get("note")
    if note is not None and not isinstance(note, str):
        note = ""
    try:
        result = service.decide(current_user, suggestion_id, accept=accept, note=note)
        db.session.commit()
    except service.SuggestionError as exc:
        db.session.rollback()
        return _refusal(exc)
    return jsonify(result)


@bp.post("/suggestions/<int:suggestion_id>/accept")
@login_required
@limiter.limit("60 per minute")
def accept(suggestion_id: int):
    """Write the proposed text as the translation (source ``edited``) for
    every project using this locale. 409 ``stale`` when the translation moved
    since the suggestion. Body: optional ``note``."""
    return _decide(suggestion_id, True)


@bp.post("/suggestions/<int:suggestion_id>/reject")
@login_required
@limiter.limit("60 per minute")
def reject(suggestion_id: int):
    """Leave the translation as it is. Body: optional ``note``."""
    return _decide(suggestion_id, False)
