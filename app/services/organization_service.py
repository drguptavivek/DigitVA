"""Health-system organization master data: levels, units, cadres, workers.

Plan: docs/planning/health-system-organization-model-plan.md
Policy: docs/policy/organization-model.md

All codes are unique within one project only. Unit paths are ltree values
built from unit codes, so subtree queries use ``path <@ :ancestor_path``.
Every write here is validated against the project's level definitions and
never deletes rows: deactivation is the only removal.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from openpyxl import Workbook, load_workbook

from app import db
from app.models import (
    MapOrgLevelCadre,
    MapOrgUnitCodingGate,
    MapOrgUnitVaPresets,
    MasCadre,
    MasOrgLevel,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_selectives import ROLE_LABELS
from app.services import authz
from app.services.authz.consulted import mark_consulted
from app.services.tabular_import_service import (
    TabularImportError,
    parse_rows,
    parse_table,
    validate_xlsx,
)

log = logging.getLogger(__name__)

__all__ = [
    "OrganizationError",
    "ImportPlan",
    "EXPORT_SHEETS",
    "normalize_code",
    "normalize_level_code",
    "odk_field_name_for_level",
    "odk_choice_list_name_for_level",
    # levels
    "list_levels", "create_level", "update_level",
    # units
    "list_units", "list_units_by_codes", "get_unit_tree", "create_unit", "update_unit", "set_unit_active",
    "place_units", "unplaced_unit_codes", "MAX_PLACEMENTS",
    "find_unit_by_code", "subtree_unit_ids",
    "get_unit_coding_gate", "set_unit_coding_gate", "clear_unit_coding_gate",
    "serialize_unit_coding_gate",
    # cadres and level permissions
    "list_cadres", "create_cadre", "update_cadre",
    "list_level_cadres", "upsert_level_cadre", "get_level_cadre_permission",
    # workers
    "list_workers", "create_worker", "update_worker", "resolve_user",
    "lookup_existing_user", "sync_worker_unit_scope_grants",
    # presets and mentoring
    "list_project_va_presets", "bulk_set_unit_va_presets",
    "project_mentoring_overview", "sync_mentor_scientist_unit_grants",
    # template, export, import
    "seed_default_organization", "district_reference_model",
    "export_organization_rows", "export_organization_xlsx", "export_organization_csv",
    "export_odk_choices_rows", "export_odk_choices_csv",
    "parse_organization_workbook", "parse_organization_csv", "import_organization",
    # serializers
    "serialize_level", "serialize_unit", "serialize_cadre", "serialize_level_cadre", "serialize_worker",
    # my organization page (digitva-e7sz)
    "my_organization", "unit_people", "MY_ORG_PEOPLE_CAP",
    # export dimensions
    "resolve_org_unit_export_labels",
    # project structure
    "require_organization_mode", "organization_site_name", "ensure_organization_site",
]

# ltree labels accept [A-Za-z0-9_]; codes are stored upper-case.
CODE_RE = re.compile(r"^[A-Z0-9_]{1,32}$")
LEVEL_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# Seed template ("Populate district defaults"), the district reference model:
# docs/policy/district-reference-model.md. Codes and depths are stable (existing
# projects and ODK field names org_<level_code>_code depend on them); only the
# labels follow the AAM naming. Village is optional: villages often have no
# code, and an optional level with no units is left out of the ODK form.
DEFAULT_LEVEL_TEMPLATE: tuple[tuple[str, str, int, bool], ...] = (
    ("district", "District / District Hospital (DH)", 1, False),
    ("taluka", "Sub-divisional Hospital (SDH)", 2, True),
    ("chc", "Community Health Centre (CHC)", 3, False),
    ("phc", "PHC-AAM", 4, False),
    ("subcentre", "SC-AAM / Sub-centre", 5, False),
    ("village", "Village", 6, True),
)
DEFAULT_CADRE_TEMPLATE: tuple[tuple[str, str], ...] = (
    ("CS", "Civil Surgeon"),
    ("DPM", "District Programme Manager"),
    ("DEPI", "District Epidemiologist"),
    ("SMO", "Senior Medical Officer"),
    ("MO", "Medical Officer"),
    ("BPM", "Block Programme Manager"),
    ("SN", "Staff Nurse"),
    ("CHO", "Community Health Officer"),
    ("MPW", "Multipurpose Worker"),
    ("ANM", "Auxiliary Nurse Midwife"),
    ("ASHA", "Accredited Social Health Activist"),
)
# (level_code, cadre_code) -> (can_fill_va_form, can_code_va_form,
# can_supervise_interviews, can_report_deaths): what a cadre MAY be given at
# that level.
DEFAULT_LEVEL_CADRE_TEMPLATE: dict[tuple[str, str], tuple[bool, bool, bool, bool]] = {
    ("district", "CS"): (False, False, True, False),
    ("district", "DPM"): (False, False, False, False),
    ("district", "DEPI"): (False, False, False, False),
    ("district", "MO"): (False, True, False, False),
    ("district", "SN"): (True, False, False, False),
    ("chc", "SMO"): (False, True, True, False),
    ("chc", "MO"): (False, True, False, False),
    ("chc", "BPM"): (False, False, False, False),
    ("chc", "SN"): (True, False, False, False),
    ("phc", "MO"): (False, True, True, False),
    ("phc", "CHO"): (True, False, False, False),
    ("subcentre", "CHO"): (True, False, False, False),
    # Owner 2026-10-12: ANM and MPW report deaths and may fill VAs; ASHA
    # reports deaths only. New projects only; an existing grid row is never
    # rewritten.
    ("subcentre", "MPW"): (True, False, False, True),
    ("subcentre", "ANM"): (True, False, False, True),
    ("village", "ASHA"): (False, False, False, True),
}
# The default roles a new project's grid starts with (digitva-vjt): the grants
# an administrator would normally give each cadre, stored on the grid row as
# ``default_roles`` and pre-ticked in the grant forms. Never read for
# authorization; access comes only from each person's grants. site_pi here is
# the In-charge (site_pi held at the unit; docs/policy/access-control-model.md,
# "In-charge"). Also shown as the reference table on the Organization page.
DEFAULT_TYPICAL_ROLES: dict[tuple[str, str], tuple[str, ...]] = {
    ("district", "CS"): ("site_pi",),
    ("district", "DPM"): ("data_manager",),
    ("district", "DEPI"): ("collaborator_pii",),
    ("district", "MO"): ("coder", "reviewer"),
    ("district", "SN"): ("interviewer",),
    ("chc", "SMO"): ("site_pi", "reviewer"),
    ("chc", "MO"): ("coder",),
    ("chc", "BPM"): ("data_manager",),
    ("chc", "SN"): ("interviewer",),
    ("phc", "MO"): ("site_pi", "coder"),
    ("subcentre", "CHO"): ("interviewer",),
    ("subcentre", "MPW"): ("death_reporter",),
    ("subcentre", "ANM"): ("death_reporter",),
    ("village", "ASHA"): ("death_reporter",),
}

EXPORT_SHEETS = ("levels", "units", "cadres", "level_cadres", "workers")


class OrganizationError(ValueError):
    """Validation failure reported to the caller (HTTP 400 in routes)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_code(raw: object, *, what: str = "Code") -> str:
    code = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not CODE_RE.match(code):
        raise OrganizationError(
            f"{what} must be 1-32 characters of letters, digits or underscore (got {raw!r})."
        )
    return code


def normalize_level_code(raw: object) -> str:
    code = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not LEVEL_CODE_RE.match(code):
        raise OrganizationError(
            "Level code must start with a letter and use lower-case letters, digits or "
            f"underscore, at most 32 characters (got {raw!r})."
        )
    return code


def odk_field_name_for_level(level_code: str) -> str:
    """The XLSForm ``survey`` field carrying this level's unit code."""
    return f"org_{level_code}_code"


def odk_choice_list_name_for_level(level_code: str) -> str:
    """The XLSForm ``choices`` list_name holding this level's units."""
    return f"org_{level_code}"


def _clean_text(raw: object, *, max_len: int | None = None, required: bool = False, what: str = "Value") -> str | None:
    value = str(raw).strip() if raw is not None else ""
    if not value:
        if required:
            raise OrganizationError(f"{what} is required.")
        return None
    if max_len is not None and len(value) > max_len:
        raise OrganizationError(f"{what} must be at most {max_len} characters.")
    return value


def _clean_coordinate(raw: object, *, what: str, limit: int) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise OrganizationError(f"{what} must be a decimal number.") from exc
    if value < -limit or value > limit:
        raise OrganizationError(f"{what} must be between -{limit} and {limit}.")
    return value.quantize(Decimal("0.000001"))


def _clean_url(raw: object) -> str | None:
    value = _clean_text(raw, what="Google Maps URL")
    if value is None:
        return None
    if not (value.startswith("https://") or value.startswith("http://")):
        raise OrganizationError("Google Maps URL must start with http:// or https://.")
    return value


def _to_bool(raw: object, *, what: str) -> bool:
    """Parse an import flag; reject values outside the documented boolean forms."""
    if isinstance(raw, bool):
        return raw
    value = str(raw or "").strip().lower()
    if value in {"1", "true", "yes", "y", "t"}:
        return True
    if value in {"", "0", "false", "no", "n", "f"}:
        return False
    raise OrganizationError(f"{what} must be true or false")


def _get_project(project_id: str) -> VaProjectMaster:
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        raise OrganizationError(f"Project not found: {project_id}")
    return project


def require_organization_mode(project_id: str) -> VaProjectMaster:
    """The project, or OrganizationError when its tree may not be edited.

    Only a project whose ``project_structure_mode`` is 'organization' may have
    levels, units, cadres, workers or gates written. Callers that write (the
    admin organization API's guard, the ``flask org`` seed/import commands)
    call this first; reads do not. Policy: docs/policy/organization-model.md
    ("Project structure mode").
    """
    project = _get_project(project_id)
    if project.project_structure_mode != "organization":
        raise OrganizationError(
            "This project uses sites, not organization. Set its Structure to "
            "Organization in the Projects panel first."
        )
    return project


#: Prefix of the automatic site's code: 'O' + three digits (O001, O002, ...).
#: site_id is String(4) and the admin site API accepts only [A-Z0-9]{4}, and a
#: form id is project_id + site_id + two digits, so the code must fit in four.
_ORGANIZATION_SITE_PREFIX = "O"


def organization_site_name(project_id: str) -> str:
    """The name that identifies a project's automatic site."""
    return f"Sites_in_project_{project_id}"


def _next_organization_site_id() -> str:
    """First 'O###' code unused in va_site_master and the legacy va_sites.

    Raises OrganizationError when all 999 are taken.
    """
    pattern = f"{_ORGANIZATION_SITE_PREFIX}___"
    used = set(
        db.session.scalars(
            sa.select(VaSiteMaster.site_id).where(VaSiteMaster.site_id.like(pattern))
        ).all()
    ) | set(
        db.session.scalars(
            sa.select(VaSites.site_id).where(VaSites.site_id.like(pattern))
        ).all()
    )
    for number in range(1, 1000):
        site_id = f"{_ORGANIZATION_SITE_PREFIX}{number:03d}"
        if site_id not in used:
            return site_id
    raise OrganizationError("No free automatic site code is left (O001-O999).")


def ensure_organization_site(project_id: str) -> VaSiteMaster:
    """Give an organization project its one automatic site, mapped and active.

    Web forms are materialized per project-site, so an organization project
    with no site could collect nothing. The site is found by its name,
    ``Sites_in_project_<project_id>``, among the sites mapped to the project
    (a mapping is never deleted, only deactivated), so repeated calls create
    nothing new; a deactivated site or mapping is reactivated. When the
    project has web intake on, its web forms are materialized for every
    active site, the same call the Projects panel makes when web intake is
    switched on.

    Flushes, never commits. Raises OrganizationError when the project is
    missing, and ValueError (from ``resolve_web_form_type``) when the project
    names a deactivated web form type. Policy: docs/policy/organization-model.md
    ("Project structure mode").
    """
    from app.services.runtime_form_sync_service import ensure_web_forms_for_project

    project = _get_project(project_id)
    site_name = organization_site_name(project_id)
    mapping = db.session.scalar(
        sa.select(VaProjectSites)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_id == project_id,
            VaSiteMaster.site_name == site_name,
        )
        .order_by(VaProjectSites.site_id)
        .limit(1)
    )
    if mapping is None:
        # ponytail: first-free code with no lock; two concurrent first saves
        # collide on the primary key and one fails. Admin-only and rare.
        site = VaSiteMaster(
            site_id=_next_organization_site_id(),
            site_name=site_name,
            site_abbr=project_id,
            site_status=VaStatuses.active,
        )
        db.session.add(site)
        # No ORM relationship orders these inserts; the mapping's FK needs the site.
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=project_id,
                site_id=site.site_id,
                project_site_status=VaStatuses.active,
            )
        )
        db.session.flush()
    else:
        site = db.session.get(VaSiteMaster, mapping.site_id)
        site.site_status = VaStatuses.active
        mapping.project_site_status = VaStatuses.active
        db.session.flush()

    if (project.web_intake_mode or "off") != "off":
        ensure_web_forms_for_project(project_id)
    return site


def _uuid(raw: object, *, what: str) -> uuid.UUID:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise OrganizationError(f"{what} is not a valid id.") from exc


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_level(level: MasOrgLevel) -> dict:
    return {
        "org_level_id": str(level.org_level_id),
        "project_id": level.project_id,
        "level_code": level.level_code,
        "level_name": level.level_name,
        "depth": level.depth,
        "is_optional": level.is_optional,
        "is_active": level.is_active,
        "odk_field_name": odk_field_name_for_level(level.level_code),
        "odk_choice_list_name": odk_choice_list_name_for_level(level.level_code),
    }


def serialize_unit(
    unit: MasOrgUnit,
    *,
    level: MasOrgLevel | None = None,
    parent_code: str | None = None,
    top_depth: int | None = None,
) -> dict:
    """One unit as JSON. ``top_depth`` is the project's top active level depth
    (see ``_top_level_depth``); list callers pass it once so flagging
    ``is_unplaced`` costs no query per row. Omitted, it is looked up.
    """
    level = level or unit.level
    if top_depth is None:
        top_depth = _top_level_depth(unit.project_id)
    return {
        "org_unit_id": str(unit.org_unit_id),
        "project_id": unit.project_id,
        "org_level_id": str(unit.org_level_id),
        "level_code": level.level_code,
        "level_name": level.level_name,
        "depth": level.depth,
        "parent_org_unit_id": str(unit.parent_org_unit_id) if unit.parent_org_unit_id else None,
        "parent_code": parent_code,
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "path": str(unit.path),
        "address": unit.address,
        "phone": unit.phone,
        "latitude": str(unit.latitude) if unit.latitude is not None else None,
        "longitude": str(unit.longitude) if unit.longitude is not None else None,
        "google_maps_url": unit.google_maps_url,
        "remarks": unit.remarks,
        "is_active": unit.is_active,
        "is_unplaced": _is_unplaced(unit, level, top_depth),
    }


def serialize_cadre(cadre: MasCadre) -> dict:
    return {
        "cadre_id": str(cadre.cadre_id),
        "project_id": cadre.project_id,
        "cadre_code": cadre.cadre_code,
        "cadre_name": cadre.cadre_name,
        "is_active": cadre.is_active,
    }


def serialize_level_cadre(row: MapOrgLevelCadre, *, level: MasOrgLevel, cadre: MasCadre) -> dict:
    return {
        "level_cadre_id": str(row.level_cadre_id),
        "org_level_id": str(row.org_level_id),
        "level_code": level.level_code,
        "cadre_id": str(row.cadre_id),
        "cadre_code": cadre.cadre_code,
        "can_fill_va_form": row.can_fill_va_form,
        "can_code_va_form": row.can_code_va_form,
        "can_supervise_interviews": row.can_supervise_interviews,
        "can_report_deaths": row.can_report_deaths,
        "default_roles": list(row.default_roles or []),
        "is_active": row.is_active,
    }


