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
        from app.models import (
            VaFinalAssessments,
            VaForms,
            VaResearchProjects,
            VaReviewerFinalAssessments,
            VaSites,
            VaStatuses,
            VaSubmissionPayloadVersion,
            VaSubmissions,
            VaUsers,
        )
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

                project_id = "UNIQ01"
                site_id = "UQ01"
                form_id = "UNIQFORM001"
                now = datetime.now(UTC).replace(tzinfo=None)
                user = VaUsers(
                    user_id=uuid4(),
                    name="Constraint Test",
                    email="constraint-test@example.test",
                    password="unused",
                    vacode_language=["English"],
                    permission={},
                    landing_page="coder",
                    user_status=VaStatuses.active,
                    user_created_at=now,
                    user_updated_at=now,
                )
                db.session.add_all(
                    [
                        VaResearchProjects(
                            project_id=project_id,
                            project_code=project_id,
                            project_name="Constraint test",
                            project_nickname="Constraint test",
                            project_status=VaStatuses.active,
                            project_registered_at=now,
                            project_updated_at=now,
                        ),
                        VaSites(
                            site_id=site_id,
                            project_id=project_id,
                            site_name="Constraint site",
                            site_abbr=site_id,
                            site_status=VaStatuses.active,
                            site_registered_at=now,
                            site_updated_at=now,
                        ),
                        user,
                    ]
                )
                db.session.flush()
                db.session.add(
                    VaForms(
                        form_id=form_id,
                        project_id=project_id,
                        site_id=site_id,
                        odk_form_id="CONSTRAINT_FORM",
                        odk_project_id="1",
                        form_type="WHO_2022_VA",
                        form_status=VaStatuses.active,
                        form_registered_at=now,
                        form_updated_at=now,
                    )
                )
                submission = VaSubmissions(
                    va_sid="uuid:constraint-final",
                    va_form_id=form_id,
                    va_data_collector="test",
                    va_uniqueid_masked="constraint-final",
                    va_consent="yes",
                    va_narration_language="English",
                    va_deceased_age=42,
                    va_deceased_gender="male",
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                    va_created_at=now,
                    va_updated_at=now,
                )
                db.session.add(submission)
                db.session.flush()
                payload = VaSubmissionPayloadVersion(
                    va_sid=submission.va_sid,
                    payload_fingerprint="constraint-fingerprint",
                    payload_data={},
                    version_status="active",
                    created_by_role="vasystem",
                    version_created_at=now,
                )
                db.session.add(payload)
                db.session.flush()
                submission.active_payload_version_id = payload.payload_version_id
                db.session.flush()

                coder = VaFinalAssessments(
                    va_sid=submission.va_sid,
                    payload_version_id=payload.payload_version_id,
                    va_finassess_by=user.user_id,
                    va_conclusive_cod="A00",
                    va_finassess_status=VaStatuses.active,
                    va_finassess_createdat=now,
                    va_finassess_updatedat=now,
                )
                db.session.add(coder)
                db.session.commit()

                duplicate_coder = VaFinalAssessments(
                    va_sid=submission.va_sid,
                    payload_version_id=payload.payload_version_id,
                    va_finassess_by=user.user_id,
                    va_conclusive_cod="A01",
                    va_finassess_status=VaStatuses.active,
                    va_finassess_createdat=now,
                    va_finassess_updatedat=now,
                )
                db.session.add(duplicate_coder)
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.flush()
                db.session.rollback()

                reviewer = VaReviewerFinalAssessments(
                    va_sid=submission.va_sid,
                    payload_version_id=payload.payload_version_id,
                    va_rfinassess_by=user.user_id,
                    va_conclusive_cod="A00",
                    va_rfinassess_status=VaStatuses.active,
                    va_rfinassess_createdat=now,
                    va_rfinassess_updatedat=now,
                )
                db.session.add(reviewer)
                db.session.commit()
                duplicate_reviewer = VaReviewerFinalAssessments(
                    va_sid=submission.va_sid,
                    payload_version_id=payload.payload_version_id,
                    va_rfinassess_by=user.user_id,
                    va_conclusive_cod="A01",
                    va_rfinassess_status=VaStatuses.active,
                    va_rfinassess_createdat=now,
                    va_rfinassess_updatedat=now,
                )
                db.session.add(duplicate_reviewer)
                with self.assertRaises(sa.exc.IntegrityError):
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
