"""Organization levels and units: serializers, listing, create, update, placement, deactivation, gates."""

from __future__ import annotations

import uuid
from datetime import date as date_type

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgUnitCodingGate,
    MapOrgUnitCollectionGate,
    MasOrgLevel,
    MasOrgUnit,
)
from app.services.org_common import (
    OrganizationError,
    _clean_coordinate,
    _clean_text,
    _clean_url,
    _get_project,
    _uuid,
    normalize_code,
    normalize_level_code,
    odk_choice_list_name_for_level,
    odk_field_name_for_level,
)


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
    new_optional = bool(fields["is_optional"]) if "is_optional" in fields else level.is_optional
    new_active = bool(fields["is_active"]) if "is_active" in fields else level.is_active
    if "is_active" in fields and not new_active:
        active_units = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasOrgUnit).where(
                MasOrgUnit.org_level_id == level.org_level_id, MasOrgUnit.is_active.is_(True)
            )
        )
        if active_units:
            raise OrganizationError("Deactivate or move the units at this level first.")
    if new_active and not new_optional and (level.is_optional or not level.is_active):
        parent_u = _aliased_parent()
        parent_lv = sa.orm.aliased(MasOrgLevel)
        skipping_codes = list(
            db.session.scalars(
                sa.select(MasOrgUnit.unit_code)
                .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
                .outerjoin(parent_u, parent_u.org_unit_id == MasOrgUnit.parent_org_unit_id)
                .outerjoin(parent_lv, parent_lv.org_level_id == parent_u.org_level_id)
                .where(
                    MasOrgUnit.project_id == project_id,
                    MasOrgUnit.is_active.is_(True),
                    MasOrgLevel.depth > level.depth,
                    sa.or_(
                        MasOrgUnit.parent_org_unit_id.is_(None),
                        parent_lv.depth < level.depth,
                    ),
                )
                .order_by(MasOrgUnit.unit_code)
                .limit(10)
            ).all()
        )
        if skipping_codes:
            sample = ", ".join(skipping_codes[:5])
            raise OrganizationError(
                f"Cannot mark level {level.level_code!r} as required while active units skip it "
                f"({sample}). Place those units under a {level.level_code!r} parent first."
            )
    level.is_optional = new_optional
    level.is_active = new_active
    db.session.flush()
    return level


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
    """Maximum depth at which a unit without a parent is a valid placed root.

    Equals the shallowest active non-optional level's depth (so optional top
    levels such as ``state`` above ``district`` do not mark root ``district``
    units as unplaced), falling back to the shallowest active level's depth
    when every active level is optional, or ``None`` with no active level.
    """
    req_depth = db.session.scalar(
        sa.select(sa.func.min(MasOrgLevel.depth)).where(
            MasOrgLevel.project_id == project_id,
            MasOrgLevel.is_active.is_(True),
            MasOrgLevel.is_optional.is_(False),
        )
    )
    if req_depth is not None:
        return req_depth
    return db.session.scalar(
        sa.select(sa.func.min(MasOrgLevel.depth)).where(
            MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True)
        )
    )


def _is_unplaced(unit: MasOrgUnit, level: MasOrgLevel, top_depth: int | None) -> bool:
    """A unit with no parent below the top required level: imported, not yet mapped.

    Policy: docs/policy/organization-model.md ("Unplaced units").
    """
    return unit.parent_org_unit_id is None and top_depth is not None and level.depth > top_depth


