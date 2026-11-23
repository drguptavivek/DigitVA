"""Shared helpers of the organization service: errors, code normalisers, cleaners, project and site lookups."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa

from app import db
from app.models import (
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaSites,
    VaStatuses,
)

# ltree labels accept [A-Za-z0-9_]; codes are stored upper-case.
CODE_RE = re.compile(r"^[A-Z0-9_]{1,32}$")


LEVEL_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class OrganizationError(ValueError):
    """Validation failure reported to the caller (HTTP 400 in routes)."""


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
