"""Cases: the worklist, one case, flags, visits, contact attempts, pause. Part of the intake API package (``__init__``)."""

from flask import jsonify, request, url_for
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.routes.api.intake._common import _client_id, _content_refusals, _pkg, bp
from app.routes.api.request_helpers import (
    idempotent_create,
    interviewer_context,
    parse_body,
    request_project_id,
)
from app.services import death_identifier_service as identifiers_svc
from app.services import intake_revision_access as revision_access
from app.services import training_scope
from app.services import web_intake_service as intake_svc
from app.services.authz.actions import DEATH_REGISTERING_ROLES

# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@bp.get("/cases")
@role_required("interviewer", "death_reporter")
@limiter.limit("120 per minute")
def list_cases():
    """Team cases in the caller's interviewer scope (the worklist), plus the
    deaths a death_reporter registered in their reporter reach:
    ``web_intake_service.worklist_page``. Query: ``project_id`` (optional
    filter), ``mine``, ``state``, ``limit``, ``cursor``. The app downloads its
    active cases with ``state=`` and then each case's detail."""
    training_scope.resolve("interview")
    # A reporter's own deaths widen the projects it may narrow to; an
    # interviewer alone keeps the interviewer refusal.
    if current_user.is_death_reporter():
        project_id = request_project_id(required=False, roles=DEATH_REGISTERING_ROLES)
    else:
        project_id = request_project_id(required=False)
    return jsonify(intake_svc.worklist_page(current_user, request.args, project_id=project_id, context=interviewer_context()))


def _reporter_only() -> bool:
    """The caller is a death_reporter and no interviewer (an interview
    supervisor or data manager correcting a death keeps the full body)."""
    return current_user.is_death_reporter() and not current_user.is_interviewer()


def _reporter_view(death) -> bool:
    """Whether the reply about *death* is the reporter's registration-only
    shape: the caller holds a death_reporter grant and no interviewer grant
    of theirs reaches this case (so a both-roles user gets the interview's
    prefill and links only where they interview)."""
    return current_user.is_death_reporter() and not intake_svc.interviewer_reaches(current_user, death)


def _case_body(death, unit_name, my_draft_id, other_draft_started_at=None, my_submission=False,
               other_complete_interview=False, ready_for_coding=False, other_draft_started_by=None) -> dict:
    """The case with its full contact details (``serialize_case_detail``), this
    API's links, and the ``prefill`` an interview started offline needs, only
    when the caller may start or resume the interview (``case_prefill``);
    otherwise the key is absent."""
    body = intake_svc.serialize_case_detail(
        current_user, death, unit_name, my_draft_id, other_draft_started_at, my_submission,
        other_complete_interview, ready_for_coding, other_draft_started_by,
    )
    # Registration numbers: values for a viewer who may see them, else a badge.
    body["identifiers"] = identifiers_svc.identifier_payloads(current_user, [death])[death.death_id]
    body["can_edit_identifiers"] = intake_svc.can_edit_identifiers(current_user, [death])[death.death_id]
    if not intake_svc.interviewer_reaches(current_user, death):
        # A death_reporter (or supervisor without interviewer reach) registers
        # and corrects; the interview, contact attempts and visit are not
        # theirs, so no prefill, no link to a route that answers 403, and
        # nothing about other interviewers' drafts (digitva-t6q).
        for key in ("other_draft_active", "other_draft_started_at", "other_draft_started_by"):
            body.pop(key, None)
        body["links"] = {"update": url_for(".update_death", death_id=death.death_id)}
        return body
    prefill = intake_svc.case_prefill(current_user, death, my_draft_id)
    if prefill is not None:
        body["prefill"] = prefill
    links = {
        "self": url_for(".case_detail", death_id=death.death_id),
        "attempts": url_for(".log_attempt", death_id=death.death_id),
        "visit": url_for(".set_visit", death_id=death.death_id),
        "start_interview": url_for(".start_draft"),
    }
    if my_draft_id:
        links["form"] = url_for("intake.form_page", draft_id=my_draft_id)
    # The submitted interview: read-only view (GET /va/<sid>/workspace?mode=view)
    # and the submitter's correction (POST links.revise with a reason_code).
    body.update(intake_svc.case_submission_view(current_user, death, my_submission))
    if body["can_revise"]:
        links["revise"] = url_for(".revise_submission", va_sid=death.va_sid)
    body["links"] = links
    return body


def _case_reply(death, status=200, warnings=None):
    """The one reply of every single-case action: ``{"case": <detail>}``, plus
    ``warnings`` (identifier duplicate warnings) when there are any."""
    body = {"case": _case_body(*intake_svc.case_row(current_user, death))}
    if warnings:
        body["warnings"] = warnings
    return jsonify(body), status