def serialize_worker(
    worker: MasOrgUnitWorker,
    *,
    unit: MasOrgUnit,
    cadre: MasCadre,
    user_email: str | None,
    coding_unit_ids: list[str] | None = None,
    coding_unit_codes: list[str] | None = None,
    supervision_unit_ids: list[str] | None = None,
    supervision_unit_codes: list[str] | None = None,
    active_roles: list[str] | None = None,
) -> dict:
    return {
        "worker_id": str(worker.worker_id),
        "project_id": worker.project_id,
        "org_unit_id": str(worker.org_unit_id),
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "cadre_id": str(worker.cadre_id),
        "cadre_code": cadre.cadre_code,
        "worker_code": worker.worker_code,
        "worker_name": worker.worker_name,
        "phone": worker.phone,
        "user_id": str(worker.user_id) if worker.user_id else None,
        "user_email": user_email,
        "remarks": worker.remarks,
        "is_active": worker.is_active,
        "coding_unit_ids": list(coding_unit_ids or []),
        "coding_unit_codes": list(coding_unit_codes or []),
        "supervision_unit_ids": list(supervision_unit_ids or []),
        "supervision_unit_codes": list(supervision_unit_codes or []),
        "active_roles": list(active_roles or []),
    }


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


def list_levels(project_id: str, *, include_inactive: bool = False) -> list[MasOrgLevel]:
    stmt = sa.select(MasOrgLevel).where(MasOrgLevel.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(MasOrgLevel.is_active.is_(True))
    return list(db.session.scalars(stmt.order_by(MasOrgLevel.depth)).all())


def _get_level(project_id: str, org_level_id: object) -> MasOrgLevel:
    level = db.session.get(MasOrgLevel, _uuid(org_level_id, what="Level id"))
    if level is None or level.project_id != project_id:
        raise OrganizationError("Level not found in this project.")
    return level


def create_level(
    project_id: str,
    *,
    level_code: object,
    level_name: object,
    depth: object,
    is_optional: bool = False,
) -> MasOrgLevel:
    _get_project(project_id)
    code = normalize_level_code(level_code)
    name = _clean_text(level_name, max_len=128, required=True, what="Level name")
    try:
        depth_value = int(depth)
    except (TypeError, ValueError) as exc:
        raise OrganizationError("Depth must be a positive integer.") from exc
    if depth_value < 1:
        raise OrganizationError("Depth must be a positive integer.")
    clash = db.session.scalar(
        sa.select(MasOrgLevel).where(
            MasOrgLevel.project_id == project_id,
            sa.or_(MasOrgLevel.level_code == code, MasOrgLevel.depth == depth_value),
        )
    )
    if clash is not None:
        raise OrganizationError(
            f"A level with code {clash.level_code!r} or depth {clash.depth} already exists."
        )
    level = MasOrgLevel(
        project_id=project_id,
        level_code=code,
        level_name=name,
        depth=depth_value,
        is_optional=bool(is_optional),
    )
    db.session.add(level)
    db.session.flush()
    return level


def update_level(project_id: str, org_level_id: object, **fields) -> MasOrgLevel:
    level = _get_level(project_id, org_level_id)
    if "level_name" in fields:
        level.level_name = _clean_text(fields["level_name"], max_len=128, required=True, what="Level name")
    if "is_optional" in fields:
        level.is_optional = bool(fields["is_optional"])
    if "level_code" in fields:
        new_code = normalize_level_code(fields["level_code"])
        if new_code != level.level_code:
            dup = db.session.scalar(
                sa.select(MasOrgLevel.org_level_id).where(
                    MasOrgLevel.project_id == project_id, MasOrgLevel.level_code == new_code
                )
            )
            if dup is not None:
                raise OrganizationError(f"Level code {new_code!r} already exists.")
            level.level_code = new_code
    if "depth" in fields and int(fields["depth"]) != level.depth:
        has_units = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasOrgUnit).where(MasOrgUnit.org_level_id == level.org_level_id)
        )
        if has_units:
            raise OrganizationError("Depth cannot change while units exist at this level.")
        new_depth = int(fields["depth"])
        if new_depth < 1:
            raise OrganizationError("Depth must be a positive integer.")
        dup = db.session.scalar(
            sa.select(MasOrgLevel.org_level_id).where(
                MasOrgLevel.project_id == project_id, MasOrgLevel.depth == new_depth
            )
        )
        if dup is not None:
            raise OrganizationError(f"Depth {new_depth} is already used.")
        level.depth = new_depth
    if "is_active" in fields:
        active = bool(fields["is_active"])
        if not active:
            active_units = db.session.scalar(
                sa.select(sa.func.count()).select_from(MasOrgUnit).where(
                    MasOrgUnit.org_level_id == level.org_level_id, MasOrgUnit.is_active.is_(True)
                )
            )
            if active_units:
                raise OrganizationError("Deactivate or move the units at this level first.")
        level.is_active = active
    db.session.flush()
    return level


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def list_units(project_id: str, *, include_inactive: bool = False, top_depth: int | None = None) -> list[dict]:
    parent = _aliased_parent()
    stmt = (
        sa.select(MasOrgUnit, MasOrgLevel, parent.unit_code)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .outerjoin(parent, parent.org_unit_id == MasOrgUnit.parent_org_unit_id)
        .where(MasOrgUnit.project_id == project_id)
    )
    if not include_inactive:
        stmt = stmt.where(MasOrgUnit.is_active.is_(True))
    rows = db.session.execute(stmt.order_by(MasOrgUnit.path)).all()
    if top_depth is None:
        top_depth = _top_level_depth(project_id)
    return [
        serialize_unit(unit, level=level, parent_code=parent_code, top_depth=top_depth)
        for unit, level, parent_code in rows
    ]


def list_units_by_codes(project_id: str, unit_codes, *, include_inactive: bool = False, top_depth: int | None = None) -> list[dict]:
    """Units in *project_id* named by *unit_codes*, in one query.

    For resolving the codes packed into another unit's ``path`` ltree back
    into full unit rows — e.g. the ancestor units implied by a scoped
    picker's reachable units, or the ancestor context of one submission's
    unit — without a per-unit or per-code round trip. Shared by
    ``app/routes/api/organization.py`` (ancestor context for a scoped
    picker) and ``web_intake_service._unit_context`` (ancestor codes/names
    for a submitted payload); keep both callers' semantics in mind before
    changing the active-only default.
    """
    codes = {c for c in unit_codes if c}
    if not codes:
        return []
    parent = _aliased_parent()
    stmt = (
        sa.select(MasOrgUnit, MasOrgLevel, parent.unit_code)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .outerjoin(parent, parent.org_unit_id == MasOrgUnit.parent_org_unit_id)
        .where(MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code.in_(sorted(codes)))
    )
    if not include_inactive:
        stmt = stmt.where(MasOrgUnit.is_active.is_(True))
    rows = db.session.execute(stmt.order_by(MasOrgUnit.path)).all()
    if top_depth is None:
        top_depth = _top_level_depth(project_id)
    return [
        serialize_unit(unit, level=level, parent_code=parent_code, top_depth=top_depth)
        for unit, level, parent_code in rows
    ]


def resolve_org_unit_export_labels(org_unit_ids) -> dict[uuid.UUID, dict]:
    """Batched unit code/name/level-path lookup for exports.

    Takes any iterable of unit ids (``None`` entries are ignored) and returns
    ``{org_unit_id: {"unit_code", "unit_name", "level_path"}}`` for every id
    actually found — inactive units included, since history must stay
    readable. Exactly two queries regardless of how many rows the caller is
    exporting: one for the referenced units themselves, one for the ancestor
    codes named in their ``path`` (deduplicated across all of them), so a
    large export never turns into a per-row walk up the tree.
    """
    ids = {uid for uid in org_unit_ids if uid is not None}
    if not ids:
        return {}

    units = db.session.execute(
        sa.select(
            MasOrgUnit.org_unit_id,
            MasOrgUnit.project_id,
            MasOrgUnit.unit_code,
            MasOrgUnit.unit_name,
            MasOrgUnit.path,
        ).where(MasOrgUnit.org_unit_id.in_(ids))
    ).all()
    if not units:
        return {}

    project_ids = {row.project_id for row in units}
    ancestor_codes = {code for row in units for code in str(row.path).split(".")}

    name_by_project_code: dict[tuple[str, str], str] = {}
    if ancestor_codes:
        code_rows = db.session.execute(
            sa.select(MasOrgUnit.project_id, MasOrgUnit.unit_code, MasOrgUnit.unit_name).where(
                MasOrgUnit.project_id.in_(project_ids),
                MasOrgUnit.unit_code.in_(ancestor_codes),
            )
        ).all()
        name_by_project_code = {
            (row.project_id, row.unit_code): row.unit_name for row in code_rows
        }

    labels: dict[uuid.UUID, dict] = {}
    for row in units:
        codes = str(row.path).split(".")
        level_path = " / ".join(
            name_by_project_code.get((row.project_id, code), code) for code in codes
        )
        labels[row.org_unit_id] = {
            "unit_code": row.unit_code,
            "unit_name": row.unit_name,
            "level_path": level_path,
        }
    return labels


def _aliased_parent():
    from sqlalchemy.orm import aliased

    return aliased(MasOrgUnit)


def _top_level_depth(project_id: str) -> int | None:
    """Depth of the project's top active level, or None with no active level."""
    return db.session.scalar(
        sa.select(sa.func.min(MasOrgLevel.depth)).where(
            MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True)
        )
    )


def _is_unplaced(unit: MasOrgUnit, level: MasOrgLevel, top_depth: int | None) -> bool:
    """A unit with no parent below the top active level: imported, not yet mapped.

    Policy: docs/policy/organization-model.md ("Unplaced units").
    """
    return unit.parent_org_unit_id is None and top_depth is not None and level.depth != top_depth


def unplaced_unit_codes(project_id: str, *, include_inactive: bool = False) -> list[str]:
    """Codes of the project's unplaced units, in one query, sorted.

    Their descendants are not included; a descendant's ``path`` starts with
    its unplaced root's code, which is how callers exclude whole subtrees.
    """
    stmt = (
        sa.select(MasOrgUnit.unit_code)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.parent_org_unit_id.is_(None),
            MasOrgLevel.depth != sa.select(sa.func.min(MasOrgLevel.depth))
            .where(MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True))
            .scalar_subquery(),
        )
    )
    if not include_inactive:
        stmt = stmt.where(MasOrgUnit.is_active.is_(True))
    return list(db.session.scalars(stmt.order_by(MasOrgUnit.unit_code)).all())


def get_unit_tree(project_id: str, *, include_inactive: bool = False) -> list[dict]:
    """Nested tree (children under ``children``) in path order.

    Unplaced units (``is_unplaced``) come back as extra roots.
    """
    flat = list_units(project_id, include_inactive=include_inactive)
    by_id = {u["org_unit_id"]: {**u, "children": []} for u in flat}
    roots: list[dict] = []
    for node in by_id.values():
        parent_id = node["parent_org_unit_id"]
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def _get_unit(project_id: str, org_unit_id: object) -> MasOrgUnit:
    unit = db.session.get(MasOrgUnit, _uuid(org_unit_id, what="Unit id"))
    if unit is None or unit.project_id != project_id:
        raise OrganizationError("Unit not found in this project.")
    return unit


def _validate_parent_for_level(
    project_id: str, level: MasOrgLevel, parent: MasOrgUnit | None, *, allow_unplaced: bool = False
) -> None:
    """Refuse a parent that does not fit *level* (optional levels may be skipped).

    ``allow_unplaced`` lets a unit below the top level have no parent. Only the
    importer passes it; the admin forms stay strict. Policy:
    docs/policy/organization-model.md ("Unplaced units").
    """
    levels = list_levels(project_id, include_inactive=False)
    if not levels:
        raise OrganizationError("Define the project's levels before adding units.")
    top_depth = levels[0].depth
    if parent is None:
        if level.depth != top_depth and not allow_unplaced:
            raise OrganizationError(
                f"Units at level {level.level_code!r} need a parent; only the top level "
                f"({levels[0].level_code!r}) may have none."
            )
        return
    if parent.project_id != project_id:
        raise OrganizationError("Parent unit belongs to another project.")
    parent_level = parent.level
    if parent_level.depth >= level.depth:
        raise OrganizationError(
            f"Parent {parent.unit_code!r} is at level {parent_level.level_code!r} (depth "
            f"{parent_level.depth}); a {level.level_code!r} unit needs a parent at a shallower level."
        )
    skipped = [lv for lv in levels if parent_level.depth < lv.depth < level.depth and not lv.is_optional]
    if skipped:
        names = ", ".join(repr(lv.level_code) for lv in skipped)
        raise OrganizationError(
            f"Level(s) {names} between {parent_level.level_code!r} and {level.level_code!r} are not "
            "optional; the parent must be at the next level up."
        )


def create_unit(
    project_id: str,
    *,
    org_level_id: object,
    unit_code: object,
    unit_name: object,
    parent_org_unit_id: object | None = None,
    address: object = None,
    phone: object = None,
    latitude: object = None,
    longitude: object = None,
    google_maps_url: object = None,
    remarks: object = None,
    allow_unplaced: bool = False,
) -> MasOrgUnit:
    _get_project(project_id)
    level = _get_level(project_id, org_level_id)
    if not level.is_active:
        raise OrganizationError("Level is inactive.")
    code = normalize_code(unit_code, what="Unit code")
    name = _clean_text(unit_name, required=True, what="Unit name")
    parent = _get_unit(project_id, parent_org_unit_id) if parent_org_unit_id else None
    if parent is not None and not parent.is_active:
        raise OrganizationError("Parent unit is inactive.")
    _validate_parent_for_level(project_id, level, parent, allow_unplaced=allow_unplaced)
    dup = db.session.scalar(
        sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code == code
        )
    )
    if dup is not None:
        raise OrganizationError(f"Unit code {code!r} already exists in this project.")
    unit = MasOrgUnit(
        project_id=project_id,
        org_level_id=level.org_level_id,
        parent_org_unit_id=parent.org_unit_id if parent else None,
        unit_code=code,
        unit_name=name,
        path=f"{parent.path}.{code}" if parent else code,
        address=_clean_text(address, what="Address"),
        phone=_clean_text(phone, max_len=32, what="Phone"),
        latitude=_clean_coordinate(latitude, what="Latitude", limit=90),
        longitude=_clean_coordinate(longitude, what="Longitude", limit=180),
        google_maps_url=_clean_url(google_maps_url),
        remarks=_clean_text(remarks, what="Remarks"),
    )
    db.session.add(unit)
    db.session.flush()
    return unit


def _rewrite_subtree_paths(project_id: str, old_path: str, new_path: str) -> None:
    """Rewrite ``path`` for a unit and every descendant after a move or rename.

    Unit codes are unique per project only, so the same path can exist in
    another project; the ``project_id`` filter keeps the rewrite in this one.
    """
    # Raw SQL escapes the ORM hooks that bump the grant cache.
    from app.services.authz import invalidate_all

    invalidate_all()
    db.session.execute(
        sa.text(
            """
            UPDATE mas_org_unit
            SET path = CASE
                WHEN path = CAST(:old_path AS ltree) THEN CAST(:new_path AS ltree)
                ELSE CAST(:new_path AS ltree) || subpath(path, nlevel(CAST(:old_path AS ltree)))
            END
            WHERE project_id = :project_id
              AND path <@ CAST(:old_path AS ltree)
            """
        ),
        {"project_id": project_id, "old_path": old_path, "new_path": new_path},
    )
    db.session.expire_all()


