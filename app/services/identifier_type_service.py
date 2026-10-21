"""Identifier type configuration: who may configure, save, audit, list.

Policy: docs/policy/death-registration-identifiers.md ("Data model",
"Authorization", "API outline"). Types are per project; they are never
deleted, only deactivated. Every create and update writes one append-only
``map_identifier_audit`` row holding changed rule fields, never a value.
The caller owns the transaction (commit).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    MapDeathIdentifier,
    MapIdentifierAudit,
    MasDeathIdentifierType,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
)
from app.services.authz import resolve_grants
from app.services.authz.actions import SUPERVISING_ROLES
from app.services.authz.consulted import mark_consulted
from app.services.death_identifier_rules import IdentifierRuleError, clean_type_fields

#: Columns a request may set. ``identifier_type_id`` and timestamps never come from a client.
TYPE_FIELDS = (
    "code", "label", "min_length", "max_length", "char_type", "pattern", "example",
    "required_at_report", "uniqueness_scope", "sort_order", "is_active",
)
#: What a field worker or supervisor needs to render and pre-check the entry field.
INTAKE_FIELDS = (
    "code", "label", "min_length", "max_length", "char_type", "pattern", "example",
    "required_at_report", "sort_order",
)
#: A project holds a handful of types; the cap only bounds a runaway.
MAX_TYPES_LISTED = 200
_CONFIGURING_ROLES = (VaAccessRoles.project_pi, VaAccessRoles.data_manager)


class IdentifierTypeError(Exception):
    """A refusal with an HTTP status and machine code; the message is safe to show."""

    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


def normalise_project_id(project_id) -> str:
    return (project_id or "").strip().upper()


def configuring_role(user, project_id: str) -> str:
    """The role that lets *user* configure *project_id*'s types: ``admin``, a
    live ``project_pi`` grant on that project, or a ``data_manager`` grant
    scoped to the whole project (owner, 2026-10-21: a site- or unit-scoped
    data manager may not change what the whole project collects). A project
    the user has no live grant in (or that does not exist) is 404, alike; a
    user with a grant there but not one of those is 403."""
    mark_consulted()
    resolved = resolve_grants(user)
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        raise IdentifierTypeError("Project not found.", 404, "not_found")
    if resolved.is_admin:
        return VaAccessRoles.admin.value
    mine = [g for g in resolved.grants if g.project_id == project_id and not g.virtual]
    if not mine:
        raise IdentifierTypeError("Project not found.", 404, "not_found")
    for role in _CONFIGURING_ROLES:
        if any(g.role == role and (role != VaAccessRoles.data_manager or g.scope_type == VaAccessScopeTypes.project)
               for g in mine):
            return role.value
    raise IdentifierTypeError("You may not configure identifier types in this project.", 403, "forbidden")


def serialize_type(row: MasDeathIdentifierType, fields=TYPE_FIELDS) -> dict:
    body = {name: getattr(row, name) for name in fields}
    if fields is TYPE_FIELDS:
        body["identifier_type_id"] = str(row.identifier_type_id)
        body["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
    return body


def list_types(project_id: str) -> list[MasDeathIdentifierType]:
    return list(db.session.scalars(
        sa.select(MasDeathIdentifierType)
        .where(MasDeathIdentifierType.project_id == project_id)
        .order_by(MasDeathIdentifierType.sort_order, MasDeathIdentifierType.label, MasDeathIdentifierType.code)
        .limit(MAX_TYPES_LISTED)
    ))


def active_types(project_id: str) -> list[MasDeathIdentifierType]:
    return [t for t in list_types(project_id) if t.is_active]


def _unknown_keys(body: dict) -> None:
    unknown = sorted(set(body) - set(TYPE_FIELDS))
    if unknown:
        raise IdentifierTypeError(f"Unknown field: {', '.join(unknown)}.", 400)


def _audit(user, role: str, project_id: str, event: str, row, details: dict) -> None:
    db.session.add(MapIdentifierAudit(
        project_id=project_id,
        event=event,
        actor_user_id=user.user_id,
        actor_role=role,
        identifier_type_id=row.identifier_type_id,
        details=details,
    ))


def _clean(body: dict, current: dict | None = None) -> dict:
    try:
        return clean_type_fields(body, current)
    except IdentifierRuleError as exc:
        raise IdentifierTypeError(str(exc), 400) from None


def create_type(user, project_id: str, body: dict) -> MasDeathIdentifierType:
    role = configuring_role(user, project_id)
    _unknown_keys(body)
    cleaned = _clean(body)
    taken = db.session.scalar(sa.select(sa.exists().where(
        MasDeathIdentifierType.project_id == project_id,
        MasDeathIdentifierType.code == cleaned["code"],
    )))
    if taken:
        raise IdentifierTypeError("That code is already used in this project.", 409, "duplicate_code")
    row = MasDeathIdentifierType(project_id=project_id, **cleaned)
    db.session.add(row)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise IdentifierTypeError("That code is already used in this project.", 409, "duplicate_code") from None
    _audit(user, role, project_id, "type_created", row,
           {name: {"old": None, "new": cleaned[name]} for name in TYPE_FIELDS})
    return row


def update_type(user, project_id: str, type_id, body: dict) -> MasDeathIdentifierType:
    role = configuring_role(user, project_id)
    _unknown_keys(body)
    row = db.session.scalar(sa.select(MasDeathIdentifierType).where(
        MasDeathIdentifierType.identifier_type_id == type_id,
        MasDeathIdentifierType.project_id == project_id,
    ).with_for_update())
    if row is None:
        raise IdentifierTypeError("Identifier type not found.", 404, "not_found")
    before = {name: getattr(row, name) for name in TYPE_FIELDS}
    cleaned = _clean(body, before)
    if cleaned["code"] != row.code:
        in_use = db.session.scalar(sa.select(sa.exists().where(
            MapDeathIdentifier.identifier_type_id == row.identifier_type_id
        )))
        if in_use:
            raise IdentifierTypeError("The code cannot change once values exist.", 409, "code_locked")
        if db.session.scalar(sa.select(sa.exists().where(
            MasDeathIdentifierType.project_id == project_id,
            MasDeathIdentifierType.code == cleaned["code"],
        ))):
            raise IdentifierTypeError("That code is already used in this project.", 409, "duplicate_code")
    changed = {
        name: {"old": before[name], "new": cleaned[name]}
        for name in TYPE_FIELDS if before[name] != cleaned[name]
    }
    if not changed:
        return row
    for name in changed:
        setattr(row, name, cleaned[name])
    db.session.flush()
    _audit(user, role, project_id, "type_updated", row, changed)
    return row


def supervises_project(user, project_id: str) -> bool:
    """Whether *user* holds a supervising grant in *project_id* (the grants
    behind ``supervised_case_condition``): interview_supervisor, data_manager,
    the In-charge (site_pi at a unit) or project_pi on a tree project."""
    resolved = resolve_grants(user)
    for g in resolved.grants:
        if g.virtual or g.project_id != project_id:
            continue
        if g.role == VaAccessRoles.site_pi:
            if g.scope_type == VaAccessScopeTypes.org_unit:
                return True
        elif g.role in SUPERVISING_ROLES:
            return True
        elif g.role == VaAccessRoles.project_pi and resolved.has_tree(project_id):
            return True
    return False