def unplaced_unit_codes(project_id: str, *, include_inactive: bool = False) -> list[str]:
    """Codes of the project's unplaced units, in one query, sorted.

    Their descendants are not included; a descendant's ``path`` starts with
    its unplaced root's code, which is how callers exclude whole subtrees.
    """
    req_min = (
        sa.select(sa.func.min(MasOrgLevel.depth))
        .where(
            MasOrgLevel.project_id == project_id,
            MasOrgLevel.is_active.is_(True),
            MasOrgLevel.is_optional.is_(False),
        )
        .scalar_subquery()
    )
    all_min = (
        sa.select(sa.func.min(MasOrgLevel.depth))
        .where(MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True))
        .scalar_subquery()
    )
    stmt = (
        sa.select(MasOrgUnit.unit_code)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.parent_org_unit_id.is_(None),
            MasOrgLevel.depth > sa.func.coalesce(req_min, all_min),
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
    max_root_depth = next((lv.depth for lv in levels if not lv.is_optional), levels[0].depth)
    if parent is None:
        if level.depth > max_root_depth and not allow_unplaced:
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
            # Children must still sit below the new level, with no required level skipped in between.
            child_depth = db.session.scalar(
                sa.select(sa.func.min(MasOrgLevel.depth))
                .select_from(MasOrgUnit)
                .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
                .where(MasOrgUnit.parent_org_unit_id == unit.org_unit_id)
            )
            if child_depth is not None and child_depth <= level.depth:
                raise OrganizationError("Children of this unit would end up at or above its new level.")
            child_levels = list(
                db.session.scalars(
                    sa.select(MasOrgLevel)
                    .join(MasOrgUnit, MasOrgUnit.org_level_id == MasOrgLevel.org_level_id)
                    .where(
                        MasOrgUnit.parent_org_unit_id == unit.org_unit_id,
                        MasOrgUnit.is_active.is_(True),
                    )
                    .distinct()
                ).all()
            )
            if child_levels:
                active_levels = list_levels(project_id, include_inactive=False)
                for ch_lv in child_levels:
                    skipped_down = [
                        lv for lv in active_levels if level.depth < lv.depth < ch_lv.depth and not lv.is_optional
                    ]
                    if skipped_down:
                        names = ", ".join(repr(lv.level_code) for lv in skipped_down)
                        raise OrganizationError(
                            f"Changing this unit to {level.level_code!r} would skip required level(s) "
                            f"{names} above its {ch_lv.level_code!r} child units."
                        )
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
        set_unit_active(
            project_id,
            unit.org_unit_id,
            bool(fields["is_active"]),
            reparent_children_to_org_unit_id=fields.get("reparent_children_to_org_unit_id"),
            cascade_deactivate_children=bool(fields.get("cascade_deactivate_children", False)),
        )
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


def unit_deactivation_preview(project_id: str, org_unit_id: object) -> dict:
    """Return active child units, total active descendants, and eligible replacement parents for *org_unit_id*."""
    unit = _get_unit(project_id, org_unit_id)
    unit_path = str(unit.path)
    active_children_rows = db.session.execute(
        sa.select(MasOrgUnit, MasOrgLevel)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.parent_org_unit_id == unit.org_unit_id,
            MasOrgUnit.is_active.is_(True),
        )
        .order_by(MasOrgUnit.unit_code)
    ).all()
    active_descendant_count = (
        db.session.scalar(
            sa.select(sa.func.count())
            .select_from(MasOrgUnit)
            .where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.org_unit_id != unit.org_unit_id,
                sa.text("path <@ CAST(:path AS ltree)"),
                MasOrgUnit.is_active.is_(True),
            )
            .params(path=unit_path)
        )
        or 0
    )
    active_children = [
        {
            "org_unit_id": str(c.org_unit_id),
            "unit_code": c.unit_code,
            "unit_name": c.unit_name,
            "level_code": lv.level_code,
            "level_name": lv.level_name,
            "depth": lv.depth,
        }
        for c, lv in active_children_rows
    ]
    eligible_parents: list[dict] = []
    if active_children_rows:
        levels = list_levels(project_id, include_inactive=False)
        child_depths = {lv.depth for _, lv in active_children_rows}
        min_child_depth = min(child_depths)
        max_child_depth = max(child_depths)
        for cand in list_units(project_id, include_inactive=False):
            cand_path = str(cand["path"])
            if cand["org_unit_id"] == str(unit.org_unit_id) or cand_path.startswith(unit_path + "."):
                continue
            cand_depth = cand["depth"]
            if cand_depth >= min_child_depth:
                continue
            skipped_req = [
                lv for lv in levels if cand_depth < lv.depth < max_child_depth and not lv.is_optional
            ]
            if skipped_req:
                continue
            eligible_parents.append({
                "org_unit_id": cand["org_unit_id"],
                "unit_code": cand["unit_code"],
                "unit_name": cand["unit_name"],
                "level_code": cand["level_code"],
                "level_name": cand["level_name"],
                "depth": cand_depth,
                "path": cand_path,
            })
    return {
        "org_unit_id": str(unit.org_unit_id),
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "requires_child_action": bool(active_children),
        "active_children_count": len(active_children),
        "active_descendant_count": int(active_descendant_count),
        "active_children": active_children,
        "eligible_parents": eligible_parents,
    }