def update_unit(project_id: str, org_unit_id: object, *, allow_unplaced: bool = False, **fields) -> MasOrgUnit:
    """Update a unit; a parent or level change is validated and moves the subtree.

    ``allow_unplaced`` is for the importer only (see ``_validate_parent_for_level``).
    Setting a parent on an unplaced unit is the normal path, so it needs no flag.
    """
    unit = _get_unit(project_id, org_unit_id)
    old_path = str(unit.path)
    level = unit.level
    parent = unit.parent

    if "org_level_id" in fields and fields["org_level_id"]:
        level = _get_level(project_id, fields["org_level_id"])
    if "parent_org_unit_id" in fields:
        raw_parent = fields["parent_org_unit_id"]
        parent = _get_unit(project_id, raw_parent) if raw_parent else None
        if parent is not None:
            if parent.org_unit_id == unit.org_unit_id or str(parent.path).startswith(old_path + "."):
                raise OrganizationError("A unit cannot be moved under itself or its own descendants.")
            if not parent.is_active:
                raise OrganizationError("Parent unit is inactive.")
    level_or_parent_changed = level.org_level_id != unit.org_level_id or (
        (parent.org_unit_id if parent else None) != unit.parent_org_unit_id
    )
    if level_or_parent_changed:
        _validate_parent_for_level(project_id, level, parent, allow_unplaced=allow_unplaced)
        if level.org_level_id != unit.org_level_id:
            # Children must still sit below the new level.
            child_depth = db.session.scalar(
                sa.select(sa.func.min(MasOrgLevel.depth))
                .select_from(MasOrgUnit)
                .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
                .where(MasOrgUnit.parent_org_unit_id == unit.org_unit_id)
            )
            if child_depth is not None and child_depth <= level.depth:
                raise OrganizationError("Children of this unit would end up at or above its new level.")
        unit.org_level_id = level.org_level_id
        unit.parent_org_unit_id = parent.org_unit_id if parent else None

    new_code = unit.unit_code
    if "unit_code" in fields and fields["unit_code"] is not None:
        new_code = normalize_code(fields["unit_code"], what="Unit code")
        if new_code != unit.unit_code:
            dup = db.session.scalar(
                sa.select(MasOrgUnit.org_unit_id).where(
                    MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code == new_code
                )
            )
            if dup is not None:
                raise OrganizationError(f"Unit code {new_code!r} already exists in this project.")
            unit.unit_code = new_code

    if "unit_name" in fields:
        unit.unit_name = _clean_text(fields["unit_name"], required=True, what="Unit name")
    if "address" in fields:
        unit.address = _clean_text(fields["address"], what="Address")
    if "phone" in fields:
        unit.phone = _clean_text(fields["phone"], max_len=32, what="Phone")
    if "latitude" in fields:
        unit.latitude = _clean_coordinate(fields["latitude"], what="Latitude", limit=90)
    if "longitude" in fields:
        unit.longitude = _clean_coordinate(fields["longitude"], what="Longitude", limit=180)
    if "google_maps_url" in fields:
        unit.google_maps_url = _clean_url(fields["google_maps_url"])
    if "remarks" in fields:
        unit.remarks = _clean_text(fields["remarks"], what="Remarks")

    db.session.flush()
    new_path = f"{parent.path}.{new_code}" if parent else new_code
    if new_path != old_path:
        _rewrite_subtree_paths(project_id, old_path, new_path)
        unit = db.session.get(MasOrgUnit, unit.org_unit_id)

    if "is_active" in fields:
        set_unit_active(project_id, unit.org_unit_id, bool(fields["is_active"]))
        unit = db.session.get(MasOrgUnit, unit.org_unit_id)
    return unit


#: Most placements one ``place_units`` call accepts.
MAX_PLACEMENTS = 500


def place_units(project_id: str, placements: object) -> list[MasOrgUnit]:
    """Set the parent of several units, all or nothing.

    *placements* is a list of ``{"org_unit_id", "parent_org_unit_id"}``. Each
    goes through ``update_unit``, so the usual level rules apply (optional
    levels may be skipped) and each moved subtree's paths are rewritten. A
    blank parent is refused: detaching a unit is not a placement. Raises
    ``OrganizationError`` naming the unit on the first bad item; the caller
    rolls back. Works on placed units too (the Units tree's drag-and-drop).
    """
    if not isinstance(placements, list) or not placements:
        raise OrganizationError("placements must be a non-empty list.")
    if len(placements) > MAX_PLACEMENTS:
        raise OrganizationError(f"At most {MAX_PLACEMENTS} placements per request.")
    seen: set[uuid.UUID] = set()
    moved = []
    # ponytail: one update_unit per item (a few queries each); batch the reads if imports reach thousands.
    for item in placements:
        if not isinstance(item, dict):
            raise OrganizationError("Each placement must be an object.")
        unit_id = _uuid(item.get("org_unit_id"), what="Unit id")
        if unit_id in seen:
            raise OrganizationError("A unit is listed twice.")
        seen.add(unit_id)
        if not item.get("parent_org_unit_id"):
            raise OrganizationError("Choose a parent for every unit.")
        unit = _get_unit(project_id, unit_id)
        code = unit.unit_code
        try:
            moved.append(update_unit(project_id, unit_id, parent_org_unit_id=item["parent_org_unit_id"]))
        except OrganizationError as exc:
            raise OrganizationError(f"{code}: {exc}") from exc
    return moved


def set_unit_active(project_id: str, org_unit_id: object, active: bool) -> int:
    """Deactivate a unit with its whole subtree, or reactivate a single unit.

    Returns the number of units changed.
    """
    unit = _get_unit(project_id, org_unit_id)
    if active:
        if unit.parent is not None and not unit.parent.is_active:
            raise OrganizationError("Reactivate the parent unit first.")
        if unit.is_active:
            return 0
        unit.is_active = True
        db.session.flush()
        return 1
    # Raw SQL escapes the ORM hooks that bump the grant cache.
    from app.services.authz import invalidate_all

    invalidate_all()
    result = db.session.execute(
        sa.text(
            """
            UPDATE mas_org_unit
            SET is_active = false, updated_at = now()
            WHERE project_id = :project_id
              AND path <@ CAST(:path AS ltree)
              AND is_active = true
            """
        ),
        {"project_id": project_id, "path": str(unit.path)},
    )
    db.session.expire_all()
    return result.rowcount or 0


def serialize_unit_coding_gate(gate: MapOrgUnitCodingGate | None) -> dict | None:
    if gate is None:
        return None
    return {
        "org_unit_id": str(gate.org_unit_id),
        "coding_enabled": gate.coding_enabled,
        "coding_start_date": gate.coding_start_date.isoformat() if gate.coding_start_date else None,
        "coding_end_date": gate.coding_end_date.isoformat() if gate.coding_end_date else None,
        "daily_coder_limit": gate.daily_coder_limit,
    }


def get_unit_coding_gate(project_id: str, org_unit_id: object) -> MapOrgUnitCodingGate | None:
    """Return this unit's own gate row, or None -- absence is not a closed unit.

    This is the unit's own row only, not the resolved (nearest-ancestor) gate
    that actually governs coding -- see
    ``app.services.org_grant_service.resolve_unit_coding_gates`` for that.
    """
    unit = _get_unit(project_id, org_unit_id)
    return db.session.get(MapOrgUnitCodingGate, unit.org_unit_id)


def set_unit_coding_gate(
    project_id: str,
    org_unit_id: object,
    *,
    coding_enabled: object,
    coding_start_date: object = None,
    coding_end_date: object = None,
    daily_coder_limit: object = None,
) -> MapOrgUnitCodingGate:
    """Create or update this unit's own coding gate row.

    ``daily_coder_limit`` is optional (unlike the site column it is checked
    alongside): leaving it unset means this gate carries no unit-specific
    cap, only whatever ``coding_enabled``/date window it sets.
    """
    unit = _get_unit(project_id, org_unit_id)
    if not isinstance(coding_enabled, bool):
        raise OrganizationError("coding_enabled must be a boolean.")

    start = None
    end = None
    try:
        if coding_start_date:
            start = date_type.fromisoformat(coding_start_date)
        if coding_end_date:
            end = date_type.fromisoformat(coding_end_date)
    except (ValueError, TypeError) as exc:
        raise OrganizationError(
            "coding_start_date and coding_end_date must be ISO date strings (YYYY-MM-DD)."
        ) from exc
    if start and end and end < start:
        raise OrganizationError("coding_end_date must be on or after coding_start_date.")

    limit = None
    if daily_coder_limit is not None:
        try:
            limit = int(daily_coder_limit)
        except (ValueError, TypeError) as exc:
            raise OrganizationError("daily_coder_limit must be an integer.") from exc
        if limit < 1:
            raise OrganizationError("daily_coder_limit must be at least 1.")

    gate = db.session.get(MapOrgUnitCodingGate, unit.org_unit_id)
    if gate is None:
        gate = MapOrgUnitCodingGate(org_unit_id=unit.org_unit_id)
        db.session.add(gate)
    gate.coding_enabled = coding_enabled
    gate.coding_start_date = start
    gate.coding_end_date = end
    gate.daily_coder_limit = limit
    db.session.flush()
    return gate


VA_PRESET_VALUES = ("high", "low", "veryl")


def serialize_unit_va_presets(presets: MapOrgUnitVaPresets | None) -> dict | None:
    if presets is None:
        return None
    return {
        "org_unit_id": str(presets.org_unit_id),
        "hiv_mortality": presets.hiv_mortality,
        "malaria_mortality": presets.malaria_mortality,
        "updated_at": presets.updated_at.isoformat() if presets.updated_at else None,
    }


def get_unit_va_presets(project_id: str, org_unit_id: object) -> MapOrgUnitVaPresets | None:
    """Return this unit's own VA presets row, or None -- absence means inherited.

    This is the unit's own row only, not the resolved (nearest-ancestor)
    value that actually prefills a draft -- see
    ``app.services.org_grant_service.resolve_unit_va_presets`` for that.
    """
    unit = _get_unit(project_id, org_unit_id)
    return db.session.get(MapOrgUnitVaPresets, unit.org_unit_id)


def _validate_va_preset_value(raw: object, *, what: str) -> str | None:
    if raw is None or raw == "":
        return None
    value = str(raw)
    if value not in VA_PRESET_VALUES:
        raise OrganizationError(f"{what} must be one of {', '.join(VA_PRESET_VALUES)}, or empty (not set).")
    return value


def set_unit_va_presets(
    project_id: str,
    org_unit_id: object,
    *,
    hiv_mortality: object,
    malaria_mortality: object,
    actor_id=None,
) -> MapOrgUnitVaPresets:
    """Create or update this unit's own HIV/malaria mortality presets.

    Either field left empty/None clears that preset on this unit -- it then
    inherits its nearest ancestor's value, if any, same as a unit that never
    set one.
    """
    unit = _get_unit(project_id, org_unit_id)
    hiv = _validate_va_preset_value(hiv_mortality, what="hiv_mortality")
    malaria = _validate_va_preset_value(malaria_mortality, what="malaria_mortality")

    presets = db.session.get(MapOrgUnitVaPresets, unit.org_unit_id)
    if presets is None:
        presets = MapOrgUnitVaPresets(org_unit_id=unit.org_unit_id)
        db.session.add(presets)
    presets.hiv_mortality = hiv
    presets.malaria_mortality = malaria
    presets.updated_by_user_id = actor_id
    db.session.flush()
    return presets


def clear_unit_va_presets(project_id: str, org_unit_id: object) -> bool:
    """Delete this unit's own VA presets row, if any. Returns whether one existed."""
    unit = _get_unit(project_id, org_unit_id)
    presets = db.session.get(MapOrgUnitVaPresets, unit.org_unit_id)
    if presets is None:
        return False
    db.session.delete(presets)
    db.session.flush()
    return True


def clear_unit_coding_gate(project_id: str, org_unit_id: object) -> bool:
    """Delete this unit's own gate row, if any. Returns whether one existed.

    The unit then inherits its nearest gated ancestor (if any), same as a
    unit that never had a gate of its own.
    """
    unit = _get_unit(project_id, org_unit_id)
    gate = db.session.get(MapOrgUnitCodingGate, unit.org_unit_id)
    if gate is None:
        return False
    db.session.delete(gate)
    db.session.flush()
    return True


def find_unit_by_code(project_id: str, unit_code: object) -> MasOrgUnit | None:
    try:
        code = normalize_code(unit_code, what="Unit code")
    except OrganizationError:
        return None
    return db.session.scalar(
        sa.select(MasOrgUnit).where(MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code == code)
    )


def subtree_unit_ids(unit: MasOrgUnit, *, include_inactive: bool = False) -> list[uuid.UUID]:
    stmt = sa.select(MasOrgUnit.org_unit_id).where(
        MasOrgUnit.project_id == unit.project_id,
        sa.text("path <@ CAST(:ancestor AS ltree)").bindparams(ancestor=str(unit.path)),
    )
    if not include_inactive:
        stmt = stmt.where(MasOrgUnit.is_active.is_(True))
    return list(db.session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Cadres and level permissions
# ---------------------------------------------------------------------------


def list_cadres(project_id: str, *, include_inactive: bool = False) -> list[MasCadre]:
    stmt = sa.select(MasCadre).where(MasCadre.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(MasCadre.is_active.is_(True))
    return list(db.session.scalars(stmt.order_by(MasCadre.cadre_code)).all())


def _get_cadre(project_id: str, cadre_id: object) -> MasCadre:
    cadre = db.session.get(MasCadre, _uuid(cadre_id, what="Cadre id"))
    if cadre is None or cadre.project_id != project_id:
        raise OrganizationError("Cadre not found in this project.")
    return cadre


def create_cadre(project_id: str, *, cadre_code: object, cadre_name: object) -> MasCadre:
    _get_project(project_id)
    code = normalize_code(cadre_code, what="Cadre code")
    name = _clean_text(cadre_name, max_len=128, required=True, what="Cadre name")
    dup = db.session.scalar(
        sa.select(MasCadre.cadre_id).where(MasCadre.project_id == project_id, MasCadre.cadre_code == code)
    )
    if dup is not None:
        raise OrganizationError(f"Cadre code {code!r} already exists in this project.")
    cadre = MasCadre(project_id=project_id, cadre_code=code, cadre_name=name)
    db.session.add(cadre)
    db.session.flush()
    return cadre


def update_cadre(project_id: str, cadre_id: object, **fields) -> MasCadre:
    cadre = _get_cadre(project_id, cadre_id)
    if "cadre_name" in fields:
        cadre.cadre_name = _clean_text(fields["cadre_name"], max_len=128, required=True, what="Cadre name")
    if "cadre_code" in fields and fields["cadre_code"] is not None:
        new_code = normalize_code(fields["cadre_code"], what="Cadre code")
        if new_code != cadre.cadre_code:
            dup = db.session.scalar(
                sa.select(MasCadre.cadre_id).where(
                    MasCadre.project_id == project_id, MasCadre.cadre_code == new_code
                )
            )
            if dup is not None:
                raise OrganizationError(f"Cadre code {new_code!r} already exists in this project.")
            cadre.cadre_code = new_code
    if "is_active" in fields:
        cadre.is_active = bool(fields["is_active"])
    db.session.flush()
    return cadre


def list_level_cadres(project_id: str) -> list[dict]:
    rows = db.session.execute(
        sa.select(MapOrgLevelCadre, MasOrgLevel, MasCadre)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MapOrgLevelCadre.org_level_id)
        .join(MasCadre, MasCadre.cadre_id == MapOrgLevelCadre.cadre_id)
        .where(MasOrgLevel.project_id == project_id)
        .order_by(MasOrgLevel.depth, MasCadre.cadre_code)
    ).all()
    return [serialize_level_cadre(row, level=level, cadre=cadre) for row, level, cadre in rows]


def normalize_default_roles(
    roles: Iterable[str] | None,
    row: MapOrgLevelCadre,
    *,
    level: MasOrgLevel,
    cadre: MasCadre,
    drop_disallowed: bool = False,
) -> list[str]:
    """Validate a row's default roles against its flags; return them canonical.

    Each role must be a unit-scope role (``ROLES_ALLOWING_ORG_UNIT``) and, when
    ``CADRE_FLAG_BY_ROLE`` names a flag for it, the row must carry that flag:
    the one rule a unit grant is written by (``validate_org_unit_grant``).
    Duplicates collapse; the order is the role enum's, so a round trip through
    an export is stable. Raises OrganizationError for the operator, or with
    *drop_disallowed* leaves out a role whose flag the row lacks (the stored
    defaults after a flag was cleared).
    """
    # org_grant_service imports this module, so the rule is read at call time.
    from app.services.org_grant_service import CADRE_FLAG_BY_ROLE, ROLES_ALLOWING_ORG_UNIT

    wanted = set()
    for raw in roles or ():
        name = str(raw).strip()
        if not name:
            continue
        try:
            role = VaAccessRoles(name)
        except ValueError as exc:
            raise OrganizationError(f"Unknown default role {name!r}.") from exc
        if role not in ROLES_ALLOWING_ORG_UNIT:
            raise OrganizationError(f"Default role {name!r} cannot be held at a unit.")
        if role in CADRE_FLAG_BY_ROLE:
            flag, permits = CADRE_FLAG_BY_ROLE[role]
            if not getattr(row, flag):
                if drop_disallowed:
                    continue
                raise OrganizationError(
                    f"Default role {name!r} needs a cadre that may {permits}: cadre "
                    f"{cadre.cadre_code!r} may not at level {level.level_code!r}."
                )
        wanted.add(role)
    return [role.value for role in VaAccessRoles if role in wanted]


def upsert_level_cadre(
    project_id: str,
    *,
    org_level_id: object,
    cadre_id: object,
    can_fill_va_form: bool,
    can_code_va_form: bool,
    can_supervise_interviews: bool | None = None,
    can_report_deaths: bool | None = None,
    default_roles: Iterable[str] | None = None,
    is_active: bool = True,
) -> MapOrgLevelCadre:
    """Create or update one level x cadre row.

    ``can_supervise_interviews``, ``can_report_deaths`` and ``default_roles``
    of ``None`` keep the row's current value (false or empty on a new row), so
    callers and workbooks that predate a column cannot clear it. Default roles
    that are supplied are checked against the row's resulting flags
    (``normalize_default_roles``) and refused if the flags do not allow one;
    kept ones that a cleared flag no longer allows are dropped, so a caller
    that never mentions defaults can still clear the flag.
    """
    level = _get_level(project_id, org_level_id)
    cadre = _get_cadre(project_id, cadre_id)
    row = db.session.scalar(
        sa.select(MapOrgLevelCadre).where(
            MapOrgLevelCadre.org_level_id == level.org_level_id,
            MapOrgLevelCadre.cadre_id == cadre.cadre_id,
        )
    )
    if row is None:
        row = MapOrgLevelCadre(org_level_id=level.org_level_id, cadre_id=cadre.cadre_id)
        db.session.add(row)
    row.can_fill_va_form = bool(can_fill_va_form)
    row.can_code_va_form = bool(can_code_va_form)
    if can_supervise_interviews is not None:
        row.can_supervise_interviews = bool(can_supervise_interviews)
    if can_report_deaths is not None:
        row.can_report_deaths = bool(can_report_deaths)
    row.default_roles = normalize_default_roles(
        row.default_roles if default_roles is None else default_roles,
        row, level=level, cadre=cadre, drop_disallowed=default_roles is None,
    )
    if not is_active:
        active_workers = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(MasOrgUnitWorker)
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
            .where(
                MasOrgUnit.org_level_id == level.org_level_id,
                MasOrgUnitWorker.cadre_id == cadre.cadre_id,
                MasOrgUnitWorker.is_active.is_(True),
            )
        )
        if active_workers:
            raise OrganizationError(
                f"Deactivate or move the {active_workers} active {cadre.cadre_code!r} worker(s) "
                f"at level {level.level_code!r} first."
            )
    row.is_active = bool(is_active)
    try:
        db.session.flush()
    except sa.exc.IntegrityError as exc:
        # Fallback for a constraint the checks above missed (the default_roles
        # CHECK, say): the operator gets a 400, never a 500. The caller rolls back.
        raise OrganizationError("The level x cadre row violates a database constraint.") from exc
    return row


