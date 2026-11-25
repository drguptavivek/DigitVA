"""Registration: identifier types, consent settings, the death register and
the identity-free refusal receipt. Part of the intake API package (``__init__``)."""

from flask import g, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.decorators import role_required
from app.routes.api.intake._common import (
    _REGISTER_FIELDS,
    _carries_identifiers,
    _client_id,
    _consent_channel,
    _content_refusals,
    _identifiers_arg,
    _site_id,
    bp,
)
from app.routes.api.intake.cases import _case_reply, _identifier_reply, _reporter_only
from app.routes.api.request_helpers import (
    error,
    idempotent_create,
    identifier_rate_limit,
    parse_body,
    request_project_id,
    require_project,
)
from app.services import consent_service as consent_svc
from app.services import death_identifier_service as identifiers_svc
from app.services import death_identifier_write as identifier_write_svc
from app.services import device_auth_service as devices
from app.services import identifier_type_service as identifier_types_svc
from app.services import register_pii_accessor, training_scope
from app.services import registration_refusal_service as service
from app.services import web_intake_service as intake_svc
from app.services.authz import resolve_grants
from app.services.authz.actions import DEATH_REGISTERING_ROLES

# ---------------------------------------------------------------------------
# Registration identifier types
# ---------------------------------------------------------------------------


def _reference_project():
    """The ``project_id`` query argument of a project reference read
    (identifier types, consent settings) and whether the caller may read it:
    ``(project_id, None)`` or ``(None, reply)``. Allowed where the caller may
    register a death or supervise (``supervises_project``), and for an admin
    in any project; in the training area, the training project only. A
    missing id is 400 ``invalid_request``; anything else refused is 403
    ``project_forbidden`` (``require_project``), alike whether the project
    exists or not."""
    training_scope.resolve("interview")
    project_id = identifier_types_svc.normalise_project_id(request.args.get("project_id"))
    if not project_id:
        raise devices.DeviceAuthError("project_id is required.", "invalid_request", 400)
    if not training_scope.keeps_project(project_id):
        return None, error("This project is not available in this area.", "project_forbidden", 403)
    if training_scope.current() == training_scope.ONLY:
        from app.services.training_demo_service import may_use_area

        if project_id != training_scope.training_project_id() or not may_use_area(current_user.user_id, "interview"):
            return None, error("This project is not available in this area.", "project_forbidden", 403)
    elif not (resolve_grants(current_user).is_admin
              or identifier_types_svc.supervises_project(current_user, project_id)):
        require_project(project_id, DEATH_REGISTERING_ROLES)
    return project_id, None


@bp.get("/identifier-types")
@role_required("admin", "interviewer", "interview_supervisor", "data_manager", "death_reporter")
@limiter.limit("120 per minute")
def identifier_types():
    """The active registration identifier types of one project, for the entry
    fields and the offline cache. Query: ``project_id`` (required). Allowed
    where the caller may register a death (``register_death_context``) or
    supervise (an In-charge and a tree project's PI pass the supervisor gate
    through their effective roles), and for an admin in any project; anything
    else is 403 ``project_forbidden``, alike whether the project exists or
    not. Either credential."""
    project_id, refusal = _reference_project()
    if refusal is not None:
        return refusal
    return jsonify({
        "project_id": project_id,
        "identifier_types": [
            identifier_types_svc.serialize_type(t, identifier_types_svc.INTAKE_FIELDS)
            for t in identifier_types_svc.active_types(project_id)
        ],
    })


@bp.get("/consent-config")
@role_required("admin", "interviewer", "interview_supervisor", "data_manager", "death_reporter")
@limiter.limit("120 per minute")
def consent_config():
    """The project's respondent consent settings and current notice versions
    (docs/policy/offline-api-contract.md 5.2). Query: ``project_id``
    (required). Who: as ``identifier_types``; anything else is 403
    ``project_forbidden``. A project without consent settings answers
    ``consent_required: false`` and no notice versions. Either credential."""
    project_id, refusal = _reference_project()
    if refusal is not None:
        return refusal
    return jsonify(consent_svc.get_consent_config(project_id))


# ---------------------------------------------------------------------------
# Death register
# ---------------------------------------------------------------------------


