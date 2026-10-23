"""Users list filters and the per-user Status payload (digitva-9npt).

Fixture users and the AZTA01 tree come from the authz fixture; this file sets
the account facts the filters read.
"""
import uuid
from zoneinfo import ZoneInfo
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthSecurityEvent, AuthWebauthnCredential
from app.models.auth_devices import AuthDeviceEnrolmentCode
from app.services import device_auth_service as devices
from tests.authz.fixture import TA, AuthzFixtureMixin
from tests.base import BaseTestCase
from tests.routes.test_users_api import SECRET_KEYS, URL, _walk_keys


class UsersFilterStatusTests(AuthzFixtureMixin, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        u = cls.users
        u["coder_p1"].email_verified = True
        u["coder_p1"].pw_reset_t_and_c = True
        u["coder_p1"].user_created_at = (now - timedelta(days=10)).replace(tzinfo=None)
        u["interviewer_p1"].email_verified = False
        u["interviewer_p1"].pw_reset_t_and_c = False
        u["interviewer_p1"].mobile_verified_at = None
        u["interviewer_p1"].user_created_at = now.replace(tzinfo=None)
        db.session.add(AuthWebauthnCredential(
            user_id=u["coder_p1"].user_id, credential_id=uuid.uuid4().bytes, public_key=b"k",
            name="Key", last_used_at=now,
        ))
        db.session.add_all([
            AuthSecurityEvent(user_id=u["coder_p1"].user_id, event_type="email_verified"),
            AuthSecurityEvent(user_id=u["coder_p1"].user_id, event_type="terms_accepted"),
        ])
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _get(self, key, path="", status=200, **query):
        self._login(str(self.users[key].user_id))
        res = self.client.get(URL + path, query_string=query)
        self.assertEqual(res.status_code, status, res.get_json())
        return res.get_json()

    def _emails(self, key, **query):
        return {x["email"] for x in self._get(key, limit=100, **query)["users"]}

    def _e(self, key):
        return self.users[key].email

    def test_email_verified_yes_and_no(self):
        yes = self._emails("admin", email_verified="yes")
        no = self._emails("admin", email_verified="no")
        self.assertIn(self._e("coder_p1"), yes)
        self.assertNotIn(self._e("coder_p1"), no)
        self.assertIn(self._e("interviewer_p1"), no)
        self.assertNotIn(self._e("interviewer_p1"), yes)

    def test_password_set_yes_and_no(self):
        yes = self._emails("admin", password_set="yes")
        no = self._emails("admin", password_set="no")
        self.assertIn(self._e("coder_p1"), yes)
        self.assertNotIn(self._e("coder_p1"), no)
        self.assertIn(self._e("interviewer_p1"), no)

    def test_passkey_yes_and_no(self):
        yes = self._emails("admin", passkey="yes")
        no = self._emails("admin", passkey="no")
        self.assertIn(self._e("coder_p1"), yes)
        self.assertNotIn(self._e("coder_p1"), no)
        self.assertIn(self._e("interviewer_p1"), no)
        self.assertNotIn(self._e("interviewer_p1"), yes)

    def test_created_today_and_range(self):
        today = self._emails("admin", created="today")
        self.assertIn(self._e("interviewer_p1"), today)
        self.assertNotIn(self._e("coder_p1"), today)
        d = (datetime.now(UTC) - timedelta(days=10)).astimezone(ZoneInfo(self.users["admin"].timezone)).date()
        ranged = self._emails("admin", created_from=d.isoformat(), created_to=d.isoformat())
        self.assertIn(self._e("coder_p1"), ranged)
        self.assertNotIn(self._e("interviewer_p1"), ranged)
        yesterday = self._emails("admin", created="yesterday")
        self.assertNotIn(self._e("interviewer_p1"), yesterday)

    def test_combined_filters_count(self):
        body = self._get("admin", email_verified="yes", passkey="yes", password_set="yes", limit=100)
        emails = {x["email"] for x in body["users"]}
        self.assertIn(self._e("coder_p1"), emails)
        self.assertEqual(body["total"], len(body["users"]))
        self.assertNotIn(self._e("interviewer_p1"), emails)

    def test_scope_not_widened(self):
        # dm_c1 does not reach coder_ta; no filter value may change that.
        for q in ({"email_verified": "yes"}, {"email_verified": "no"}, {"passkey": "no"}, {"created": "today"}):
            self.assertNotIn(self._e("coder_ta"), self._emails("dm_c1", **q))
        self.assertIn(self._e("coder_p1"), self._emails("dm_c1", email_verified="yes"))

    def test_bad_values_refused(self):
        for q in ({"email_verified": "maybe"}, {"created": "tomorrow"}, {"created_from": "x"},
                  {"created_from": "2026-02-02", "created_to": "2026-01-01"}):
            self._get("admin", status=400, **q)

    def test_status_payload_and_no_secrets(self):
        u = self.users["coder_p1"]
        _row, code = devices.create_enrolment_code(TA, actor=self.users["admin"], subject_user_id=u.user_id)
        db.session.commit()
        body = self._get("admin", f"/{u.user_id}/status")
        self.assertTrue(body["active"])
        self.assertTrue(body["email_verified"])
        self.assertIsNotNone(body["email_verified_at"])
        self.assertTrue(body["terms_accepted"])
        self.assertIsNotNone(body["terms_accepted_at"])
        self.assertTrue(body["password_set"])
        self.assertEqual(body["passkeys"]["count"], 1)
        self.assertIsNotNone(body["passkeys"]["last_used_at"])
        self.assertEqual(body["enrolment_codes"][0]["status"], "valid")
        self.assertEqual(body["mobile"]["status"], "none")
        self.assertEqual(body["training"], [])
        self.assertTrue(SECRET_KEYS.isdisjoint(set(_walk_keys(body))))
        self.assertNotIn(code, str(body))

    def test_status_scope_and_missing(self):
        self._get("dm_c1", f"/{self.users['coder_ta'].user_id}/status", status=404)
        self._get("admin", f"/{uuid.uuid4()}/status", status=404)
        self._get("admin", "/not-a-uuid/status", status=404)
        self._get("dm_c1", f"/{self.users['coder_p1'].user_id}/status")

    def test_status_query_count_is_bounded(self):
        uid = self.users["coder_p1"].user_id
        for _ in range(4):
            devices.create_enrolment_code(TA, actor=self.users["admin"], subject_user_id=uid)
        db.session.commit()
        self._login(str(self.users["admin"].user_id))
        statements = []

        def count(conn, cursor, statement, *a):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", count)
        try:
            res = self.client.get(f"{URL}/{uid}/status")
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", count)
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(len(statements), 20, len(statements))
        self.assertGreaterEqual(len(res.get_json()["enrolment_codes"]), 4)