def get_level_cadre_permission(org_level_id: uuid.UUID, cadre_id: uuid.UUID) -> MapOrgLevelCadre | None:
    return db.session.scalar(
        sa.select(MapOrgLevelCadre).where(
            MapOrgLevelCadre.org_level_id == org_level_id,
            MapOrgLevelCadre.cadre_id == cadre_id,
            MapOrgLevelCadre.is_active.is_(True),
        )
    )


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


_WORKER_CODING_ROLES = frozenset({
    VaAccessRoles.coder,
    VaAccessRoles.reviewer,
    VaAccessRoles.coding_tester,
})
_WORKER_SUPERVISION_ROLES = frozenset({
    VaAccessRoles.interview_supervisor,
})


def list_workers(project_id: str, *, include_inactive: bool = False, org_unit_id: object | None = None) -> list[dict]:
    stmt = (
        sa.select(MasOrgUnitWorker, MasOrgUnit, MasCadre, VaUsers.email)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .outerjoin(VaUsers, VaUsers.user_id == MasOrgUnitWorker.user_id)
        .where(MasOrgUnitWorker.project_id == project_id)
    )
    if org_unit_id:
        stmt = stmt.where(MasOrgUnitWorker.org_unit_id == _uuid(org_unit_id, what="Unit id"))
    if not include_inactive:
        stmt = stmt.where(MasOrgUnitWorker.is_active.is_(True))
    rows = db.session.execute(stmt.order_by(MasOrgUnit.path, MasOrgUnitWorker.worker_code)).all()
    user_ids = {worker.user_id for worker, _, _, _ in rows if worker.user_id is not None}
    grants_by_user: dict[uuid.UUID, list[tuple[VaAccessRoles, uuid.UUID, str, uuid.UUID]]] = {}
    if user_ids:
        grant_rows = db.session.execute(
            sa.select(
                VaUserAccessGrants.user_id,
                VaUserAccessGrants.role,
                MasOrgUnit.org_unit_id,
                MasOrgUnit.unit_code,
                MasOrgUnit.org_level_id,
            )
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(
                VaUserAccessGrants.user_id.in_(user_ids),
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.is_active.is_(True),
            )
            .order_by(MasOrgUnit.path)
        ).all()
        for uid, role, u_id, u_code, u_level_id in grant_rows:
            grants_by_user.setdefault(uid, []).append((role, u_id, u_code, u_level_id))

    result = []
    for worker, unit, cadre, email in rows:
        coding_ids: list[str] = []
        coding_codes: list[str] = []
        sup_ids: list[str] = []
        sup_codes: list[str] = []
        roles_set: set[str] = set()
        if worker.user_id and worker.user_id in grants_by_user:
            for role, u_id, u_code, u_level_id in grants_by_user[worker.user_id]:
                roles_set.add(role.value if hasattr(role, "value") else str(role))
                u_id_str = str(u_id)
                if u_level_id == unit.org_level_id:
                    if role in _WORKER_CODING_ROLES and u_id_str not in coding_ids:
                        coding_ids.append(u_id_str)
                        coding_codes.append(u_code)
                    if role in _WORKER_SUPERVISION_ROLES and u_id_str not in sup_ids:
                        sup_ids.append(u_id_str)
                        sup_codes.append(u_code)
        result.append(
            serialize_worker(
                worker,
                unit=unit,
                cadre=cadre,
                user_email=email,
                coding_unit_ids=coding_ids,
                coding_unit_codes=coding_codes,
                supervision_unit_ids=sup_ids,
                supervision_unit_codes=sup_codes,
                active_roles=sorted(roles_set),
            )
        )
    return result


def _get_worker(project_id: str, worker_id: object) -> MasOrgUnitWorker:
    worker = db.session.get(MasOrgUnitWorker, _uuid(worker_id, what="Worker id"))
    if worker is None or worker.project_id != project_id:
        raise OrganizationError("Worker not found in this project.")
    return worker


def _require_cadre_at_unit_level(unit: MasOrgUnit, cadre: MasCadre) -> None:
    if not cadre.is_active:
        raise OrganizationError(f"Cadre {cadre.cadre_code!r} is inactive.")
    if get_level_cadre_permission(unit.org_level_id, cadre.cadre_id) is None:
        raise OrganizationError(
            f"Cadre {cadre.cadre_code!r} is not defined at level {unit.level.level_code!r}; "
            "add it in the level permissions grid first."
        )


def resolve_user(raw: object, *, require_active: bool = True) -> VaUsers | None:
    """Resolve a worker account, refusing inactive accounts by default.

    Existing worker links may point to an account that was deactivated later;
    callers updating that worker can pass ``require_active=False`` and decide
    whether the link is unchanged. New links must use the default guard.
    """
    if isinstance(raw, VaUsers):
        user = raw
    else:
        value = str(raw or "").strip()
        if not value:
            return None
        user = None
        try:
            user = db.session.get(VaUsers, uuid.UUID(value))
        except ValueError:
            user = db.session.scalar(sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == value.lower()))
        if user is None:
            raise OrganizationError(f"DigitVA user not found: {value}")
    if require_active and user.user_status != VaStatuses.active:
        raise OrganizationError("DigitVA user is inactive.")
    return user


def _resolve_user(raw: object) -> VaUsers | None:
    """Backward-compatible private alias for existing import callers."""
    return resolve_user(raw)


def _next_worker_code(project_id: str) -> str:
    """Next free generated code, W00001, W00002, ... (one scan of this project's codes)."""
    codes = db.session.scalars(
        sa.select(MasOrgUnitWorker.worker_code).where(
            MasOrgUnitWorker.project_id == project_id, MasOrgUnitWorker.worker_code.like("W%")
        )
    ).all()
    numbers = [int(c[1:]) for c in codes if c[1:].isdigit()]
    return f"W{(max(numbers, default=0) + 1):05d}"


def create_worker(
    project_id: str,
    *,
    org_unit_id: object,
    cadre_id: object,
    worker_name: object,
    worker_code: object = None,
    phone: object = None,
    user: object = None,
    remarks: object = None,
) -> MasOrgUnitWorker:
    _get_project(project_id)
    unit = _get_unit(project_id, org_unit_id)
    cadre = _get_cadre(project_id, cadre_id)
    _require_cadre_at_unit_level(unit, cadre)
    # The code is an internal key (import matching); admins need not give one.
    if worker_code is None or not str(worker_code).strip():
        code = _next_worker_code(project_id)
    else:
        code = normalize_code(worker_code, what="Worker code")
    dup = db.session.scalar(
        sa.select(MasOrgUnitWorker.worker_id).where(
            MasOrgUnitWorker.project_id == project_id, MasOrgUnitWorker.worker_code == code
        )
    )
    if dup is not None:
        raise OrganizationError(f"Worker code {code!r} already exists in this project.")
    resolved_user = resolve_user(user)
    worker = MasOrgUnitWorker(
        project_id=project_id,
        org_unit_id=unit.org_unit_id,
        cadre_id=cadre.cadre_id,
        worker_code=code,
        worker_name=_clean_text(worker_name, required=True, what="Worker name"),
        phone=_clean_text(phone, max_len=32, what="Phone"),
        user_id=resolved_user.user_id if resolved_user else None,
        remarks=_clean_text(remarks, what="Remarks"),
    )
    db.session.add(worker)
    db.session.flush()
    return worker


def update_worker(project_id: str, worker_id: object, **fields) -> MasOrgUnitWorker:
    worker = _get_worker(project_id, worker_id)
    resolved_user = None
    if "user" in fields:
        # Resolve before mutating any other worker field so a refused relink
        # leaves the in-memory object unchanged for direct service callers.
        resolved_user = resolve_user(fields["user"], require_active=False)
        if (
            resolved_user is not None
            and resolved_user.user_status != VaStatuses.active
            and resolved_user.user_id != worker.user_id
        ):
            raise OrganizationError("DigitVA user is inactive.")
    unit = worker.unit
    cadre = worker.cadre
    if "org_unit_id" in fields and fields["org_unit_id"]:
        unit = _get_unit(project_id, fields["org_unit_id"])
    if "cadre_id" in fields and fields["cadre_id"]:
        cadre = _get_cadre(project_id, fields["cadre_id"])
    if unit.org_unit_id != worker.org_unit_id or cadre.cadre_id != worker.cadre_id:
        _require_cadre_at_unit_level(unit, cadre)
        worker.org_unit_id = unit.org_unit_id
        worker.cadre_id = cadre.cadre_id
    if "worker_code" in fields and fields["worker_code"] is not None:
        new_code = normalize_code(fields["worker_code"], what="Worker code")
        if new_code != worker.worker_code:
            dup = db.session.scalar(
                sa.select(MasOrgUnitWorker.worker_id).where(
                    MasOrgUnitWorker.project_id == project_id, MasOrgUnitWorker.worker_code == new_code
                )
            )
            if dup is not None:
                raise OrganizationError(f"Worker code {new_code!r} already exists in this project.")
            worker.worker_code = new_code
    if "worker_name" in fields:
        worker.worker_name = _clean_text(fields["worker_name"], required=True, what="Worker name")
    if "phone" in fields:
        worker.phone = _clean_text(fields["phone"], max_len=32, what="Phone")
    if "user" in fields:
        # Editing an existing worker must not unexpectedly unlink it just
        # because the linked account was deactivated after the original link.
        worker.user_id = resolved_user.user_id if resolved_user else None
    if "remarks" in fields:
        worker.remarks = _clean_text(fields["remarks"], what="Remarks")
    if "is_active" in fields:
        worker.is_active = bool(fields["is_active"])
    db.session.flush()
    return worker


# ---------------------------------------------------------------------------
# Seed template
# ---------------------------------------------------------------------------


def seed_default_organization(project_id: str, *, include_cadres: bool = True) -> dict[str, int]:
    """Additively add the template levels, cadres and level x cadre rows.

    Only what is missing is created: an existing level (by code or depth),
    cadre or grid row is never changed, so flags an admin set survive a
    rerun. Returns how many of each were created.
    """
    _get_project(project_id)
    counts = {"levels": 0, "cadres": 0, "level_cadres": 0}
    existing_levels = {lv.level_code: lv for lv in list_levels(project_id, include_inactive=True)}
    used_depths = {lv.depth for lv in existing_levels.values()}
    for code, name, depth, optional in DEFAULT_LEVEL_TEMPLATE:
        if code in existing_levels or depth in used_depths:
            continue
        existing_levels[code] = create_level(
            project_id, level_code=code, level_name=name, depth=depth, is_optional=optional
        )
        used_depths.add(depth)
        counts["levels"] += 1
    if not include_cadres:
        return counts
    existing_cadres = {c.cadre_code: c for c in list_cadres(project_id, include_inactive=True)}
    for code, name in DEFAULT_CADRE_TEMPLATE:
        if code in existing_cadres:
            continue
        existing_cadres[code] = create_cadre(project_id, cadre_code=code, cadre_name=name)
        counts["cadres"] += 1
    existing_pairs = set(
        db.session.execute(
            sa.select(MapOrgLevelCadre.org_level_id, MapOrgLevelCadre.cadre_id)
            .join(MasOrgLevel, MasOrgLevel.org_level_id == MapOrgLevelCadre.org_level_id)
            .where(MasOrgLevel.project_id == project_id)
        ).all()
    )
    for (level_code, cadre_code), (can_fill, can_code, can_supervise, can_report) in DEFAULT_LEVEL_CADRE_TEMPLATE.items():
        level = existing_levels.get(level_code)
        cadre = existing_cadres.get(cadre_code)
        if level is None or cadre is None or (level.org_level_id, cadre.cadre_id) in existing_pairs:
            continue
        upsert_level_cadre(
            project_id,
            org_level_id=level.org_level_id,
            cadre_id=cadre.cadre_id,
            can_fill_va_form=can_fill,
            can_code_va_form=can_code,
            can_supervise_interviews=can_supervise,
            can_report_deaths=can_report,
            default_roles=DEFAULT_TYPICAL_ROLES.get((level_code, cadre_code), ()),
        )
        counts["level_cadres"] += 1
    db.session.flush()
    return counts


