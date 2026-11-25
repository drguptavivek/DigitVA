"""Supervision (digitva-vzk.5). Part of the intake API package (``__init__``)."""

from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.intake._common import _pkg, bp
from app.routes.api.request_helpers import (
    error,
    parse_body,
)
from app.services import case_transition_service as case_svc
from app.services import consent_withdrawal_service as withdrawal_svc
from app.services import death_identifier_service as identifiers_svc
from app.services import intake_revision_access as revision_access
from app.services import interview_send_back_service as send_back_svc
from app.services import register_pii_accessor, training_scope
from app.services import web_intake_service as intake_svc
from app.services.visit_note import visit_note_for_viewer

# ---------------------------------------------------------------------------
# Supervision (digitva-vzk.5)
#
# The interview_supervisor or data_manager gate opens through
# authz.effective_roles, so an In-charge (site_pi at a unit) and a project_pi
# on a tree project pass it too; which cases the caller supervises is decided
# per case by case_transition_service.is_interview_supervisor_for, and a case
# outside that reach reads as 404.
# ---------------------------------------------------------------------------

_TRUE, _FALSE = intake_svc._TRUE, intake_svc._FALSE


def _reason(p):
    return p.get("reason") if isinstance(p.get("reason"), str) else None


def _supervised_body(*row) -> dict:
    """A supervisor row with its ``identifiers`` (one case: ``identifier_payloads``)."""
    body = intake_svc.serialize_supervised_row(current_user, *row)
    body.update(intake_svc.supervised_row_facts(current_user, [row[0]])[row[0].death_id])
    body["identifiers"] = identifiers_svc.identifier_payloads(current_user, [row[0]])[row[0].death_id]
    body["can_edit_identifiers"] = intake_svc.can_edit_identifiers(current_user, [row[0]])[row[0].death_id]
    body["can_record_consent_withdrawal"] = withdrawal_svc.can_record(current_user, row[0])
    # The withdrawal's details (who asked: person text) only on the sealed,
    # admin-only case; a data manager never reaches a withdrawn case here.
    if row[0].consent_withdrawn_at is not None:
        body["consent_withdrawal"] = withdrawal_svc.serialize(withdrawal_svc.active_withdrawal(row[0]))
    return body


def _supervisor_reply(death):
    """What a supervisor action returns: ``{"case": <supervisor row>}``, the
    shape of ``GET /supervision/cases`` (no informant contact details, no
    prefill): a supervisor need not hold an interviewer grant, so the
    interviewer's case detail is not theirs to read."""
    return jsonify({"case": _pkg()._supervised_body(*intake_svc.supervised_case_row(death))})


def _supervised_rows(rows) -> list[dict]:
    """The supervision list's rows, the page's ``identifiers`` loaded once."""
    identifiers = identifiers_svc.identifier_payloads(current_user, [row[0] for row in rows])
    editable = intake_svc.can_edit_identifiers(current_user, [row[0] for row in rows])
    recordable = withdrawal_svc.recordable_ids(current_user, [row[0].death_id for row in rows])
    # Names open only where the caller sees PII (``serialize_supervised_row``).
    pii = _pkg().pii_scope(current_user)
    names = register_pii_accessor.open_register_pii(
        [row[0] for row in rows if pii.sees(row[0].project_id)], only=intake_svc.SUPERVISED_ROW_PII
    )
    facts = intake_svc.supervised_row_facts(current_user, [row[0] for row in rows])
    return [dict(intake_svc.serialize_supervised_row(current_user, *row, register=names.get(row[0].death_id)),
                 **facts[row[0].death_id],
                 identifiers=identifiers[row[0].death_id],
                 can_edit_identifiers=editable[row[0].death_id],
                 can_record_consent_withdrawal=row[0].death_id in recordable)
            for row in rows]


