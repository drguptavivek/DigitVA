"""App versions screen (digitva-jrzd).

Contract: GET /admin/api/projects/<id>/app-versions, behind the roster gate
(``_guard(project_id, roster=True)``), returns a summary per (platform,
app_version) of the project's non-revoked devices and the roster people
signed in on them, with ``behind_latest`` against the hosted APK. Read-only,
no-store, no contact details or device identifiers.
Policy: docs/policy/app-versions-screen.md.
"""
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from app import db, limiter
from app.models import (
    MapProjectMember,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
import sqlalchemy as sa

from app.models.auth_devices import AuthDevice, AuthDeviceSession
from app.services import app_versions_service as svc
from tests.base import BaseTestCase

R = VaAccessRoles
P = VaAccessScopeTypes.project


@contextmanager
def count_queries():
    statements = []

    def before(conn, cursor, statement, *args):
        statements.append(statement)

    engine = db.session.get_bind()
    target = getattr(engine, "engine", engine)
    event.listen(target, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(target, "before_cursor_execute", before)


class AppVersionsScreenTests(BaseTestCase):
    A = "AVSA01"
    B = "AVSB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.A, cls.B):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Versions {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
            ))
        db.session.flush()
        cls.dm_a = cls._staff("dm.a", R.data_manager, cls.A)
        cls.dm_b = cls._staff("dm.b", R.data_manager, cls.B)
        cls.coder_a = cls._staff("coder.a", R.coder, cls.A)
        db.session.commit()

    @classmethod
    def _staff(cls, name, role, project_id):
        user = cls._make_user(f"avs.{name}@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=P, project_id=project_id,
            grant_status=VaStatuses.active,
        ))
        return user

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.app.config["DIGITVA_ANDROID_APK_DIR"] = self.dir.name

    def _host(self, name):
        with open(os.path.join(self.dir.name, name), "wb") as fh:
            fh.write(b"apk")

    def _person(self, name, project_id=None, role=R.interviewer):
        number = f"9{uuid.uuid4().int % 10**9:09d}"
        user = VaUsers(
            user_id=uuid.uuid4(), name=name, email=f"{uuid.uuid4().hex[:10]}@avs.test",
            mobile_login=number, phone=number, vacode_language=["English"], permission={},
            landing_page="coder", pw_reset_t_and_c=False, email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password("Unused123!x")
        db.session.add(user)
        db.session.flush()
        if project_id:
            db.session.add(MapProjectMember(project_id=project_id, user_id=user.user_id))
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=P, project_id=project_id,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()
        return user

    def _device(self, version, *, project_id=None, platform="android", seen_days=0, revoked=False,
                users=()):
        now = datetime.now(UTC)
        device = AuthDevice(
            project_id=project_id or self.A, name=f"Phone {uuid.uuid4().hex[:6]}", platform=platform,
            app_version=version, secret_hash=uuid.uuid4().hex, enrolled_at=now - timedelta(days=60),
            last_seen_at=None if seen_days is None else now - timedelta(days=seen_days),
            revoked_at=now if revoked else None,
        )
        db.session.add(device)
        db.session.flush()
        for user in users:
            db.session.add(AuthDeviceSession(
                device_id=device.device_id, user_id=user.user_id,
                access_hash=uuid.uuid4().hex, access_expires_at=now + timedelta(hours=1),
                refresh_hash=uuid.uuid4().hex, refresh_expires_at=now + timedelta(days=30),
                last_seen_at=device.last_seen_at,
            ))
        db.session.commit()
        return device

    def _get(self, project_id=None, query=""):
        return self.client.get(f"/admin/api/projects/{project_id or self.A}/app-versions{query}")

    def _summary(self, body):
        return {(r["platform"], r["app_version"]): r for r in body["summary"]}

    # -- who may see it -----------------------------------------------------

    def test_admin_sees_summary_and_people_for_any_project(self):
        person = self._person("Asha Admin View", self.B)
        self._device("0.3.20", project_id=self.B, users=[person])
        self._login(self.base_admin_id)
        response = self._get(self.B)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(self._summary(body)[("android", "0.3.20")]["active_devices"], 1)
        self.assertEqual([p["name"] for p in body["people"]], ["Asha Admin View"])
        self.assertEqual(body["people"][0]["roles"], ["interviewer"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_data_manager_sees_only_own_project_and_roster_people(self):
        on_roster = self._person("On Roster", self.A)
        off_roster = self._person("Off Roster")  # signed in on a project phone, not on the roster
        self._device("0.3.20", users=[on_roster, off_roster])
        self._login(str(self.dm_a.user_id))
        body = self._get().get_json()
        names = [p["name"] for p in body["people"]]
        self.assertIn("On Roster", names)
        self.assertNotIn("Off Roster", names)
        self.assertEqual(body["people_total"], 1)
        # The other project's refusal is the roster's own.
        roster = self.client.get(f"/admin/api/projects/{self.B}/users-grid")
        mine = self._get(self.B)
        self.assertEqual(roster.status_code, 403)
        self.assertEqual((mine.status_code, mine.get_json()), (roster.status_code, roster.get_json()))

    def test_data_manager_of_another_project_is_refused_like_the_roster(self):
        self._login(str(self.dm_b.user_id))
        self.assertEqual(self._get(self.B).status_code, 200)
        roster = self.client.get(f"/admin/api/projects/{self.A}/users-grid")
        mine = self._get(self.A)
        self.assertEqual(mine.status_code, 403)
        self.assertEqual(mine.get_json(), roster.get_json())

    def test_coder_is_refused(self):
        self._login(str(self.coder_a.user_id))
        self.assertEqual(self._get().status_code, 403)

    def test_unknown_project_is_404_for_admin(self):
        self._login(self.base_admin_id)
        self.assertEqual(self._get("ZZZZ99").status_code, 404)

    # -- counts ---------------------------------------------------------------

    def test_revoked_devices_are_excluded(self):
        person = self._person("Revoked Phone User", self.A)
        self._device("0.3.15", revoked=True, users=[person])
        self._device("0.3.16")
        self._login(self.base_admin_id)
        body = self._get().get_json()
        summary = self._summary(body)
        self.assertIn(("android", "0.3.16"), summary)
        self.assertNotIn(("android", "0.3.15"), summary)
        self.assertNotIn("Revoked Phone User", [p["name"] for p in body["people"]])

    def test_people_seen_in_thirty_days_are_listed_even_with_a_lapsed_session(self):
        lapsed = self._person("Lapsed Old Apk", self.A)
        stale = self._person("Not Seen Lately", self.A)
        self._device("0.3.15", seen_days=10, users=[lapsed])
        self._device("0.3.13", seen_days=40, users=[stale])
        past = datetime.now(UTC) - timedelta(days=5)
        db.session.execute(
            sa.update(AuthDeviceSession)
            .where(AuthDeviceSession.user_id.in_([lapsed.user_id, stale.user_id]))
            .values(access_expires_at=past, refresh_expires_at=past)
        )
        db.session.commit()
        self._login(self.base_admin_id)
        names = [p["name"] for p in self._get().get_json()["people"]]
        self.assertIn("Lapsed Old Apk", names)
        self.assertNotIn("Not Seen Lately", names)

    def test_seven_and_thirty_day_counts(self):
        for days in (0, 6, 8, 29, 31, None):
            self._device("0.3.22", seen_days=days)
        self._device("0.3.22", project_id=self.B)  # another project: not counted
        self._login(self.base_admin_id)
        row = self._summary(self._get().get_json())[("android", "0.3.22")]
        self.assertEqual((row["active_devices"], row["seen_7d"], row["seen_30d"]), (6, 2, 4))
        self.assertIsNotNone(row["last_seen_at"])

    def test_version_filter_limits_people(self):
        old = self._person("Old Version", self.A)
        new = self._person("New Version", self.A)
        unknown = self._person("No Version", self.A)
        self._device("0.3.15", users=[old])
        self._device("0.3.28", users=[new])
        self._device(None, users=[unknown])
        self._login(self.base_admin_id)
        self.assertEqual([p["name"] for p in self._get(query="?app_version=0.3.15").get_json()["people"]],
                         ["Old Version"])
        self.assertEqual([p["name"] for p in self._get(query="?app_version=").get_json()["people"]],
                         ["No Version"])
        self.assertEqual(self._get().get_json()["people_total"], 3)
        self.assertEqual(self._get(query="?app_version=" + "9" * 33).status_code, 400)

    # -- behind the latest release ------------------------------------------

    def test_version_filter_with_a_nul_byte_is_400_not_500(self):
        self._login(self.base_admin_id)
        self.assertEqual(self._get(query="?app_version=0.3%0015").status_code, 400)

    def test_behind_latest_for_normal_plus_and_none(self):
        latest = {"normal": (0, 3, 10), "plus": (0, 3, 12)}
        cases = [
            ("android", "0.3.9", True),       # numeric, not string, comparison
            ("android", "0.3.10", False),
            ("android", "0.3.11", False),
            ("android", "0.3.11-plus", True),  # against the Plus release
            ("android", "0.3.12-plus", False),
            ("android", None, None),
            ("android", "garbage", None),
            ("ios", "0.3.1", None),
        ]
        for platform, version, expected in cases:
            with self.subTest(version=version, platform=platform):
                self.assertIs(svc.behind_latest(platform, version, latest), expected)
        self.assertIsNone(svc.behind_latest("android", "0.3.1-plus", {"normal": (0, 3, 10), "plus": None}))

    def test_behind_latest_uses_the_hosted_apk(self):
        self._host("digitva-collect-0.3.28-arm64-v8a.apk")
        self._host("digitva-collect-plus-0.3.19-arm64-v8a.apk")
        person = self._person("Field Worker", self.A)
        self._device("0.3.27", users=[person])
        self._device("0.3.28")
        self._device("0.3.19-plus")
        self._device(None)
        self._login(self.base_admin_id)
        body = self._get().get_json()
        self.assertEqual(body["latest"], {"normal": "0.3.28", "plus": "0.3.19"})
        summary = self._summary(body)
        self.assertIs(summary[("android", "0.3.27")]["behind_latest"], True)
        self.assertIs(summary[("android", "0.3.28")]["behind_latest"], False)
        self.assertIs(summary[("android", "0.3.19-plus")]["behind_latest"], False)
        self.assertIsNone(summary[("android", None)]["behind_latest"])
        self.assertIs(body["people"][0]["behind_latest"], True)

    # -- no identifiers --------------------------------------------------------

    def test_no_contact_details_or_device_identifiers(self):
        person = self._person("Private Person", self.A)
        device = self._device("0.3.20", users=[person])
        self._login(str(self.dm_a.user_id))
        response = self._get()
        text = response.get_data(as_text=True)
        body = response.get_json()
        row = body["people"][0]
        self.assertEqual(row["name"], "Private Person")  # presence first
        self.assertEqual(set(row), {"name", "roles", "platform", "app_version", "last_seen_at",
                                    "enrolled_at", "behind_latest"})
        for secret in (person.email, person.phone, str(person.user_id), str(device.device_id),
                       device.name, device.secret_hash):
            self.assertNotIn(secret, text)

    # -- bounded -----------------------------------------------------------------

    def test_query_count_does_not_grow_with_devices(self):
        def run():
            with count_queries() as statements:
                svc.project_app_versions(self.A)
            return len(statements)

        for i in range(3):
            self._device(f"0.3.{i}", users=[self._person(f"Batch {i}", self.A)])
        small = run()
        for i in range(9):
            self._device(f"0.4.{i}", users=[self._person(f"More {i}", self.A)])
        self.assertEqual(run(), small)
        self.assertEqual(len(svc.project_app_versions(self.A)["people"]), 12)

    # -- the screen ------------------------------------------------------------

    def test_roster_page_shows_the_app_versions_tab_to_a_data_manager(self):
        self._login(str(self.dm_a.user_id))
        response = self.client.get(f"/admin/project-roster?project_id={self.A}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="setup-ptab-appver-btn"', html)
        self.assertIn("/app-versions", html)
