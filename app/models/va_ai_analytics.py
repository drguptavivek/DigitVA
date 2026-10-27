import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db

AI_MODE_LLM = "ai_llm"
AI_MODE_SAVED_RERUN = "saved_query_rerun"


class VaAiSavedQuery(db.Model):
    """A user's own saved AI analytics question (docs/policy/ai-analytics-questions.md).

    Stores the validated SQL over ``ai_cube`` and the chart recipe, never a
    scope: the scope is resolved for the caller on every run. Never shared.
    """

    __tablename__ = "va_ai_saved_queries"

    id: so.Mapped[int] = so.mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    owner_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False, index=True
    )
    title: so.Mapped[str] = so.mapped_column(sa.String(160), nullable=False)
    description: so.Mapped[str | None] = so.mapped_column(sa.String(500), nullable=True)
    original_prompt: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    validated_sql: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    layout_recipe: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    run_count: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    last_run_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=sa.text("now()"),
    )


class VaAiQueryAuditLog(db.Model):
    """One row per model call (``ai_llm``) or saved-query rerun.

    ``ai_llm`` rows since the start of the ISO week are the weekly quota.
    Holds the question and SQL, never result rows.
    """

    __tablename__ = "va_ai_query_audit_log"
    __table_args__ = (
        sa.CheckConstraint("mode IN ('ai_llm', 'saved_query_rerun')", name="mode"),
        sa.Index("ix_va_ai_query_audit_log_user_id_created_at", "user_id", "created_at"),
    )

    id: so.Mapped[int] = so.mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    mode: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    prompt: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    generated_sql: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    turn: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=1, server_default=sa.text("1")
    )
    used_retry: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    prompt_tokens: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    cached_tokens: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    output_tokens: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    error_code: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    # The provider ("anthropic", "gemini") and model of an ai_llm call.
    provider: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    model: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=sa.text("now()"),
    )