@bp.get("/deaths")
@role_required("interviewer", "death_reporter")
def list_deaths():
    """The death register of one project-site (an interviewer: ``project_id``
    and ``site_id`` required), or, for a death_reporter without interviewer
    rights, the deaths they registered across their reach: optional
    ``project_id``, ``site_id``, ``limit``, ``cursor``; replies ``{"deaths",
    "next_cursor"}`` (``web_intake_service.reported_deaths_page``). A user who
    holds both roles gets that list with ``registered=mine`` or without
    ``project_id``/``site_id``. A row's GPS
    fix follows ``intake_svc.shows_gps``; otherwise its keys are absent."""
    training_scope.resolve("interview")
    registered = request.args.get("registered")
    if registered not in (None, "", "mine"):
        return error("registered must be mine.", "invalid_request", 400)
    project_id = request.args.get("project_id", "")
    site_id = request.args.get("site_id", "")
    # A reporter who also holds an interviewer grant (old APKs send no
    # parameters) gets their own list rather than the register's 400.
    no_register = not project_id or not site_id
    if _reporter_only() or (current_user.is_death_reporter() and (registered == "mine" or no_register)):
        return jsonify(intake_svc.reported_deaths_page(current_user, request.args))
    status = request.args.get("status") or None
    if no_register:
        return error("project_id and site_id are required.", "invalid_request", 400)
    deaths = intake_svc.list_deaths(current_user, project_id=project_id, site_id=site_id, status=status)
    visible = intake_svc.gps_projects(current_user, {project_id}) if deaths else set()
    identifiers = identifiers_svc.identifier_payloads(current_user, deaths)
    editable = intake_svc.can_edit_identifiers(current_user, deaths)
    gps = {d.death_id: intake_svc.shows_gps(current_user, d, visible) for d in deaths}
    # A fix the viewer may not see is never opened (no coordinates decrypted).
    opened = register_pii_accessor.open_register_pii([d for d in deaths if gps[d.death_id]])
    opened |= register_pii_accessor.open_register_pii(
        [d for d in deaths if not gps[d.death_id]], only=intake_svc.without_location())
    return jsonify({"deaths": [
        dict(intake_svc.serialize_death(d, show_gps=gps[d.death_id], register=opened[d.death_id]),
             identifiers=identifiers[d.death_id], can_edit_identifiers=editable[d.death_id])
        for d in deaths
    ]})


@bp.post("/deaths")
@role_required("interviewer", "death_reporter")
@identifier_rate_limit(_carries_identifiers)
def register_death():
    """Register a death (an interviewer or a death_reporter). Body: ``project_id``, ``site_id``, ``org_unit_id`` and
    the register form's fields, optional ``identifiers`` (``{type code: text}``,
    the project's registration numbers; ``required_at_report`` types are
    enforced here), optional ``client_death_id`` (UUID): an offline
    registration is idempotent on it, a resend returns the same case with 200
    (the numbers are stored once and not warned about again). Replies
    ``{"case": <detail>, "warnings": [...]}`` as ``GET /cases/<id>``;
    ``warnings`` only when a number is already on another case. Optional
    ``consent`` (contract 5.3, ``client_draft_id: null``): the informant's
    registration consent, stored with the case in one transaction; where the
    project requires consent, informant fields need a granted one (422
    ``consent_required``; ``consent_conflict`` when refused,
    ``consent_invalid`` for a bad object, 409 ``conflict`` for a reused id)."""
    p = parse_body()
    client_death_id = _client_id(p, "client_death_id")
    site_id = _site_id(p)
    project_id = request_project_id(p, roles=DEATH_REGISTERING_ROLES)
    if isinstance(p.get("consent"), dict) and p["consent"].get("decision") == "refused":
        return error("Consent was refused; record the refusal through an interview draft.", "consent_refused", 422)

    if client_death_id is not None:
        existing = intake_svc.find_device_registration(current_user, project_id, client_death_id)
        if existing is not None:
            return _case_reply(existing)
    warnings = []

    def create():
        with _content_refusals("invalid_registration"):
            if any(isinstance(p.get(k), (dict, list)) for k in _REGISTER_FIELDS):
                raise intake_svc.WebIntakeError("Registration fields must be text or numbers.")
            death = intake_svc.register_death(
                current_user,
                project_id=project_id,
                site_id=site_id,
                org_unit_id=p.get("org_unit_id") or None,
                client_death_id=client_death_id,
                identifiers=_identifiers_arg(p),
                warnings=warnings,
                # A client id is the phone pushing a registration it already
                # made (maybe offline): never refused by the collection gate.
                enforce_collection_gate=client_death_id is None,
                **{k: p.get(k) for k in _REGISTER_FIELDS},
            )
        db.session.flush()
        consent_svc.apply_registration_consent(
            current_user, death, p.get("consent"), fields=p, channel=_consent_channel())
        db.session.commit()
        return death

    # A concurrent resend of the same client_death_id wins the unique index.
    death, created = idempotent_create(
        create,
        lambda: (
            intake_svc.find_device_registration(current_user, project_id, client_death_id)
            if client_death_id else None
        ),
    )
    return _case_reply(death, 201, warnings) if created else _case_reply(death)


