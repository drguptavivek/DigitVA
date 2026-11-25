"""Seed template, spreadsheet export and the dry-run-first import of the organization."""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgLevelCadre,
    MasOrgLevel,
    MasOrgUnit,
)
from app.services.org_cadres import (
    create_cadre,
    list_cadres,
    list_level_cadres,
    serialize_cadre,
    update_cadre,
)
from app.services.org_common import (
    OrganizationError,
    _get_project,
    _to_bool,
    normalize_code,
    normalize_level_code,
)
from app.services.org_levels_units import (
    _top_level_depth,
    create_level,
    create_unit,
    list_levels,
    list_units,
    serialize_level,
    serialize_unit,
    set_unit_active,
    unplaced_unit_codes,
    update_level,
    update_unit,
)
from app.services.org_workers import (
    _next_worker_code,
    create_worker,
    list_workers,
    update_worker,
)
from app.services.tabular_import_service import (
    TabularImportError,
    parse_rows,
    parse_table,
    validate_xlsx,
)


def upsert_level_cadre(*args, **kwargs):
    """Call ``organization_service.upsert_level_cadre`` at call time.

    The function stays in the facade so a test patching
    ``organization_service.normalize_default_roles`` still reaches it; looking it
    up here, not importing it, keeps the modules free of an import cycle.
    """
    from app.services import organization_service

    return organization_service.upsert_level_cadre(*args, **kwargs)