def _identifier_reply(death, warnings):
    """The reply of a registration-number write. A caller whose interviewer or
    reporter reach opens the case keeps ``_case_reply``'s detail; one who
    reaches it only by supervision (a supervisor, In-charge, project PI, data
    manager) or as admin gets the supervisor row (``_supervisor_reply``: no
    informant name, phones or address, no links, no prefill) with its
    ``identifiers``, ``can_edit_identifiers`` and ``updated_at``."""
    if intake_svc.interviewer_reaches(current_user, death) or intake_svc.reporter_reaches(current_user, death):
        return _case_reply(death, warnings=warnings)
    body = {"case": _pkg()._supervised_body(*intake_svc.supervised_case_row(death))}
    if warnings:
        body["warnings"] = warnings
    return jsonify(body), 200


@bp.get("/cases/<death_id>")
# A supervisor or data manager opens the death-report edit form here (the
# roles update_death takes, but the reporter, who has its own list).
@role_required("interviewer", "interview_supervisor", "data_manager")
# A device downloads its active cases one detail call each after the list, so
# the budget covers a large worklist; each call is one indexed case read
# (digitva-p6fs.33).
@limiter.limit("600 per minute")
def case_detail(death_id):
    """One case with its full contact details (and prefill, when the caller may
    start or resume it), visible exactly as
    the worklist would list it (any project of the caller's, any state);
    otherwise 404. Starting or resuming the interview is
    ``POST links.start_interview`` with the case's project, site and id.
    A supervisor of the case who sees personal data in its project
    (``get_case_for_supervisor``) gets the same detail without the
    interview's prefill and links, to correct the death report
    (``PATCH /deaths/<id>``)."""
    training_scope.resolve("interview")
    row = revision_access.case_row_reachable_by(current_user, death_id, context=interviewer_context())
    return jsonify({"case": _case_body(*row)})


@bp.get("/cases/<death_id>/possible-duplicates")
@role_required("interviewer")
def possible_duplicates(death_id):
    """Cases in the caller's reach that may be the same death (a warning;
    never blocks submit, never merges). Out-of-scope ids read as 404."""
    training_scope.resolve("interview")
    death = intake_svc.get_death(current_user, death_id)
    return jsonify({"possible_duplicates": intake_svc.possible_duplicates(current_user, death)})


@bp.post("/cases/<death_id>/flags")
@role_required("interviewer")
def flag_case(death_id):
    """Flag a case as a possible duplicate or for cancellation (a supervisor
    confirms or rejects it). Body: ``kind``, ``reason``, ``duplicate_of``."""
    p = parse_body()
    death = intake_svc.flag_death(
        current_user,
        death_id,
        kind=str(p.get("kind") or ""),
        reason=p.get("reason") if isinstance(p.get("reason"), str) else None,
        duplicate_of=p.get("duplicate_of") or None,
    )
    db.session.commit()
    return _case_reply(death)


@bp.post("/cases/<death_id>/visit")
@role_required("interviewer")
def set_visit(death_id):
    """Set (or clear, with ``null``) the case's next visit. Idempotent by
    value, so no client id: a resend sets the same date. Body:
    ``next_visit_at`` (ISO date-time with timezone)."""
    p = parse_body()
    with _content_refusals("invalid_visit"):
        death = intake_svc.set_visit(current_user, death_id, next_visit_at=p.get("next_visit_at"))
    db.session.commit()
    return _case_reply(death)


@bp.post("/cases/<death_id>/attempts")
@role_required("interviewer")
def log_attempt(death_id):
    """Log a contact attempt. Body: ``outcome``, optional ``next_visit_at``,
    optional ``client_attempt_id`` (UUID): an offline attempt is idempotent on
    it, a resend returns the case with 200 and logs nothing."""
    p = parse_body()
    client_attempt_id = _client_id(p, "client_attempt_id")
    if client_attempt_id is not None:
        existing = intake_svc.find_device_attempt(current_user, death_id, client_attempt_id)
        if existing is not None:
            return _case_reply(existing)
    def create():
        with _content_refusals("invalid_attempt"):
            death = intake_svc.log_contact_attempt(
                current_user, death_id, outcome=str(p.get("outcome") or ""),
                next_visit_at=p.get("next_visit_at"), client_attempt_id=client_attempt_id,
            )
        db.session.commit()
        return death

    # A concurrent resend of the same client_attempt_id wins the unique index.
    death, created = idempotent_create(
        create,
        lambda: intake_svc.find_device_attempt(current_user, death_id, client_attempt_id) if client_attempt_id else None,
    )
    return _case_reply(death, 201) if created else _case_reply(death)


@bp.post("/cases/<death_id>/pause")
@role_required("interviewer")
def pause_interview(death_id):
    """Pause an in-progress interview. Body: ``reason`` (a code), optional
    ``next_visit_at``. Resume is ``POST /drafts`` with the case."""
    p = parse_body()
    death = intake_svc.pause_interview(
        current_user, death_id, reason=str(p.get("reason") or ""), next_visit_at=p.get("next_visit_at"),
    )
    db.session.commit()
    return _case_reply(death)

