"""Web intake: death register and WHO VA 2022 questionnaire pages plus JSON API.

Thin layer over ``app.services.web_intake_service``. Pages render Jinja
templates that load the vendored questionnaire bundle; the API serves the
page's draft store (section-wise saves) and the submission step.
Policy: docs/policy/web-intake.md
"""
import logging
from secrets import token_hex

from flask import Blueprint, jsonify, render_template, request, session
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from app import db
from app.decorators import role_required
from app.models import VaSubmissionPayloadVersion
from app.services import web_intake_service as intake_svc

log = logging.getLogger(__name__)

intake = Blueprint("intake", __name__)


def _json_error(message, status_code):
    return jsonify({"error": message}), status_code


def _payload():
    return request.get_json(silent=True) or {}


def _handle(fn):
    """Run a service call; map WebIntakeError to a JSON error and roll back."""
    try:
        return fn()
    except intake_svc.WebIntakeError as exc:
        db.session.rollback()
        return _json_error(str(exc), exc.status_code)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@intake.get("/")
@role_required("interviewer")
def dashboard():
    return render_template("va_frontpages/va_intake.html")


@intake.get("/deaths/new")
@role_required("interviewer")
def new_death_page():
    return render_template("va_frontpages/va_intake_death.html")


@intake.get("/form/<draft_id>")
@role_required("interviewer")
def form_page(draft_id):
    try:
        draft = intake_svc.get_draft(current_user, draft_id)
    except intake_svc.WebIntakeError as exc:
        return render_template("va_errors/va_404.html"), exc.status_code
    return render_template(
        "va_frontpages/va_intake_form.html",
        draft=intake_svc.serialize_draft(draft),
        prefill=draft.prefill or {},
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@intake.get("/api/bootstrap")
@role_required("interviewer")
def api_bootstrap():
    if "csrf_token" not in session:
        session["csrf_token"] = token_hex(32)
    return jsonify(
        {
            "csrf_header_name": "X-CSRFToken",
            "csrf_token": generate_csrf(),
            "user": {"user_id": str(current_user.user_id), "name": current_user.name},
            "context": intake_svc.interviewer_context(current_user),
        }
    )


@intake.get("/api/deaths")
@role_required("interviewer")
def api_list_deaths():
    project_id = request.args.get("project_id", "")
    site_id = request.args.get("site_id", "")
    status = request.args.get("status") or None
    if not project_id or not site_id:
        return _json_error("project_id and site_id are required.", 400)
    return _handle(
        lambda: jsonify(
            {"deaths": [intake_svc.serialize_death(d) for d in intake_svc.list_deaths(current_user, project_id=project_id, site_id=site_id, status=status)]}
        )
    )


@intake.post("/api/deaths")
@role_required("interviewer")
def api_register_death():
    p = _payload()

    def run():
        death = intake_svc.register_death(
            current_user,
            project_id=str(p.get("project_id") or ""),
            site_id=str(p.get("site_id") or ""),
            org_unit_id=p.get("org_unit_id") or None,
            **{k: p.get(k) for k in (
                "deceased_name", "deceased_sex", "abha_number", "abha_address", "date_of_birth",
                "age_years", "date_of_death", "place_of_death", "address", "informant_name",
                "informant_phone", "remarks",
            )},
        )
        db.session.commit()
        return jsonify({"death": intake_svc.serialize_death(death)}), 201

    return _handle(run)


@intake.get("/api/drafts")
@role_required("interviewer")
def api_list_drafts():
    status = request.args.get("status", "draft") or None
    return jsonify({"drafts": [intake_svc.serialize_draft(d) for d in intake_svc.list_drafts(current_user, status=status)]})


@intake.post("/api/drafts")
@role_required("interviewer")
def api_start_draft():
    p = _payload()

    def run():
        draft = intake_svc.start_draft(
            current_user,
            project_id=str(p.get("project_id") or ""),
            site_id=str(p.get("site_id") or ""),
            org_unit_id=p.get("org_unit_id") or None,
            death_id=p.get("death_id") or None,
        )
        db.session.commit()
        return jsonify({"draft": intake_svc.serialize_draft(draft)}), 201

    return _handle(run)


@intake.get("/api/drafts/<draft_id>")
@role_required("interviewer")
def api_get_draft(draft_id):
    def run():
        draft = intake_svc.get_draft(current_user, draft_id)
        return jsonify(
            {
                "draft": intake_svc.serialize_draft(draft),
                "envelope": intake_svc.load_draft_envelope(draft),
                "prefill": draft.prefill or {},
            }
        )

    return _handle(run)


@intake.patch("/api/drafts/<draft_id>")
@role_required("interviewer")
def api_save_draft(draft_id):
    p = _payload()

    def run():
        draft = intake_svc.get_draft(current_user, draft_id, for_update=True)
        written = intake_svc.save_draft_sections(
            draft,
            sections=p.get("sections") or {},
            meta=p.get("meta") or None,
            current_section=p.get("current_section"),
        )
        db.session.commit()
        return jsonify({"saved_sections": written, "draft": intake_svc.serialize_draft(draft)})

    return _handle(run)


@intake.post("/api/drafts/<draft_id>/discard")
@role_required("interviewer")
def api_discard_draft(draft_id):
    def run():
        draft = intake_svc.get_draft(current_user, draft_id, for_update=True)
        intake_svc.discard_draft(draft)
        db.session.commit()
        return jsonify({"draft": intake_svc.serialize_draft(draft)})

    return _handle(run)


@intake.post("/api/drafts/<draft_id>/submit")
@role_required("interviewer")
def api_submit_draft(draft_id):
    p = _payload()

    def run():
        draft = intake_svc.get_draft(current_user, draft_id, for_update=True)
        submission = intake_svc.submit_draft(draft, current_user, completion=p.get("completion") or {})
        # Re-derived server/client disagreements (beads digitva-cal.2), never
        # blocking: surfaced here so a field problem is debuggable, not just
        # logged. No answer value is ever in these entries.
        version = db.session.get(
            VaSubmissionPayloadVersion, submission.active_payload_version_id
        )
        validation_err = version.validation_err if version else []
        db.session.commit()
        return jsonify(
            {
                "va_sid": submission.va_sid,
                "draft": intake_svc.serialize_draft(draft),
                "validation_err": validation_err,
            }
        ), 201

    return _handle(run)
