"""Every composed form version this server has served.

Policy: docs/policy/field-data-collection.md ("Form version", "Form definition
from the server"). The server records a version the first time it serves it
(``app/services/served_form_service.py``), so there is no deploy step.
``activated_at`` is that first-serve time. ``definition`` keeps the complete
composed definition (every conditional extension on, items tagged with the
extensions that contribute them) so an upload filled on an older version can
be re-checked against the rules that version showed, not today's.
"""

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class MasInstrumentVersions(db.Model):
    __tablename__ = "mas_instrument_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "instrument_code", "version", name="uq_mas_instrument_versions_code_version"
        ),
    )

    id: so.Mapped[int] = so.mapped_column(sa.Integer, primary_key=True)
    instrument_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    version: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    activated_at: so.Mapped[object] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    definition: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return f"InstrumentVersion({self.instrument_code}/{self.version})"
