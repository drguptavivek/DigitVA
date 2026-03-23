"""Add SmartVA run history and output tables.

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-03-23 15:15:00.000000
"""

from datetime import datetime, timezone
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "3c4d5e6f7a8b"
down_revision = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_smartva_runs",
        sa.Column("va_smartva_run_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_source", sa.String(length=32), nullable=False),
        sa.Column("va_smartva_outcome", sa.String(length=16), nullable=False),
        sa.Column("va_smartva_failure_stage", sa.String(length=32), nullable=True),
        sa.Column("va_smartva_failure_detail", sa.Text(), nullable=True),
        sa.Column("run_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("va_smartva_run_started_at", sa.DateTime(), nullable=False),
        sa.Column("va_smartva_run_completed_at", sa.DateTime(), nullable=False),
        sa.Column("va_smartva_run_updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["payload_version_id"], ["va_submission_payload_versions.payload_version_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
        sa.PrimaryKeyConstraint("va_smartva_run_id"),
    )
    op.create_index(
        "ix_va_smartva_runs_va_sid",
        "va_smartva_runs",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_runs_payload_version_id",
        "va_smartva_runs",
        ["payload_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_runs_trigger_source",
        "va_smartva_runs",
        ["trigger_source"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_runs_va_smartva_outcome",
        "va_smartva_runs",
        ["va_smartva_outcome"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_runs_va_smartva_run_id",
        "va_smartva_runs",
        ["va_smartva_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_runs_started_at",
        "va_smartva_runs",
        ["va_smartva_run_started_at"],
        unique=False,
    )

    op.create_table(
        "va_smartva_run_outputs",
        sa.Column("va_smartva_run_output_id", sa.Uuid(), nullable=False),
        sa.Column("va_smartva_run_id", sa.Uuid(), nullable=False),
        sa.Column("output_kind", sa.String(length=32), nullable=False),
        sa.Column("output_source_name", sa.String(length=64), nullable=True),
        sa.Column("output_row_index", sa.Integer(), nullable=False),
        sa.Column("output_sid", sa.String(length=64), nullable=True),
        sa.Column("output_resultfor", sa.String(length=16), nullable=True),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["va_smartva_run_id"],
            ["va_smartva_runs.va_smartva_run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("va_smartva_run_output_id"),
    )
    op.create_index(
        "ix_va_smartva_run_outputs_run_id",
        "va_smartva_run_outputs",
        ["va_smartva_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_run_outputs_output_sid",
        "va_smartva_run_outputs",
        ["output_sid"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_run_outputs_created_at",
        "va_smartva_run_outputs",
        ["output_created_at"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_run_outputs_id",
        "va_smartva_run_outputs",
        ["va_smartva_run_output_id"],
        unique=False,
    )

    op.add_column(
        "va_smartva_results",
        sa.Column("smartva_run_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_smartva_results_smartva_run_id",
        "va_smartva_results",
        ["smartva_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_smartva_results_run_id",
        "va_smartva_results",
        "va_smartva_runs",
        ["smartva_run_id"],
        ["va_smartva_run_id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    results = bind.execute(
        sa.text(
            """
            SELECT
                va_smartva_id,
                va_sid,
                payload_version_id,
                va_smartva_age,
                va_smartva_gender,
                va_smartva_cause1,
                va_smartva_likelihood1,
                va_smartva_keysymptom1,
                va_smartva_cause2,
                va_smartva_likelihood2,
                va_smartva_keysymptom2,
                va_smartva_cause3,
                va_smartva_likelihood3,
                va_smartva_keysymptom3,
                va_smartva_allsymptoms,
                va_smartva_resultfor,
                va_smartva_cause1icd,
                va_smartva_cause2icd,
                va_smartva_cause3icd,
                va_smartva_outcome,
                va_smartva_failure_stage,
                va_smartva_failure_detail,
                va_smartva_addedat,
                va_smartva_updatedat
            FROM va_smartva_results
            """
        )
    ).mappings()

    now = datetime.now(timezone.utc)
    for row in results:
        run_id = uuid.uuid4()
        bind.execute(
            sa.text(
                """
                INSERT INTO va_smartva_runs (
                    va_smartva_run_id,
                    va_sid,
                    payload_version_id,
                    trigger_source,
                    va_smartva_outcome,
                    va_smartva_failure_stage,
                    va_smartva_failure_detail,
                    run_metadata,
                    va_smartva_run_started_at,
                    va_smartva_run_completed_at,
                    va_smartva_run_updated_at
                ) VALUES (
                    :run_id,
                    :va_sid,
                    :payload_version_id,
                    'legacy_backfill',
                    :outcome,
                    :failure_stage,
                    :failure_detail,
                    CAST(:run_metadata AS JSONB),
                    :started_at,
                    :completed_at,
                    :updated_at
                )
                """
            ),
            {
                "run_id": run_id,
                "va_sid": row["va_sid"],
                "payload_version_id": row["payload_version_id"],
                "outcome": row["va_smartva_outcome"],
                "failure_stage": row["va_smartva_failure_stage"],
                "failure_detail": row["va_smartva_failure_detail"],
                "run_metadata": '{"backfilled": true}',
                "started_at": row["va_smartva_addedat"] or now,
                "completed_at": row["va_smartva_updatedat"] or row["va_smartva_addedat"] or now,
                "updated_at": row["va_smartva_updatedat"] or row["va_smartva_addedat"] or now,
            },
        )

        if row["va_smartva_outcome"] == "success":
            bind.execute(
                sa.text(
                    """
                    INSERT INTO va_smartva_run_outputs (
                        va_smartva_run_output_id,
                        va_smartva_run_id,
                        output_kind,
                        output_source_name,
                        output_row_index,
                        output_sid,
                        output_resultfor,
                        output_payload,
                        output_created_at
                    ) VALUES (
                        :output_id,
                        :run_id,
                        'formatted_result_row',
                        :source_name,
                        0,
                        :output_sid,
                        :resultfor,
                        CAST(:payload AS JSONB),
                        :created_at
                    )
                    """
                ),
                {
                    "output_id": uuid.uuid4(),
                    "run_id": run_id,
                    "source_name": _source_name_for_result_for(
                        row["va_smartva_resultfor"]
                    ),
                    "output_sid": row["va_sid"],
                    "resultfor": row["va_smartva_resultfor"],
                    "payload": _payload_json_for_result_row(row),
                    "created_at": row["va_smartva_addedat"] or now,
                },
            )

        bind.execute(
            sa.text(
                """
                UPDATE va_smartva_results
                SET smartva_run_id = :run_id
                WHERE va_smartva_id = :result_id
                """
            ),
            {"run_id": run_id, "result_id": row["va_smartva_id"]},
        )


def downgrade():
    op.drop_constraint(
        "fk_va_smartva_results_run_id",
        "va_smartva_results",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_smartva_results_smartva_run_id",
        table_name="va_smartva_results",
    )
    op.drop_column("va_smartva_results", "smartva_run_id")

    op.drop_index(
        "ix_va_smartva_run_outputs_id",
        table_name="va_smartva_run_outputs",
    )
    op.drop_index(
        "ix_va_smartva_run_outputs_created_at",
        table_name="va_smartva_run_outputs",
    )
    op.drop_index(
        "ix_va_smartva_run_outputs_output_sid",
        table_name="va_smartva_run_outputs",
    )
    op.drop_index(
        "ix_va_smartva_run_outputs_run_id",
        table_name="va_smartva_run_outputs",
    )
    op.drop_table("va_smartva_run_outputs")

    op.drop_index(
        "ix_va_smartva_runs_started_at",
        table_name="va_smartva_runs",
    )
    op.drop_index(
        "ix_va_smartva_runs_va_smartva_run_id",
        table_name="va_smartva_runs",
    )
    op.drop_index(
        "ix_va_smartva_runs_va_smartva_outcome",
        table_name="va_smartva_runs",
    )
    op.drop_index(
        "ix_va_smartva_runs_trigger_source",
        table_name="va_smartva_runs",
    )
    op.drop_index(
        "ix_va_smartva_runs_payload_version_id",
        table_name="va_smartva_runs",
    )
    op.drop_index(
        "ix_va_smartva_runs_va_sid",
        table_name="va_smartva_runs",
    )
    op.drop_table("va_smartva_runs")


def _source_name_for_result_for(result_for):
    if result_for == "for_adult":
        return "adult-likelihoods.csv"
    if result_for == "for_child":
        return "child-likelihoods.csv"
    if result_for == "for_neonate":
        return "neonate-likelihoods.csv"
    return None


def _payload_json_for_result_row(row):
    return json.dumps({
        "sid": row["va_sid"],
        "age": row["va_smartva_age"],
        "sex": row["va_smartva_gender"],
        "cause1": row["va_smartva_cause1"],
        "likelihood1": row["va_smartva_likelihood1"],
        "key_symptom1": row["va_smartva_keysymptom1"],
        "cause2": row["va_smartva_cause2"],
        "likelihood2": row["va_smartva_likelihood2"],
        "key_symptom2": row["va_smartva_keysymptom2"],
        "cause3": row["va_smartva_cause3"],
        "likelihood3": row["va_smartva_likelihood3"],
        "key_symptom3": row["va_smartva_keysymptom3"],
        "all_symptoms": row["va_smartva_allsymptoms"],
        "result_for": row["va_smartva_resultfor"],
        "cause1_icd": row["va_smartva_cause1icd"],
        "cause2_icd": row["va_smartva_cause2icd"],
        "cause3_icd": row["va_smartva_cause3icd"],
    })