def district_reference_model() -> dict:
    """The seed template as display data for the Organization page.

    Pure (no database): levels, cadres and one row per grid entry with its
    flags and the default roles a new project's grid is seeded with. Default
    roles are pre-ticked in grant forms and never used to decide access.
    """
    level_names = {code: name for code, name, _depth, _optional in DEFAULT_LEVEL_TEMPLATE}
    cadre_names = dict(DEFAULT_CADRE_TEMPLATE)
    grid = []
    for (level_code, cadre_code), (can_fill, can_code, can_supervise, can_report) in DEFAULT_LEVEL_CADRE_TEMPLATE.items():
        roles = DEFAULT_TYPICAL_ROLES.get((level_code, cadre_code), ())
        grid.append(
            {
                "level_code": level_code,
                "level_name": level_names[level_code],
                "cadre_code": cadre_code,
                "cadre_name": cadre_names[cadre_code],
                "can_fill_va_form": can_fill,
                "can_code_va_form": can_code,
                "can_supervise_interviews": can_supervise,
                "can_report_deaths": can_report,
                "typical_roles": list(roles),
            }
        )
    return {
        "levels": [
            {"level_code": code, "level_name": name, "depth": depth, "is_optional": optional}
            for code, name, depth, optional in DEFAULT_LEVEL_TEMPLATE
        ],
        "cadres": [{"cadre_code": code, "cadre_name": name} for code, name in DEFAULT_CADRE_TEMPLATE],
        "grid": grid,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

_LEVEL_HEADERS = ("level_code", "level_name", "depth", "is_optional", "is_active", "odk_field_name")
_UNIT_HEADERS = (
    "unit_code", "unit_name", "level_code", "parent_code", "path", "address", "phone",
    "latitude", "longitude", "google_maps_url", "remarks", "is_active",
)
_CADRE_HEADERS = ("cadre_code", "cadre_name", "is_active")
_LEVEL_CADRE_HEADERS = (
    "level_code", "cadre_code", "can_fill_va_form", "can_code_va_form", "can_supervise_interviews",
    "can_report_deaths", "default_roles", "is_active",
)
# Separates the role names in the default_roles cell of the level_cadres sheet.
_DEFAULT_ROLES_SEPARATOR = "|"
_WORKER_HEADERS = (
    "worker_code", "worker_name", "unit_code", "cadre_code", "phone", "user_email", "remarks", "is_active",
)


def export_organization_rows(project_id: str) -> dict[str, list[dict]]:
    """All master data of one project as plain rows keyed by sheet name."""
    _get_project(project_id)
    levels = [serialize_level(lv) for lv in list_levels(project_id, include_inactive=True)]
    units = list_units(project_id, include_inactive=True)
    cadres = [serialize_cadre(c) for c in list_cadres(project_id, include_inactive=True)]
    level_cadres = list_level_cadres(project_id)
    workers = list_workers(project_id, include_inactive=True)
    return {
        "levels": [{k: lv[k] for k in _LEVEL_HEADERS} for lv in levels],
        "units": [{k: u[k] for k in _UNIT_HEADERS} for u in units],
        "cadres": [{k: c[k] for k in _CADRE_HEADERS} for c in cadres],
        "level_cadres": [
            {k: _DEFAULT_ROLES_SEPARATOR.join(lc[k]) if k == "default_roles" else lc[k] for k in _LEVEL_CADRE_HEADERS}
            for lc in level_cadres
        ],
        "workers": [{k: w[k] for k in _WORKER_HEADERS} for w in workers],
    }


def _spreadsheet_safe(value, column=None):
    """Keep exported text from becoming a formula when opened in a spreadsheet."""
    if column in {"latitude", "longitude"} and isinstance(value, str):
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            return value
    if isinstance(value, str) and value.lstrip()[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def export_organization_xlsx(project_id: str) -> bytes:
    rows = export_organization_rows(project_id)
    headers = {
        "levels": _LEVEL_HEADERS,
        "units": _UNIT_HEADERS,
        "cadres": _CADRE_HEADERS,
        "level_cadres": _LEVEL_CADRE_HEADERS,
        "workers": _WORKER_HEADERS,
    }
    workbook = Workbook()
    first = True
    for sheet_name in EXPORT_SHEETS:
        sheet = workbook.active if first else workbook.create_sheet()
        first = False
        sheet.title = sheet_name
        sheet.append(list(headers[sheet_name]))
        for row in rows[sheet_name]:
            sheet.append([_spreadsheet_safe(row.get(col), col) for col in headers[sheet_name]])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_organization_csv(project_id: str, sheet: str) -> str:
    if sheet not in EXPORT_SHEETS:
        raise OrganizationError(f"Unknown sheet {sheet!r}; choose one of {', '.join(EXPORT_SHEETS)}.")
    rows = export_organization_rows(project_id)[sheet]
    headers = {
        "levels": _LEVEL_HEADERS,
        "units": _UNIT_HEADERS,
        "cadres": _CADRE_HEADERS,
        "level_cadres": _LEVEL_CADRE_HEADERS,
        "workers": _WORKER_HEADERS,
    }[sheet]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(headers))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else _spreadsheet_safe(row.get(k), k)) for k in headers})
    return buffer.getvalue()


def export_odk_choices_rows(project_id: str, *, parent_at_required_level: bool = False) -> list[dict]:
    """XLSForm ``choices`` rows: one list per level, filtered by parent code.

    ``list_name`` is ``org_<level_code>``; ``name`` is the unit code; ``label``
    the unit name; ``parent_code`` is the filter column for cascading selects.
    The matching survey fields are ``org_<level_code>_code``.

    By default ``parent_code`` is the direct parent (the shared choices CSV:
    forms authored outside DigitVA filter on it). ``parent_at_required_level``
    gives instead the nearest active ancestor at a required level, or ``""``:
    the generated XLSForm filters every level on the nearest required level
    above it, so a unit placed under an optional level (a CHC under an SDH) or
    skipping it (a CHC directly under the DH) stays reachable either way.
    """
    levels = {lv.org_level_id: lv for lv in list_levels(project_id)}
    units = list_units(project_id)
    required_codes: set[str] = set()
    if parent_at_required_level:
        for unit in units:
            level = levels.get(uuid.UUID(unit["org_level_id"]))
            if level is not None and not level.is_optional:
                required_codes.add(unit["unit_code"])
    rows: list[dict] = []
    for unit in units:
        level = levels.get(uuid.UUID(unit["org_level_id"]))
        if level is None:
            continue
        parent_code = unit["parent_code"] or ""
        if parent_at_required_level:
            # path is the ltree of unit codes, self last. An inactive ancestor
            # is not in required_codes and is skipped: it is not selectable.
            ancestors = unit["path"].split(".")[:-1]
            parent_code = next((code for code in reversed(ancestors) if code in required_codes), "")
        rows.append(
            {
                "list_name": f"org_{level.level_code}",
                "name": unit["unit_code"],
                "label": unit["unit_name"],
                "parent_code": parent_code,
            }
        )
    return rows


def export_odk_choices_csv(project_id: str) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["list_name", "name", "label", "parent_code"])
    writer.writeheader()
    for row in export_odk_choices_rows(project_id):
        writer.writerow({key: _spreadsheet_safe(value) for key, value in row.items()})
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Import (dry run first, then apply)
# ---------------------------------------------------------------------------


@dataclass
class ImportPlan:
    sheets: dict[str, list[dict]] = field(default_factory=dict)
    creates: dict[str, list[str]] = field(default_factory=dict)
    updates: dict[str, list[str]] = field(default_factory=dict)
    deactivates: dict[str, list[str]] = field(default_factory=dict)
    #: Active units left with no parent below the top level after the import.
    unplaced: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    applied: bool = False

    def as_dict(self) -> dict:
        return {
            "creates": self.creates,
            "updates": self.updates,
            "deactivates": self.deactivates,
            "unplaced": self.unplaced,
            "errors": self.errors,
            "applied": self.applied,
            "counts": {
                sheet: {
                    "rows": len(self.sheets.get(sheet, [])),
                    "create": len(self.creates.get(sheet, [])),
                    "update": len(self.updates.get(sheet, [])),
                    "deactivate": len(self.deactivates.get(sheet, [])),
                }
                for sheet in EXPORT_SHEETS
            },
        }


def parse_organization_workbook(file_obj) -> dict[str, list[dict]]:
    """Read the export workbook back into rows keyed by sheet; missing sheets are skipped."""
    raw = file_obj.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise OrganizationError("Workbook exceeds the 5 MB limit.")
    try:
        validate_xlsx(raw, max_rows=10000, max_columns=max(len(h) for h in
                      (_LEVEL_HEADERS, _UNIT_HEADERS, _CADRE_HEADERS, _LEVEL_CADRE_HEADERS, _WORKER_HEADERS)))
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    except (TabularImportError, ValueError, OSError, KeyError) as exc:
        raise OrganizationError("The XLSX workbook could not be read.") from exc
    sheets: dict[str, list[dict]] = {}
    headers = {"levels": _LEVEL_HEADERS, "units": _UNIT_HEADERS,
               "cadres": _CADRE_HEADERS, "level_cadres": _LEVEL_CADRE_HEADERS,
               "workers": _WORKER_HEADERS}
    try:
        for sheet_name in EXPORT_SHEETS:
            if sheet_name not in workbook.sheetnames:
                continue
            worksheet = workbook[sheet_name]
            if ((worksheet.max_row or 0) > 20001 or
                    (worksheet.max_column or 0) > len(headers[sheet_name]) + 16):
                raise OrganizationError("The XLSX worksheet dimensions exceed the import limit.")
            sheets[sheet_name] = parse_rows(
                worksheet.iter_rows(values_only=True), headers[sheet_name],
                max_rows=10000,
            )
    except TabularImportError as exc:
        raise OrganizationError(str(exc)) from exc
    finally:
        workbook.close()
    return sheets


def parse_organization_csv(file_obj, sheet: str) -> dict[str, list[dict]]:
    """Read one sheet's CSV (the per-sheet export layout) into import rows.

    Blank cells become None, as empty workbook cells do, so an empty
    ``is_active`` keeps the existing value instead of reading as false.
    """
    if sheet not in EXPORT_SHEETS:
        raise OrganizationError(f"Unknown sheet {sheet!r}; choose one of {', '.join(EXPORT_SHEETS)}.")
    headers = {"levels": _LEVEL_HEADERS, "units": _UNIT_HEADERS,
               "cadres": _CADRE_HEADERS, "level_cadres": _LEVEL_CADRE_HEADERS,
               "workers": _WORKER_HEADERS}
    try:
        return {sheet: parse_table(file_obj, "organization.csv", headers[sheet],
                                   max_bytes=5 * 1024 * 1024, max_rows=10000)}
    except TabularImportError as exc:
        raise OrganizationError(str(exc)) from exc


def parse_units_upload(file_obj, filename):
    """Read the first sheet of a guided units file with bounded validation."""
    try:
        rows = parse_table(file_obj, filename, tuple(h for h in _UNIT_HEADERS if h != "path"),
                           max_bytes=5 * 1024 * 1024, max_rows=10000)
    except TabularImportError as exc:
        raise OrganizationError(str(exc)) from exc
    return {"units": rows}


def import_organization(project_id: str, sheets: dict[str, list[dict]], *, dry_run: bool = True, deactivate_missing: bool = False) -> ImportPlan:
    """Upsert master data by business codes. Never deletes.

    With ``deactivate_missing`` rows absent from a supplied sheet are
    deactivated. Runs inside a SAVEPOINT so a dry run or a failed import
    leaves nothing behind.
    """
    _get_project(project_id)
    plan = ImportPlan(sheets=sheets)
    for sheet in EXPORT_SHEETS:
        plan.creates[sheet] = []
        plan.updates[sheet] = []
        plan.deactivates[sheet] = []

    savepoint = db.session.begin_nested()
    try:
        _import_levels(project_id, sheets.get("levels"), plan, deactivate_missing)
        _import_cadres(project_id, sheets.get("cadres"), plan, deactivate_missing)
        # Level-cadre deactivations wait until workers are imported, so a
        # file that retires a level-cadre and deactivates its workers
        # together is not refused by the active-worker guard.
        deferred_level_cadres = _import_level_cadres(
            project_id, sheets.get("level_cadres"), plan, deactivate_missing
        )
        _import_units(project_id, sheets.get("units"), plan, deactivate_missing)
        if sheets.get("units") is not None:
            plan.unplaced = unplaced_unit_codes(project_id)
        _import_workers(project_id, sheets.get("workers"), plan, deactivate_missing)
        for label, kwargs in deferred_level_cadres:
            try:
                upsert_level_cadre(project_id, **kwargs)
            except OrganizationError as exc:
                raise OrganizationError(f"{label}: {exc}") from exc
    except OrganizationError as exc:
        plan.errors.append(str(exc))
    if plan.errors or dry_run:
        savepoint.rollback()
        return plan
    savepoint.commit()
    plan.applied = True
    return plan


def _import_levels(project_id, rows, plan, deactivate_missing):
    if rows is None:
        return
    existing = {lv.level_code: lv for lv in list_levels(project_id, include_inactive=True)}
    seen = set()
    for i, row in enumerate(rows, start=2):
        try:
            code = normalize_level_code(row.get("level_code"))
            seen.add(code)
            if code in existing:
                lv = existing[code]
                update_level(
                    project_id,
                    lv.org_level_id,
                    level_name=row.get("level_name") or lv.level_name,
                    is_optional=_to_bool(row.get("is_optional"), what="is_optional"),
                    is_active=_to_bool(row["is_active"], what="is_active") if row.get("is_active") not in (None, "") else lv.is_active,
                    **({"depth": row.get("depth")} if row.get("depth") not in (None, "") else {}),
                )
                plan.updates["levels"].append(code)
            else:
                is_active = _to_bool(row["is_active"], what="is_active") if row.get("is_active") not in (None, "") else True
                existing[code] = create_level(
                    project_id,
                    level_code=code,
                    level_name=row.get("level_name"),
                    depth=row.get("depth"),
                    is_optional=_to_bool(row.get("is_optional"), what="is_optional"),
                )
                existing[code].is_active = is_active
                plan.creates["levels"].append(code)
        except OrganizationError as exc:
            raise OrganizationError(f"levels row {i}: {exc}") from exc
    if deactivate_missing:
        for code, lv in existing.items():
            if code not in seen and lv.is_active:
                update_level(project_id, lv.org_level_id, is_active=False)
                plan.deactivates["levels"].append(code)


def _import_cadres(project_id, rows, plan, deactivate_missing):
    if rows is None:
        return
    existing = {c.cadre_code: c for c in list_cadres(project_id, include_inactive=True)}
    seen = set()
    for i, row in enumerate(rows, start=2):
        try:
            code = normalize_code(row.get("cadre_code"), what="Cadre code")
            seen.add(code)
            if code in existing:
                c = existing[code]
                update_cadre(
                    project_id,
                    c.cadre_id,
                    cadre_name=row.get("cadre_name") or c.cadre_name,
                    is_active=_to_bool(row["is_active"], what="is_active") if row.get("is_active") not in (None, "") else c.is_active,
                )
                plan.updates["cadres"].append(code)
            else:
                is_active = _to_bool(row["is_active"], what="is_active") if row.get("is_active") not in (None, "") else True
                existing[code] = create_cadre(project_id, cadre_code=code, cadre_name=row.get("cadre_name"))
                existing[code].is_active = is_active
                plan.creates["cadres"].append(code)
        except OrganizationError as exc:
            raise OrganizationError(f"cadres row {i}: {exc}") from exc
    if deactivate_missing:
        for code, c in existing.items():
            if code not in seen and c.is_active:
                update_cadre(project_id, c.cadre_id, is_active=False)
                plan.deactivates["cadres"].append(code)


def _import_level_cadres(project_id, rows, plan, deactivate_missing):
    """Apply level-cadre rows; return the deactivations as (label, kwargs)
    for the caller to apply after workers."""
    deferred = []
    if rows is None:
        return deferred
    levels = {lv.level_code: lv for lv in list_levels(project_id, include_inactive=True)}
    cadres = {c.cadre_code: c for c in list_cadres(project_id, include_inactive=True)}
    existing = {(lc["level_code"], lc["cadre_code"]): lc for lc in list_level_cadres(project_id)}
    seen = set()
    for i, row in enumerate(rows, start=2):
        try:
            level_code = normalize_level_code(row.get("level_code"))
            cadre_code = normalize_code(row.get("cadre_code"), what="Cadre code")
            level = levels.get(level_code)
            cadre = cadres.get(cadre_code)
            if level is None:
                raise OrganizationError(f"unknown level {level_code!r}")
            if cadre is None:
                raise OrganizationError(f"unknown cadre {cadre_code!r}")
            key = (level_code, cadre_code)
            seen.add(key)
            kwargs = dict(
                org_level_id=level.org_level_id,
                cadre_id=cadre.cadre_id,
                can_fill_va_form=_to_bool(row.get("can_fill_va_form"), what="can_fill_va_form"),
                can_code_va_form=_to_bool(row.get("can_code_va_form"), what="can_code_va_form"),
                # Blank or absent (an older workbook) keeps the current value.
                can_supervise_interviews=(
                    None if row.get("can_supervise_interviews") in (None, "")
                    else _to_bool(row["can_supervise_interviews"], what="can_supervise_interviews")
                ),
                can_report_deaths=(
                    None if row.get("can_report_deaths") in (None, "")
                    else _to_bool(row["can_report_deaths"], what="can_report_deaths")
                ),
                # Blank or absent keeps the current defaults; the grid editor clears them.
                default_roles=(
                    None if str(row.get("default_roles") or "").strip() == ""
                    else str(row["default_roles"]).split(_DEFAULT_ROLES_SEPARATOR)
                ),
                is_active=_to_bool(row["is_active"], what="is_active") if row.get("is_active") not in (None, "") else True,
            )
            if kwargs["is_active"]:
                upsert_level_cadre(project_id, **kwargs)
            else:
                deferred.append((f"level_cadres row {i}", kwargs))
            (plan.updates if key in existing else plan.creates)["level_cadres"].append(f"{level_code}/{cadre_code}")
        except OrganizationError as exc:
            raise OrganizationError(f"level_cadres row {i}: {exc}") from exc
    if deactivate_missing:
        for key, lc in existing.items():
            if key not in seen and lc["is_active"]:
                deferred.append((
                    f"level_cadres {key[0]}/{key[1]}",
                    dict(
                        org_level_id=lc["org_level_id"],
                        cadre_id=lc["cadre_id"],
                        can_fill_va_form=lc["can_fill_va_form"],
                        can_code_va_form=lc["can_code_va_form"],
                        can_supervise_interviews=lc["can_supervise_interviews"],
                        can_report_deaths=lc["can_report_deaths"],
                        default_roles=lc["default_roles"],
                        is_active=False,
                    ),
                ))
                plan.deactivates["level_cadres"].append(f"{key[0]}/{key[1]}")
    return deferred


