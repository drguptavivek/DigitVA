"""Organization cadres and the level-cadre permission grid."""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgLevelCadre,
    MasCadre,
    MasOrgLevel,
)
from app.services.org_common import (
    OrganizationError,
    _clean_text,
    _get_project,
    _uuid,
    normalize_code,
)


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
        "can_edit_interviews": row.can_edit_interviews,
        "default_roles": list(row.default_roles or []),
        "is_active": row.is_active,
    }


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


def get_level_cadre_permission(org_level_id: uuid.UUID, cadre_id: uuid.UUID) -> MapOrgLevelCadre | None:
    return db.session.scalar(
        sa.select(MapOrgLevelCadre).where(
            MapOrgLevelCadre.org_level_id == org_level_id,
            MapOrgLevelCadre.cadre_id == cadre_id,
            MapOrgLevelCadre.is_active.is_(True),
        )
    )
