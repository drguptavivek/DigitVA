"""``flask seed e2e-users create|teardown``: throwaway TST001 accounts per Maestro run."""
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.commands.seed import TEST_PROJECT_ID
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    AuthSecurityEvent,
    MasOrgUnit,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import device_auth_service as devices
from tests.base import BaseTestCase


class SeedE2eUsersTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()
        self.assertEqual(self.runner.invoke(args=["seed", "test-project"]).exit_code, 0)
        self.out = os.path.join(tempfile.mkdtemp(), "e2e-users.json")

    def _create(self):
        result = self.runner.invoke(args=["seed", "e2e-users", "create", "--out", self.out])
        self.assertEqual(result.exit_code, 0, result.output)
        with open(self.out) as fh:
            return result, json.load(fh)

    def _grants(self, email):
        return sorted(db.session.execute(
            sa.select(VaUserAccessGrants.role, MasOrgUnit.unit_code)
            .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
            .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(VaUsers.email == email, VaUserAccessGrants.grant_status == VaStatuses.active)
        ).all(), key=lambda r: (r.role.value, r.unit_code or ""))

    def test_create_writes_users_grants_and_a_private_file_without_echoing_the_password(self):
        result, creds = self._create()
        users = creds["users"]
        self.assertEqual(set(users), {"all", "interviewer", "interviewer2", "coder",
                                "coder2", "reporter", "supervisor", "reviewer", "datamgr"})
        self.assertNotIn(creds["password"], result.output)
        self.assertIn(self.out, result.output)
        self.assertEqual(os.stat(self.out).st_mode & 0o777, 0o600)
        for email in users.values():
            self.assertIn(email, result.output)
            user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
            self.assertTrue(user.check_password(creds["password"]))
        self.assertEqual(
            [(r.role.value, r.unit_code) for r in self._grants(users["all"])],
            [("coder", None), ("data_manager", None), ("death_reporter", "SC01"),
             ("interview_supervisor", "PHC01"), ("interviewer", "SC01"), ("reviewer", None)],
        )
        self.assertEqual([(r.role.value, r.unit_code) for r in self._grants(users["interviewer"])],
                         [("interviewer", "SC01")])
        self.assertEqual([(r.role.value, r.unit_code) for r in self._grants(users["coder"])],
                         [("coder", None)])
        single = {"interviewer2": ("interviewer", "SC01"), "coder2": ("coder", None),
                  "reporter": ("death_reporter", "SC01"), "supervisor": ("interview_supervisor", "PHC01"),
                  "reviewer": ("reviewer", None), "datamgr": ("data_manager", None)}
        for key, grant in single.items():
            self.assertEqual([(r.role.value, r.unit_code) for r in self._grants(users[key])], [grant], key)

        # A second run gets fresh accounts.
        _result, second = self._create()
        self.assertNotEqual(second["users"]["all"], users["all"])

    def test_teardown_revokes_devices_ends_sessions_deactivates_and_is_idempotent(self):
        _result, creds = self._create()
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == creds["users"]["all"]))
        device = AuthDevice(project_id=TEST_PROJECT_ID, name="maestro", platform="android",
                            secret_hash=devices.hash_token("s"))
        db.session.add(device)
        db.session.flush()
        now = datetime.now(UTC)
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=user.user_id,
            access_hash=devices.hash_token("a"), access_expires_at=now + devices.ACCESS_TTL,
            refresh_hash=devices.hash_token("r"), refresh_expires_at=now + timedelta(days=30),
            user_session_version=user.auth_session_version or 0,
        )
        db.session.add(session)
        db.session.commit()
        version = user.auth_session_version or 0

        first = self.runner.invoke(args=["seed", "e2e-users", "teardown", "--run", creds["run_id"]])
        self.assertEqual(first.exit_code, 0, first.output)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(AuthDevice, device.device_id).revoked_at)
        self.assertIsNotNone(db.session.get(AuthDeviceSession, session.session_id).revoked_at)
        self.assertGreater(db.session.get(VaUsers, user.user_id).auth_session_version, version)
        self.assertTrue(db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_revoked")))
        for email in creds["users"].values():
            u = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
            self.assertEqual(u.user_status, VaStatuses.deactive)
        self.assertIn("9 deactivated", first.output)
        self.assertIn("14 revoked", first.output)
        for email in creds["users"].values():
            self.assertEqual(self._grants(email), [])
        revoked = db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants)
                                    .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
                                    .where(VaUsers.email.in_(list(creds["users"].values())),
                                           VaUserAccessGrants.grant_status == VaStatuses.deactive))
        self.assertEqual(revoked, 14)

        again = self.runner.invoke(args=["seed", "e2e-users", "teardown"])
        self.assertEqual(again.exit_code, 0, again.output)
        self.assertIn("0 revoked", again.output)
        self.assertIn("0 deactivated", again.output)
        self.assertIn("grants     0 revoked", again.output)

    def test_teardown_cancels_the_runs_open_cases_and_keeps_the_rows(self):
        from app.models import VaDeathRegister

        _result, creds = self._create()
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == creds["users"]["interviewer"]))
        from app.models import VaProjectSites
        site_id = db.session.scalar(sa.select(VaProjectSites.site_id).where(VaProjectSites.project_id == TEST_PROJECT_ID).limit(1))
        self.assertIsNotNone(site_id)
        now = datetime.now(UTC)
        cases = {}
        for n, status in enumerate(("registered", "paused", "submitted")):
            case = VaDeathRegister(project_id=TEST_PROJECT_ID, site_id=site_id, death_number=900000 + n,
                                   unique_id=f"E2E-T-{creds['run_id']}-{n}", registered_by=user.user_id,
                                   status=status, created_at=now, updated_at=now, has_deceased_name=True,
                                   deceased_name="E2E Test", deceased_sex="female", date_of_death=now.date())
            db.session.add(case)
            db.session.flush()
            cases[status] = case.death_id
        db.session.commit()

        result = self.runner.invoke(args=["seed", "e2e-users", "teardown", "--run", creds["run_id"]])
        self.assertEqual(result.exit_code, 0, result.output)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaDeathRegister, cases["registered"]).status, "cancelled")
        self.assertEqual(db.session.get(VaDeathRegister, cases["paused"]).status, "cancelled")
        self.assertEqual(db.session.get(VaDeathRegister, cases["submitted"]).status, "submitted")
        self.assertIn("cases      2 of 2 open case(s) cancelled", result.output)

    def test_older_than_hours_spares_a_fresh_run(self):
        _result, creds = self._create()
        result = self.runner.invoke(args=["seed", "e2e-users", "teardown", "--older-than-hours", "1"])
        self.assertEqual(result.exit_code, 0, result.output)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == creds["users"]["coder"]))
        self.assertEqual(user.user_status, VaStatuses.active)

    def test_refuses_a_non_debug_app(self):
        self.app.testing, self.app.debug = False, False
        try:
            for cmd in ("create", "teardown"):
                refused = self.runner.invoke(args=["seed", "e2e-users", cmd, "--out", self.out]
                                             if cmd == "create" else ["seed", "e2e-users", cmd])
                self.assertNotEqual(refused.exit_code, 0)
                self.assertIn("debug or testing", refused.output)
        finally:
            self.app.testing = True
        self.assertFalse(os.path.exists(self.out))
