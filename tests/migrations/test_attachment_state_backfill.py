"""The Phase 2 attachment-state migration backfills existing rows correctly.

``b7e4c2a91d38`` adds the source/derivative/local-fallback columns to
``va_submission_attachments`` and derives their starting values from the rows
already there. The rest of the suite builds its schema with ``create_all()`` and
so never runs a backfill; this test builds a throwaway database at the previous
head, seeds the shapes the backfill distinguishes, upgrades, and checks what
landed. It then downgrades and asserts the columns are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_attachment_state_backfill.py -q
"""
import unittest
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, kept clear of every database the suite or the developer
# uses: it is dropped and recreated here.
BACKFILL_DB_NAME = "minerva_test_phase2"

PREVIOUS_HEAD = "d3f1a7c92b64"
PHASE_2_REVISION = "b7e4c2a91d38"

NEW_COLUMNS = (
    "source_state",
    "source_verified_at",
    "source_error_code",
    "source_mime_type",
    "derivative_state",
    "derivative_mime_type",
    "derivative_source_validator",
    "derivative_verified_at",
    "derivative_error_code",
    "local_fallback_state",
)

PROJECT_ID = "PH2PRJ"
SITE_ID = "PH2S"
FORM_ID = "PH2FORM"


def _server_url(database):
    """Swap the database name in the test URL, keeping host/user/password."""
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(
        database=database
    )


class BackfillConfig(TestConfig):
    """TestConfig pointed at the throwaway migration-built database."""

    SQLALCHEMY_DATABASE_URI = _server_url(BACKFILL_DB_NAME).render_as_string(
        hide_password=False
    )


def _admin_execute(*statements):
    """Run CREATE/DROP DATABASE statements outside a transaction."""
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    """Drop the throwaway database, evicting any connection Alembic left open."""
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{BACKFILL_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{BACKFILL_DB_NAME}"',
    )


class AttachmentStateBackfillTest(unittest.TestCase):
    """Deliberate exception to test-harness rule 2, like the schema-drift guard:
    the Alembic env needs an app whose db is bound to the throwaway database.
    This test never touches the shared session schema."""

    maxDiff = None

    def test_backfill_and_downgrade(self):
        from app import create_app, db

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{BACKFILL_DB_NAME}"')
        try:
            app = create_app(BackfillConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                sids = self._seed(db)

                alembic_upgrade(revision=PHASE_2_REVISION)
                self._assert_backfill(db, sids)

                alembic_downgrade(revision=PREVIOUS_HEAD)
                remaining = {
                    column["name"]
                    for column in sa.inspect(db.engine).get_columns(
                        "va_submission_attachments"
                    )
                }
                self.assertEqual(remaining & set(NEW_COLUMNS), set())
                db.engine.dispose()
        finally:
            _drop_database()

    # -- fixtures ---------------------------------------------------------

    def _seed(self, db):
        """Seed one form and the attachment shapes the backfill distinguishes."""
        from app.models import VaForms, VaResearchProjects, VaSites, VaStatuses
        from app.models.va_submissions import VaSubmissions

        now = datetime.now(timezone.utc)
        db.session.add(VaResearchProjects(
            project_id=PROJECT_ID,
            project_code=PROJECT_ID,
            project_name="Phase 2 backfill project",
            project_nickname="Phase2",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=SITE_ID,
            project_id=PROJECT_ID,
            site_name="Phase 2 backfill site",
            site_abbr=SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaForms(
            form_id=FORM_ID,
            project_id=PROJECT_ID,
            site_id=SITE_ID,
            odk_form_id="PH2ODK",
            odk_project_id="97",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()

        sids = {name: str(uuid.uuid4()) for name in ("live", "retired")}
        for name, va_sid in sids.items():
            db.session.add(VaSubmissions(
                va_sid=va_sid,
                va_form_id=FORM_ID,
                va_data_collector="collector",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=1,
                va_deceased_gender="male",
                va_uniqueid_masked="X",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
                va_sync_issue_code="missing_in_odk" if name == "retired" else None,
            ))
        db.session.flush()

        # Written as SQL, not through the model: the model already carries the
        # columns this migration is about to add.
        insert = sa.text(
            "INSERT INTO va_submission_attachments "
            "(va_sid, filename, local_path, mime_type, etag, exists_on_odk, storage_name) "
            "VALUES (:va_sid, :filename, :local_path, :mime_type, :etag, "
            ":exists_on_odk, :storage_name)"
        )
        rows = [
            # image present on disk
            dict(va_sid=sids["live"], filename="photo.jpg", local_path="/data/a.jpg",
                 mime_type="image/jpeg", etag="etag-img", exists_on_odk=True,
                 storage_name="aaa.jpg"),
            # AMR whose MP3 was written
            dict(va_sid=sids["live"], filename="narration.amr", local_path="/data/b.mp3",
                 mime_type="audio/amr", etag="etag-amr", exists_on_odk=True,
                 storage_name="bbb.mp3"),
            # AMR row that never got a local blob
            dict(va_sid=sids["live"], filename="second.AMR", local_path=None,
                 mime_type="audio/amr", etag="etag-amr-2", exists_on_odk=True,
                 storage_name="ccc.mp3"),
            # removed upstream
            dict(va_sid=sids["live"], filename="gone.jpg", local_path=None,
                 mime_type=None, etag=None, exists_on_odk=False, storage_name=None),
            # attachment of a submission retired from ODK
            dict(va_sid=sids["retired"], filename="photo.jpg", local_path="/data/c.jpg",
                 mime_type="image/jpeg", etag="etag-ret", exists_on_odk=True,
                 storage_name="ddd.jpg"),
        ]
        for row in rows:
            db.session.execute(insert, row)
        db.session.commit()
        # Release the connection so the migration's ALTER TABLE is not blocked.
        db.session.remove()
        return sids

    # -- assertions -------------------------------------------------------

    def _assert_backfill(self, db, sids):
        with db.engine.connect() as conn:
            state = {
                (row.va_sid, row.filename): row
                for row in conn.execute(
                    sa.text(
                        "SELECT va_sid, filename, source_state, source_verified_at, "
                        "source_error_code, source_mime_type, derivative_state, "
                        "derivative_mime_type, derivative_source_validator, "
                        "local_fallback_state FROM va_submission_attachments"
                    )
                )
            }

        image = state[(sids["live"], "photo.jpg")]
        self.assertEqual(image.source_state, "listed")
        self.assertIsNone(image.source_verified_at)
        self.assertIsNone(image.source_error_code)
        self.assertIsNone(image.source_mime_type)
        self.assertIsNone(image.derivative_state)
        self.assertEqual(image.local_fallback_state, "present")

        audio_ready = state[(sids["live"], "narration.amr")]
        self.assertEqual(audio_ready.source_state, "listed")
        self.assertEqual(audio_ready.derivative_state, "ready")
        self.assertEqual(audio_ready.derivative_mime_type, "audio/mpeg")
        self.assertEqual(audio_ready.derivative_source_validator, "etag-amr")

        audio_pending = state[(sids["live"], "second.AMR")]
        self.assertEqual(audio_pending.derivative_state, "pending")
        self.assertEqual(audio_pending.derivative_source_validator, "etag-amr-2")

        removed = state[(sids["live"], "gone.jpg")]
        self.assertEqual(removed.source_state, "missing")
        self.assertIsNone(removed.derivative_state)

        retired = state[(sids["retired"], "photo.jpg")]
        self.assertEqual(retired.source_state, "listed")
        self.assertEqual(retired.local_fallback_state, "retained")
