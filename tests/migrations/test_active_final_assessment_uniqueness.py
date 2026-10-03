"""Migration and database-constraint coverage for active final COD rows."""

import unittest
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DATABASE = "minerva_test_final_uniqueness"
PARENT = "d9e0f1a2b3c4"
REVISION = "c7a4e2d9f1b6"


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(
        database=database
    )


class FinalUniquenessMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _url(DATABASE).render_as_string(hide_password=False)


def _admin(*statements):
    engine = sa.create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for statement in statements:
                connection.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DATABASE}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DATABASE}"',
    )


class ActiveFinalAssessmentUniquenessTest(unittest.TestCase):
    def test_upgrade_adds_partial_unique_constraints_for_each_role(self):
        from app import db
        from app.models import VaStatuses
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin(f'CREATE DATABASE "{DATABASE}"')
        try:
            app = create_app_without_celery_takeover(FinalUniquenessMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT)
                alembic_upgrade(revision=REVISION)

                inspector = sa.inspect(db.engine)
                coder_indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes("va_final_assessments")
                }
                reviewer_indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes(
                        "va_reviewer_final_assessments"
                    )
                }
                self.assertTrue(
                    coder_indexes["uq_va_final_assessments_active_sid_payload"][
                        "unique"
                    ]
                )
                self.assertTrue(
                    reviewer_indexes[
                        "uq_va_reviewer_final_assessments_active_sid_payload"
                    ]["unique"]
                )

                # Insert through the tables as they stand at REVISION, not the
                # app's models: a later column (va_users.mobile_login,
                # va_final_assessments.is_tester) does not exist yet here.
                meta = sa.MetaData()

                def insert(table, **values):
                    t = sa.Table(table, meta, autoload_with=db.engine)
                    model = db.metadata.tables.get(table)
                    # Required columns the model fills in Python, limited to
                    # those that exist at this revision.
                    for column in t.columns:
                        if (column.name in values or column.nullable
                                or column.server_default is not None
                                or model is None or column.name not in model.c):
                            continue
                        default = model.c[column.name].default
                        if default is not None and default.is_scalar:
                            values[column.name] = default.arg
                        elif default is not None and default.is_callable:
                            values[column.name] = default.arg(None)
                    db.session.execute(sa.insert(t).values(**values))

                project_id = "UNIQ01"
                site_id = "UQ01"
                form_id = "UNIQFORM001"
                sid = "uuid:constraint-final"
                user_id = uuid4()
                payload_id = uuid4()
                now = datetime.now(UTC).replace(tzinfo=None)
                active = VaStatuses.active.name
                insert(
                    "va_users", user_id=user_id, name="Constraint Test",
                    email="constraint-test@example.test", password="unused",
                    vacode_language=["English"], permission={}, landing_page="coder",
                    user_status=active, user_created_at=now, user_updated_at=now,
                )
                insert(
                    "va_research_projects", project_id=project_id, project_code=project_id,
                    project_name="Constraint test", project_nickname="Constraint test",
                    project_status=active, project_registered_at=now, project_updated_at=now,
                )
                if sa.inspect(db.engine).has_table("va_site_master"):
                    insert(
                        "va_site_master", site_id=site_id, site_abbr=site_id,
                        site_name="Constraint site", site_status=active,
                        site_registered_at=now, site_updated_at=now,
                    )
                insert(
                    "va_sites", site_id=site_id, project_id=project_id,
                    site_name="Constraint site", site_abbr=site_id, site_status=active,
                    site_registered_at=now, site_updated_at=now,
                )
                insert(
                    "va_forms", form_id=form_id, project_id=project_id, site_id=site_id,
                    odk_form_id="CONSTRAINT_FORM", odk_project_id="1",
                    form_type="WHO_2022_VA", form_status=active,
                    form_registered_at=now, form_updated_at=now,
                )
                insert(
                    "va_submissions", va_sid=sid, va_form_id=form_id,
                    va_data_collector="test", va_uniqueid_masked="constraint-final",
                    va_consent="yes", va_narration_language="English",
                    va_deceased_age=42, va_deceased_gender="male", va_summary=[],
                    va_catcount={}, va_category_list=[], va_created_at=now, va_updated_at=now,
                )
                insert(
                    "va_submission_payload_versions", payload_version_id=payload_id,
                    va_sid=sid, payload_fingerprint="constraint-fingerprint",
                    payload_data={}, version_status="active",
                    created_by_role="vasystem", version_created_at=now,
                )
                db.session.commit()

                def final(cod):
                    insert(
                        "va_final_assessments", va_finassess_id=uuid4(), va_sid=sid,
                        payload_version_id=payload_id, va_finassess_by=user_id,
                        va_conclusive_cod=cod, va_finassess_status=active,
                        va_finassess_createdat=now, va_finassess_updatedat=now,
                    )

                def reviewer_final(cod):
                    insert(
                        "va_reviewer_final_assessments", va_rfinassess_id=uuid4(), va_sid=sid,
                        payload_version_id=payload_id, va_rfinassess_by=user_id,
                        va_conclusive_cod=cod, va_rfinassess_status=active,
                        va_rfinassess_createdat=now, va_rfinassess_updatedat=now,
                    )

                final("A00")
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    final("A01")
                    db.session.flush()
                db.session.rollback()

                reviewer_final("A00")
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    reviewer_final("A01")
                    db.session.flush()
                db.session.rollback()
                db.session.remove()
                from flask_migrate import downgrade as alembic_downgrade

                alembic_downgrade(revision=PARENT)
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