def _import_units(project_id, rows, plan, deactivate_missing):
    if rows is None:
        return
    levels = {lv.level_code: lv for lv in list_levels(project_id, include_inactive=True)}
    existing = {u["unit_code"]: u for u in list_units(project_id, include_inactive=True)}
    top_depth = _top_level_depth(project_id)
    seen = set()
    deactivate_after_create = []
    explicitly_active = []
    # Parents must exist before children: sort by level depth, keep file order otherwise.
    indexed = []
    for i, row in enumerate(rows, start=2):
        level_code = str(row.get("level_code") or "").strip().lower()
        depth = levels[level_code].depth if level_code in levels else 10**6
        indexed.append((depth, i, row))
    indexed.sort(key=lambda t: (t[0], t[1]))
    for _, i, row in indexed:
        try:
            code = normalize_code(row.get("unit_code"), what="Unit code")
            if code in seen:
                raise OrganizationError(f"duplicate unit code {code!r}")
            level = levels.get(normalize_level_code(row.get("level_code")))
            if level is None:
                raise OrganizationError(f"unknown level {row.get('level_code')!r}")
            parent_code = str(row.get("parent_code") or "").strip().upper()
            parent_id = existing[parent_code]["org_unit_id"] if parent_code in existing else None
            if parent_code and parent_id is None:
                raise OrganizationError(f"unknown parent unit {parent_code!r}")
            # A blank parent_code never detaches: an existing unit keeps its
            # parent, a new one below the top level is created unplaced.
            placement = {"parent_org_unit_id": parent_id} if parent_code else {}
            seen.add(code)
            active_raw = row.get("is_active")
            active = _to_bool(active_raw, what="is_active") if active_raw not in (None, "") else None
            fields = dict(
                unit_name=row.get("unit_name"),
                address=row.get("address"),
                phone=row.get("phone"),
                latitude=row.get("latitude"),
                longitude=row.get("longitude"),
                google_maps_url=row.get("google_maps_url"),
                remarks=row.get("remarks"),
            )
            if code in existing:
                update_fields = dict(
                    org_level_id=level.org_level_id,
                    allow_unplaced=True,
                    **placement,
                    **fields,
                )
                if active is True:
                    update_fields["is_active"] = True
                update_unit(
                    project_id,
                    existing[code]["org_unit_id"],
                    **update_fields,
                )
                if active is False:
                    deactivate_after_create.append((i, code, existing[code]["org_unit_id"]))
                elif active is True:
                    explicitly_active.append((i, code, existing[code]["org_unit_id"]))
                plan.updates["units"].append(code)
            else:
                unit = create_unit(
                    project_id,
                    org_level_id=level.org_level_id,
                    unit_code=code,
                    parent_org_unit_id=parent_id,
                    allow_unplaced=True,
                    **fields,
                )
                existing[code] = serialize_unit(unit, level=level, parent_code=parent_code or None, top_depth=top_depth)
                if active is False:
                    deactivate_after_create.append((i, code, unit.org_unit_id))
                elif active is True:
                    explicitly_active.append((i, code, unit.org_unit_id))
                plan.creates["units"].append(code)
        except OrganizationError as exc:
            raise OrganizationError(f"units row {i}: {exc}") from exc
    for i, code, unit_id in deactivate_after_create:
        try:
            set_unit_active(project_id, unit_id, False)
        except OrganizationError as exc:
            raise OrganizationError(f"units row {i} ({code}): {exc}") from exc
    if deactivate_after_create and explicitly_active:
        active_by_id = dict(db.session.execute(
            sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.is_active).where(
                MasOrgUnit.org_unit_id.in_([
                    uuid.UUID(str(unit_id)) for _, _, unit_id in explicitly_active
                ])
            )
        ).all())
        for i, code, unit_id in explicitly_active:
            if not active_by_id.get(uuid.UUID(str(unit_id)), False):
                raise OrganizationError(
                    f"units row {i} ({code}): an active unit cannot be beneath an inactive unit"
                )
    if deactivate_missing:
        for code, u in existing.items():
            if code not in seen and u["is_active"]:
                current = db.session.get(MasOrgUnit, uuid.UUID(u["org_unit_id"]))
                if current is not None and current.is_active:
                    set_unit_active(project_id, current.org_unit_id, False)
                    plan.deactivates["units"].append(code)


def _import_workers(project_id, rows, plan, deactivate_missing):
    if rows is None:
        return
    cadres = {c.cadre_code: c for c in list_cadres(project_id, include_inactive=True)}
    units_by_code = {u["unit_code"]: u["org_unit_id"] for u in list_units(project_id, include_inactive=True)}
    existing = {w["worker_code"]: w for w in list_workers(project_id, include_inactive=True)}
    # Rows without a worker_code match an existing worker by unit and name.
    by_unit_name = {(w["org_unit_id"], (w["worker_name"] or "").strip().casefold()): w["worker_code"] for w in existing.values()}
    seen = set()
    for i, row in enumerate(rows, start=2):
        try:
            unit_id = units_by_code.get(str(row.get("unit_code") or "").strip().upper())
            if unit_id is None:
                raise OrganizationError(f"unknown unit {row.get('unit_code')!r}")
            if str(row.get("worker_code") or "").strip():
                code = normalize_code(row.get("worker_code"), what="Worker code")
            else:
                name_key = (unit_id, str(row.get("worker_name") or "").strip().casefold())
                code = by_unit_name.get(name_key) or _next_worker_code(project_id)
                by_unit_name[name_key] = code
            cadre = cadres.get(normalize_code(row.get("cadre_code"), what="Cadre code"))
            if cadre is None:
                raise OrganizationError(f"unknown cadre {row.get('cadre_code')!r}")
            seen.add(code)
            is_active = _to_bool(row["is_active"], what="is_active") if row.get("is_active") not in (None, "") else None
            fields = dict(
                worker_name=row.get("worker_name"),
                phone=row.get("phone"),
                user=row.get("user_email"),
                remarks=row.get("remarks"),
            )
            if code in existing:
                update_worker(
                    project_id,
                    existing[code]["worker_id"],
                    org_unit_id=unit_id,
                    cadre_id=cadre.cadre_id,
                    is_active=is_active if is_active is not None else existing[code]["is_active"],
                    **fields,
                )
                plan.updates["workers"].append(code)
            else:
                worker = create_worker(
                    project_id,
                    org_unit_id=unit_id,
                    cadre_id=cadre.cadre_id,
                    worker_code=code,
                    **fields,
                )
                if is_active is False:
                    worker.is_active = False
                if not str(row.get("worker_code") or "").strip():
                    # A repeat of this code-less row later in the file updates it.
                    existing[code] = {
                        "worker_id": str(worker.worker_id),
                        "is_active": is_active is not False,
                    }
                plan.creates["workers"].append(code)
        except OrganizationError as exc:
            raise OrganizationError(f"workers row {i}: {exc}") from exc
    if deactivate_missing:
        for code, w in existing.items():
            if code not in seen and w["is_active"]:
                update_worker(project_id, w["worker_id"], is_active=False)
                plan.deactivates["workers"].append(code)


# ---------------------------------------------------------------------------
# My organization page (digitva-e7sz). Read-only; names and cadres only.
# Policy: docs/policy/organization-model.md, "Who sees worker names".
# ---------------------------------------------------------------------------

#: Most people returned for one unit. Bounds the response, not the roster.
MY_ORG_PEOPLE_CAP = 500


def _granted_project_ids(user) -> set[str]:
    """Active projects in which the user holds any live grant, from authz's
    resolved grants (closed projects and inactive grants are already out).

    Not gated on ``effective_roles``: a grant whose role gate is still closed
    (an interviewer on a project with no form yet) still lists its project.
    Demo-training grants are virtual and do not count. ``resolve_grants`` does
    not mark the request consulted itself, so this does it, as the other
    services that read resolved grants do.
    """
    return set(_granted(user)[0])


def _granted(user) -> tuple[dict[str, list], authz.ResolvedGrants]:
    """The user's live explicit grants grouped by project, and the resolved
    grants they came from (see ``_granted_project_ids``)."""
    mark_consulted()
    resolved = authz.resolve_grants(user)
    by_project: dict[str, list] = {}
    for grant in resolved.grants:
        if not grant.virtual:
            by_project.setdefault(grant.project_id, []).append(grant)
    return by_project, resolved


def _my_units(user_id: uuid.UUID, project_id: str) -> dict[str, dict]:
    """Units the user is placed at in *project_id*: its unit grants and its own
    worker rows. Keyed by unit id; one query whatever the unit count. Each
    entry carries ``roles``: ``{role value: cadre name or None}`` from the unit
    grants (a worker row adds a cadre, no role).
    """
    grant_stmt = (
        sa.select(
            MasOrgUnit.org_unit_id.label("org_unit_id"),
            MasCadre.cadre_name.label("cadre_name"),
            sa.cast(VaUserAccessGrants.role, sa.Text).label("role"),
        )
        .select_from(VaUserAccessGrants)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .outerjoin(MasCadre, MasCadre.cadre_id == VaUserAccessGrants.cadre_id)
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.is_active.is_(True),
        )
    )
    worker_stmt = (
        sa.select(
            MasOrgUnit.org_unit_id.label("org_unit_id"),
            MasCadre.cadre_name.label("cadre_name"),
            sa.cast(sa.null(), sa.Text).label("role"),
        )
        .select_from(MasOrgUnitWorker)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .where(
            MasOrgUnitWorker.user_id == user_id,
            MasOrgUnitWorker.is_active.is_(True),
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.is_active.is_(True),
        )
    )
    combined = sa.union(grant_stmt, worker_stmt).subquery("my_units_placement")
    rows = db.session.execute(
        sa.select(MasOrgUnit, MasOrgLevel, combined.c.cadre_name, combined.c.role)
        .select_from(combined)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == combined.c.org_unit_id)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
    ).all()
    mine: dict[str, dict] = {}
    for unit, level, cadre_name, role in rows:
        entry = mine.setdefault(
            str(unit.org_unit_id), {"unit": unit, "level": level, "cadres": set(), "roles": {}})
        if cadre_name:
            entry["cadres"].add(cadre_name)
        if role:
            # Two grants of one role at one unit: keep a cadre over none.
            entry["roles"][role] = entry["roles"].get(role) or cadre_name
    return mine


def _ancestor_units(project_id: str, mine: dict[str, dict]) -> list[dict]:
    """Active units above any of *mine*, root first, in one query.

    The ancestors are named by the codes in each unit's ltree path (the path
    is the chain of unit codes). Units of *mine* are left out: they are shown
    as the user's own level, not as context above it.
    """
    codes = {
        code
        for entry in mine.values()
        for code in str(entry["unit"].path).split(".")[:-1]
    }
    if not codes:
        return []
    return [
        unit
        for unit in list_units_by_codes(project_id, codes)
        if unit["org_unit_id"] not in mine
    ]


def _people_by_unit(unit_ids: Iterable[str]) -> dict[str, list[dict]]:
    """Active workers of *unit_ids*, as ``{name, cadre, roles}``, one query.

    Name, cadre and role labels only: never phone, email, worker code or user
    id (docs/policy/organization-model.md, "Who sees worker names"). ``roles``
    are the labels of the linked user's active grants in the unit's own
    project (closed projects resolve none), gathered by one correlated
    aggregate in the same query; empty without a linked user. Each unit is
    capped at ``MY_ORG_PEOPLE_CAP`` by a window over the same query.
    """
    from app.services.org_grant_service import active_project_condition

    ids = [uuid.UUID(unit_id) for unit_id in unit_ids]
    if not ids:
        return {}
    roles = (
        sa.select(sa.func.array_agg(sa.distinct(sa.cast(VaUserAccessGrants.role, sa.Text))))
        .where(
            VaUserAccessGrants.user_id == MasOrgUnitWorker.user_id,
            VaUserAccessGrants.project_id == MasOrgUnit.project_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            active_project_condition(VaUserAccessGrants.project_id),
        )
        .correlate(MasOrgUnitWorker, MasOrgUnit)
        .scalar_subquery()
    )
    ranked = (
        sa.select(
            MasOrgUnitWorker.org_unit_id.label("org_unit_id"),
            MasOrgUnitWorker.worker_name.label("name"),
            MasCadre.cadre_name.label("cadre"),
            roles.label("roles"),
            sa.func.row_number()
            .over(
                partition_by=MasOrgUnitWorker.org_unit_id,
                order_by=(MasOrgUnitWorker.worker_name, MasOrgUnitWorker.worker_id),
            )
            .label("rank"),
        )
        .select_from(MasOrgUnitWorker)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .where(MasOrgUnitWorker.org_unit_id.in_(ids), MasOrgUnitWorker.is_active.is_(True))
        .subquery()
    )
    rows = db.session.execute(
        sa.select(ranked.c.org_unit_id, ranked.c.name, ranked.c.cadre, ranked.c.roles)
        .where(ranked.c.rank <= MY_ORG_PEOPLE_CAP)
        .order_by(ranked.c.rank)
    ).all()
    people: dict[str, list[dict]] = {}
    for org_unit_id, name, cadre, role_values in rows:
        labels = sorted({ROLE_LABELS[r] for r in role_values or () if r in ROLE_LABELS})
        people.setdefault(str(org_unit_id), []).append({"name": name, "cadre": cadre, "roles": labels})
    return people


def _unit_summaries(project_id: str, *conditions) -> list[dict]:
    """Active units of *project_id* matching *conditions*, with their worker
    count and whether they have child units. One query: both are correlated
    scalars on the unit row, so the cost does not grow per unit in Python.
    """
    child = sa.orm.aliased(MasOrgUnit, name="child_unit")
    people_count = (
        sa.select(sa.func.count(MasOrgUnitWorker.worker_id))
        .where(
            MasOrgUnitWorker.org_unit_id == MasOrgUnit.org_unit_id,
            MasOrgUnitWorker.is_active.is_(True),
        )
        .correlate(MasOrgUnit)
        .scalar_subquery()
    )
    has_children = sa.exists().where(
        child.parent_org_unit_id == MasOrgUnit.org_unit_id,
        child.is_active.is_(True),
    )
    rows = db.session.execute(
        sa.select(
            MasOrgUnit,
            MasOrgLevel.level_name,
            people_count.label("people_count"),
            has_children.label("has_children"),
        )
        .select_from(MasOrgUnit)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True), *conditions)
        .order_by(MasOrgUnit.unit_name, MasOrgUnit.unit_code)
    ).all()
    return [
        {
            "org_unit_id": str(unit.org_unit_id),
            "unit_name": unit.unit_name,
            "level_name": level_name,
            "parent_org_unit_id": str(unit.parent_org_unit_id) if unit.parent_org_unit_id else None,
            "people_count": people_count_value,
            "has_children": bool(has_children_value),
        }
        for unit, level_name, people_count_value, has_children_value in rows
    ]


