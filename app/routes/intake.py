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


@intake.get("/supervision")
@role_required("interview_supervisor", "data_manager")
def supervision_page():
    """The supervisor list over ``/api/supervision/cases`` (digitva-vzk.8)."""
    return render_template("va_frontpages/va_intake_supervision.html")


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
        names=intake_svc.resolve_draft_display_names(draft),
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
                "age_years", "date_of_death", "place_of_death", "address", "address_house_street",
                "address_village_ward", "address_landmark", "informant_name", "informant_phone",
                "informant_phone_2", "remarks", "father_name", "mother_name",
            )},
        )
        db.session.commit()
        return jsonify({"death": intake_svc.serialize_death(death)}), 201

    return _handle(run)


_TRUE, _FALSE = ("1", "true", "yes"), ("", "0", "false", "no")


@intake.get("/api/cases")
@role_required("interviewer")
def api_worklist():
    """Team cases in the caller's interviewer scope (the worklist).

    Query: ``mine`` (true/false), ``state`` (comma-separated case states),
    ``limit`` (clamped to 1..200), ``cursor`` (from ``next_cursor``).
    """
    mine_raw = (request.args.get("mine") or "").lower()
    if mine_raw not in _TRUE + _FALSE:
        return _json_error("mine must be true or false.", 400)
    states = [s for s in (request.args.get("state") or "").split(",") if s]
    try:
        limit = int(request.args.get("limit") or intake_svc.WORKLIST_PAGE_DEFAULT)
    except ValueError:
        return _json_error("limit must be a whole number.", 400)

    def run():
        result = intake_svc.list_worklist(
            current_user,
            mine=mine_raw in _TRUE,
            states=states,
            cursor=request.args.get("cursor") or None,
            limit=limit,
        )
        return jsonify(
            {
                "cases": [intake_svc.serialize_worklist_row(current_user, *row) for row in result["cases"]],
                "counts": result["counts"],
                "next_cursor": result["next_cursor"],
            }
        )

    return _handle(run)


@intake.post("/api/cases/<death_id>/flags")
@role_required("interviewer")
def api_flag_case(death_id):
    """Flag a case as a possible duplicate or for cancellation (a supervisor
    confirms or rejects it). Body: ``kind``, ``reason``, ``duplicate_of``."""
    p = _payload()

    def run():
        death = intake_svc.flag_death(
            current_user,
            death_id,
            kind=str(p.get("kind") or ""),
            reason=p.get("reason") if isinstance(p.get("reason"), str) else None,
            duplicate_of=p.get("duplicate_of") or None,
        )
        db.session.commit()
        return jsonify({"death": intake_svc.serialize_death(death)})

    return _handle(run)


def _visit_ack(death):
    """What a visit, attempt or pause returns: the case's new state and dates,
    no identifiers (the page reloads its list)."""
    return {
        "death_id": str(death.death_id),
        "unique_id": death.unique_id,
        "status": death.status,
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
    }


@intake.post("/api/cases/<death_id>/visit")
@role_required("interviewer")
def api_set_visit(death_id):
    """Set (or clear, with ``null``) the case's next visit. Body: ``next_visit_at``
    (ISO date-time with timezone)."""
    p = _payload()

    def run():
        death = intake_svc.set_visit(current_user, death_id, next_visit_at=p.get("next_visit_at"))
        db.session.commit()
        return jsonify({"case": _visit_ack(death)})

    return _handle(run)


@intake.post("/api/cases/<death_id>/attempts")
@role_required("interviewer")
def api_log_contact_attempt(death_id):
    """Log a contact attempt. Body: ``outcome``, optional ``next_visit_at``."""
    p = _payload()

    def run():
        death = intake_svc.log_contact_attempt(
            current_user, death_id, outcome=str(p.get("outcome") or ""),
            next_visit_at=p.get("next_visit_at"),
        )
        db.session.commit()
        return jsonify({"case": _visit_ack(death)}), 201

    return _handle(run)


@intake.post("/api/cases/<death_id>/pause")
@role_required("interviewer")
def api_pause_interview(death_id):
    """Pause an in-progress interview. Body: ``reason`` (a code), optional
    ``next_visit_at``. Resume is ``POST /api/drafts`` with the case."""
    p = _payload()

    def run():
        death = intake_svc.pause_interview(
            current_user, death_id, reason=str(p.get("reason") or ""),
            next_visit_at=p.get("next_visit_at"),
        )
        db.session.commit()
        return jsonify({"case": _visit_ack(death)})

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
            actor=current_user,
        )
        db.session.commit()
        return jsonify({"saved_sections": written, "draft": intake_svc.serialize_draft(draft)})

    return _handle(run)


@intake.post("/api/drafts/<draft_id>/discard")
@role_required("interviewer")
def api_discard_draft(draft_id):
    def run():
        draft = intake_svc.get_draft(current_user, draft_id, for_update=True)
        intake_svc.discard_draft(draft, current_user)
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


