"""Weekly reset safety against a disposable test database, with fake verified backups."""

import os
import uuid
from datetime import UTC, datetime
from unittest import TestCase, mock

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from app import db
from app.models import (
    MasOrgUnit,
    VaDbBackup,
    VaDeathRegister,
    VaDemoResetRun,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import synthetic_demo_service as svc
from app.services.db_backup_service import BackupOutcome
from tests.base import BaseTestCase


class SyntheticDemoTests(BaseTestCase):
    # Reset deliberately uses a second connection to hold locks across backup commits.
    isolate_in_transaction = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.config = mock.patch.dict(self.app.config, DIGITVA_WEEKLY_DEMO_PROJECT_ID="DEMO01")
        self.config.start()
        self.addCleanup(self.config.stop)
        self.env = mock.patch.dict(os.environ, DIGITVA_DEMO_PASSWORD="Synthetic-Test-Only-123")
        self.env.start()
        self.addCleanup(self.env.stop)
        self.backups = []
        self.control_deaths = []
        svc.seed_organization_demo()
        self.backup_mock = mock.patch.object(svc, "create_db_backup", side_effect=self._backup)
        self.backup_mock.start()
        self.addCleanup(self.backup_mock.stop)

    def _backup(self, **_kwargs):
        row = VaDbBackup(
            status="success",
            triggered_by="scheduled",
            store="local",
            object_key="synthetic-test.dump",
            size_bytes=100,
            sha256="a" * 64,
        )
        db.session.add(row)
        db.session.commit()
        self.backups.append(row.backup_id)
        return BackupOutcome(
            str(row.backup_id), "success", "local", row.object_key, row.size_bytes, row.sha256, None
        )

    def tearDown(self):
        db.session.rollback()
        db.session.execute(
            sa.delete(VaDeathRegister).where(VaDeathRegister.death_id.in_(self.control_deaths))
        )
        predicates = svc._scope_predicates()
        db.session.execute(
            sa.update(VaSubmissions)
            .where(predicates["va_submissions"])
            .values(active_payload_version_id=None)
        )
        db.session.execute(
            sa.update(VaDeathRegister)
            .where(predicates["va_death_register"])
            .values(duplicate_of_death_id=None)
        )
        for name in svc.DELETE_TABLES:
            db.session.execute(sa.delete(db.metadata.tables[name]).where(predicates[name]))
        tables = db.metadata.tables
        ids = sa.select(VaUsers.user_id).where(VaUsers.email.in_([x[1] for x in svc.DEMO_ACCOUNTS]))
        units = sa.select(MasOrgUnit.org_unit_id).where(MasOrgUnit.project_id == "DEMO01")
        db.session.execute(sa.delete(VaUserAccessGrants).where(VaUserAccessGrants.user_id.in_(ids)))
        for name in ("mas_org_unit_worker", "map_org_unit_coding_gate", "map_org_unit_va_presets"):
            table = tables.get(name)
            if table is not None:
                db.session.execute(sa.delete(table).where(table.c.org_unit_id.in_(units)))
        for name in ("mas_org_unit", "map_org_level_cadre", "mas_cadre", "mas_org_level"):
            table = tables[name]
            if "project_id" in table.c:
                predicate = table.c.project_id == "DEMO01"
            else:
                levels = tables["mas_org_level"]
                predicate = table.c.org_level_id.in_(
                    sa.select(levels.c.org_level_id).where(levels.c.project_id == "DEMO01")
                )
            db.session.execute(sa.delete(table).where(predicate))
        site_ids = list(
            db.session.scalars(sa.select(VaForms.site_id).where(VaForms.project_id == "DEMO01"))
        )
        for name in (
            "va_demo_reset_runs",
            "va_forms",
            "va_project_sites",
            "va_sites",
            "va_project_master",
            "va_research_projects",
        ):
            table = tables[name]
            db.session.execute(sa.delete(table).where(table.c.project_id == "DEMO01"))
        db.session.execute(
            sa.delete(tables["va_site_master"]).where(
                tables["va_site_master"].c.site_id.in_(site_ids)
            )
        )
        db.session.execute(sa.delete(VaUsers).where(VaUsers.user_id.in_(ids)))
        db.session.execute(sa.delete(VaDbBackup).where(VaDbBackup.backup_id.in_(self.backups)))
        db.session.commit()
        super().tearDown()

    def _reset(self, **kwargs):
        return svc.reset_weekly_demo(datetime(2026, 10, 18, 17, 30, tzinfo=UTC), **kwargs)

    def _snapshot(self):
        return {
            "users": list(
                db.session.execute(
                    sa.select(VaUsers.user_id, VaUsers.password, VaUsers.other)
                    .where(VaUsers.email.in_([x[1] for x in svc.DEMO_ACCOUNTS]))
                    .order_by(VaUsers.email)
                )
            ),
            "grants": list(
                db.session.execute(
                    sa.select(VaUserAccessGrants.__table__)
                    .where(
                        VaUserAccessGrants.org_unit_id.in_(
                            sa.select(MasOrgUnit.org_unit_id).where(
                                MasOrgUnit.project_id == "DEMO01"
                            )
                        )
                    )
                    .order_by(VaUserAccessGrants.grant_id)
                )
            ),
            "units": list(
                db.session.execute(
                    sa.select(MasOrgUnit.__table__).where(MasOrgUnit.project_id == "DEMO01")
                )
            ),
        }

    def test_seed_has_real_stages_and_rerun_preserves_identity(self):
        before = self._snapshot()
        demo = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == svc.DEMO_ACCOUNTS[0][1]))
        self.assertEqual(demo.other["created_via"], "system")
        self.assertIsNone(demo.other["created_by_user_id"])
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaDeathRegister)
                .where(VaDeathRegister.project_id == "DEMO01")
            ),
            4,
        )
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaFinalAssessments)
                .where(VaFinalAssessments.va_sid.like("synthetic-demo-%"))
            ),
            2,
        )
        svc.seed_organization_demo()
        self.assertEqual(before, self._snapshot())
        self.assertTrue(svc.get_demo_metadata()["enabled"])

    def test_reset_restores_cases_preserves_other_projects_and_identity_is_idempotent(self):
        before = self._snapshot()
        control = db.session.scalar(
            sa.select(VaProjectMaster).where(VaProjectMaster.project_id != "DEMO01").limit(1)
        )
        self.assertIsNotNone(control)
        control_id, control_name = control.project_id, control.project_name
        row = db.session.scalar(
            sa.select(VaDeathRegister).where(VaDeathRegister.project_id == "DEMO01").limit(1)
        )
        row.remarks = "changed synthetic data"
        db.session.commit()
        outcome = self._reset()
        self.assertEqual(outcome["status"], "success", outcome)
        db.session.expire_all()
        self.assertEqual(before, self._snapshot())
        self.assertEqual(db.session.get(VaProjectMaster, control_id).project_name, control_name)
        self.assertFalse(
            db.session.scalar(
                sa.select(VaDeathRegister.death_id)
                .where(
                    VaDeathRegister.project_id == "DEMO01",
                    VaDeathRegister.remarks == "changed synthetic data",
                )
                .limit(1)
            )
        )
        again = self._reset()
        self.assertEqual(again["status"], "already_reset", again)
        self.assertEqual(len(self.backups), 1)
        audit = db.session.scalar(
            sa.select(VaDemoResetRun).where(VaDemoResetRun.project_id == "DEMO01")
        )
        self.assertEqual(audit.backup_sha256, "a" * 64)

    def test_backup_failure_and_reseed_failure_leave_operational_data(self):
        row = db.session.scalar(
            sa.select(VaDeathRegister).where(VaDeathRegister.project_id == "DEMO01").limit(1)
        )
        row.remarks = "preserved synthetic change"
        db.session.commit()
        failed = BackupOutcome(str(uuid.uuid4()), "failed", "local", None, 0, None, "dump_empty")
        with mock.patch.object(svc, "create_db_backup", return_value=failed):
            self.assertEqual(self._reset()["error_code"], "backup_failed")
        with mock.patch.object(svc, "_seed_cases", side_effect=RuntimeError("test failure")):
            self.assertEqual(self._reset()["error_code"], "reset_failed")
        db.session.expire_all()
        self.assertEqual(
            db.session.get(VaDeathRegister, row.death_id).remarks, "preserved synthetic change"
        )

    def test_exact_opt_in_and_short_retention_are_required(self):
        with mock.patch.dict(self.app.config, DIGITVA_WEEKLY_DEMO_PROJECT_ID="TST001"):
            self.assertEqual(self._reset()["error_code"], "target_not_configured")
        project = db.session.get(VaProjectMaster, "DEMO01")
        project.synthetic_demo_reset_enabled = False
        db.session.commit()
        self.assertEqual(self._reset()["error_code"], "target_not_opted_in")
        self.assertEqual(len(self.backups), 0)

    def test_unknown_dependency_and_busy_lock_refuse_before_backup(self):
        with mock.patch.object(
            svc, "_check_dependencies", side_effect=svc.SyntheticDemoError("unknown_dependency")
        ):
            self.assertEqual(self._reset()["error_code"], "unknown_dependency")
        with db.engine.connect() as connection:
            connection.execute(sa.text("SELECT pg_advisory_lock(184721, 1001)"))
            try:
                self.assertEqual(self._reset()["status"], "busy")
            finally:
                connection.execute(sa.text("SELECT pg_advisory_unlock(184721, 1001)"))
        self.assertEqual(len(self.backups), 0)

    def test_existing_and_new_demo_writes_are_excluded_during_backup(self):
        backup = self._backup

        def guarded_backup(**kwargs):
            with db.engine.connect() as writer:
                writer.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
                with self.assertRaises(DBAPIError) as update_error:
                    writer.execute(
                        sa.update(VaDeathRegister)
                        .where(VaDeathRegister.project_id == "DEMO01")
                        .values(remarks="concurrent write")
                    )
                self.assertEqual(
                    getattr(
                        update_error.exception.orig,
                        "sqlstate",
                        getattr(update_error.exception.orig, "pgcode", None),
                    ),
                    "55P03",
                )
                writer.rollback()
                writer.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
                row = db.session.scalar(
                    sa.select(VaDeathRegister)
                    .where(VaDeathRegister.project_id == "DEMO01")
                    .limit(1)
                )
                with self.assertRaises(DBAPIError) as insert_error:
                    writer.execute(
                        sa.insert(VaDeathRegister).values(
                            project_id="DEMO01",
                            site_id=row.site_id,
                            org_unit_id=row.org_unit_id,
                            death_number=99,
                            unique_id="DEMO-099",
                            registered_by=row.registered_by,
                            deceased_name="Synthetic concurrency control",
                            deceased_sex="female",
                            date_of_death=row.date_of_death,
                        )
                    )
                self.assertEqual(
                    getattr(
                        insert_error.exception.orig,
                        "sqlstate",
                        getattr(insert_error.exception.orig, "pgcode", None),
                    ),
                    "55P03",
                )
                writer.rollback()
            return backup(**kwargs)

        with mock.patch.object(svc, "create_db_backup", side_effect=guarded_backup):
            self.assertEqual(self._reset()["status"], "success")

    def test_cross_project_fk_is_refused_without_touching_either_project(self):
        demo = db.session.scalar(
            sa.select(VaDeathRegister)
            .where(VaDeathRegister.project_id == "DEMO01", VaDeathRegister.va_sid.is_not(None))
            .limit(1)
        )
        self.assertIsNotNone(demo)
        control = VaDeathRegister(
            project_id=self.BASE_PROJECT_ID,
            site_id=self.BASE_SITE_ID,
            death_number=999,
            unique_id="SYNTHETIC-CROSS-CONTROL",
            deceased_name="Synthetic control",
            deceased_sex="female",
            date_of_death=demo.date_of_death,
            registered_by=demo.registered_by,
            va_sid=demo.va_sid,
        )
        db.session.add(control)
        db.session.commit()
        self.control_deaths.append(control.death_id)
        outcome = self._reset()
        self.assertEqual(outcome["error_code"], "cross_project_dependency", outcome)
        self.assertEqual(len(self.backups), 0)
        self.assertIsNotNone(db.session.get(VaDeathRegister, control.death_id))
        self.assertIsNotNone(db.session.get(VaSubmissions, demo.va_sid))

    def test_dry_run_counts_without_backup_or_audit(self):
        outcome = self._reset(dry_run=True)
        self.assertEqual(outcome["status"], "dry_run", outcome)
        self.assertEqual(outcome["counts"]["va_death_register"], 4)
        self.assertEqual(len(self.backups), 0)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaDemoResetRun)
                .where(VaDemoResetRun.project_id == "DEMO01")
            ),
            0,
        )


class ScheduledWeekTests(TestCase):
    def test_sunday_before_at_and_after_2300_india(self):
        previous = datetime(2026, 10, 11, 17, 30, tzinfo=UTC)
        boundary = datetime(2026, 10, 18, 17, 30, tzinfo=UTC)
        self.assertEqual(svc._scheduled_week(datetime(2026, 10, 18, 17, 29, tzinfo=UTC)), previous)
        self.assertEqual(svc._scheduled_week(boundary), boundary)
        self.assertEqual(svc._scheduled_week(datetime(2026, 10, 19, 0, 0, tzinfo=UTC)), boundary)
        with self.assertRaises(svc.SyntheticDemoError):
            svc._scheduled_week(datetime(2026, 10, 18, 17, 30))
