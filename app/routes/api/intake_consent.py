"""The browser interview's respondent consent —
/api/v1/intake/drafts/<draft_id>/consent (digitva-athy, owner 2026-10-22).

Before a web interview opens, the page asks whether the project requires
consent and what decision is on file for the draft's case; when none is, it
shows the notice and records the decision here (the contract 5.3 object,
``client_draft_id`` equal to the draft's own, null for a browser draft). The
browser's ``/drafts/<id>/submit`` then finds it on file (contract 5.3/5.4).
Only the draft's owner (``get_draft``); browser session only; the POST needs
``X-CSRFToken``. Policy: docs/policy/respondent-consent-notice-draft.md "Web
flow".
"""

from flask import Blueprint, jsonify
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only, error, intake_error, parse_body
from app.services import consent_service
from app.services import web_intake_service as intake_svc

bp = Blueprint("intake_consent_api", __name__)


@bp.before_request
def _require_browser_session():
    return browser_session_only()


@bp.errorhandler(intake_svc.WebIntakeError)
def _intake_refused(exc):
    db.session.rollback()
    return intake_error(exc)


@bp.errorhandler(consent_service.ConsentError)
def _consent_refused(exc):
    db.session.rollback()
    return error(str(exc), exc.code, exc.status_code, **({"fields": exc.fields} if exc.fields else {}))


@bp.get("/drafts/<draft_id>/consent")
@role_required("interviewer")
@limiter.limit("120 per minute")
def get_draft_consent(draft_id):
    """``{consent_required, decision (granted|refused|withdrawn|null),
    covered_fields, client_draft_id}``."""
    draft = intake_svc.get_draft(current_user, draft_id)
    return jsonify(consent_service.draft_consent_status(draft))


@bp.post("/drafts/<draft_id>/consent")
@role_required("interviewer")
@limiter.limit("30 per minute")
def post_draft_consent(draft_id):
    """Body ``{"consent": <5.3 object>}``; replies 201 with the GET shape.
    422 ``consent_invalid``, 409 ``conflict`` (a reused ``client_id``), 409
    for a draft no longer open, 404 for anyone else's draft."""
    draft = intake_svc.get_draft(current_user, draft_id, require_open=True)
    status = consent_service.record_draft_consent(current_user, draft, parse_body().get("consent"))
    db.session.commit()
    return jsonify(status), 201
