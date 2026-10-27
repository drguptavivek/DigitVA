"""Add auth_devices.client_device_uuid.

Revision ID: c7a3e9d1f5b8
Revises: b4f8d2e6a1c3
Create Date: 2026-10-27 15:00:00.000000

Collect Plus mints one UUID per install and sends it at enrolment (both
enrolment QR and sign-in QR) so a later standalone push can name its device
(docs/policy/field-data-collection.md, Path C). Additive and nullable: devices
enrolled before this, and the plain build, leave it NULL.

A plain (non-unique) index: every enrolment makes a new device row, so a
reinstalled or re-enrolled install legitimately repeats its UUID, and the value
is a client claim that must not let one caller block another's enrolment.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7a3e9d1f5b8"
down_revision = "b4f8d2e6a1c3"
branch_labels = None
depends_on = None

INDEX = "ix_auth_devices_client_device_uuid"


def upgrade():
    op.add_column("auth_devices", sa.Column("client_device_uuid", sa.Uuid(as_uuid=True), nullable=True))
    op.create_index(INDEX, "auth_devices", ["client_device_uuid"])


def downgrade():
    op.drop_index(INDEX, table_name="auth_devices")
    op.drop_column("auth_devices", "client_device_uuid")
