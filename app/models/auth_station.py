"""Offline station onboarding: custodian, roster and the signed station
configs issued to a station (beads digitva-gb8w.4, digitva-gb8w.8).

A station is an ``auth_devices`` row. Contract
docs/policy/offline-api-contract.md 3.8 and 4.1; file format
docs/policy/offline-bundle-and-transfer.md 6.4. Rules live in
app/services/station_config_service.py; every change is audited in
``auth_security_events``.
"""

import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


def _utcnow():
    return datetime.now(UTC)


class AuthStationCustodian(db.Model):
    """The responsible person identified at onboarding, one per station
    (contract 4.1). ``verified_by`` is the admin or data manager who
    verified them."""

    __tablename__ = "auth_station_custodians"
    __table_args__ = (
        sa.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="contact"),
    )

    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), primary_key=True
    )
    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    designation: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    phone: so.Mapped[str | None] = so.mapped_column(sa.String(10), nullable=True)
    email: so.Mapped[str | None] = so.mapped_column(sa.String(254), nullable=True)
    onboarded_on: so.Mapped[date] = so.mapped_column(sa.Date, nullable=False)
    verified_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AuthStationRosterMember(db.Model):
    """One server user on a station's roster. ``roles`` is
    ``[{role, project_id, site_id, org_unit_id}]``, validated by the service
    against the user's live grants when set and again when a config is
    issued."""

    __tablename__ = "auth_station_roster"
    __table_args__ = (
        sa.UniqueConstraint("device_id", "user_id", name="uq_auth_station_roster_device_user"),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), nullable=False
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    designation: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    roles: so.Mapped[list] = so.mapped_column(JSONB, nullable=False)
    active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    updated_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AuthStationConfig(db.Model):
    """A signed station config issued to a station: the exact two-line file
    served to the browser export and the station's bearer. The newest row of
    a device is the config in force; older rows stay so a bundle naming an
    earlier ``station_config_id`` can be checked (bundle spec 5.2)."""

    __tablename__ = "auth_station_configs"
    __table_args__ = (
        sa.Index("ix_auth_station_configs_device_issued", "device_id", "issued_at"),
    )

    config_id: so.Mapped[uuid.UUID] = so.mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), nullable=False
    )
    issued_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    issued_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    signed_text: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    text_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
