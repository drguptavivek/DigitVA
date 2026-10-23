"""``e7b2c4d8f1a3`` gives web/device submissions ``finalAgeInYears`` and a real age.

Builds a throwaway database at the previous head, seeds a web row (no
``finalAgeInYears``, ``va_deceased_age`` 0), a web row that already has one and
an ODK row, upgrades, checks, then downgrades and checks the web row is back.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_backfill_final_age_in_years.py -q
"""
import json
import unittest
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB_NAME = "minerva_test_finalage"
PREVIOUS_HEAD = "d6a1f3b8c2e4"
REVISION = "e7b2c4d8f1a3"
AUDIT = "_mig_e7b2c4d8f1a3_final_age"
PROJECT_ID, SITE_ID, FORM_ID = "FAGPRJ", "FAGS", "FAGFORM"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class FinalAgeConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(DB_NAME).render_as_string(hide_password=False)


def _admin_execute(*statements):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


class BackfillFinalAgeTest(unittest.TestCase):
    """Deliberate exception to test-harness rule 2, like the schema-drift guard."""

    def test_backfill_and_downgrade(self):
        from app import db

        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(FinalAgeConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                sids = self._seed(db)

                alembic_upgrade(revision=REVISION)
                web, kept, odk = (self._state(db, sids[k]) for k in ("web", "kept", "odk"))
                self.assertEqual(web["payload"]["finalAgeInYears"], "47")
                self.assertEqual(web["age"], 47)
                self.assertEqual(web["source"], "ageInYears")
                self.assertEqual(kept["payload"]["finalAgeInYears"], "62")
                self.assertEqual(kept["age"], 0)
                self.assertNotIn("finalAgeInYears", odk["payload"])
                self.assertEqual(odk["age"], 0)

                alembic_downgrade(revision=PREVIOUS_HEAD)
                web = self._state(db, sids["web"])
                self.assertNotIn("finalAgeInYears", web["payload"])
                self.assertEqual(web["age"], 0)
                self.assertEqual(self._state(db, sids["kept"])["payload"]["finalAgeInYears"], "62")
                self.assertFalse(sa.inspect(db.engine).has_table(AUDIT))
                db.engine.dispose()
        finally:
            _drop_database()

    def _state(self, db, va_sid):
        with db.engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT v.payload_data, s.va_deceased_age, s.va_deceased_age_source "
                "FROM va_submissions s JOIN va_submission_payload_versions v ON v.va_sid = s.va_sid "
                "WHERE s.va_sid = :sid"), {"sid": va_sid}).one()
        return {"payload": row[0], "age": row[1], "source": row[2]}

    def _seed(self, db):
        from app.models import VaResearchProjects, VaSites, VaStatuses

        now = datetime.now(timezone.utc)
        db.session.add(VaResearchProjects(
            project_id=PROJECT_ID, project_code=PROJECT_ID, project_name="Final age project",
            project_nickname="FinalAge", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=SITE_ID, project_id=PROJECT_ID, site_name="Final age site", site_abbr=SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.execute(sa.text(
            "INSERT INTO va_forms (form_id, project_id, site_id, odk_form_id, odk_project_id, form_type, "
            "form_smartvahiv, form_smartvamalaria, form_smartvahce, form_smartvafreetext, form_smartvacountry, "
            "form_status, form_registered_at, form_updated_at) VALUES (:form_id, :project_id, :site_id, "
            ":odk_form_id, '97', 'WHO VA 2022', 'False', 'False', 'True', 'True', 'IND', :status, :now, :now)"),
            dict(form_id=FORM_ID, project_id=PROJECT_ID, site_id=SITE_ID, odk_form_id="FAGODK",
                 status=VaStatuses.active.value, now=now))
        sids = {"web": f"web-{uuid.uuid4()}", "kept": f"web-{uuid.uuid4()}", "odk": f"uuid:{uuid.uuid4()}"}
        payloads = {
            "web": {"ageInYears": "47", "isAdult": "1"},
            "kept": {"ageInYears": "47", "finalAgeInYears": "62"},
            "odk": {"ageInYears": "47"},
        }
        for name, va_sid in sids.items():
            db.session.execute(sa.text(
                "INSERT INTO va_submissions (va_sid, va_form_id, va_data_collector, va_consent, "
                "va_narration_language, va_deceased_age, va_deceased_gender, va_uniqueid_masked, va_summary, "
                "va_catcount, va_category_list, va_created_at, va_updated_at) VALUES (:sid, :form, 'c', 'yes', "
                "'English', 0, 'male', 'X', :empty, '{}', :empty, :now, :now)"),
                dict(sid=va_sid, form=FORM_ID, empty=[], now=now))
            db.session.execute(sa.text(
                "INSERT INTO va_submission_payload_versions (payload_version_id, va_sid, payload_fingerprint, "
                "payload_data, version_status, created_by_role, version_created_at) VALUES (:id, :sid, 'x', "
                "CAST(:data AS jsonb), 'active', 'vasystem', :now)"),
                dict(id=uuid.uuid4(), sid=va_sid, data=json.dumps(payloads[name]), now=now))
        db.session.commit()
        db.session.remove()
        return sids
