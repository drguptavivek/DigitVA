from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import sqlalchemy as sa

from app import db
from app.models import VaSiteMaintenance

MAINTENANCE_GRACE_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_active_site_maintenance(*, now: datetime | None = None) -> VaSiteMaintenance | None:
    reference_time = now or _utcnow()
    return db.session.scalar(
        sa.select(VaSiteMaintenance)
        .where(
            VaSiteMaintenance.enabled.is_(True),
            VaSiteMaintenance.cutoff_at >= reference_time - timedelta(days=7),
        )
        .order_by(VaSiteMaintenance.starts_at.desc(), VaSiteMaintenance.created_at.desc())
        .limit(1)
    )


def serialize_site_maintenance(
    maintenance: VaSiteMaintenance | None,
    *,
    now: datetime | None = None,
) -> dict:
    if maintenance is None:
        return {
            "enabled": False,
            "starts_at": None,
            "cutoff_at": None,
            "message": None,
            "remaining_seconds": None,
            "is_grace_period": False,
            "is_cutoff_passed": False,
        }

    reference_time = now or _utcnow()
    remaining_seconds = max(0, int((maintenance.cutoff_at - reference_time).total_seconds()))
    is_cutoff_passed = reference_time >= maintenance.cutoff_at
    return {
        "enabled": bool(maintenance.enabled),
        "starts_at": maintenance.starts_at.isoformat(),
        "cutoff_at": maintenance.cutoff_at.isoformat(),
        "message": maintenance.message or "",
        "remaining_seconds": remaining_seconds,
        "is_grace_period": maintenance.enabled and not is_cutoff_passed,
        "is_cutoff_passed": is_cutoff_passed,
    }


def start_site_maintenance(
    *,
    actor_user_id: uuid.UUID,
    message: str | None = None,
    now: datetime | None = None,
) -> VaSiteMaintenance:
    reference_time = now or _utcnow()
    maintenance = get_active_site_maintenance(now=reference_time)
    if maintenance is None:
        maintenance = VaSiteMaintenance(
            enabled=True,
            starts_at=reference_time,
            cutoff_at=reference_time + timedelta(minutes=MAINTENANCE_GRACE_MINUTES),
            message=(message or "").strip() or None,
            enabled_by_user_id=actor_user_id,
        )
        db.session.add(maintenance)
    else:
        maintenance.enabled = True
        maintenance.starts_at = reference_time
        maintenance.cutoff_at = reference_time + timedelta(minutes=MAINTENANCE_GRACE_MINUTES)
        maintenance.message = (message or "").strip() or None
        maintenance.enabled_by_user_id = actor_user_id
        maintenance.disabled_at = None
        maintenance.disabled_by_user_id = None
    db.session.commit()
    return maintenance


def end_site_maintenance(
    *,
    actor_user_id: uuid.UUID,
    now: datetime | None = None,
) -> VaSiteMaintenance | None:
    reference_time = now or _utcnow()
    maintenance = get_active_site_maintenance(now=reference_time)
    if maintenance is None:
        return None
    maintenance.enabled = False
    maintenance.disabled_at = reference_time
    maintenance.disabled_by_user_id = actor_user_id
    db.session.commit()
    return maintenance


def should_block_non_admin_after_cutoff(*, now: datetime | None = None) -> bool:
    maintenance = get_active_site_maintenance(now=now)
    if maintenance is None:
        return False
    return bool(serialize_site_maintenance(maintenance, now=now)["is_cutoff_passed"])


def get_site_maintenance_banner_context(
    *,
    is_authenticated: bool,
    is_admin: bool,
    now: datetime | None = None,
) -> dict | None:
    if not is_authenticated:
        return None
    maintenance = get_active_site_maintenance(now=now)
    if maintenance is None:
        return None
    payload = serialize_site_maintenance(maintenance, now=now)
    if not payload["enabled"]:
        return None
    payload["show_countdown"] = bool(not is_admin and payload["is_grace_period"])
    return payload
