"""Kept public-demo accounts (digitva-xfxb). Policy: docs/policy/public-demo.md
sections 8 and 9: an admin may mark a demo account kept; it is never purged
or evicted but still counts toward the cap; every change is audited.
"""
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import AuthSecurityEvent, VaUsers
from app.services import public_demo_purge_service as purge
from app.services import public_demo_service as demo
from tests.test_public_demo_purge import PurgeBase


class KeptAccountPurgeTests(PurgeBase):
    def _kept(self, name, days):
        user = self._account(name)
        self._idle(user, days)
        user.public_demo_keep = True
        db.session.commit()
        return user

    def test_the_daily_purge_takes_the_unkept_account_and_leaves_the_kept_one(self):
        kept = self._kept("demo.kp1", 90)
        unkept = self._account("demo.kp2")
        self._idle(unkept, 90)
        self.assertNotIn(kept.user_id, purge.idle_user_ids(30, limit=100))
        self.assertIn(unkept.user_id, purge.idle_user_ids(30, limit=100))

        result = purge.purge_run(apply=True)

        self.assertEqual(result["accounts"], 1)
        self.assertIsNotNone(self._user("demo.kp1"))
        self.assertIsNone(self._user("demo.kp2"))

    def test_the_per_account_recheck_refuses_a_kept_account(self):
        kept = self._kept("demo.kp3", 90)
        with self.assertRaises(purge.PurgeRefused) as ctx:
            purge.delete_account(kept.user_id, 30)
        self.assertEqual(ctx.exception.reason, "not_eligible")
        self.assertIsNotNone(db.session.get(VaUsers, kept.user_id))

    def test_eviction_at_the_cap_passes_over_the_kept_account(self):
        self._kept("demo.kp4", 40)
        unkept = self._account("demo.kp5")
        self._idle(unkept, 8)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_MAX_ACCOUNTS=demo.active_account_count()):
            demo.create_account("demo.kp.new", "plain-demo-password-1")
            db.session.commit()
        self.assertIsNotNone(self._user("demo.kp4"))
        self.assertIsNone(self._user("demo.kp5"))
        self.assertIsNotNone(self._user("demo.kp.new"))

    def test_kept_accounts_count_toward_the_cap(self):
        self._kept("demo.kp6", 40)
        self._kept("demo.kp7", 40)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_MAX_ACCOUNTS=demo.active_account_count()):
            with self.assertRaises(demo.PublicDemoError) as ctx:
                demo.create_account("demo.kp.new2", "plain-demo-password-1")
        self.assertEqual(ctx.exception.code, "cap_reached")
        self.assertIsNotNone(self._user("demo.kp6"))
        self.assertIsNone(self._user("demo.kp.new2"))


class KeptAccountToggleTests(PurgeBase):
    def setUp(self):
        super().setUp()
        self.demo_user = self._account("demo.kt1")

    def _url(self, user_id=None):
        return f"/admin/api/users/{user_id or self.demo_user.user_id}/public-demo-keep"

    def _events(self):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "public_demo_keep",
            AuthSecurityEvent.user_id == self.demo_user.user_id,
        )).all()

    def _reload(self):
        db.session.expire_all()
        return db.session.get(VaUsers, self.demo_user.user_id).public_demo_keep

    def test_an_admin_marks_and_clears_kept_and_each_change_is_audited(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        response = self.client.post(self._url(), json={"keep": True}, headers=headers)

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["public_demo_keep"], True)
        self.assertTrue(self._reload())
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor_user_id, self.base_admin_user.user_id)
        self.assertEqual(events[0].detail, {"keep": True})
        self.assertNotIn("demo.kt1", str(events[0].detail))

        # Setting the same value again changes nothing and records nothing.
        self.client.post(self._url(), json={"keep": True}, headers=headers)
        self.assertEqual(len(self._events()), 1)

        response = self.client.post(self._url(), json={"keep": False}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._reload())
        self.assertEqual([e.detail for e in self._events()].count({"keep": False}), 1)

    def test_the_users_list_carries_the_mark_for_demo_accounts_only(self):
        self._login(self.base_admin_id)
        users = {u["user_id"]: u for u in self.client.get("/admin/api/users?master=1").get_json()["users"]}
        self.assertIn(str(self.demo_user.user_id), users)
        self.assertIs(users[str(self.demo_user.user_id)]["public_demo_keep"], False)
        self.assertIn(self.base_admin_id, users)
        self.assertNotIn("public_demo_keep", users[self.base_admin_id])

    def test_a_non_admin_is_refused(self):
        self._login(self.base_coder_id)
        response = self.client.post(self._url(), json={"keep": True}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self._reload())
        self.assertEqual(self._events(), [])

    def test_a_request_without_the_csrf_header_is_refused(self):
        self._login(self.base_admin_id)
        response = self.client.post(self._url(), json={"keep": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.get_json()["error"])
        self.assertFalse(self._reload())

    def test_a_non_demo_account_or_a_bad_body_is_refused(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        response = self.client.post(self._url(self.base_coder_id), json={"keep": True}, headers=headers)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(db.session.get(VaUsers, self.base_coder_user.user_id).public_demo_keep)
        response = self.client.post(self._url(), json={"keep": "yes"}, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self._reload())

    def test_the_toggle_and_the_mark_do_not_exist_with_the_demo_off(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            response = self.client.post(self._url(), json={"keep": True}, headers=headers)
            users = {u["user_id"]: u for u in self.client.get("/admin/api/users?master=1").get_json()["users"]}
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self._reload())
        self.assertEqual(self._events(), [])
        self.assertIn(str(self.demo_user.user_id), users)
        self.assertNotIn("public_demo_keep", users[str(self.demo_user.user_id)])
