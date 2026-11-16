"""Project roster membership (digitva-plgm).

A member is a person on a project's roster, added by the roster's
"Upload users CSV" so a trainer can place them in a unit later. It grants
nothing: no authorization path reads this table
(docs/policy/access-control-model.md, "Project membership").
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MapProjectMember(db.Model):
    __tablename__ = "map_project_members"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "user_id", name="uq_map_project_members_project_user"),
    )

    project_member_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False, index=True
    )
    # Nullable: purging the account that added a member keeps the membership.
    added_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id", ondelete="SET NULL"), nullable=True
    )
    added_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