def set_unit_active(
    project_id: str,
    org_unit_id: object,
    active: bool,
    *,
    reparent_children_to_org_unit_id: object | None = None,
    cascade_deactivate_children: bool = False,
) -> int:
    """Activate a unit, or deactivate a unit after moving or cascading its active children.

    When deactivating a unit that has active child units, the caller must pass
    either ``reparent_children_to_org_unit_id`` (moving active direct children
    and their subtrees under an eligible active parent unit) or
    ``cascade_deactivate_children=True`` (deactivating the entire subtree).
    Returns the number of units whose ``is_active`` state changed.
    """
    unit = _get_unit(project_id, org_unit_id)
    if active:
        parent_unit = db.session.get(MasOrgUnit, unit.parent_org_unit_id) if unit.parent_org_unit_id else None
        if parent_unit is not None and not parent_unit.is_active:
            raise OrganizationError("Reactivate the parent unit first.")
        if unit.is_active:
            return 0
        unit.is_active = True
        db.session.flush()
        return 1

    if reparent_children_to_org_unit_id and cascade_deactivate_children:
        raise OrganizationError(
            "Choose either reparent_children_to_org_unit_id or cascade_deactivate_children, not both."
        )

    unit_path = str(unit.path)
    active_children = list(
        db.session.scalars(
            sa.select(MasOrgUnit)
            .where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.parent_org_unit_id == unit.org_unit_id,
                MasOrgUnit.is_active.is_(True),
            )
            .order_by(MasOrgUnit.unit_code)
        ).all()
    )

    if active_children:
        if reparent_children_to_org_unit_id is not None and str(reparent_children_to_org_unit_id).strip():
            new_parent = _get_unit(project_id, reparent_children_to_org_unit_id)
            if not new_parent.is_active:
                raise OrganizationError("Replacement parent unit is inactive.")
            if new_parent.org_unit_id == unit.org_unit_id or str(new_parent.path).startswith(unit_path + "."):
                raise OrganizationError(
                    "Replacement parent cannot be the unit being deactivated or one of its descendants."
                )
            for child in active_children:
                _validate_parent_for_level(project_id, child.level, new_parent)
            new_parent_path = str(new_parent.path)
            for child in active_children:
                old_child_path = str(child.path)
                new_child_path = f"{new_parent_path}.{child.unit_code}"
                child.parent_org_unit_id = new_parent.org_unit_id
                db.session.flush()
                if new_child_path != old_child_path:
                    _rewrite_subtree_paths(project_id, old_child_path, new_child_path)
            unit = _get_unit(project_id, org_unit_id)
            unit_path = str(unit.path)
        elif not cascade_deactivate_children:
            child_codes = ", ".join(c.unit_code for c in active_children[:5])
            if len(active_children) > 5:
                child_codes += f", +{len(active_children) - 5} more"
            raise OrganizationError(
                f"Unit {unit.unit_code!r} has {len(active_children)} active child unit(s) ({child_codes}). "
                "Choose a replacement parent unit to move them under, or confirm deactivating all child units."
            )

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
        {"project_id": project_id, "path": unit_path},
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


def get_unit_collection_gate(project_id: str, org_unit_id: object) -> MapOrgUnitCollectionGate | None:
    """This unit's own collection gate row, or None (not gated); the resolved
    gate is ``org_grant_service.resolve_unit_collection_gates``."""
    unit = _get_unit(project_id, org_unit_id)
    return db.session.get(MapOrgUnitCollectionGate, unit.org_unit_id)


def serialize_unit_collection_gate(gate: MapOrgUnitCollectionGate | None) -> dict | None:
    from app.services.collection_gate import serialize_settings

    if gate is None:
        return None
    return {"org_unit_id": str(gate.org_unit_id), **serialize_settings(gate)}


def set_unit_collection_gate(project_id: str, org_unit_id: object, data: dict) -> MapOrgUnitCollectionGate:
    """Create or update this unit's own collection gate row from *data*
    (validated by ``collection_gate.clean_settings``; no limit when empty)."""
    from app.services.collection_gate import clean_settings

    unit = _get_unit(project_id, org_unit_id)
    try:
        values = clean_settings(data)
    except ValueError as exc:
        raise OrganizationError(str(exc)) from None
    gate = db.session.get(MapOrgUnitCollectionGate, unit.org_unit_id)
    if gate is None:
        gate = MapOrgUnitCollectionGate(org_unit_id=unit.org_unit_id)
        db.session.add(gate)
    for name, value in values.items():
        setattr(gate, name, value)
    db.session.flush()
    return gate


def clear_unit_collection_gate(project_id: str, org_unit_id: object) -> bool:
    """Delete this unit's own collection gate row, if any; it then inherits."""
    unit = _get_unit(project_id, org_unit_id)
    gate = db.session.get(MapOrgUnitCollectionGate, unit.org_unit_id)
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
