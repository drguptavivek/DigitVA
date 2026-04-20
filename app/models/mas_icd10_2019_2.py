from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasIcd1020192(db.Model):
    """ICD-10 2019 hierarchy row with local policy flags."""

    __tablename__ = "mas_icd10_2019_2"
    __table_args__ = (
        sa.Index("ix_mas_icd10_2019_2_parent_code", "parent_code"),
        sa.Index("ix_mas_icd10_2019_2_chapter_code", "chapter_code"),
        sa.Index("ix_mas_icd10_2019_2_block_code", "block_code"),
        sa.Index("ix_mas_icd10_2019_2_three_character_code", "three_character_code"),
        sa.Index("ix_mas_icd10_2019_2_semantic_level", "semantic_level"),
        sa.Index("ix_mas_icd10_2019_2_is_active", "is_active"),
    )

    code: so.Mapped[str] = so.mapped_column(sa.String(16), primary_key=True)
    title: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    node_type: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    semantic_level: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    sort_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=0)

    parent_code: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    chapter_code: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    chapter_title: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    block_code: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    block_title: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    three_character_code: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    three_character_title: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)

    has_children: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=False)
    is_leaf: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    is_three_character_code: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    is_detailed_code: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False
    )

    is_coding_selectable: so.Mapped[bool | None] = so.mapped_column(sa.Boolean, nullable=True)
    sex_selectable: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    age_group_selectable: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    policy_status: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, default="unreviewed"
    )
    restriction_note: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)

    source_version: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    source_path: so.Mapped[str | None] = so.mapped_column(sa.String(512), nullable=True)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
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
        return f"<MasIcd1020192 {self.code}>"