def _my_project(user_id: uuid.UUID, project_id: str, project_name: str) -> dict:
    """One project's block of the My organization page.

    The user's own units, the units above them (with their people), their
    level, and the units one level below. A user with no unit placement (a
    project- or site-scoped grant) gets no ``my_units``; ``below`` is then the
    tree's root units, which sit above every grant.
    """
    mine = _my_units(user_id, project_id)
    ancestors = _ancestor_units(project_id, mine)
    if mine:
        mine_ids = [uuid.UUID(unit_id) for unit_id in mine]
        below = _unit_summaries(
            project_id,
            MasOrgUnit.parent_org_unit_id.in_(mine_ids),
            # A unit the user is placed at is shown as their own level, not as a
            # child below it.
            MasOrgUnit.org_unit_id.not_in(mine_ids),
        )
    else:
        top_depth_subq = (
            sa.select(sa.func.min(MasOrgLevel.depth))
            .where(MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True))
            .scalar_subquery()
        )
        below = _unit_summaries(
            project_id,
            MasOrgUnit.parent_org_unit_id.is_(None),
            MasOrgLevel.depth == top_depth_subq,
        )
    people = _people_by_unit([*mine, *(unit["org_unit_id"] for unit in ancestors)])
    ordered = sorted(mine.items(), key=lambda item: str(item[1]["unit"].path))
    return {
        "project_id": project_id,
        "project_name": project_name,
        "my_units": [
            {
                "org_unit_id": unit_id,
                "unit_name": entry["unit"].unit_name,
                "level_name": entry["level"].level_name,
                "cadres": sorted(entry["cadres"]),
                "roles": [
                    {"role": role, "cadre": cadre}
                    for role, cadre in sorted(entry["roles"].items())
                ],
            }
            for unit_id, entry in ordered
        ],
        "above": [
            {
                "org_unit_id": unit["org_unit_id"],
                "unit_name": unit["unit_name"],
                "level_name": unit["level_name"],
                "parent_org_unit_id": unit["parent_org_unit_id"],
                "people": people.get(unit["org_unit_id"], []),
            }
            for unit in ancestors
        ],
        "my_level": [
            {
                "org_unit_id": unit_id,
                "unit_name": entry["unit"].unit_name,
                "parent_org_unit_id": (
                    str(entry["unit"].parent_org_unit_id) if entry["unit"].parent_org_unit_id else None
                ),
                "people": people.get(unit_id, []),
            }
            for unit_id, entry in ordered
        ],
        "below": below,
    }


def _granted_site_names(grants_by_project: dict[str, list]) -> dict[tuple[str, str], str]:
    """``{(project_id, site_id): site_name}`` for the active project sites the
    user holds a project_site grant at, all projects in one query."""
    pairs = sorted({
        (grant.project_id, grant.site_id)
        for grants in grants_by_project.values()
        for grant in grants
        if grant.scope_type == VaAccessScopeTypes.project_site and grant.site_id
    })
    if not pairs:
        return {}
    rows = db.session.execute(
        sa.select(VaProjectSites.project_id, VaProjectSites.site_id, VaSiteMaster.site_name)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            sa.tuple_(VaProjectSites.project_id, VaProjectSites.site_id).in_(pairs),
            VaProjectSites.project_site_status == VaStatuses.active,
        )
    ).all()
    return {(row.project_id, row.site_id): row.site_name for row in rows}


def _my_positions(project_id: str, grants: list, site_names: dict) -> dict:
    """The user's own project- and site-scope roles in one project (unit roles
    ride on ``my_units``). Grant roles as granted, sorted; no derived roles."""
    project_roles = sorted({
        grant.role.value for grant in grants if grant.scope_type == VaAccessScopeTypes.project
    })
    site_roles: dict[str, set[str]] = {}
    for grant in grants:
        if grant.scope_type == VaAccessScopeTypes.project_site and (project_id, grant.site_id) in site_names:
            site_roles.setdefault(grant.site_id, set()).add(grant.role.value)
    return {
        "project_roles": project_roles,
        "sites": [
            {"site_id": site_id, "site_name": site_names[(project_id, site_id)], "roles": sorted(roles)}
            for site_id, roles in sorted(site_roles.items())
        ],
    }


def my_organization(user) -> dict:
    """The My organization page's data: every project the user holds a live
    grant in, with ``has_tree`` and ``my_positions`` (their own roles). The
    tree lists (``my_units``, ``above``, ``my_level``, ``below``) are filled for
    org-tree projects and empty for sites-mode projects.
    """
    grants_by_project, resolved = _granted(user)
    if not grants_by_project:
        return {"projects": []}
    project_ids = sorted(grants_by_project)
    names = dict(
        db.session.execute(
            sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name).where(
                VaProjectMaster.project_id.in_(project_ids)
            )
        ).all()
    )
    site_names = _granted_site_names(grants_by_project)
    projects = []
    for pid in project_ids:
        has_tree = resolved.has_tree(pid)
        block = (
            _my_project(user.user_id, pid, names[pid])
            if has_tree
            else {"project_id": pid, "project_name": names[pid],
                  "my_units": [], "above": [], "my_level": [], "below": []}
        )
        block["has_tree"] = has_tree
        block["my_positions"] = _my_positions(pid, grants_by_project[pid], site_names)
        projects.append(block)
    return {"projects": projects}


def unit_people(user, org_unit_id: object) -> dict | None:
    """One unit's people and its child units, for opening a unit on the page.

    Allowed to any user holding an active grant in the unit's project. Returns
    ``None`` (the route answers 404) for a bad id, an unknown or inactive unit,
    or a project the user holds no grant in: the same answer in every case, so
    the reply does not reveal that a unit exists elsewhere.
    """
    # Decided first, so a bad id also consults authz (the reach is the same).
    granted = _granted_project_ids(user)
    try:
        unit_uuid = _uuid(org_unit_id, what="Unit")
    except OrganizationError:
        return None
    row = db.session.execute(
        sa.select(MasOrgUnit, MasOrgLevel.level_name)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(MasOrgUnit.org_unit_id == unit_uuid, MasOrgUnit.is_active.is_(True))
    ).first()
    if row is None:
        return None
    unit, level_name = row
    if unit.project_id not in granted:
        return None
    unit_id = str(unit.org_unit_id)
    return {
        "unit": {"org_unit_id": unit_id, "unit_name": unit.unit_name, "level_name": level_name},
        "people": _people_by_unit([unit_id]).get(unit_id, []),
        "children": _unit_summaries(unit.project_id, MasOrgUnit.parent_org_unit_id == unit.org_unit_id),
    }


# ---------------------------------------------------------------------------
# Existing account lookup, per-worker multi-unit scope grants, bulk VA
# mortality presets, and project mentoring institutes overview.
# ---------------------------------------------------------------------------


def lookup_existing_user(query: object, *, is_admin: bool = True) -> dict:
    """Exact email or 10-digit mobile match on active VaUsers for Add/Edit Worker UI."""
    from app.services.mentor_institute_service import member_user_ids
    from app.services.user_account_service import PHONE_CANONICAL, canonical_mobile

    raw = str(query or "").strip()
    if not raw:
        return {"found": False}
    user = None
    matched_by_email = "@" in raw
    if matched_by_email:
        user = db.session.scalar(
            sa.select(VaUsers).where(
                sa.func.lower(VaUsers.email) == raw.lower(),
                VaUsers.user_status == VaStatuses.active,
            )
        )
    else:
        mobile = canonical_mobile(raw)
        if mobile:
            user = db.session.scalar(
                sa.select(VaUsers).where(
                    sa.or_(VaUsers.mobile_login == mobile, PHONE_CANONICAL == mobile),
                    VaUsers.user_status == VaStatuses.active,
                )
            )
    if user is None:
        return {"found": False}
    is_mentor = user.user_id in member_user_ids([user.user_id])
    # Do not disclose the unqueried contact channel to non-admin callers.
    email_out = user.email if (is_admin or matched_by_email) else None
    phone_out = (user.phone or user.mobile_login) if (is_admin or not matched_by_email) else None
    status_str = user.user_status.value if hasattr(user.user_status, "value") else str(user.user_status)
    user_payload = {
        "user_id": str(user.user_id),
        "name": user.name,
        "email": email_out,
        "phone": phone_out,
        "mobile": phone_out,
        "is_active": user.user_status == VaStatuses.active,
        "user_status": status_str,
        "coding_languages": list(user.vacode_language or []),
        "is_mentor_member": is_mentor,
    }
    return {
        "found": True,
        **user_payload,
        "user": user_payload,
    }


SUGGEST_LIMIT = 8
SUGGEST_MIN_EMAIL = 3
SUGGEST_MIN_DIGITS = 4
SUGGEST_MAX_LEN = 128


def suggest_existing_users(query: object, *, is_admin: bool = True) -> list[dict]:
    """Up to 8 active accounts whose email (any text with a letter or ``@``,
    from 3 characters) or canonical mobile (digits only, from 4) contains
    *query*, case-insensitive: exact match first, then prefix, then by name.

    Owner decision 2026-10-22 (organization-model.md): any admin or project
    PI sees every matching account. A non-admin gets only the channel being
    typed, as in ``lookup_existing_user``. A short or overlong query returns [].
    """
    from app.services.user_account_service import PHONE_CANONICAL

    raw = str(query or "").strip().lower()
    if len(raw) > SUGGEST_MAX_LEN:
        return []
    by_email = not raw.isdigit()
    if by_email:
        if len(raw) < SUGGEST_MIN_EMAIL:
            return []
        field = sa.func.lower(VaUsers.email)
        match = field.contains(raw, autoescape=True)
    else:
        if len(raw) < SUGGEST_MIN_DIGITS:
            return []
        field = sa.func.coalesce(VaUsers.mobile_login, PHONE_CANONICAL)
        match = field.contains(raw, autoescape=True)
    # ponytail: contains-match is a sequential scan; fine at ~1k accounts,
    # add a pg_trgm index on lower(email) and mobile_login past ~100k.
    rank = sa.case((field == raw, 0), (field.startswith(raw, autoescape=True), 1), else_=2)
    rows = db.session.execute(
        sa.select(VaUsers.user_id, VaUsers.name, VaUsers.email, VaUsers.phone, VaUsers.mobile_login)
        .where(match, VaUsers.user_status == VaStatuses.active)
        .order_by(rank, VaUsers.name, VaUsers.user_id)
        .limit(SUGGEST_LIMIT)
    ).all()
    suggestions = []
    for user_id, name, email, phone, mobile_login in rows:
        mobile = (phone or mobile_login) if (is_admin or not by_email) else None
        suggestions.append({
            "user_id": str(user_id),
            "name": name,
            "email": email if (is_admin or by_email) else None,
            "mobile": mobile,
        })
    return suggestions


def worker_data_collector_user(project_id: str, worker_id: object) -> VaUsers:
    """The active, emailable account behind a worker that holds an active
    interviewer or death_reporter grant in *project_id*, for the enrolment
    email resend. Raises OrganizationError naming what is missing."""
    worker = _get_worker(project_id, worker_id)
    user = db.session.get(VaUsers, worker.user_id) if worker.user_id else None
    if user is None or user.user_status != VaStatuses.active:
        raise OrganizationError("This worker has no active DigitVA account.")
    if not user.email:
        raise OrganizationError("This worker has no email; use the QR on the Devices page.")
    collector = db.session.scalar(
        sa.select(VaUserAccessGrants.grant_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_((VaAccessRoles.interviewer, VaAccessRoles.death_reporter)),
            sa.or_(VaUserAccessGrants.project_id == project_id, MasOrgUnit.project_id == project_id),
        )
        .limit(1)
    )
    if collector is None:
        raise OrganizationError("This worker is not an interviewer or death reporter in this project.")
    return user


def sync_worker_unit_scope_grants(
    project_id: str,
    worker: MasOrgUnitWorker,
    *,
    coding_unit_ids: Iterable[object] | None = None,
    supervision_unit_ids: Iterable[object] | None = None,
    actor: VaUsers,
) -> list[tuple[dict, str]]:
    """Sync a worker's multi-unit coding and/or supervision grants at their level.

    Allows configuring within-tree (own unit), cross-tree (other units at the
    same level), all units at the level, or a custom selection of units at the
    worker's level (e.g. 2 PHCs for one MO and 10 PHCs for another).
    Omitting ``coding_unit_ids`` or ``supervision_unit_ids`` leaves that bucket
    unchanged.
    """
    from app.services.org_grant_service import validate_org_unit_grant

    if coding_unit_ids is None and supervision_unit_ids is None:
        return []
    if worker.user_id is None:
        if (coding_unit_ids and list(coding_unit_ids)) or (supervision_unit_ids and list(supervision_unit_ids)):
            raise OrganizationError(
                "Link this worker to a DigitVA account (email or mobile) before assigning coding or supervision units."
            )
        return []

    unit = _get_unit(project_id, worker.org_unit_id)
    cadre = _get_cadre(project_id, worker.cadre_id)
    permission = get_level_cadre_permission(unit.org_level_id, cadre.cadre_id)
    if permission is None:
        raise OrganizationError(
            f"Cadre {cadre.cadre_code!r} is not active at level {unit.level.level_code!r}."
        )

    level_units = {
        u.org_unit_id: u
        for u in db.session.scalars(
            sa.select(MasOrgUnit).where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.org_level_id == unit.org_level_id,
                MasOrgUnit.is_active.is_(True),
            )
        ).all()
    }
    existing_grants = {
        (g.role, g.org_unit_id): g
        for g in db.session.scalars(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == worker.user_id,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                VaUserAccessGrants.org_unit_id.in_(list(level_units.keys())),
            )
        ).all()
    }
    actor_grants = authz.resolve_grants(actor)
    changed: list[tuple[dict, str]] = []

    def _sync_bucket(
        raw_ids: Iterable[object] | None,
        bucket_roles: frozenset[VaAccessRoles],
        fallback_role: VaAccessRoles,
    ) -> None:
        if raw_ids is None:
            return
        target_ids: list[uuid.UUID] = []
        for raw in raw_ids:
            uid = _uuid(raw, what="Unit id")
            if uid not in level_units:
                raise OrganizationError(
                    "Selected coding or supervision units must be active units at the worker's level in this project."
                )
            if uid not in target_ids:
                target_ids.append(uid)

        active_bucket_roles = {
            r for (r, _), g in existing_grants.items()
            if r in bucket_roles and g.grant_status == VaStatuses.active
        }
        default_bucket_roles = {
            VaAccessRoles(r) for r in (permission.default_roles or ())
            if r in {br.value for br in bucket_roles}
        }
        roles_to_sync = sorted(
            active_bucket_roles or default_bucket_roles or ({fallback_role} if target_ids else set()),
            key=lambda r: r.value,
        )

        for role in roles_to_sync:
            for uid in target_ids:
                validate_org_unit_grant(
                    role=role,
                    org_unit_id=uid,
                    cadre_id=cadre.cadre_id,
                    user_id=worker.user_id,
                )
                if not authz.can_grant(
                    actor,
                    authz.GrantTarget(
                        role=role,
                        scope_type=VaAccessScopeTypes.org_unit,
                        project_id=None,
                        org_unit_id=uid,
                    ),
                    _grants=actor_grants,
                ):
                    raise OrganizationError("You are not permitted to grant this role on the selected unit.")
                g = existing_grants.get((role, uid))
                if g is None:
                    g = VaUserAccessGrants(
                        user_id=worker.user_id,
                        role=role,
                        scope_type=VaAccessScopeTypes.org_unit,
                        project_id=None,
                        org_unit_id=uid,
                        cadre_id=cadre.cadre_id,
                        grant_status=VaStatuses.active,
                        created_by_user_id=actor.user_id,
                    )
                    db.session.add(g)
                    db.session.flush()
                    existing_grants[(role, uid)] = g
                    changed.append((
                        {
                            "user_id": worker.user_id,
                            "grant_id": g.grant_id,
                            "role": role.value,
                            "scope_type": VaAccessScopeTypes.org_unit.value,
                            "org_unit_id": uid,
                            "cadre_id": cadre.cadre_id,
                        },
                        "grant_created",
                    ))
                elif g.grant_status != VaStatuses.active or g.cadre_id != cadre.cadre_id:
                    was_active = g.grant_status == VaStatuses.active
                    g.grant_status = VaStatuses.active
                    g.cadre_id = cadre.cadre_id
                    changed.append((
                        {
                            "user_id": worker.user_id,
                            "grant_id": g.grant_id,
                            "role": role.value,
                            "scope_type": VaAccessScopeTypes.org_unit.value,
                            "org_unit_id": uid,
                            "cadre_id": cadre.cadre_id,
                        },
                        "grant_updated" if was_active else "grant_reactivated",
                    ))

        target_set = set(target_ids)
        for (role, uid), g in list(existing_grants.items()):
            if role in bucket_roles and uid not in target_set and g.grant_status == VaStatuses.active:
                g.grant_status = VaStatuses.deactive
                changed.append((
                    {
                        "user_id": worker.user_id,
                        "grant_id": g.grant_id,
                        "role": role.value,
                        "scope_type": VaAccessScopeTypes.org_unit.value,
                        "org_unit_id": uid,
                        "cadre_id": g.cadre_id,
                    },
                    "grant_revoked",
                ))

    _sync_bucket(coding_unit_ids, _WORKER_CODING_ROLES, VaAccessRoles.coder)
    _sync_bucket(supervision_unit_ids, _WORKER_SUPERVISION_ROLES, VaAccessRoles.interview_supervisor)
    db.session.flush()
    return changed


