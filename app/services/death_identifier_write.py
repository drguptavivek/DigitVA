"""The any-time registration-number write (``PUT /api/v1/intake/cases/<id>/identifiers``).

Policy: docs/policy/death-registration-identifiers.md, decisions 11 and 12 and
"Authorization". Not gated on interview completion (``update_death`` is), and
the case state does not change: the value work and its one ``identifiers_set``
audit row are ``death_identifier_service.set_identifiers``. This module only
decides, per request and per case, whether the caller may write
(``web_intake_service.identifier_write_status``; the id in the request is a
claim, not permission) and whether the write is stale.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister, VaUsers, VaWebIntakeDraft, VaWebIntakeDraftSection
from app.services import case_list_service
from app.services import case_transition_service as cases
from app.services import death_identifier_service as death_identifiers
from app.services import web_intake_service as intake

WebIntakeError = cases.WebIntakeError


def _authorise(user: VaUsers, death: VaDeathRegister) -> None:
    """Return when *user* may write *death*'s numbers now; else 404 when the
    case is outside the caller's reach, 409 ``case_closed`` when only the
    case being cancelled or a confirmed duplicate stops them, else 403."""
    status = intake.identifier_write_status(user, death)
    if status == "ok":
        return
    if not case_list_service.case_in_scope(user, death.death_id):
        raise WebIntakeError("Case not found.", 404)
    if status == "closed":
        raise WebIntakeError(intake.CASE_CLOSED_MESSAGE, 409, "case_closed")
    raise WebIntakeError(intake.IDENTIFIER_FORBIDDEN_MESSAGE, 403)


def put_identifiers(user: VaUsers, death_id: object, values: dict, *, if_updated_at: object | None = None,
                    warnings: list | None = None, station_roster: bool = False) -> VaDeathRegister:
    """Set, change or clear the listed identifier values of a case, in the
    caller's transaction (the route commits). *values* is ``{type code: text
    | None}``. *if_updated_at* (``updated_at`` of the last reply seen) guards a
    concurrent edit: a different one is 409 ``death_stale`` (400 if malformed).
    ``identifier_in_use`` warnings are appended to *warnings*. Raises
    ``WebIntakeError``: 404 / 403 / 409 ``case_closed`` as ``_authorise``,
    400 ``fields`` ``identifiers.<code>`` for a value the type's rules
    refuse. Authorised before and after the case lock, because the state may
    have moved while the request waited for it.

    *station_roster*: a station supervisor's ``identifiers_set`` from a
    bundle; the caller authorized *user* from the station's signed roster
    (offline-api-contract.md 4.1, 4.2), so ``_authorise`` is replaced by one
    rule: a cancelled or confirmed-duplicate case is 409 ``case_closed``.
    """
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if death is None:
        raise WebIntakeError("Case not found.", 404)
    if not station_roster:
        _authorise(user, death)
    death = cases.lock_case(death)
    if station_roster:
        if death.status in intake.IDENTIFIER_CLOSED_STATES:
            raise WebIntakeError("This case is closed; correct it on the web.", 409, "case_closed")
    else:
        _authorise(user, death)
    if isinstance(values, dict) and any(value not in (None, "") for value in values.values()):
        refused_draft = db.session.scalar(sa.select(sa.exists().where(
            VaWebIntakeDraft.death_id == death.death_id,
            VaWebIntakeDraft.status == "draft",
            sa.or_(
                VaWebIntakeDraft.meta["refusalResumePending"].astext == "true",
                sa.exists().where(
                    VaWebIntakeDraftSection.draft_id == VaWebIntakeDraft.draft_id,
                    sa.func.lower(VaWebIntakeDraftSection.data["Id10013"].astext) == "no",
                ),
            ),
        )))
        if death.status == "refused" or refused_draft:
            raise WebIntakeError("Consent was refused; do not add identifiers.", 422, "consent_refused")
    if if_updated_at is not None and intake.draft_is_stale(death, if_updated_at):
        raise WebIntakeError("This case was changed since you opened it; reload it.", 409, "death_stale")
    _, found = death_identifiers.set_identifiers(
        death, user, values, reason_context="update", enforce_required=False)
    if warnings is not None:
        warnings.extend(found)
    db.session.flush()
    return death