# ---------------------------------------------------------------------------
# Supervisor API (digitva-vzk.5). Kept at the end of the module on purpose.
#
# An interview_supervisor unit grant or a data_manager grant opens the gate;
# which cases the caller supervises is decided per case by
# case_transition_service.is_interview_supervisor_for, and a case outside
# that reach reads as 404. POSTs are CSRF-checked by the global CSRFProtect.
# ---------------------------------------------------------------------------

from app.services import case_transition_service as case_svc  # noqa: E402


def _reason(p):
    return p.get("reason") if isinstance(p.get("reason"), str) else None


@intake.get("/api/supervision/cases")
@role_required("interview_supervisor", "data_manager")
def api_supervised_cases():
    """All cases in the caller's supervisor scope, with who registered and
    started each. Query: ``state``, ``flagged``, ``limit``, ``cursor``."""
    flagged_raw = (request.args.get("flagged") or "").lower()
    if flagged_raw not in _TRUE + _FALSE:
        return _json_error("flagged must be true or false.", 400)
    states = [s for s in (request.args.get("state") or "").split(",") if s]
    try:
        limit = int(request.args.get("limit") or intake_svc.WORKLIST_PAGE_DEFAULT)
    except ValueError:
        return _json_error("limit must be a whole number.", 400)

    def run():
        result = intake_svc.list_supervised_cases(
            current_user,
            states=states,
            flagged=flagged_raw in _TRUE,
            cursor=request.args.get("cursor") or None,
            limit=limit,
        )
        return jsonify(
            {
                "cases": [intake_svc.serialize_supervised_row(current_user, *row) for row in result["cases"]],
                "counts": result["counts"],
                "next_cursor": result["next_cursor"],
            }
        )

    return _handle(run)


@intake.post("/api/supervision/cases/<death_id>/resolve-flag")
@role_required("interview_supervisor", "data_manager")
def api_supervisor_resolve_flag(death_id):
    """Confirm or reject the case's pending flag. Body: ``confirm`` (bool), ``reason``."""
    p = _payload()
    if not isinstance(p.get("confirm"), bool):
        return _json_error("confirm must be true or false.", 400)

    def run():
        death = intake_svc.get_supervised_case(current_user, death_id)
        case_svc.resolve_flag(death, actor=current_user, confirm=p["confirm"], reason=_reason(p))
        db.session.commit()
        return jsonify({"death": _supervisor_ack(death)})

    return _handle(run)


@intake.post("/api/supervision/cases/<death_id>/cancel")
@role_required("interview_supervisor", "data_manager")
def api_supervisor_cancel(death_id):
    """Cancel a case outright (details pending, registered, scheduled, in progress or
    paused). Body: ``reason``."""
    p = _payload()

    def run():
        death = intake_svc.get_supervised_case(current_user, death_id)
        reason = _reason(p)
        if not (reason or "").strip():
            raise intake_svc.WebIntakeError("Give a reason for cancelling.")
        case_svc.transition(death, "cancelled", actor=current_user, action="supervisor_cancel", reason=reason)
        db.session.commit()
        return jsonify({"death": _supervisor_ack(death)})

    return _handle(run)


@intake.post("/api/supervision/cases/<death_id>/reopen")
@role_required("interview_supervisor", "data_manager")
def api_supervisor_reopen(death_id):
    """Reopen a submitted, duplicate or cancelled case to its earlier state. Body: ``reason``."""
    p = _payload()

    def run():
        death = intake_svc.get_supervised_case(current_user, death_id)
        case_svc.reopen(death, actor=current_user, reason=_reason(p))
        db.session.commit()
        return jsonify({"death": _supervisor_ack(death)})

    return _handle(run)


@intake.post("/api/supervision/cases/<death_id>/duplicate")
@role_required("interview_supervisor", "data_manager")
def api_supervisor_mark_duplicate(death_id):
    """Mark a case as a duplicate of another supervised case of the same
    project; confirmed at once unless the data-manager rule holds it as a
    pending flag. Needs no interviewer grant. Body: ``duplicate_of``, ``reason``."""
    p = _payload()

    def run():
        death = intake_svc.get_supervised_case(current_user, death_id)
        if not p.get("duplicate_of"):
            raise intake_svc.WebIntakeError("Name the case this one duplicates.")
        kept = intake_svc.get_supervised_case(current_user, p["duplicate_of"])
        case_svc.flag_case(death, actor=current_user, kind="duplicate", reason=_reason(p), duplicate_of=kept)
        db.session.commit()
        return jsonify({"death": _supervisor_ack(death)})

    return _handle(run)


def _supervisor_ack(death):
    """What a supervisor action returns: the case's new state, no identifiers.

    The supervisor list already shows the case; echoing serialize_death here
    would hand back informant phone, address and ABHA the client never needs.
    """
    return {
        "death_id": str(death.death_id),
        "unique_id": death.unique_id,
        "status": death.status,
        "pending_flag": death.pending_flag,
    }