def list_project_va_presets(project_id: str) -> list[dict]:
    """All active units of *project_id* with own and resolved (inherited) HIV/malaria presets."""
    from app.services.org_grant_service import resolve_unit_va_presets

    _get_project(project_id)
    units = list_units(project_id, include_inactive=False)
    if not units:
        return []
    unit_uuids = [uuid.UUID(u["org_unit_id"]) for u in units]
    own_rows = {
        str(row.org_unit_id): row
        for row in db.session.scalars(
            sa.select(MapOrgUnitVaPresets).where(MapOrgUnitVaPresets.org_unit_id.in_(unit_uuids))
        ).all()
    }
    resolved_map = resolve_unit_va_presets(unit_uuids)
    result = []
    for u in units:
        uid = u["org_unit_id"]
        u_uuid = uuid.UUID(uid)
        own = own_rows.get(uid)
        res = resolved_map.get(u_uuid, {})
        hiv_res = res.get("hiv_mortality")
        mal_res = res.get("malaria_mortality")
        own_hiv = own.hiv_mortality if own else None
        own_mal = own.malaria_mortality if own else None
        eff_hiv = hiv_res["value"] if hiv_res else None
        eff_mal = mal_res["value"] if mal_res else None
        hiv_src = (
            hiv_res["source_unit_name"]
            if hiv_res and str(hiv_res["source_unit_id"]) != uid
            else None
        )
        mal_src = (
            mal_res["source_unit_name"]
            if mal_res and str(mal_res["source_unit_id"]) != uid
            else None
        )
        result.append({
            "org_unit_id": uid,
            "org_level_id": u["org_level_id"],
            "unit_code": u["unit_code"],
            "unit_name": u["unit_name"],
            "level_code": u["level_code"],
            "level_name": u["level_name"],
            "depth": u["depth"],
            "parent_org_unit_id": u["parent_org_unit_id"],
            "path": u["path"],
            "own_hiv_mortality": own_hiv,
            "own_malaria_mortality": own_mal,
            "hiv_aids": own_hiv,
            "malaria": own_mal,
            "Id10002": own_hiv,
            "Id10003": own_mal,
            "effective_hiv_mortality": eff_hiv,
            "effective_hiv_aids": eff_hiv,
            "effective_Id10002": eff_hiv,
            "hiv_source_unit_name": hiv_src,
            "inherited_hiv_aids_from": hiv_src,
            "effective_malaria_mortality": eff_mal,
            "effective_malaria": eff_mal,
            "effective_Id10003": eff_mal,
            "malaria_source_unit_name": mal_src,
            "inherited_malaria_from": mal_src,
        })
    return result


def bulk_set_unit_va_presets(project_id: str, items: list[dict], *, actor_id=None) -> int:
    """Update HIV/malaria presets across multiple units of *project_id* in one batch without N+1 queries."""
    _get_project(project_id)
    if not isinstance(items, list):
        raise OrganizationError("items must be a list of unit preset updates.")
    if len(items) > 1000:
        raise OrganizationError("At most 1000 units can be updated in one request.")
    if not items:
        return 0

    project_units = {
        u.org_unit_id: u
        for u in db.session.scalars(
            sa.select(MasOrgUnit).where(MasOrgUnit.project_id == project_id)
        ).all()
    }
    existing_presets = {
        row.org_unit_id: row
        for row in db.session.scalars(
            sa.select(MapOrgUnitVaPresets).where(
                MapOrgUnitVaPresets.org_unit_id.in_(list(project_units.keys()))
            )
        ).all()
    }

    updated = 0
    for item in items:
        if not isinstance(item, dict):
            raise OrganizationError("Each preset entry must be an object.")
        uid = _uuid(item.get("org_unit_id"), what="Unit id")
        if uid not in project_units:
            raise OrganizationError("Unit does not belong to this project.")
        raw_hiv = (
            item.get("hiv_mortality")
            if "hiv_mortality" in item
            else (item.get("hiv_aids") if "hiv_aids" in item else item.get("Id10002"))
        )
        raw_mal = (
            item.get("malaria_mortality")
            if "malaria_mortality" in item
            else (item.get("malaria") if "malaria" in item else item.get("Id10003"))
        )
        hiv = _validate_va_preset_value(raw_hiv, what="hiv_mortality")
        malaria = _validate_va_preset_value(raw_mal, what="malaria_mortality")
        row = existing_presets.get(uid)
        if hiv is None and malaria is None:
            if row is not None:
                db.session.delete(row)
                del existing_presets[uid]
                updated += 1
        elif row is None:
            row = MapOrgUnitVaPresets(
                org_unit_id=uid,
                hiv_mortality=hiv,
                malaria_mortality=malaria,
                updated_by_user_id=actor_id,
            )
            db.session.add(row)
            existing_presets[uid] = row
            updated += 1
        elif row.hiv_mortality != hiv or row.malaria_mortality != malaria:
            row.hiv_mortality = hiv
            row.malaria_mortality = malaria
            row.updated_by_user_id = actor_id
            updated += 1

    db.session.flush()
    return updated


def project_mentoring_overview(project_id: str) -> dict:
    """Districts, attached mentoring institutes, institute scientists, and their unit grants in *project_id*."""
    from app.models import MapMentorInstituteOrgUnit, MapMentorInstituteUser, MasMentorInstitute
    from app.services.mentor_institute_service import MENTOR_ROLES

    _get_project(project_id)
    units = list_units(project_id, include_inactive=False)
    districts = [u for u in units if u["depth"] == 1]
    district_uuids = [uuid.UUID(d["org_unit_id"]) for d in districts]

    inst_objs = db.session.scalars(
        sa.select(MasMentorInstitute)
        .where(MasMentorInstitute.is_active.is_(True))
        .order_by(MasMentorInstitute.institute_code)
    ).all()

    links = []
    attached_inst_ids: set[uuid.UUID] = set()
    districts_by_inst: dict[uuid.UUID, list[str]] = {}
    if district_uuids:
        link_rows = db.session.execute(
            sa.select(MapMentorInstituteOrgUnit, MasMentorInstitute, MasOrgUnit)
            .join(
                MasMentorInstitute,
                MasMentorInstitute.institute_id == MapMentorInstituteOrgUnit.institute_id,
            )
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == MapMentorInstituteOrgUnit.org_unit_id)
            .where(
                MapMentorInstituteOrgUnit.org_unit_id.in_(district_uuids),
                MapMentorInstituteOrgUnit.is_active.is_(True),
                MasMentorInstitute.is_active.is_(True),
            )
            .order_by(MasOrgUnit.unit_code, MasMentorInstitute.institute_code)
        ).all()
        for link, inst, dist in link_rows:
            attached_inst_ids.add(inst.institute_id)
            districts_by_inst.setdefault(inst.institute_id, []).append(str(dist.org_unit_id))
            links.append({
                "institute_id": str(inst.institute_id),
                "institute_code": inst.institute_code,
                "institute_name": inst.institute_name,
                "org_unit_id": str(dist.org_unit_id),
                "unit_code": dist.unit_code,
                "unit_name": dist.unit_name,
            })

    scientists = []
    scientists_by_inst: dict[uuid.UUID, list[dict]] = {}
    all_inst_uuids = [inst.institute_id for inst in inst_objs]
    if all_inst_uuids:
        staff_rows = db.session.execute(
            sa.select(VaUsers, MapMentorInstituteUser, MasMentorInstitute)
            .join(MapMentorInstituteUser, MapMentorInstituteUser.user_id == VaUsers.user_id)
            .join(
                MasMentorInstitute,
                MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
            )
            .where(
                MapMentorInstituteUser.institute_id.in_(all_inst_uuids),
                MapMentorInstituteUser.is_active.is_(True),
                VaUsers.user_status == VaStatuses.active,
            )
            .order_by(MasMentorInstitute.institute_code, VaUsers.name, VaUsers.email)
        ).all()
        staff_user_ids = {u.user_id for u, _, _ in staff_rows}
        grants_by_user: dict[uuid.UUID, list[dict]] = {}
        if staff_user_ids:
            g_rows = db.session.execute(
                sa.select(VaUserAccessGrants, MasOrgUnit)
                .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
                .where(
                    VaUserAccessGrants.user_id.in_(staff_user_ids),
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                    VaUserAccessGrants.grant_status == VaStatuses.active,
                    VaUserAccessGrants.role.in_(MENTOR_ROLES),
                    MasOrgUnit.project_id == project_id,
                    MasOrgUnit.is_active.is_(True),
                )
                .order_by(MasOrgUnit.path)
            ).all()
            for g, u in g_rows:
                grants_by_user.setdefault(g.user_id, []).append({
                    "grant_id": str(g.grant_id),
                    "role": g.role.value,
                    "org_unit_id": str(u.org_unit_id),
                    "unit_code": u.unit_code,
                    "unit_name": u.unit_name,
                })
        for u, member_link, inst in staff_rows:
            user_grants = grants_by_user.get(u.user_id, [])
            grants_by_role: dict[str, list[str]] = {}
            for g_item in user_grants:
                grants_by_role.setdefault(g_item["role"], []).append(g_item["org_unit_id"])
            sci_entry = {
                "user_id": str(u.user_id),
                "name": u.name,
                "email": u.email,
                "phone": u.phone or u.mobile_login,
                "mobile": u.phone or u.mobile_login,
                "coding_languages": list(u.vacode_language or []),
                "institute_code": inst.institute_code,
                "institute_name": inst.institute_name,
                "is_institute_admin": bool(member_link.is_admin),
                "grants": user_grants,
                "grants_by_role": grants_by_role,
            }
            scientists_by_inst.setdefault(inst.institute_id, []).append(sci_entry)
            if inst.institute_id in attached_inst_ids:
                scientists.append(sci_entry)

    all_institutes = [
        {
            "institute_id": str(inst.institute_id),
            "mentor_institute_id": str(inst.institute_id),
            "institute_code": inst.institute_code,
            "institute_name": inst.institute_name,
            "is_active": inst.is_active,
            "project_district_unit_ids": districts_by_inst.get(inst.institute_id, []),
            "scientists": scientists_by_inst.get(inst.institute_id, []),
        }
        for inst in inst_objs
    ]

    return {
        "units": units,
        "districts": districts,
        "all_institutes": all_institutes,
        "institutes": all_institutes,
        "attached_links": links,
        "scientists": scientists,
        "mentor_roles": ["coder", "reviewer", "coding_tester", "collaborator_pii", "collaborator"],
    }


def sync_mentor_scientist_unit_grants(
    project_id: str,
    *,
    user_id: object,
    role_name: str,
    org_unit_ids: Iterable[object],
    actor: VaUsers,
) -> list[tuple[dict, str]]:
    """Sync a mentoring-institute scientist's unit grants for *role_name* in *project_id*."""
    from app.services.mentor_institute_service import MENTOR_ROLES, check_mentor_grant
    from app.services.org_grant_service import validate_org_unit_grant

    _get_project(project_id)
    target_user_uuid = _uuid(user_id, what="Scientist user id")
    user = db.session.get(VaUsers, target_user_uuid)
    if user is None or user.user_status != VaStatuses.active:
        raise OrganizationError("Active scientist account not found.")
    try:
        role = VaAccessRoles(str(role_name or "").strip())
    except ValueError as exc:
        raise OrganizationError(f"Invalid role {role_name!r}.") from exc
    if role not in MENTOR_ROLES:
        raise OrganizationError(f"Role {role.value!r} is not a mentoring institute role.")

    target_ids: list[uuid.UUID] = []
    for raw in org_unit_ids or ():
        uid = _uuid(raw, what="Unit id")
        if uid not in target_ids:
            target_ids.append(uid)

    project_units = {
        u.org_unit_id: u
        for u in db.session.scalars(
            sa.select(MasOrgUnit).where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.is_active.is_(True),
            )
        ).all()
    }
    for uid in target_ids:
        if uid not in project_units:
            raise OrganizationError("Selected unit does not belong to this project or is inactive.")

    # For 'coder', validate_org_unit_grant requires an active cadre at the unit's level with can_code_va_form=True.
    coding_cadre_by_level: dict[uuid.UUID, uuid.UUID] = {}
    if role == VaAccessRoles.coder and target_ids:
        for lc, cadre in db.session.execute(
            sa.select(MapOrgLevelCadre, MasCadre)
            .join(MasCadre, MasCadre.cadre_id == MapOrgLevelCadre.cadre_id)
            .join(MasOrgLevel, MasOrgLevel.org_level_id == MapOrgLevelCadre.org_level_id)
            .where(
                MasOrgLevel.project_id == project_id,
                MapOrgLevelCadre.is_active.is_(True),
                MapOrgLevelCadre.can_code_va_form.is_(True),
                MasCadre.is_active.is_(True),
            )
            .order_by(MasCadre.cadre_code)
        ).all():
            coding_cadre_by_level.setdefault(lc.org_level_id, cadre.cadre_id)

    existing_grants = {
        g.org_unit_id: g
        for g in db.session.scalars(
            sa.select(VaUserAccessGrants)
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(
                VaUserAccessGrants.user_id == target_user_uuid,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                MasOrgUnit.project_id == project_id,
            )
        ).all()
    }
    actor_grants = authz.resolve_grants(actor)
    changed: list[tuple[dict, str]] = []

    for uid in target_ids:
        unit = project_units[uid]
        check_mentor_grant(target_user_uuid, role, unit)
        cadre_id = coding_cadre_by_level.get(unit.org_level_id) if role == VaAccessRoles.coder else None
        if role == VaAccessRoles.coder and cadre_id is None:
            raise OrganizationError(
                f"To grant 'coder' at {unit.unit_code} ({unit.level.level_name}), enable 'Code VA' for at least one cadre at that level first."
            )
        validate_org_unit_grant(
            role=role,
            org_unit_id=uid,
            cadre_id=cadre_id,
            user_id=target_user_uuid,
        )
        if not authz.can_grant(
            actor,
            authz.GrantTarget(
                role=role,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=None,
                org_unit_id=uid,
            ),
            _grants=actor_grants,
        ):
            raise OrganizationError("You are not permitted to grant this role on the selected unit.")
        g = existing_grants.get(uid)
        if g is None:
            g = VaUserAccessGrants(
                user_id=target_user_uuid,
                role=role,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=None,
                org_unit_id=uid,
                cadre_id=cadre_id,
                grant_status=VaStatuses.active,
                created_by_user_id=actor.user_id,
            )
            db.session.add(g)
            db.session.flush()
            existing_grants[uid] = g
            changed.append((
                {
                    "user_id": target_user_uuid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": uid,
                    "cadre_id": cadre_id,
                },
                "grant_created",
            ))
        elif g.grant_status != VaStatuses.active:
            g.grant_status = VaStatuses.active
            if cadre_id is not None:
                g.cadre_id = cadre_id
            changed.append((
                {
                    "user_id": target_user_uuid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": uid,
                    "cadre_id": g.cadre_id,
                },
                "grant_reactivated",
            ))

    target_set = set(target_ids)
    for uid, g in list(existing_grants.items()):
        if uid not in target_set and g.grant_status == VaStatuses.active:
            g.grant_status = VaStatuses.deactive
            changed.append((
                {
                    "user_id": target_user_uuid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": uid,
                    "cadre_id": g.cadre_id,
                },
                "grant_revoked",
            ))

    db.session.flush()
    return changed