# Seed template ("Populate district defaults"), the district reference model:
# docs/policy/district-reference-model.md. Codes and depths are stable (existing
# projects and ODK field names org_<level_code>_code depend on them); only the
# labels follow the AAM naming. Village is optional: villages often have no
# code, and an optional level with no units is left out of the ODK form.
DEFAULT_LEVEL_TEMPLATE: tuple[tuple[str, str, int, bool], ...] = (
    ("state", "State / Province", 1, True),
    ("district", "District / District Hospital (DH)", 2, False),
    ("taluka", "Block / Taluka / Sub-divisional Hospital (SDH)", 3, True),
    ("chc", "Community Health Centre (CHC)", 4, False),
    ("phc", "PHC / UPHC (PHC-AAM)", 5, False),
    ("subcentre", "SC-AAM / Sub-centre", 6, False),
    ("village", "Village", 7, True),
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


# (level_code, cadre_code) -> the unit-scope roles a cadre MAY hold at that
# level (allowed_roles, digitva-4650). Each list holds the row's default roles
# below. Owner 2026-10-12: ANM and MPW report deaths and may fill VAs; ASHA
# reports deaths only. New projects only; an existing grid row is never
# rewritten.
DEFAULT_LEVEL_CADRE_TEMPLATE: dict[tuple[str, str], tuple[str, ...]] = {
    ("district", "CS"): ("site_pi", "interview_supervisor"),
    ("district", "DPM"): ("data_manager",),
    ("district", "DEPI"): ("data_manager",),
    ("district", "MO"): ("coder", "reviewer"),
    ("district", "SN"): ("interviewer",),
    ("chc", "SMO"): ("site_pi", "coder", "reviewer", "interview_supervisor"),
    ("chc", "MO"): ("coder",),
    ("chc", "BPM"): ("data_manager",),
    ("chc", "SN"): ("interviewer",),
    ("phc", "MO"): ("site_pi", "coder", "interview_supervisor"),
    ("phc", "CHO"): ("interviewer",),
    ("subcentre", "CHO"): ("interviewer",),
    ("subcentre", "MPW"): ("interviewer", "death_reporter"),
    ("subcentre", "ANM"): ("interviewer", "death_reporter"),
    ("village", "ASHA"): ("death_reporter",),
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
    ("district", "DEPI"): ("data_manager",),
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
    for (level_code, cadre_code), allowed in DEFAULT_LEVEL_CADRE_TEMPLATE.items():
        level = existing_levels.get(level_code)
        cadre = existing_cadres.get(cadre_code)
        if level is None or cadre is None or (level.org_level_id, cadre.cadre_id) in existing_pairs:
            continue
        upsert_level_cadre(
            project_id,
            org_level_id=level.org_level_id,
            cadre_id=cadre.cadre_id,
            allowed_roles=allowed,
            default_roles=DEFAULT_TYPICAL_ROLES.get((level_code, cadre_code), ()),
        )
        counts["level_cadres"] += 1
    db.session.flush()
    return counts


def district_reference_model() -> dict:
    """The seed template as display data for the Organization page.

    Pure (no database): levels, cadres and one row per grid entry with its
    allowed roles and the default roles a new project's grid is seeded with.
    Default roles are pre-ticked in grant forms and never used to decide access.
    """
    level_names = {code: name for code, name, _depth, _optional in DEFAULT_LEVEL_TEMPLATE}
    cadre_names = dict(DEFAULT_CADRE_TEMPLATE)
    grid = []
    for (level_code, cadre_code), allowed in DEFAULT_LEVEL_CADRE_TEMPLATE.items():
        roles = DEFAULT_TYPICAL_ROLES.get((level_code, cadre_code), ())
        grid.append(
            {
                "level_code": level_code,
                "level_name": level_names[level_code],
                "cadre_code": cadre_code,
                "cadre_name": cadre_names[cadre_code],
                "allowed_roles": list(allowed),
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


_LEVEL_HEADERS = ("level_code", "level_name", "depth", "is_optional", "is_active", "odk_field_name")


_UNIT_HEADERS = (
    "unit_code", "unit_name", "level_code", "parent_code", "path", "address", "phone",
    "latitude", "longitude", "google_maps_url", "remarks", "is_active",
)


_CADRE_HEADERS = ("cadre_code", "cadre_name", "is_active")


_LEVEL_CADRE_HEADERS = (
    "level_code", "cadre_code", "allowed_roles", "default_roles", "is_active",
)


# Separates the role names in the allowed_roles and default_roles cells of the
# level_cadres sheet.
_DEFAULT_ROLES_SEPARATOR = "|"
_ROLE_LIST_HEADERS = ("allowed_roles", "default_roles")


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
            {k: _DEFAULT_ROLES_SEPARATOR.join(lc[k]) if k in _ROLE_LIST_HEADERS else lc[k]
             for k in _LEVEL_CADRE_HEADERS}
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
    from openpyxl import Workbook
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
    from openpyxl import load_workbook

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
                # Blank or absent keeps the current list; the grid editor clears it.
                # The five flag columns of older workbooks are no longer read.
                allowed_roles=_role_list(row.get("allowed_roles")),
                default_roles=_role_list(row.get("default_roles")),
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
                        allowed_roles=lc["allowed_roles"],
                        default_roles=lc["default_roles"],
                        is_active=False,
                    ),
                ))
                plan.deactivates["level_cadres"].append(f"{key[0]}/{key[1]}")
    return deferred


def _role_list(cell) -> list[str] | None:
    """A ``|``-separated role cell as a list; None for a blank cell (keep)."""
    text = str(cell or "").strip()
    return None if text == "" else text.split(_DEFAULT_ROLES_SEPARATOR)


def _without_blank(fields: dict, optional: tuple) -> dict:
    """Drop optional fields whose workbook cell is blank or absent.

    On an existing row a blank cell means "leave as is": the parser cannot
    tell a blank cell from a missing column, and the export leaves e.g.
    ``user_email`` blank for mobile-only accounts, so passing it through
    would unlink or wipe data. Clearing stays an explicit UI/API action.
    """
    return {
        k: v for k, v in fields.items()
        if k not in optional or (v is not None and str(v).strip() != "")
    }


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
                    **_without_blank(
                        fields, ("address", "phone", "latitude", "longitude", "google_maps_url", "remarks")
                    ),
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
            set_unit_active(project_id, unit_id, False, cascade_deactivate_children=True)
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
                    set_unit_active(project_id, current.org_unit_id, False, cascade_deactivate_children=True)
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
                    **_without_blank(fields, ("phone", "user", "remarks")),
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
