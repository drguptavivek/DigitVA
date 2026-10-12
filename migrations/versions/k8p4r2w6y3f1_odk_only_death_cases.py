"""ODK-only interviews get a death-register case (digitva-l8y3).

In a tree (organization) project a VA that arrives from ODK sync with no case
gets one, so "deaths reported" counts every death the system knows. The case
is ``source = 'odk'``, state ``submitted``, owned by the "ODK sync" service
account below (no sign-in: deactivated, no password, no verified email).

- ``va_death_register.source`` CHECK gains ``'odk'``.
- Partial unique index on ``va_sid`` where ``source = 'odk'``: one ODK case per
  submission, so reruns of the sync cannot create a second one.
- The service account row, inserted ``ON CONFLICT DO NOTHING``. Its UUID is
  ``ODK_SYNC_USER_ID`` in app/services/odk_case_service.py; keep the two equal.

Downgrade never deletes cases: it refuses while ``source = 'odk'`` rows exist.
The account row stays, because cases and audit rows may reference it.
Additive and reversible.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "k8p4r2w6y3f1"
down_revision = "j7n3q9w5y2e8"
branch_labels = None
depends_on = None

ODK_SYNC_USER_ID = "a906d0c7-cff9-43bf-ab59-cabaf703535a"
ODK_SYNC_EMAIL = "odk-sync@system.invalid"
SOURCE_CHECK_OLD = "source IN ('register', 'direct')"
SOURCE_CHECK_NEW = "source IN ('register', 'direct', 'odk')"
ODK_SID_INDEX = "uq_va_death_register_odk_va_sid"


def upgrade():
    op.drop_constraint(op.f("ck_va_death_register_source"), "va_death_register", type_="check")
    op.create_check_constraint(op.f("ck_va_death_register_source"), "va_death_register", SOURCE_CHECK_NEW)
    op.create_index(
        ODK_SID_INDEX,
        "va_death_register",
        ["va_sid"],
        unique=True,
        postgresql_where=sa.text("source = 'odk'"),
    )
    # user_status 'deactive' blocks sign-in and sessions (VaUsers.is_active);
    # the password is not a hash, so no password can match it.
    op.execute(
        sa.text(
            """
            INSERT INTO va_users (
                user_id, name, email, password, vacode_language, vacode_formcount,
                permission, landing_page, pw_reset_t_and_c, email_verified,
                user_status, user_created_at, user_updated_at, timezone, auth_session_version
            ) VALUES (
                :user_id, 'ODK sync', :email, '!', '{}', 0,
                CAST('{}' AS jsonb), 'admin', false, false,
                'deactive', now(), now(), 'Asia/Kolkata', 0
            )
            ON CONFLICT (user_id) DO NOTHING
            """
        ).bindparams(user_id=ODK_SYNC_USER_ID, email=ODK_SYNC_EMAIL)
    )


def downgrade():
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM va_death_register WHERE source = 'odk'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} ODK-only case(s) exist; they are data and are not deleted. "
            "Remove or convert them by hand before downgrading."
        )
    op.drop_index(ODK_SID_INDEX, table_name="va_death_register")
    op.drop_constraint(op.f("ck_va_death_register_source"), "va_death_register", type_="check")
    op.create_check_constraint(op.f("ck_va_death_register_source"), "va_death_register", SOURCE_CHECK_OLD)
