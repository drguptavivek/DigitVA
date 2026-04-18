"""ensure celery scheduler tables exist

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c6
Create Date: 2026-04-19 00:35:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d7"
down_revision = "d0e1f2a3b4c6"
branch_labels = None
depends_on = None


PERIOD_ENUM = postgresql.ENUM(
    "days",
    "hours",
    "minutes",
    "seconds",
    "microseconds",
    name="period",
    create_type=False,
)

SOLAR_EVENT_ENUM = postgresql.ENUM(
    "dawn_astronomical",
    "dawn_nautical",
    "dawn_civil",
    "sunrise",
    "solar_noon",
    "sunset",
    "dusk_civil",
    "dusk_nautical",
    "dusk_astronomical",
    name="solarevent",
    create_type=False,
)


def _ensure_enum_types() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'period') THEN
                    CREATE TYPE period AS ENUM (
                        'days',
                        'hours',
                        'minutes',
                        'seconds',
                        'microseconds'
                    );
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'solarevent') THEN
                    CREATE TYPE solarevent AS ENUM (
                        'dawn_astronomical',
                        'dawn_nautical',
                        'dawn_civil',
                        'sunrise',
                        'solar_noon',
                        'sunset',
                        'dusk_civil',
                        'dusk_nautical',
                        'dusk_astronomical'
                    );
                END IF;
            END $$;
            """
        )
    )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_enum_types()

    if not inspector.has_table("celery_intervalschedule"):
        op.create_table(
            "celery_intervalschedule",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "every",
                sa.Integer(),
                nullable=False,
                comment="Number of interval periods to wait before running the task again",
            ),
            sa.Column(
                "period",
                PERIOD_ENUM,
                nullable=False,
                comment="The type of period between task runs (Example: days)",
            ),
            sa.CheckConstraint("every >= 1", name="celery_intervalschedule_every_check"),
            sa.PrimaryKeyConstraint("id", name="celery_intervalschedule_pkey"),
        )

    if not inspector.has_table("celery_crontabschedule"):
        op.create_table(
            "celery_crontabschedule",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "minute",
                sa.String(length=240),
                nullable=False,
                comment='Cron Minutes to Run. Use "*" for "all". (Example: "0,30")',
            ),
            sa.Column(
                "hour",
                sa.String(length=96),
                nullable=False,
                comment='Cron Hours to Run. Use "*" for "all". (Example: "8,20")',
            ),
            sa.Column(
                "day_of_week",
                sa.String(length=64),
                nullable=False,
                comment='Cron Days Of The Week to Run. Use "*" for "all", Sunday is 0 or 7, Monday is 1. (Example: "0,5")',
            ),
            sa.Column(
                "day_of_month",
                sa.String(length=124),
                nullable=False,
                comment='Cron Days Of The Month to Run. Use "*" for "all". (Example: "1,15")',
            ),
            sa.Column(
                "month_of_year",
                sa.String(length=64),
                nullable=False,
                comment='Cron Months (1-12) Of The Year to Run. Use "*" for "all". (Example: "1,12")',
            ),
            sa.Column(
                "timezone",
                sa.String(length=64),
                nullable=False,
                comment="Timezone to Run the Cron Schedule on. Default is UTC.",
            ),
            sa.PrimaryKeyConstraint("id", name="celery_crontabschedule_pkey"),
        )

    if not inspector.has_table("celery_clockedschedule"):
        op.create_table(
            "celery_clockedschedule",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "clocked_time",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id", name="celery_clockedschedule_pkey"),
        )

    if not inspector.has_table("celery_solarschedule"):
        op.create_table(
            "celery_solarschedule",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "event",
                SOLAR_EVENT_ENUM,
                nullable=False,
                comment="The type of solar event when the job should run",
            ),
            sa.Column(
                "latitude",
                sa.Numeric(precision=9, scale=6),
                nullable=False,
                comment="Run the task when the event happens at this latitude",
            ),
            sa.Column(
                "longitude",
                sa.Numeric(precision=9, scale=6),
                nullable=False,
                comment="Run the task when the event happens at this longitude",
            ),
            sa.CheckConstraint(
                "latitude >= -90::numeric AND latitude <= 90::numeric",
                name="celery_solarschedule_latitude_check",
            ),
            sa.CheckConstraint(
                "longitude >= -180::numeric AND longitude <= 180::numeric",
                name="celery_solarschedule_longitude_check",
            ),
            sa.PrimaryKeyConstraint("id", name="celery_solarschedule_pkey"),
            sa.UniqueConstraint(
                "event",
                "latitude",
                "longitude",
                name="celery_solarschedule_event_latitude_longitude_key",
            ),
        )

    if not inspector.has_table("celery_periodictaskchanged"):
        op.create_table(
            "celery_periodictaskchanged",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "last_update",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name="celery_periodictaskchanged_pkey"),
        )

    if not inspector.has_table("celery_periodictask"):
        op.create_table(
            "celery_periodictask",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "name",
                sa.String(length=255),
                nullable=False,
                comment="Short Description For This Task",
            ),
            sa.Column(
                "task",
                sa.String(length=255),
                nullable=False,
                comment='The Name of the Celery Task that Should be Run.  (Example: "proj.tasks.import_contacts")',
            ),
            sa.Column(
                "args",
                sa.Text(),
                nullable=False,
                comment='JSON encoded positional arguments (Example: ["arg1", "arg2"])',
            ),
            sa.Column(
                "kwargs",
                sa.Text(),
                nullable=False,
                comment='JSON encoded keyword arguments (Example: {"argument": "value"})',
            ),
            sa.Column(
                "queue",
                sa.String(length=255),
                nullable=True,
                comment="Queue defined in CELERY_TASK_QUEUES. Leave None for default queuing.",
            ),
            sa.Column(
                "exchange",
                sa.String(length=255),
                nullable=True,
                comment="Override Exchange for low-level AMQP routing",
            ),
            sa.Column(
                "routing_key",
                sa.String(length=255),
                nullable=True,
                comment="Override Routing Key for low-level AMQP routing",
            ),
            sa.Column(
                "headers",
                sa.Text(),
                nullable=True,
                comment="JSON encoded message headers for the AMQP message.",
            ),
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=True,
                comment="Priority Number between 0 and 255. Supported by: RabbitMQ, Redis (priority reversed, 0 is highest).",
            ),
            sa.Column(
                "expires",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
                comment="Datetime after which the schedule will no longer trigger the task to run",
            ),
            sa.Column(
                "expire_seconds",
                sa.Integer(),
                nullable=True,
                comment="Timedelta with seconds which the schedule will no longer trigger the task to run",
            ),
            sa.Column(
                "one_off",
                sa.Boolean(),
                nullable=False,
                comment="If True, the schedule will only run the task a single time",
            ),
            sa.Column(
                "start_time",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
                comment="Datetime when the schedule should begin triggering the task to run",
            ),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                comment="Set to False to disable the schedule",
            ),
            sa.Column(
                "last_run_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
                comment="Datetime that the schedule last triggered the task to run.",
            ),
            sa.Column(
                "total_run_count",
                sa.Integer(),
                nullable=False,
                comment="Running count of how many times the schedule has triggered the task",
            ),
            sa.Column(
                "date_changed",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
                comment="Datetime that this PeriodicTask was last modified",
            ),
            sa.Column(
                "description",
                sa.Text(),
                nullable=True,
                comment="Detailed description about the details of this Periodic Task",
            ),
            sa.Column(
                "discriminator",
                sa.String(length=20),
                nullable=False,
                comment="Lower case name of the schedule class.",
            ),
            sa.Column(
                "schedule_id",
                sa.Integer(),
                nullable=False,
                comment="ID of the schedule model object.",
            ),
            sa.CheckConstraint(
                "priority >= 0 AND priority <= 255",
                name="celery_periodictask_priority_check",
            ),
            sa.PrimaryKeyConstraint("id", name="celery_periodictask_pkey"),
            sa.UniqueConstraint("name", name="celery_periodictask_name_key"),
        )

    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_celery_periodictask_enabled
            ON celery_periodictask (enabled)
            """
        )
    )


def downgrade():
    op.execute(sa.text("DROP INDEX IF EXISTS ix_celery_periodictask_enabled"))
