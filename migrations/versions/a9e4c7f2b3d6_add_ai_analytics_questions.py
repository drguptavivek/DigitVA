"""add AI analytics questions: reader role, run function, saved queries, audit log

docs/policy/ai-analytics-questions.md (digitva-qwvt). Creates the
``digitva_ai_reader`` NOLOGIN role (cluster-wide, so a DO block tolerates a
role another database or a parallel test worker already made, or makes at
the same moment) and grants it
to the migrating user so the app can ``SET LOCAL ROLE`` to it. Adds
``digitva_ai_run(text, integer)``, a SECURITY DEFINER function owned by the reader
that runs the generated SQL: inside a security-definer function PostgreSQL
refuses to change ``role``, so ``SELECT set_config('role', <app user>, true)``
cannot climb back out of the reader (a plain ``SET ROLE`` can, because the
check is against the session user). The function caps ``work_mem`` at 16MB
and ``temp_file_limit`` at 256MB (a role-level setting would not apply under
``SET ROLE``), and streams the rows, raising SQLSTATE 54D01 once their JSON
passes 1MB (the second argument may only lower that). Then
``va_ai_saved_queries`` and ``va_ai_query_audit_log``.

``temp_file_limit`` is a superuser parameter. The migrating user must be a
superuser (as ``minerva`` is on dev), or on PostgreSQL 15+ hold
``SET ON PARAMETER temp_file_limit WITH GRANT OPTION``: it needs SET to create
the function with that clause, and the grant option for
``GRANT SET ON PARAMETER temp_file_limit TO digitva_ai_reader``, which the
function needs at call time (it applies its SET clauses as its owner).

Downgrade drops the function and the tables but keeps the role and its
parameter grant: both are cluster-wide, and another database on the same
cluster (a test database, a parallel worker) may still use them. To remove
them by hand: ``REVOKE SET ON PARAMETER temp_file_limit FROM
digitva_ai_reader; DROP ROLE digitva_ai_reader``.

Revision ID: a9e4c7f2b3d6
Revises: c5e8a2f4b7d1
Create Date: 2026-10-27 18:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a9e4c7f2b3d6"
down_revision = "c5e8a2f4b7d1"
branch_labels = None
depends_on = None

# Frozen copy of app.services.ai_analytics_sandbox.READER_SETUP_SQL at the
# time of writing; migrations inline their SQL
# (tests/migrations/test_no_app_imports_in_migrations.py).
READER_SETUP_SQL = r"""
DO $$
BEGIN
    CREATE ROLE digitva_ai_reader NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DO $$
BEGIN
    EXECUTE format('GRANT digitva_ai_reader TO %I', current_user);
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DO $$
BEGIN
    GRANT SET ON PARAMETER temp_file_limit TO digitva_ai_reader;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DROP FUNCTION IF EXISTS digitva_ai_run(text);
CREATE OR REPLACE FUNCTION digitva_ai_run(query text, max_bytes integer DEFAULT 1048576)
RETURNS SETOF json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET work_mem = '16MB'
SET temp_file_limit = '256MB'
AS $fn$
DECLARE
    r json;
    total bigint := 0;
    cap bigint := least(max_bytes, 1048576);
BEGIN
    FOR r IN EXECUTE 'SELECT to_json(q) FROM (' || query || E'\n) q LIMIT 501' LOOP
        total := total + octet_length(r::text);
        IF total > cap THEN
            RAISE EXCEPTION 'The result is larger than % bytes.', cap USING ERRCODE = '54D01';
        END IF;
        RETURN NEXT r;
    END LOOP;
END
$fn$;
ALTER FUNCTION digitva_ai_run(text, integer) OWNER TO digitva_ai_reader;
REVOKE ALL ON FUNCTION digitva_ai_run(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION digitva_ai_run(text, integer) TO digitva_ai_reader;
"""


def upgrade() -> None:
    op.execute(READER_SETUP_SQL)

    op.create_table(
        "va_ai_saved_queries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("original_prompt", sa.Text(), nullable=False),
        sa.Column("validated_sql", sa.Text(), nullable=False),
        sa.Column("layout_recipe", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["va_users.user_id"],
            name=op.f("fk_va_ai_saved_queries_owner_user_id_va_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_va_ai_saved_queries")),
    )
    op.create_index(
        "ix_va_ai_saved_queries_owner_user_id", "va_ai_saved_queries", ["owner_user_id"], unique=False
    )

    op.create_table(
        "va_ai_query_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("turn", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("used_retry", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("mode IN ('ai_llm', 'saved_query_rerun')", name="mode"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["va_users.user_id"],
            name=op.f("fk_va_ai_query_audit_log_user_id_va_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_va_ai_query_audit_log")),
    )
    # The composite index also serves lookups by user_id alone.
    op.create_index(
        "ix_va_ai_query_audit_log_user_id_created_at",
        "va_ai_query_audit_log",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_va_ai_query_audit_log_user_id_created_at", table_name="va_ai_query_audit_log")
    op.drop_table("va_ai_query_audit_log")
    op.drop_index("ix_va_ai_saved_queries_owner_user_id", table_name="va_ai_saved_queries")
    op.drop_table("va_ai_saved_queries")
    # The role and its parameter grant stay: cluster-wide (see the module
    # docstring). (text) is the signature of earlier drafts of this revision.
    op.execute("DROP FUNCTION IF EXISTS digitva_ai_run(text, integer)")
    op.execute("DROP FUNCTION IF EXISTS digitva_ai_run(text)")
