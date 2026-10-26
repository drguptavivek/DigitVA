"""Registration identifier values: write, duplicate warning, visibility, reads.

Policy: docs/policy/death-registration-identifiers.md ("Validation and error
shape", "Duplicate numbers", "Authorization", "Encryption at rest"). Values
are never stored, logged or audited in plaintext: a write normalises and
validates the plaintext, then stores an AES-256-GCM envelope
(``app/utils/pii_crypto.py``) and a keyed blind index; the case audit row
carries only blind-index traces. Stage 2 writes at registration and correction;
stage 3 reuses ``set_identifiers`` for the any-time write.

The caller owns authorization, the case row lock (``lock_case``) and the
commit. Plaintext exists only in memory, inside a call that has already been
authorised to see or write it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MapDeathIdentifier,
    MasCadre,
    MasDeathIdentifierType,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import case_transition_service as cases
from app.services.authz import resolve_grants
from app.services.death_identifier_rules import IdentifierRuleError, normalise, validate_value
from app.services.duplicate_exclusion import DUPLICATE_CASE_STATUS
from app.services.identifier_type_service import list_types
from app.utils import pii_crypto

log = logging.getLogger(__name__)

WebIntakeError = cases.WebIntakeError

#: Audit action of an identifier write (state unchanged).
ACTION = "identifiers_set"
#: Roles that see values in the project they hold the role in (decision 14).
#: ``admin`` is the global grant and is handled apart. Coder, coding_tester,
#: reviewer and a plain collaborator are badge-only whatever else they hold.
#: ``case_list_service`` derives its per-row SQL from the same set.
IDENTIFIER_VALUE_ROLES = frozenset({
    VaAccessRoles.project_pi,
    VaAccessRoles.site_pi,
    VaAccessRoles.interview_supervisor,
    VaAccessRoles.data_manager,
    VaAccessRoles.interviewer,
    VaAccessRoles.death_reporter,
    VaAccessRoles.collaborator_pii,
})
_CLOSED_STATES = ("cancelled", DUPLICATE_CASE_STATUS)
GENERIC_IN_USE = "This number is already on another case in this project."
#: Request limits, checked on the raw text BEFORE normalisation (which could
#: otherwise be made to chew on a large string): most codes in one write, and
#: the longest raw value (a type's own ``max_length`` is at most 64).
MAX_CODES_PER_REQUEST = 50
MAX_RAW_LENGTH = 256


# ---------------------------------------------------------------------------
# Row helpers: AAD, audit traces
# ---------------------------------------------------------------------------

def aad(death_id: uuid.UUID, identifier_type_id: uuid.UUID) -> bytes:
    """The AAD binding a ciphertext to its row: written by ``set_identifiers``
    and read by ``decrypt_row`` from this one function, so a ciphertext moved
    to another death or another type fails to decrypt."""
    return death_id.bytes + identifier_type_id.bytes


def decrypt_row(row: MapDeathIdentifier) -> str:
    """The plaintext of a stored value; ``PiiCryptoError`` on any failure."""
    return pii_crypto.decrypt_value(
        row.value_ciphertext, row.dek_wrapped, aad(row.death_id, row.identifier_type_id),
        row_ref=str(row.death_identifier_id),
    )


def _trace(blind_index: str) -> dict:
    """The audit trace of a value: the blind index prefix only (no digits)."""
    return {"bidx": blind_index[:16]}


def _old_trace(row: MapDeathIdentifier) -> dict:
    return _trace(row.value_blind_index)


# ---------------------------------------------------------------------------
# Cleaning (normalise and validate the plaintext)
# ---------------------------------------------------------------------------

def _refusal(message: str, codes: list[str]) -> WebIntakeError:
    return WebIntakeError(message, 400, fields=[f"identifiers.{c}" for c in codes])


def check_limits(values) -> None:
    """Refuse an ``identifiers`` object that is not an object, names more than
    ``MAX_CODES_PER_REQUEST`` codes, or holds a raw text longer than
    ``MAX_RAW_LENGTH``, before any value is normalised. ``WebIntakeError``
    (400) naming the field; the message never repeats a value."""
    if not isinstance(values, dict):
        raise WebIntakeError("identifiers must be an object of text values.", fields=["identifiers"])
    if len(values) > MAX_CODES_PER_REQUEST:
        raise WebIntakeError(f"At most {MAX_CODES_PER_REQUEST} identifiers can be sent at once.", fields=["identifiers"])
    too_long = [str(code)[:32] for code, raw in values.items() if isinstance(raw, str) and len(raw) > MAX_RAW_LENGTH]
    if too_long:
        raise _refusal(f"An identifier value is longer than {MAX_RAW_LENGTH} characters.", too_long)


def clean_values(project_id: str, values: dict, *, enforce_required: bool) -> list[tuple[MasDeathIdentifierType, str | None]]:
    """``[(type, normalised value or None), ...]`` for the codes in *values*,
    each validated against the project's active type (policy "Validation").

    ``None`` or an empty string means "no value" (clears on a correction).
    *enforce_required*: every active ``required_at_report`` type must end up
    with a value in *values* (a registration). Raises ``WebIntakeError`` (400)
    whose ``fields`` name every failing ``identifiers.<code>``; the message
    never repeats a submitted value.
    """
    check_limits(values)
    types = {t.code: t for t in list_types(project_id) if t.is_active}
    cleaned: list[tuple[MasDeathIdentifierType, str | None]] = []
    failures: list[tuple[str, str]] = []
    for code, raw in values.items():
        identifier_type = types.get(code) if isinstance(code, str) else None
        if identifier_type is None:
            failures.append((str(code)[:32], "That identifier type is not in use for this project."))
            continue
        try:
            value = normalise(raw)
            if value is not None:
                validate_value(identifier_type, value)
        except IdentifierRuleError as exc:
            failures.append((code, str(exc)))
            continue
        cleaned.append((identifier_type, value))
    if enforce_required:
        given = {t.code for t, value in cleaned if value is not None}
        for identifier_type in types.values():
            if identifier_type.required_at_report and identifier_type.code not in given:
                if identifier_type.code not in {c for c, _ in failures}:
                    failures.append((identifier_type.code, f"{identifier_type.label} is required."))
    if failures:
        raise _refusal(failures[0][1], [c for c, _ in failures])
    return cleaned


# ---------------------------------------------------------------------------
# Duplicate warning
# ---------------------------------------------------------------------------

def _reporter_cadre_name(project_id_column):
    """The reporter's cadre name (one of their live grants carrying a cadre in
    the case's project), as a correlated scalar so it rides the match query."""
    return (
        sa.select(MasCadre.cadre_name)
        .select_from(VaUserAccessGrants)
        .join(MasCadre, MasCadre.cadre_id == VaUserAccessGrants.cadre_id)
        .where(
            VaUserAccessGrants.user_id == VaDeathRegister.registered_by,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_((VaAccessRoles.death_reporter, VaAccessRoles.interviewer)),
            MasCadre.project_id == project_id_column,
        )
        .order_by(VaUserAccessGrants.grant_id)
        .limit(1)
        .scalar_subquery()
    )


