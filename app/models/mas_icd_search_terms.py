import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasIcdSearchTerms(db.Model):
    """Central COD search vocabulary: one row per term-code link.

    Clinician shorthand and diagnosis synonyms (`MI`, `CVA`, `Kochs`, `RTA`)
    that share no substring with any ICD title, wired into the coding-search
    endpoints. Flattened on purpose (docs/policy/icd-coding-search-vocabulary.md):
    a term that targets several codes is several rows, and `term_normalized`
    is the exact-match lookup key — indexed, deliberately NOT unique.
    `sort_order` breaks ties among a multi-code term's rows (lower first,
    default 100) so the more common target (e.g. TB -> A16, not A15) lists
    first. Admin-managed; deactivation keeps audit history (no delete).
    """

    __tablename__ = "mas_icd_search_terms"
    __table_args__ = (
        # The naming convention (app/__init__.py) already prefixes this with
        # "ck_%(table_name)s_"; pass only the discriminator (digitva-liu).
        sa.CheckConstraint(
            "icd_classification IN ('icd10', 'icd11')",
            name="icd_classification",
        ),
        sa.CheckConstraint(
            "source IN ('seed_used_cod', 'who_inclusion', 'admin', 'telemetry')",
            name="source",
        ),
        sa.Index(
            "ix_mas_icd_search_terms_lookup",
            "term_normalized",
            "icd_classification",
            "is_active",
        ),
    )

    term_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    term: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    term_normalized: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    icd_classification: so.Mapped[str] = so.mapped_column(sa.String(6), nullable=False)
    icd_code: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    source: so.Mapped[str] = so.mapped_column(sa.String(24), nullable=False, default="admin")
    sort_order: so.Mapped[int] = so.mapped_column(
        sa.SmallInteger, nullable=False, default=100, server_default=sa.text("100")
    )
    note: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<MasIcdSearchTerms {self.term_normalized}:{self.icd_classification}:{self.icd_code}>"