@bp.get("/supervision/cases")
@role_required("interview_supervisor", "data_manager")
def supervised_cases():
    """All cases in the caller's supervisor scope, with who registered and
    started each. Query: ``state``, ``flagged``, ``candidates`` (only cases
    with a second complete interview to choose), ``visit_note`` (only cases
    with a visit note), ``needs_decision`` / ``overdue`` / ``stuck`` (the
    attention tiles), ``sort`` (``newest`` default, or ``oldest``), ``limit``,
    ``cursor``. The reply's ``tiles`` count the whole scope, filters ignored."""
    training_scope.resolve("interview")
    flagged_raw = (request.args.get("flagged") or "").lower()
    if flagged_raw not in _TRUE + _FALSE:
        return error("flagged must be true or false.", "invalid_request", 400)
    candidates_raw = (request.args.get("candidates") or "").lower()
    if candidates_raw not in _TRUE + _FALSE:
        return error("candidates must be true or false.", "invalid_request", 400)
    visit_note_raw = (request.args.get("visit_note") or "").lower()
    if visit_note_raw not in _TRUE + _FALSE:
        return error("visit_note must be true or false.", "invalid_request", 400)
    attention = {}
    for name in ("needs_decision", "overdue", "stuck"):
        raw = (request.args.get(name) or "").lower()
        if raw not in _TRUE + _FALSE:
            return error(f"{name} must be true or false.", "invalid_request", 400)
        attention[name] = raw in _TRUE
    sort = request.args.get("sort") or "newest"
    if sort not in intake_svc.SUPERVISION_SORTS:
        return error("sort must be newest or oldest.", "invalid_request", 400)
    states = [s for s in (request.args.get("state") or "").split(",") if s]
    try:
        limit = int(request.args.get("limit") or intake_svc.WORKLIST_PAGE_DEFAULT)
    except ValueError:
        return error("limit must be a whole number.", "invalid_request", 400)
    result = intake_svc.list_supervised_cases(
        current_user,
        states=states,
        flagged=flagged_raw in _TRUE,
        candidates=candidates_raw in _TRUE,
        visit_note=visit_note_raw in _TRUE,
        **attention,
        sort=sort,
        cursor=request.args.get("cursor") or None,
        limit=limit,
    )
    return jsonify(
        {
            "cases": _supervised_rows(result["cases"]),
            "counts": result["counts"],
            "tiles": result["tiles"],
            "next_cursor": result["next_cursor"],
        }
    )


@bp.get("/supervision/cases/<death_id>")
@role_required("interview_supervisor", "data_manager", "admin")
def supervised_case_detail(death_id):
    """One supervised case (the list's row) with its ``candidates``: the other
    complete interviews a supervisor may choose, each ``{draft_id,
    interviewer_name, completed_at, outcome}``. Interviewers never see these
    names. ``visit_note``: the case's visit note as the viewer may see it
    (``visit_note_for_viewer``), or null. ``edit_interview``:
    ``{draft_id, va_sid, project_id, site_id}`` when the caller may correct
    the interview now (``revision_access.supervisor_edit_target``), else null; list rows and
    action replies do not carry it. 404 outside the caller's reach."""
    training_scope.resolve("interview")
    death = intake_svc.get_supervised_case(current_user, death_id)
    withdrawal_svc.record_admin_view(current_user, death)
    redact_pii = _pkg().should_redact_pii(current_user, project_id=death.project_id)
    note = _pkg().visit_notes_for([death.va_sid] if death.va_sid else [], redact_pii=redact_pii).get(death.va_sid)
    reply = {
        "case": _pkg()._supervised_body(*intake_svc.supervised_case_row(death)),
        "edit_interview": revision_access.supervisor_edit_target(current_user, death),
        "candidates": intake_svc.list_candidates(death, redact_names=redact_pii),
        "visit_note": visit_note_for_viewer(note, redact_pii=redact_pii),
    }
    db.session.commit()  # the admin view's audit row, if any
    return jsonify(reply)


# The only keys a supervisor's duplicate candidate carries: no informant name,
# village or phone (docs/policy/web-intake.md, "Supervisors").
_SUPERVISOR_DUPLICATE_KEYS = (
    "death_id", "unique_id", "unit_name", "state", "score",
    "deceased_name", "date_of_death", "age_years", "sex",
)


@bp.get("/supervision/cases/<death_id>/possible-duplicates")
@role_required("interview_supervisor", "data_manager", "admin")
def supervised_possible_duplicates(death_id):
    """Cases in the caller's supervision reach that may be the same death as
    this one (a warning; never blocks, never merges). Only supervisor-row
    fields. 404 outside the caller's reach."""
    training_scope.resolve("interview")
    death = intake_svc.get_supervised_case(current_user, death_id)
    rows = intake_svc.possible_duplicates(
        current_user, death, scope=case_svc.supervised_case_condition(current_user)
    )
    # Candidates share the subject's project (register_duplicate_service), so
    # one per-project PII check covers every row (web-intake.md item 14).
    named = _pkg().pii_scope(current_user).sees(death.project_id)
    return jsonify({
        "possible_duplicates": [
            {k: (row[k] if named or k != "deceased_name" else None) for k in _SUPERVISOR_DUPLICATE_KEYS}
            for row in rows
        ],
    })


@bp.post("/supervision/cases/<death_id>/choose-interview")
@role_required("interview_supervisor", "data_manager", "admin")
def choose_interview(death_id):
    """Choose another interviewer's complete interview of a submitted case
    over the one it holds (docs/policy/web-intake.md, "Parallel interviews").
    Body: ``draft_id`` (a candidate from the case detail), ``reason_code``
    (``better_quality``, ``more_complete``, ``original_incorrect``,
    ``switch_back``). Coding restarts, the earlier COD stays as history; the
    other interview stays a candidate. 200 ``{"case": <supervisor row>}``; 404
    outside the caller's reach; 409 ``case_not_submitted`` / ``not_a_candidate``
    / ``form_mismatch`` / ``wrong_state`` (a reviewer session is live); 422
    ``invalid_reason``."""
    p = parse_body()
    death = intake_svc.choose_interview(current_user, death_id, p.get("draft_id"), p.get("reason_code"))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/resolve-flag")
