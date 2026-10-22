"""The Users page API (digitva-75wn): /api/v1/users, .../<id>/activity and
.../<id>/enrolment-code.

Policy: docs/policy/access-control-model.md ("Users page"),
organization-model.md ("Users page: contacts shown"), mobile-sign-in.md
section 6. Users and the AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2, D2) come
from the authz fixture.
"""
import base64
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthDevice, AuthDeviceSession, AuthSecurityEvent, VaDeathRegister, VaStatuses
from app.models.auth_devices import AuthDeviceEnrolmentCode
from app.services.email_service import mail
from tests.authz.fixture import SP, TA, AuthzFixtureMixin
from tests.base import BaseTestCase

URL = "/api/v1/users"
SECRET_KEYS = {"password", "totp_secret", "code_hash", "secret_hash", "access_hash", "refresh_hash",
               "year_of_birth", "sex", "permission", "other"}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


class UsersApiTests(AuthzFixtureMixin, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        interviewer = cls.users["interviewer_p1"]
        interviewer.phone = "9876500001"
        now = datetime.now(UTC)
        live = AuthDevice(project_id=TA, name="Tab 1", platform="android", secret_hash=uuid.uuid4().hex)
        gone = AuthDevice(project_id=TA, name="Tab 2", platform="android", secret_hash=uuid.uuid4().hex,
                          revoked_at=now)
        db.session.add_all([live, gone])
        db.session.flush()
        for device, seen in ((live, now - timedelta(hours=1)), (gone, now - timedelta(days=3))):
            db.session.add(AuthDeviceSession(
                device_id=device.device_id, user_id=interviewer.user_id,
                access_hash=uuid.uuid4().hex, access_expires_at=now + timedelta(hours=1),
                refresh_hash=uuid.uuid4().hex, refresh_expires_at=now + timedelta(days=30),
                last_seen_at=seen,
            ))
        # coder_p1 only ever used a now-revoked device.
        old = AuthDevice(project_id=TA, name="Tab 3", platform="android", secret_hash=uuid.uuid4().hex,
                         revoked_at=now)
        db.session.add(old)
        db.session.flush()
        db.session.add(AuthDeviceSession(
            device_id=old.device_id, user_id=cls.users["coder_p1"].user_id,
            access_hash=uuid.uuid4().hex, access_expires_at=now, refresh_hash=uuid.uuid4().hex,
            refresh_expires_at=now + timedelta(days=30), revoked_at=now,
        ))
        cls.users["reviewer_p1"].user_status = VaStatuses.deactive
        db.session.add(VaDeathRegister(
            death_id=uuid.uuid4(), project_id=TA, site_id="AZS1", org_unit_id=cls.units["P1"].org_unit_id,
            death_number=901, unique_id=f"AZTA-USR-{uuid.uuid4().hex[:6]}", deceased_name="Test Deceased",
            deceased_sex="male", date_of_death=now.date(), status="registered",
            registered_by=interviewer.user_id, created_at=now, updated_at=now,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _as(self, key):
        self._login(str(self.users[key].user_id))

    def _list(self, key, **query):
        self._as(key)
        res = self.client.get(URL, query_string=query)
        self.assertEqual(res.status_code, 200, res.get_json())
        return res.get_json()

    def _emails(self, body):
        return {u["email"] for u in body["users"]}

    def _email(self, key):
        return self.users[key].email

    # -- scoping ------------------------------------------------------------

    def test_admin_sees_every_account_including_grantless(self):
        body = self._list("admin", limit=100)
        emails = self._emails(body)
        for key in ("nobody", "coder_tb", "coder_sp", "interviewer_p1", "dm_c1"):
            self.assertIn(self._email(key), emails)

    def test_unit_data_manager_sees_only_their_subtree(self):
        emails = self._emails(self._list("dm_c1", limit=100))
        for key in ("interviewer_p1", "coder_p1", "coder_c1", "supervisor_c1", "incharge_c1", "dm_c1"):
            self.assertIn(self._email(key), emails)
        for key in ("coder_ta", "dm_ta", "coder_tb", "coder_sp", "nobody", "pi_ta", "coder_ta_s1"):
            self.assertNotIn(self._email(key), emails)

    def test_incharge_has_the_same_reach(self):
        emails = self._emails(self._list("incharge_c1", limit=100))
        self.assertIn(self._email("coder_p1"), emails)
        self.assertNotIn(self._email("coder_ta"), emails)

    def test_project_pi_sees_their_project_only(self):
        emails = self._emails(self._list("pi_ta", limit=100))
        for key in ("coder_ta", "dm_ta", "coder_p1", "coder_ta_s1", "interviewer_p1"):
            self.assertIn(self._email(key), emails)
        for key in ("coder_sp", "coder_tb", "nobody"):
            self.assertNotIn(self._email(key), emails)

    def test_pair_data_manager_sees_their_pair(self):
        emails = self._emails(self._list("dm_ta_s1", limit=100))
        self.assertIn(self._email("coder_ta_s1"), emails)
        self.assertNotIn(self._email("coder_p1"), emails)

    def test_only_in_scope_grants_are_listed(self):
        body = self._list("dm_c1", q=self._email("mentor"))
        [mentor] = body["users"]
        self.assertEqual([(g["role"], g["unit_name"]) for g in mentor["grants"]], [("coder", "P1")])
        admin_view = self._list("admin", q=self._email("mentor"))["users"][0]
        self.assertEqual({g["role"] for g in admin_view["grants"]}, {"coder", "collaborator_pii"})

    def test_other_roles_are_refused(self):
        for key in ("coder_p1", "interviewer_p1", "nobody", "supervisor_c1"):
            self._as(key)
            self.assertEqual(self.client.get(URL).status_code, 403, key)

    def test_signed_out_is_401(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    # -- contents -----------------------------------------------------------

    def test_contacts_status_and_enrolment_present_and_no_secrets(self):
        body = self._list("dm_c1", q="9876500001")
        [row] = body["users"]
        self.assertEqual(row["email"], self._email("interviewer_p1"))
        self.assertEqual(row["phone"], "9876500001")
        self.assertTrue(row["active"])
        self.assertEqual(row["enrolment"]["status"], "enrolled")
        self.assertEqual(row["enrolment"]["devices"], 1)
        self.assertEqual(row["enrolment"]["revoked_devices"], 1)
        self.assertIsNotNone(row["enrolment"]["last_seen_at"])
        self.assertEqual(set(row), {"user_id", "name", "email", "phone", "active", "last_signed_in_at",
                                    "grants", "enrolment"})
        self.assertFalse(SECRET_KEYS & set(_walk_keys(body)))

    def test_options_name_the_viewers_projects_and_reachable_units(self):
        body = self._list("dm_c1", project=TA)
        self.assertEqual([p["project_id"] for p in body["options"]["projects"]], [TA])
        self.assertEqual({u["unit_name"] for u in body["options"]["units"]}, {"C1", "P1", "SC1", "P2"})
        self.assertNotIn("options", self._list("dm_c1", offset=1))

    # -- filters ------------------------------------------------------------

    def test_filters(self):
        def emails(**q):
            return self._emails(self._list("admin", limit=100, **q))

        by_unit = emails(project=TA, unit=str(self.units["P1"].org_unit_id))
        self.assertIn(self._email("coder_p1"), by_unit)
        self.assertNotIn(self._email("coder_c1"), by_unit)  # C1 is above P1
        self.assertIn(self._email("coder_c1"), emails(unit=str(self.units["C1"].org_unit_id)))
        by_role = emails(role="interviewer")
        self.assertIn(self._email("interviewer_p1"), by_role)
        self.assertNotIn(self._email("coder_p1"), by_role)
        self.assertIn(self._email("coder_sp"), emails(project=SP))
        self.assertNotIn(self._email("coder_sp"), emails(project=TA))
        inactive = emails(status="inactive")
        self.assertIn(self._email("reviewer_p1"), inactive)
        self.assertNotIn(self._email("reviewer_p1"), emails(status="active"))
        self.assertEqual(emails(enrolment="enrolled"), {self._email("interviewer_p1")})
        self.assertIn(self._email("coder_p1"), emails(enrolment="revoked"))
        self.assertNotIn(self._email("interviewer_p1"), emails(enrolment="none"))
        self.assertIn(self._email("coder_tb"), emails(enrolment="none"))
        self.assertEqual(emails(q="authz.coder_p1@"), {self._email("coder_p1")})
        self.assertEqual(emails(q="%"), set())  # a wildcard is a literal

    def test_unit_and_role_filters_inside_a_data_managers_scope(self):
        p1 = str(self.units["P1"].org_unit_id)
        by_unit = self._emails(self._list("dm_c1", limit=100, unit=p1))
        self.assertIn(self._email("coder_p1"), by_unit)
        self.assertNotIn(self._email("coder_c1"), by_unit)
        by_role = self._emails(self._list("dm_c1", limit=100, role="coder"))
        self.assertIn(self._email("coder_c1"), by_role)
        self.assertNotIn(self._email("interviewer_p1"), by_role)
        self.assertNotIn(self._email("coder_ta"), by_role)
        # A unit outside the subtree narrows to nothing rather than widening.
        self.assertEqual(self._list("dm_c1", unit=str(self.units["D2"].org_unit_id))["users"], [])

    def test_bad_filters_are_400(self):
        self._as("admin")
        for query in ({"role": "boss"}, {"status": "x"}, {"enrolment": "x"}, {"unit": "nope"},
                      {"limit": "0"}, {"limit": "101"}, {"offset": "-1"}, {"q": "x" * 65}):
            self.assertEqual(self.client.get(URL, query_string=query).status_code, 400, query)

    def test_paging(self):
        first = self._list("pi_ta", limit=2)
        second = self._list("pi_ta", limit=2, offset=2)
        self.assertEqual(len(first["users"]), 2)
        self.assertGreater(first["total"], 4)
        self.assertEqual(first["total"], second["total"])
        self.assertFalse(self._emails(first) & self._emails(second))

    # -- activity -----------------------------------------------------------

    def test_activity_counts_for_a_visible_user(self):
        self._as("dm_c1")
        res = self.client.get(f"{URL}/{self.users['interviewer_p1'].user_id}/activity")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["totals"]["deaths_reported"], 1)
        self.assertEqual(body["by_project"][TA]["deaths_reported"], 1)
        self.assertIsNotNone(body["last_device_seen_at"])
        self.assertEqual(body["last_active_at"], body["last_device_seen_at"])

    def test_activity_outside_scope_or_unknown_is_404(self):
        self._as("dm_c1")
        for target in (self.users["coder_tb"].user_id, uuid.uuid4(), "not-a-uuid"):
            self.assertEqual(self.client.get(f"{URL}/{target}/activity").status_code, 404, target)

    def test_activity_is_limited_to_the_viewers_projects(self):
        self._as("pi_sp")
        res = self.client.get(f"{URL}/{self.users['mixed'].user_id}/activity")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(res.get_json()["by_project"]), {SP})

    # -- enrolment code -----------------------------------------------------

    def _issue(self, key, target, **body):
        self._as(key)
        return self.client.post(f"{URL}/{self.users[target].user_id}/enrolment-code",
                                json={"project_id": TA, **body}, headers=self._csrf_headers())

    def _events(self, target):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_enrolment_code_created",
            AuthSecurityEvent.user_id == self.users[target].user_id,
        )).all()

    def test_data_manager_in_scope_issues_a_code_once_and_it_is_audited(self):
        res = self._issue("dm_c1", "interviewer_p1")
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual(res.headers["Cache-Control"], "no-store")
        body = res.get_json()
        self.assertTrue(base64.b64decode(body["qr_png"]).startswith(b"\x89PNG"))
        self.assertIn(body["code"], body["qr_payload"])
        self.assertEqual(body["max_uses"], 1)
        row = db.session.scalars(sa.select(AuthDeviceEnrolmentCode).order_by(
            AuthDeviceEnrolmentCode.created_at.desc())).first()
        self.assertNotEqual(row.code_hash, body["code"])
        self.assertAlmostEqual((row.expires_at - row.created_at).total_seconds() / 60, 60, delta=1)
        [event] = self._events("interviewer_p1")
        self.assertEqual(event.actor_user_id, self.users["dm_c1"].user_id)

    def test_admin_and_pi_may_issue_and_coders_count(self):
        self.assertEqual(self._issue("admin", "interviewer_p1").status_code, 201)
        self.assertEqual(self._issue("pi_ta", "coder_ta", expires_in_minutes=30, max_uses=1).status_code, 201)
        self.assertEqual(self._issue("admin", "interviewer_p1", expires_in_minutes=120, max_uses=3).status_code, 201)

    def test_non_admin_codes_are_single_use_within_an_hour(self):
        # Present first: the PI may issue for this user at all.
        self.assertEqual(self._issue("pi_ta", "coder_ta").status_code, 201)
        self.assertEqual(self._issue("pi_ta", "coder_ta", max_uses=2).get_json()["code"], "code_too_wide")
        self.assertEqual(self._issue("pi_ta", "coder_ta", expires_in_minutes=61).get_json()["code"], "code_too_wide")
        self.assertEqual(self._issue("dm_c1", "interviewer_p1", max_uses=5).get_json()["code"], "code_too_wide")

    def test_issue_refusals(self):
        # Outside the DM's subtree: not visible at all.
        self.assertEqual(self._issue("dm_c1", "coder_ta").status_code, 404)
        # Visible, but no device role (a supervisor) there.
        self.assertEqual(self._issue("dm_c1", "supervisor_c1").get_json()["code"], "no_device_role")
        # Inactive account.
        self.assertEqual(self._issue("pi_ta", "reviewer_p1").get_json()["code"], "user_inactive")
        # A project the device role is not in.
        self._as("admin")
        res = self.client.post(f"{URL}/{self.users['interviewer_p1'].user_id}/enrolment-code",
                               json={"project_id": SP}, headers=self._csrf_headers())
        self.assertEqual(res.get_json()["code"], "no_device_role")
        self.assertEqual(self._issue("admin", "interviewer_p1", delivery="sms").status_code, 400)
        self.assertEqual(self._issue("admin", "interviewer_p1", max_uses=0).status_code, 400)
        self.assertEqual(self._events("coder_ta"), [])
        # Not a viewer role at all.
        self.assertEqual(self._issue("coder_p1", "interviewer_p1").status_code, 403)

    def test_email_delivery_sends_the_enrolment_email(self):
        with patch.dict(self.app.config, {"MAIL_SERVER": "smtp.test.invalid", "MAIL_SUPPRESS_SEND": True}), \
                mail.record_messages() as outbox:
            res = self._issue("dm_c1", "interviewer_p1", delivery="email")
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual(res.get_json(), {"emailed": True})
        self.assertEqual([m.recipients for m in outbox], [[self._email("interviewer_p1")]])
        self.assertEqual(len(self._events("interviewer_p1")), 1)

    def test_issue_needs_csrf(self):
        self._as("admin")
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            res = self.client.post(f"{URL}/{self.users['interviewer_p1'].user_id}/enrolment-code",
                                   json={"project_id": TA})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._events("interviewer_p1"), [])
