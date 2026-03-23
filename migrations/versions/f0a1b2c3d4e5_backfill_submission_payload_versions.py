"""backfill submission payload versions

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-03-23 17:35:00.000000

"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f0a1b2c3d4e5"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


PAYLOAD_VERSION_STATUS_ACTIVE = "active"


def _canonical_payload_fingerprint(payload: dict) -> str:
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def upgrade():
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    submissions = bind.execute(
        sa.text(
            """
            SELECT va_sid, va_data, va_odk_updatedat
            FROM va_submissions
            WHERE active_payload_version_id IS NULL
            """
        )
    ).mappings().all()

    if not submissions:
        return

    payload_versions = sa.table(
        "va_submission_payload_versions",
        sa.column("payload_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("va_sid", sa.String),
        sa.column("source_updated_at", sa.DateTime),
        sa.column("payload_fingerprint", sa.String),
        sa.column("payload_data", postgresql.JSONB),
        sa.column("version_status", sa.String),
        sa.column("created_by_role", sa.String),
        sa.column("created_by", postgresql.UUID(as_uuid=True)),
        sa.column("version_created_at", sa.DateTime),
        sa.column("version_activated_at", sa.DateTime),
        sa.column("superseded_at", sa.DateTime),
        sa.column("rejected_at", sa.DateTime),
        sa.column("rejected_reason", sa.Text),
    )
    submissions_table = sa.table(
        "va_submissions",
        sa.column("va_sid", sa.String),
        sa.column("active_payload_version_id", postgresql.UUID(as_uuid=True)),
    )

    for row in submissions:
        payload_version_id = uuid.uuid4()
        payload_data = row["va_data"] or {}
        bind.execute(
            payload_versions.insert().values(
                payload_version_id=payload_version_id,
                va_sid=row["va_sid"],
                source_updated_at=row["va_odk_updatedat"],
                payload_fingerprint=_canonical_payload_fingerprint(payload_data),
                payload_data=payload_data,
                version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
                created_by_role="vasystem",
                created_by=None,
                version_created_at=now,
                version_activated_at=now,
                superseded_at=None,
                rejected_at=None,
                rejected_reason=None,
            )
        )
        bind.execute(
            submissions_table.update()
            .where(submissions_table.c.va_sid == row["va_sid"])
            .values(active_payload_version_id=payload_version_id)
        )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE va_submissions
            SET active_payload_version_id = NULL
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM va_submission_payload_versions
            WHERE version_status = :version_status
              AND created_by_role = 'vasystem'
            """
        ),
        {"version_status": PAYLOAD_VERSION_STATUS_ACTIVE},
    )