def _duplicate_warnings(death: VaDeathRegister, writer: VaUsers, marks: list[tuple[MasDeathIdentifierType, str]]) -> list[dict]:
    """One ``identifier_in_use`` warning per type whose number (blind index)
    is already on another open case of the project. One query; reporter name
    and cadre ride along. Detail only for a case the writer supervises or an
    admin (reporter identity, decision 10). A public-demo writer is matched
    against its own registrations only: another demo user's numbers are not
    even confirmed to exist (docs/policy/public-demo.md section 3)."""
    if not marks:
        return []
    pairs = [(t.identifier_type_id, bidx) for t, bidx in marks if t.uniqueness_scope == "project"]
    if not pairs:
        return []
    in_reach = cases.supervised_case_condition(writer)
    rows = db.session.execute(
        sa.select(
            MapDeathIdentifier.identifier_type_id,
            VaDeathRegister.unique_id,
            sa.func.coalesce(MasOrgUnit.unit_name, VaDeathRegister.site_id).label("unit_name"),
            VaUsers.name.label("reporter_name"),
            sa.func.coalesce(_reporter_cadre_name(VaDeathRegister.project_id), VaUsers.job_title).label("designation"),
            sa.case((in_reach, True), else_=False).label("in_reach"),
        )
        .select_from(MapDeathIdentifier)
        .join(VaDeathRegister, VaDeathRegister.death_id == MapDeathIdentifier.death_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(VaUsers, VaUsers.user_id == VaDeathRegister.registered_by)
        .where(
            sa.tuple_(MapDeathIdentifier.identifier_type_id, MapDeathIdentifier.value_blind_index).in_(pairs),
            VaDeathRegister.project_id == death.project_id,
            VaDeathRegister.death_id != death.death_id,
            VaDeathRegister.status.not_in(_CLOSED_STATES),
            *([VaDeathRegister.registered_by == writer.user_id] if writer.is_public_demo else []),
        )
        # First (earliest entered) match per type.
        .distinct(MapDeathIdentifier.identifier_type_id)
        .order_by(MapDeathIdentifier.identifier_type_id, MapDeathIdentifier.entered_at,
                  MapDeathIdentifier.death_identifier_id)
    ).all()
    if not rows:
        return []
    by_type = {t.identifier_type_id: t for t, _ in marks}
    is_admin = resolve_grants(writer).is_admin
    warnings = []
    for row in rows:
        message = GENERIC_IN_USE
        if is_admin or row.in_reach:
            who = row.reporter_name or "an unknown user"
            if row.designation and row.reporter_name:
                who = f"{who} - {row.designation}"
            message = f"This number is already on case {row.unique_id} (unit {row.unit_name}), reported by {who}."
        warnings.append({
            "code": "identifier_in_use",
            "field": f"identifiers.{by_type[row.identifier_type_id].code}",
            "message": message,
        })
    return sorted(warnings, key=lambda w: w["field"])


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _reason(codes: list[str]) -> str:
    names = ", ".join(codes)
    return names if len(names) <= cases.REASON_MAX else f"{len(codes)} identifiers"


def set_identifiers(death: VaDeathRegister, writer: VaUsers, values: dict, *, reason_context: str,
                    enforce_required: bool) -> tuple[list[str], list[dict]]:
    """Set, change or clear identifier values of *death*, in the caller's
    transaction. Returns ``(changed_codes, warnings)``.

    *values* is ``{type code: text | None}``; only the listed codes are
    touched, ``None`` or empty clears (deletes the row), and a normalised value
    equal to the stored one (compared by blind index) is a no-op. One
    ``identifiers_set`` audit row names the changed codes and, per code, the
    old and new blind-index traces; the supervisor grant and cadre are named as for
    every supervisor action. A clean write that changes nothing writes
    nothing. *reason_context* labels the log line (``registration``,
    ``correction``); it never reaches the audit row. Raises ``WebIntakeError``
    (400, ``fields`` = ``identifiers.<code>``) for a refusal. The caller has
    authorised the write, locked the case and flushed it (it needs a
    ``death_id``).
    """
    cleaned = clean_values(death.project_id, values, enforce_required=enforce_required)
    existing = {
        row.identifier_type_id: row
        for row in db.session.scalars(
            sa.select(MapDeathIdentifier).where(MapDeathIdentifier.death_id == death.death_id)
        )
    }
    now = datetime.now(UTC)
    changes: dict = {}
    marks: list[tuple[MasDeathIdentifierType, str]] = []
    changed: list[str] = []
    for identifier_type, value in cleaned:
        type_id = identifier_type.identifier_type_id
        row = existing.get(type_id)
        if value is None:
            if row is None:
                continue
            changes[f"identifier:{identifier_type.code}"] = {"old": _old_trace(row), "new": None}
            db.session.delete(row)
            changed.append(identifier_type.code)
            continue
        bidx = pii_crypto.blind_index(type_id.bytes, value)
        if row is not None and row.value_blind_index == bidx:
            continue
        old = _old_trace(row) if row is not None else None
        ciphertext, dek_wrapped, key_id = pii_crypto.encrypt_value(value, aad(death.death_id, type_id))
        if row is None:
            db.session.add(MapDeathIdentifier(
                death_id=death.death_id, identifier_type_id=type_id, value_ciphertext=ciphertext,
                dek_wrapped=dek_wrapped, value_blind_index=bidx, key_id=key_id,
                entered_by=writer.user_id, entered_at=now,
            ))
        else:
            row.value_ciphertext, row.dek_wrapped, row.value_blind_index, row.key_id = (
                ciphertext, dek_wrapped, bidx, key_id)
            row.updated_by, row.updated_at = writer.user_id, now
        changes[f"identifier:{identifier_type.code}"] = {"old": old, "new": _trace(bidx)}
        marks.append((identifier_type, bidx))
        changed.append(identifier_type.code)
    if not changed:
        return [], []
    db.session.flush()
    # The register row's activity stamp moves too, so a concurrent editor's
    # ``if_updated_at`` goes stale and the lists order by the change.
    death.updated_at = now
    cases.record_action(death, actor=writer, action=ACTION, reason=_reason(changed), changes=changes)
    db.session.flush()
    log.info("death identifiers set | death=%s | codes=%s | context=%s | by=%s",
             death.death_id, ",".join(changed), reason_context, writer.user_id)
    return changed, _duplicate_warnings(death, writer, marks)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def identifier_values_visible(user: VaUsers, project_ids) -> set[str]:
    """The projects among *project_ids* where *user* sees identifier VALUES
    (decision 14 & Three-Tier PII Model): admin everywhere, otherwise a live
    ASSIGNED PII grant (``ResolvedGrants.is_pii_grant``) or ``death_reporter``
    (own registrations) in that project. One memoised grant read."""
    wanted = set(project_ids)
    if not wanted:
        return set()
    resolved = resolve_grants(user)
    if resolved.is_admin:
        return wanted
    return wanted & {
        g.project_id for g in resolved.grants
        if not g.virtual and g.source == "assigned"
        and (
            (
                resolved.is_pii_grant(g)
                and (
                    g.role in IDENTIFIER_VALUE_ROLES
                    or (
                        g.scope_type == VaAccessScopeTypes.org_unit
                        and g.role in (VaAccessRoles.coder, VaAccessRoles.reviewer)
                    )
                )
            )
            or g.role == VaAccessRoles.death_reporter
        )
    }


def identifier_payloads(user: VaUsers, deaths, *, values_for: set | None = None) -> dict[uuid.UUID, list[dict]]:
    """``{death_id: [entry, ...]}`` for a page of *deaths* (anything with
    ``death_id`` and ``project_id``), in ``sort_order``.

    Visibility is per case (decision 14): a case shows values when the user
    has a value-granting assigned grant in its project (``identifier_values_visible``)
    AND the case is one that grant, supervision or lens reaches
    (``case_list_service.identifier_value_death_ids``, the row-level rule of the
    shared case list), so a case reached only through coding stays a badge
    whatever else the user holds in the project. *values_for* hands in that
    set when the caller already has it (the case list's own query).

    A viewer who sees values gets ``{code, label, value}`` for EVERY active
    type, ``value`` null where nothing is stored (and for an inactive type that
    holds a value); others get ``{code, label, present}`` for every active
    type (and every inactive one that holds a value), with no ``value`` key.
    At most four queries however large the page; only rows the viewer may see
    are decrypted, and a badge-only viewer triggers no unwrap. A value that
    cannot be decrypted degrades to the badge (the failure is logged with row
    and key id only).
    """
    deaths = list(deaths)
    out: dict[uuid.UUID, list[dict]] = {d.death_id: [] for d in deaths}
    if not deaths:
        return out
    project_ids = {d.project_id for d in deaths}
    types = db.session.scalars(
        sa.select(MasDeathIdentifierType)
        .where(MasDeathIdentifierType.project_id.in_(project_ids))
        .order_by(MasDeathIdentifierType.sort_order, MasDeathIdentifierType.label, MasDeathIdentifierType.code)
    ).all()
    if not types:
        return out
    stored = {}
    for row in db.session.scalars(
        sa.select(MapDeathIdentifier).where(
            MapDeathIdentifier.death_id.in_(list(out)),
            MapDeathIdentifier.identifier_type_id.in_([t.identifier_type_id for t in types]),
        )
    ):
        stored[(row.death_id, row.identifier_type_id)] = row
    visible = identifier_values_visible(user, project_ids)
    if values_for is None and visible:
        # Lazy: the case list imports this module.
        from app.services.case_list_service import identifier_value_death_ids
        values_for = identifier_value_death_ids(user, [d.death_id for d in deaths if d.project_id in visible])
    for death in deaths:
        sees_values = death.project_id in visible and (values_for is None or death.death_id in values_for)
        for identifier_type in types:
            if identifier_type.project_id != death.project_id:
                continue
            row = stored.get((death.death_id, identifier_type.identifier_type_id))
            if row is None and not identifier_type.is_active:
                continue
            entry = {"code": identifier_type.code, "label": identifier_type.label}
            if sees_values and row is None:
                entry["value"] = None
            elif sees_values:
                try:
                    entry["value"] = decrypt_row(row)
                except pii_crypto.PiiCryptoError as exc:
                    log.error("%s", exc)  # row id and key id only
                    entry["present"] = True
            else:
                entry["present"] = row is not None
            out[death.death_id].append(entry)
    return out