@bp.patch("/deaths/<death_id>")
@role_required("interviewer", "interview_supervisor", "data_manager", "death_reporter")
@identifier_rate_limit(_carries_identifiers)
def update_death(death_id):
    """Correct a registered death until an interview of it is completed. Body:
    only the register form's fields to change (an unknown key is 422), optional ``if_updated_at`` (the
    ``updated_at`` of the last reply seen; a newer one is 409 ``death_stale``),
    optional ``identifiers`` (``{type code: text | null}``: only the listed
    numbers change, null or empty clears; may be the only key; without
    ``if_updated_at`` the last write wins). Replies
    ``{"case": <detail>, "warnings": [...]}`` (``warnings`` only when a number
    is already on another case). 404 out of reach; 409 ``case_completed`` /
    ``details_pending``; 409 ``case_closed`` when ``identifiers`` is sent for a
    cancelled or confirmed-duplicate case by anyone but a supervisor (register
    fields of a closed case are unchanged); 422 ``invalid_death`` (a bad
    number names ``identifiers.<code>`` in ``fields``); 429 past the budget
    of requests that carry numbers. Optional ``consent`` (contract 5.3,
    ``client_draft_id: null``): a registration consent stored with the
    change; where the project requires consent, an informant field the patch
    fills needs it granted, or a granted registration consent on file (422
    ``consent_required`` / ``consent_conflict`` / ``consent_invalid``, 409
    ``conflict``; contract 5.5)."""
    p = parse_body()
    # Every other key goes on: the service refuses an unknown field by name.
    changes = {k: v for k, v in p.items() if k not in ("if_updated_at", "identifiers", "consent")}
    warnings = []
    with _content_refusals("invalid_death"):
        if any(isinstance(v, (dict, list)) for v in changes.values()):
            raise intake_svc.WebIntakeError("Fields must be text or numbers.")
        death = intake_svc.update_death(
            current_user, death_id, changes, if_updated_at=p.get("if_updated_at"),
            identifiers=_identifiers_arg(p), warnings=warnings, consent=p.get("consent"),
        )
    consent_svc.apply_registration_consent(
        current_user, death, p.get("consent"), fields=changes, channel=_consent_channel())
    db.session.commit()
    return _identifier_reply(death, warnings)


@bp.put("/cases/<death_id>/identifiers")
@role_required("interviewer", "death_reporter", "interview_supervisor", "data_manager", "admin")
@identifier_rate_limit(_carries_identifiers)
def put_identifiers(death_id):
    """Add, change or clear a case's registration numbers at any time, also
    after its interview is complete (policy decisions 11 and 12). Body:
    ``identifiers`` (``{type code: text | null}``; only the listed codes
    change, null or empty clears; 1..50 codes, each value at most 256
    characters), optional ``if_updated_at`` (the ``updated_at`` of the last
    reply seen). Replies 200 ``{"case": <detail>, "warnings": [...]}``
    (``warnings`` only when a number is already on another case; the detail is
    the trimmed supervisor row for a caller who reaches the case only by
    supervision or as admin, ``_identifier_reply``); the case
    state does not change. Who: admin; a supervisor, In-charge, project PI or
    data manager of the case (on a device, an interview supervisor only); the death_reporter on a death
    they reported; the interviewer on a case they registered or interviewed. Cancelled and
    confirmed-duplicate cases: supervisor, In-charge, project PI and admin
    only. 400 ``invalid_request`` (``fields``: ``identifiers.<code>``);
    403 ``forbidden``; 404 out of reach; 409 ``case_closed`` / ``death_stale``;
    429 past the budget of requests that carry numbers."""
    p = parse_body()
    if set(p) - {"identifiers", "if_updated_at"}:
        return error("Only identifiers and if_updated_at are accepted.", "invalid_request", 400)
    values = _identifiers_arg(p)
    if not values:
        return error("identifiers must name at least one identifier type.", "invalid_request", 400,
                     fields=["identifiers"])
    warnings = []
    death = identifier_write_svc.put_identifiers(
        current_user, death_id, values, if_updated_at=p.get("if_updated_at"), warnings=warnings)
    db.session.commit()
    return _identifier_reply(death, warnings)



# ---------------------------------------------------------------------------
# Registration-only, identity-free refusal receipt
# ---------------------------------------------------------------------------


@bp.post("/refusals")
@role_required("interviewer", "death_reporter")
def registration_refusal():
    body = parse_body()
    project = request_project_id(body, roles=DEATH_REGISTERING_ROLES)
    site = _site_id(body)
    channel = "device" if g.get("device_session") is not None else "web"
    try:
        created = service.record(current_user, body, project, site, channel)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        created = service.record(current_user, body, project, site, channel)
        db.session.commit()
    return jsonify({"client_draft_id": body["client_draft_id"]}), 201 if created else 200
