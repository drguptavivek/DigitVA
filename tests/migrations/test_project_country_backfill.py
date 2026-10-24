"""``c3f9a1d7e2b4`` adds the project country and stamps existing submissions.

Throwaway database at the previous head: one project whose forms agree, one
whose forms disagree, one with no forms. Upgrade sets only the agreeing project
and stamps only its submissions; downgrade drops both columns.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_project_country_backfill.py -q
"""
import unittest
from datetime import datetime, timezone

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB_NAME = "minerva_test_projcountry"
PREVIOUS_HEAD = "89f755b1156c"
REVISION = "c3f9a1d7e2b4"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class CountryConfig(TestConfig):
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


class ProjectCountryBackfillTest(unittest.TestCase):
    """Deliberate exception to test-harness rule 2, like the final-age backfill test."""

    def test_backfill_and_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(CountryConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self._seed(db)

                alembic_upgrade(revision=REVISION)
                self.assertEqual(
                    self._projects(db),
                    {"CTRYAG": "BGD", "CTRYDS": None, "CTRYNF": None},
                )
                self.assertEqual(
                    self._stamps(db),
                    {"ctry-ag-1": "BGD", "ctry-ag-2": "BGD", "ctry-ds-1": None, "ctry-ds-2": None},
                )

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                self.assertNotIn(
                    "project_country_iso3", [c["name"] for c in inspector.get_columns("va_project_master")]
                )
                self.assertNotIn(
                    "va_country_iso3", [c["name"] for c in inspector.get_columns("va_submissions")]
                )
                db.engine.dispose()
        finally:
            _drop_database()

    def _projects(self, db):
        with db.engine.connect() as conn:
            return dict(conn.execute(sa.text(
                "SELECT project_id, project_country_iso3 FROM va_project_master")).all())

    def _stamps(self, db):
        with db.engine.connect() as conn:
            return dict(conn.execute(sa.text(
                "SELECT va_sid, va_country_iso3 FROM va_submissions")).all())

    def _seed(self, db):
        now = datetime.now(timezone.utc)
        for project_id in ("CTRYAG", "CTRYDS", "CTRYNF"):
            db.session.execute(sa.text(
                "INSERT INTO va_project_master (project_id, project_code, project_name, project_nickname, "
                "project_status, project_registered_at, project_updated_at) "
                "VALUES (:p, :p, :p, :p, 'active', :now, :now)"), dict(p=project_id, now=now))
            if project_id == "CTRYNF":
                continue
            db.session.execute(sa.text(
                "INSERT INTO va_research_projects (project_id, project_code, project_name, project_nickname, "
                "project_status, project_registered_at, project_updated_at) "
                "VALUES (:p, :p, :p, :p, 'active', :now, :now)"), dict(p=project_id, now=now))
            db.session.execute(sa.text(
                "INSERT INTO va_sites (site_id, project_id, site_name, site_abbr, site_status, "
                "site_registered_at, site_updated_at) VALUES (:s, :p, :s, :s, 'active', :now, :now)"),
                dict(s=project_id[-2:] + "01", p=project_id, now=now))
        db.session.flush()
        forms = [
            ("CTRYAGAG0101", "CTRYAG", "AG01", "IND"), ("CTRYAGAG0102", "CTRYAG", "AG01", "IND"),
            ("CTRYDSDS0101", "CTRYDS", "DS01", "IND"), ("CTRYDSDS0102", "CTRYDS", "DS01", "BGD"),
        ]
        # The agreeing project's forms agree on a code other than the default.
        forms[0] = (forms[0][0], forms[0][1], forms[0][2], "BGD")
        forms[1] = (forms[1][0], forms[1][1], forms[1][2], "BGD")
        for form_id, project_id, site_id, country in forms:
            db.session.execute(sa.text(
                "INSERT INTO va_forms (form_id, project_id, site_id, odk_form_id, odk_project_id, form_type, "
                "form_smartvahiv, form_smartvamalaria, form_smartvahce, form_smartvafreetext, "
                "form_smartvacountry, form_status, form_registered_at, form_updated_at) VALUES "
                "(:f, :p, :s, :o, '97', 'WHO VA 2022', 'False', 'False', 'True', 'True', :c, 'active', "
                ":now, :now)"), dict(f=form_id, p=project_id, s=site_id, o="O" + form_id, c=country, now=now))
        for sid, form_id in (
            ("ctry-ag-1", "CTRYAGAG0101"), ("ctry-ag-2", "CTRYAGAG0102"),
            ("ctry-ds-1", "CTRYDSDS0101"), ("ctry-ds-2", "CTRYDSDS0102"),
        ):
            db.session.execute(sa.text(
                "INSERT INTO va_submissions (va_sid, va_form_id, va_data_collector, va_consent, "
                "va_narration_language, va_deceased_age, va_deceased_gender, va_uniqueid_masked, va_summary, "
                "va_catcount, va_category_list, va_created_at, va_updated_at) VALUES (:sid, :form, 'c', 'yes', "
                "'English', 0, 'male', 'X', :empty, '{}', :empty, :now, :now)"),
                dict(sid=sid, form=form_id, empty=[], now=now))
        db.session.commit()
        db.session.remove()
