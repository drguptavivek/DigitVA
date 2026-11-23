"""Health-system organization master data: levels, units, cadres, workers.

Plan: docs/planning/health-system-organization-model-plan.md
Policy: docs/policy/organization-model.md

All codes are unique within one project only. Unit paths are ltree values
built from unit codes, so subtree queries use ``path <@ :ancestor_path``.
Every write here is validated against the project's level definitions and
never deletes rows: deactivation is the only removal.

This module is the facade: the code lives in the ``org_*`` modules (digitva-r8nh.14)
and every name it ever exported is re-exported here, so importers and tests that
patch ``organization_service.<name>`` keep working. ``normalize_default_roles`` and
``upsert_level_cadre`` stay defined here because a test patches the former and the
latter looks it up in this namespace.
"""

from __future__ import annotations

# Names this module imported before the split stay importable from it.
import csv  # noqa: F401
import io  # noqa: F401
import logging  # noqa: F401
import re  # noqa: F401
import uuid  # noqa: F401
from collections.abc import Iterable  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from datetime import UTC, datetime  # noqa: F401
from datetime import date as date_type  # noqa: F401
from decimal import Decimal, InvalidOperation  # noqa: F401

import sqlalchemy as sa  # noqa: F401

from app import db  # noqa: F401
from app.models import (  # noqa: F401
    AuthDevice,
    AuthDeviceSession,
    MapMentorInstituteUser,
    MapOrgLevelCadre,
    MapOrgUnitCodingGate,
    MapOrgUnitCollectionGate,
    MapOrgUnitVaPresets,
    MapProjectMember,
    MasCadre,
    MasMentorInstitute,
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
from app.models.va_selectives import ROLE_LABELS  # noqa: F401
from app.services import authz  # noqa: F401
from app.services.authz.consulted import mark_consulted  # noqa: F401
from app.services.org_cadres import (  # noqa: F401
    _get_cadre,
    create_cadre,
    get_level_cadre_permission,
    list_cadres,
    list_level_cadres,
    serialize_cadre,
    serialize_level_cadre,
    update_cadre,
)
from app.services.org_common import (  # noqa: F401
    _ORGANIZATION_SITE_PREFIX,
    CODE_RE,
    LEVEL_CODE_RE,
    OrganizationError,
    _clean_coordinate,
    _clean_text,
    _clean_url,
    _get_project,
    _next_organization_site_id,
    _to_bool,
    _uuid,
    ensure_organization_site,
    normalize_code,
    normalize_level_code,
    odk_choice_list_name_for_level,
    odk_field_name_for_level,
    organization_site_name,
    require_organization_mode,
)
from app.services.org_grid import (  # noqa: F401
    _BULK_ROLE_MAP,
    _DISPLAY_ROLE_META,
    _grant_in_project,
    bulk_apply_project_users_grid,
    get_project_users_grid,
    on_project_roster,
    remove_from_project,
    replace_placement_grants,
    require_on_project_roster,
)
from app.services.org_import_export import (  # noqa: F401
    _CADRE_HEADERS,
    _DEFAULT_ROLES_SEPARATOR,
    _LEVEL_CADRE_HEADERS,
    _LEVEL_HEADERS,
    _UNIT_HEADERS,
    _WORKER_HEADERS,
    DEFAULT_CADRE_TEMPLATE,
    DEFAULT_LEVEL_CADRE_TEMPLATE,
    DEFAULT_LEVEL_TEMPLATE,
    DEFAULT_TYPICAL_ROLES,
    EXPORT_SHEETS,
    ImportPlan,
    _import_cadres,
    _import_level_cadres,
    _import_levels,
    _import_units,
    _import_workers,
    _spreadsheet_safe,
    _without_blank,
    district_reference_model,
    export_odk_choices_csv,
    export_odk_choices_rows,
    export_organization_csv,
    export_organization_rows,
    export_organization_xlsx,
    import_organization,
    parse_organization_csv,
    parse_organization_workbook,
    parse_units_upload,
    seed_default_organization,
)
from app.services.org_levels_units import (  # noqa: F401
    MAX_PLACEMENTS,
    _aliased_parent,
    _get_level,
    _get_unit,
    _is_unplaced,
    _rewrite_subtree_paths,
    _top_level_depth,
    _validate_parent_for_level,
    clear_unit_coding_gate,
    clear_unit_collection_gate,
    create_level,
    create_unit,
    find_unit_by_code,
    get_unit_coding_gate,
    get_unit_collection_gate,
    get_unit_tree,
    list_levels,
    list_units,
    list_units_by_codes,
    place_units,
    resolve_org_unit_export_labels,
    serialize_level,
    serialize_unit,
    serialize_unit_coding_gate,
    serialize_unit_collection_gate,
    set_unit_active,
    set_unit_coding_gate,
    set_unit_collection_gate,
    subtree_unit_ids,
    unit_deactivation_preview,
    unplaced_unit_codes,
    update_level,
    update_unit,
)
from app.services.org_my_organization import (  # noqa: F401
    MY_ORG_PEOPLE_CAP,
    _ancestor_units,
    _granted,
    _granted_project_ids,
    _granted_site_names,
    _my_positions,
    _my_project,
    _my_units,
    _people_by_unit,
    _unit_summaries,
    my_organization,
    unit_people,
)
from app.services.org_presets_mentoring import (  # noqa: F401
    VA_PRESET_VALUES,
    _validate_va_preset_value,
    bulk_set_unit_va_presets,
    clear_unit_va_presets,
    get_unit_va_presets,
    list_project_va_presets,
    project_mentoring_overview,
    serialize_unit_va_presets,
    set_unit_va_presets,
    sync_mentor_scientist_unit_grants,
)
from app.services.org_workers import (  # noqa: F401
    _WORKER_CODING_ROLES,
    _WORKER_SUPERVISION_ROLES,
    SUGGEST_LIMIT,
    SUGGEST_MAX_LEN,
    SUGGEST_MIN_DIGITS,
    SUGGEST_MIN_EMAIL,
    _get_worker,
    _next_worker_code,
    _require_cadre_at_unit_level,
    _resolve_user,
    create_worker,
    list_workers,
    lookup_existing_user,
    resolve_user,
    serialize_worker,
    suggest_existing_users,
    sync_worker_unit_scope_grants,
    update_worker,
    worker_data_collector_user,
)
from app.services.tabular_import_service import (  # noqa: F401
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
    "unit_deactivation_preview", "place_units", "unplaced_unit_codes", "MAX_PLACEMENTS",
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
    # project users grid and bulk apply
    "get_project_users_grid", "bulk_apply_project_users_grid",
]


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
    can_edit_interviews: bool | None = None,
    default_roles: Iterable[str] | None = None,
    is_active: bool = True,
) -> MapOrgLevelCadre:
    """Create or update one level x cadre row.

    ``can_supervise_interviews``, ``can_report_deaths``,
    ``can_edit_interviews`` and ``default_roles`` of ``None`` keep the row's
    current value (false or empty on a new row), so callers and workbooks that
    predate a column cannot clear it. ``can_edit_interviews`` lives only under
    ``can_supervise_interviews``: true while supervise ends up false is
    refused, and a kept true is cleared with supervise. Default roles
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
    if can_edit_interviews is not None:
        if can_edit_interviews and not row.can_supervise_interviews:
            raise OrganizationError("can_edit_interviews needs can_supervise_interviews.")
        row.can_edit_interviews = bool(can_edit_interviews)
    elif not row.can_supervise_interviews:
        row.can_edit_interviews = False
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