@role_required("interview_supervisor", "data_manager")
def resolve_flag(death_id):
    """Confirm or reject the case's pending flag. Body: ``confirm`` (bool), ``reason``."""
    p = parse_body()
    if not isinstance(p.get("confirm"), bool):
        return error("confirm must be true or false.", "invalid_request", 400)
    death = intake_svc.get_supervised_case(current_user, death_id)
    case_svc.resolve_flag(death, actor=current_user, confirm=p["confirm"], reason=_reason(p))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/cancel")
@role_required("interview_supervisor", "data_manager")
def cancel_case(death_id):
    """Cancel a case outright (details pending, registered, scheduled, in
    progress or paused). Body: ``reason``."""
    p = parse_body()
    death = intake_svc.get_supervised_case(current_user, death_id)
    reason = _reason(p)
    if not (reason or "").strip():
        raise intake_svc.WebIntakeError("Give a reason for cancelling.")
    case_svc.transition(death, "cancelled", actor=current_user, action="supervisor_cancel", reason=reason)
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/reopen")
@role_required("interview_supervisor", "data_manager")
def reopen_case(death_id):
    """Reopen a submitted, duplicate or cancelled case to its earlier state. Body: ``reason``."""
    p = parse_body()
    death = intake_svc.get_supervised_case(current_user, death_id)
    case_svc.reopen(death, actor=current_user, reason=_reason(p))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/duplicate")
@role_required("interview_supervisor", "data_manager")
def mark_duplicate(death_id):
    """Mark a case as a duplicate of another supervised case of the same
    project; confirmed at once unless the data-manager rule holds it as a
    pending flag. Needs no interviewer grant. Body: ``duplicate_of``, ``reason``."""
    p = parse_body()
    death = intake_svc.get_supervised_case(current_user, death_id)
    if not p.get("duplicate_of"):
        raise intake_svc.WebIntakeError("Name the case this one duplicates.")
    kept = intake_svc.get_supervised_case(current_user, p["duplicate_of"])
    case_svc.flag_case(death, actor=current_user, kind="duplicate", reason=_reason(p), duplicate_of=kept)
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/consent-withdrawal")
@role_required("data_manager", "site_pi", "project_pi", "admin")
def record_consent_withdrawal(death_id):
    """Record a respondent's consent withdrawal on a submitted case
    (docs/policy/consent-withdrawal.md). An admin, or a data manager,
    In-charge or project PI whose grant covers the case (404 otherwise).
    Body: ``requested_by`` (<=200), ``requested_on`` (YYYY-MM-DD, not
    future), ``channel`` (contact_form, phone, in_person, email, other),
    optional ``contact_reference`` (<=100) and ``note`` (<=2000). The case
    then leaves every coding, review, count and export path, and is sealed
    (admin only); an active allocation is released. 200 ``{"case": row}``
    for an admin, ``{"consent_withdrawn": true}`` otherwise (the case is no
    longer theirs to read); 409 not submitted or already withdrawn; 422
    ``invalid_request``."""
    death = withdrawal_svc.get_case(current_user, death_id)
    withdrawal_svc.record(current_user, death, parse_body())
    db.session.commit()
    if not current_user.is_admin():
        return jsonify({"consent_withdrawn": True})
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/consent-withdrawal/undo")
@role_required("admin")
def undo_consent_withdrawal(death_id):
    """Admin only: undo a mistaken consent withdrawal. Body: ``reason``
    (required, <=200). The case comes back everywhere. 409 when none is
    recorded."""
    death = withdrawal_svc.get_case(current_user, death_id)
    withdrawal_svc.undo(current_user, death, parse_body().get("reason"))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/submissions/<va_sid>/reopen-for-revision")
@role_required("interview_supervisor", "data_manager", "admin")
def reopen_for_revision(va_sid):
    """Reopen a finalised web or device interview for its interviewer to
    revise (docs/policy/interview-revisions.md, rule 4). Body: ``reason_code``
    (``cod_review_requested``, ``new_information``, ``data_correction``). 200
    ``{va_sid, workflow_state, reason_code}``; the earlier COD stays until the
    revision arrives. An admin, or a supervisor or data manager whose
    supervision reach covers the interview's case (404 otherwise); 409
    ``not_web_submission`` / ``wrong_state``; 422 ``invalid_reason``."""
    reply = send_back_svc.reopen_for_revision(current_user, va_sid, reason_code=parse_body().get("reason_code"))
    db.session.commit()
    return jsonify(reply)

