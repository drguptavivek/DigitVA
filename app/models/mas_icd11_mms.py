import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasIcd11Mms(db.Model):
    """ICD-11 MMS linearization row (a WHO release) with local policy flags.

    One row per ``Linearization URI`` in the WHO Simple Tabulation export for
    a given ``release`` (e.g. ``2026-01``). Mirrors the ICD-10 catalog
    (``MasIcd1020192``) conventions: hierarchy fields come from WHO, policy
    fields (``is_coding_selectable`` etc.) are DigitVA-local and preserved on
    reimport unless explicitly overwritten. See
    docs/policy/icd11-reference-catalog.md.
    """

    __tablename__ = "mas_icd11_mms"
    __table_args__ = (
        sa.UniqueConstraint(
            "release", "linearization_uri", name="uq_mas_icd11_mms_release_linearization"
        ),
        sa.Index("ix_mas_icd11_mms_code", "code"),
        sa.Index("ix_mas_icd11_mms_release", "release"),
        sa.Index(
            "ix_mas_icd11_mms_parent_linearization_uri", "parent_linearization_uri"
        ),
        sa.Index("ix_mas_icd11_mms_chapter_no", "chapter_no"),
        sa.Index("ix_mas_icd11_mms_is_active", "is_active"),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True
    )

    release: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    linearization_uri: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    foundation_uri: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    code: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    block_id: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    title: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    class_kind: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    depth_in_kind: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    chapter_no: so.Mapped[str | None] = so.mapped_column(sa.String(8), nullable=True)
    is_residual: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    is_leaf: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    # WHO leaves this flag's meaning undefined in its readme; stored as-is,
    # informational only, not used for any DigitVA policy decision.
    primary_tabulation: so.Mapped[bool | None] = so.mapped_column(sa.Boolean, nullable=True)
    coding_note: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    sort_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=0)

    parent_foundation_uri: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    parent_linearization_uri: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)

    is_coding_selectable: so.Mapped[bool | None] = so.mapped_column(sa.Boolean, nullable=True)
    sex_selectable: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    age_group_selectable: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    policy_status: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, default="unreviewed"
    )
    restriction_note: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)

    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    source_version: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    source_path: so.Mapped[str | None] = so.mapped_column(sa.String(512), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<MasIcd11Mms {self.release}:{self.code or self.linearization_uri}>"
