"""Delete my account (digitva-et16). Policy:
docs/policy/public-privacy-and-data-requests.md section 8 and
docs/policy/public-demo.md section 9a.

A public-demo account deletes itself at once after its password is checked
(``POST /api/v1/me/account/delete``); every other account files a request an
admin reviews (``POST /api/v1/me/deletion-request``, admin
``/admin/api/deletion-requests``).
"""
import os
import uuid
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthAccountDeletionRequest,
    AuthSecurityEvent,
    VaSubmissions,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import account_deletion_service
from app.services import public_demo_purge_service as purge
from app.services import public_demo_service as demo
from tests.routes import test_device_api as device_tests
from tests.test_public_demo import PASSWORD, PROJECT
from tests.test_public_demo_purge import PurgeBase, make

DELETE_URL = "/api/v1/me/account/delete"
REQUEST_URL = "/api/v1/me/deletion-request"


class SelfDeleteTests(PurgeBase):
    def setUp(self):
        super().setUp()
        self.alice = self._account("demo.self")
        self.files = self._seed_small(self.alice, "sd-case")
        # Recently active and the purge switched off: neither may stop a self-delete.
        patch = mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=False)
        patch.start()
        self.addCleanup(patch.stop)

    def _delete(self, password=PASSWORD, headers=None):
        self._login(str(self.alice.user_id))
        return self.client.post(DELETE_URL, json={"password": password},
                                headers=self._csrf_headers() if headers is None else headers)

    def _untouched(self):
        self.assertIsNotNone(self._user("demo.self"))
        self.assertIsNotNone(db.session.get(VaSubmissions, "sd-case"))
        self.assertTrue(all(os.path.exists(path) for path in self.files))

    def _events(self):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == purge.SELF_DELETE_EVENT)).all()

    def test_deletes_the_account_and_its_rows_and_audits_without_the_username(self):
        response = self._delete()

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {"deleted": True})
        db.session.expire_all()
        self.assertIsNone(self._user("demo.self"))
        self.assertIsNone(db.session.get(VaSubmissions, "sd-case"))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.va_sid == "sd-case")), 0)
        self.assertFalse(any(os.path.exists(path) for path in self.files))
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].user_id)
        self.assertEqual(events[0].detail["rows"]["va_users"], 1)
        self.assertNotIn("demo.self", str(events[0].detail))
        # The browser is signed out.
        self.assertEqual(self.client.get("/api/v1/me/access").status_code, 401)

    def test_earlier_security_events_are_kept_without_the_user_reference(self):
        db.session.add(AuthSecurityEvent(user_id=self.alice.user_id, event_type="web_sign_in", detail={}))
        db.session.commit()
        self.assertEqual(self._delete().status_code, 200)
        db.session.expire_all()
        kept = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "web_sign_in", AuthSecurityEvent.user_id.is_(None))).all()
        self.assertEqual(len(kept), 1)

    def test_a_wrong_or_missing_password_deletes_nothing(self):
        for password in ("not-the-password", "", None):
            with self.subTest(password=password):
                response = self._delete(password=password)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["code"], "wrong_password")
        self._untouched()
        self.assertEqual(self._events(), [])

    def test_a_request_without_the_csrf_header_deletes_nothing(self):
        response = self._delete(headers={})
        self.assertEqual(response.status_code, 400)
        self._untouched()

    def test_a_non_demo_account_is_refused_and_keeps_its_account(self):
        self._login(self.base_coder_id)
        response = self.client.post(DELETE_URL, json={"password": "anything"}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "not_demo_account")
        self.assertIsNotNone(db.session.get(VaUsers, self.base_coder_user.user_id))

    def test_a_guard_refusal_names_its_reason_and_deletes_nothing(self):
        bob = self._account("demo.selfb")
        db.session.add(make(VaWebIntakeDraft, project_id=PROJECT, site_id=self.site_id, form_id=self.form_id,
                            user_id=bob.user_id, va_sid="sd-case", status="submitted"))
        db.session.commit()

        response = self._delete()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "deletion_refused")
        self.assertEqual(response.get_json()["reason"], "shared_case")
        self._untouched()
        self.assertEqual(self._events(), [])

    def test_the_main_database_guard_refuses(self):
        with mock.patch.object(demo, "foreign_projects_exist", return_value=True), \
                self.assertLogs("app.services.public_demo_service", "ERROR"):
            response = self._delete()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "main_database")
        self._untouched()

    def test_a_kept_account_can_delete_itself(self):
        self.alice.public_demo_keep = True
        db.session.commit()
        self.assertEqual(self._delete().status_code, 200)
        db.session.expire_all()
        self.assertIsNone(self._user("demo.self"))

    def test_the_password_check_is_rate_limited_per_account(self):
        statuses = [self._delete(password="wrong").status_code for _ in range(6)]
        self.assertEqual(statuses[:5], [400] * 5)
        self.assertEqual(statuses[5], 429)
        self._untouched()

    def test_a_phone_deletes_with_its_bearer_token(self):
        client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        enrolled = client.post("/api/v1/auth/demo-enroll", json={
            "username": "demo.self", "password": PASSWORD, "device_name": "Pixel", "platform": "android"})
        self.assertEqual(enrolled.status_code, 201, enrolled.get_json())
        device = enrolled.get_json()
        limiter.reset()
        session = client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": "demo.self", "password": PASSWORD})
        self.assertEqual(session.status_code, 201, session.get_json())
        bearer = {"Authorization": f"Bearer {session.get_json()['access_token']}"}

        wrong = client.post(DELETE_URL, json={"password": "wrong"}, headers=bearer)
        self.assertEqual(wrong.status_code, 400)
        self.assertIsNotNone(self._user("demo.self"))

        response = client.post(DELETE_URL, json={"password": PASSWORD}, headers=bearer)

        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.expire_all()
        self.assertIsNone(self._user("demo.self"))
        self.assertEqual(client.get("/api/v1/me/access", headers=bearer).status_code, 401)

    def _bearer(self, username):
        """A demo-enrolled phone signed in as *username*: its bearer header."""
        client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        enrolled = client.post("/api/v1/auth/demo-enroll", json={
            "username": username, "password": PASSWORD, "device_name": "Pixel", "platform": "android"})
        self.assertEqual(enrolled.status_code, 201, enrolled.get_json())
        device = enrolled.get_json()
        session = client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": username, "password": PASSWORD})
        self.assertEqual(session.status_code, 201, session.get_json())
        limiter.reset()
        return client, {"Authorization": f"Bearer {session.get_json()['access_token']}"}

    def test_the_bearer_password_check_is_limited_per_account_not_shared(self):
        self._account("demo.selfc")
        alice_client, alice = self._bearer("demo.self")
        bob_client, bob = self._bearer("demo.selfc")
        statuses = [alice_client.post(DELETE_URL, json={"password": "wrong"}, headers=alice).status_code
                    for _ in range(6)]
        self.assertEqual(statuses, [400] * 5 + [429])
        # Another account's bucket is its own.
        self.assertEqual(bob_client.post(DELETE_URL, json={"password": "wrong"}, headers=bob).status_code, 400)
        self._untouched()

    def test_a_demo_account_cannot_file_a_staff_request(self):
        self._login(str(self.alice.user_id))
        response = self.client.post(REQUEST_URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "demo_account")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthAccountDeletionRequest)), 0)


class DeletionRequestTests(PurgeBase):
    def _requests(self, user_id=None):
        return db.session.scalars(sa.select(AuthAccountDeletionRequest).where(
            AuthAccountDeletionRequest.user_id == (user_id or self.base_coder_user.user_id))).all()

    def _ask(self):
        self._login(self.base_coder_id)
        return self.client.post(REQUEST_URL, headers=self._csrf_headers())

    def test_profile_shows_staff_request_and_demo_self_delete_controls(self):
        self._login(self.base_coder_id)
        staff_profile = self.client.get("/profile/")
        self.assertEqual(staff_profile.status_code, 200)
        self.assertIn(b'id="request-deletion-btn"', staff_profile.data)
        self.assertNotIn(b'id="delete-account-password"', staff_profile.data)

        self._login(str(self._account("demo.profile").user_id))
        demo_profile = self.client.get("/profile/")
        self.assertEqual(demo_profile.status_code, 200)
        self.assertIn(b'id="delete-account-password"', demo_profile.data)
        self.assertNotIn(b'id="request-deletion-btn"', demo_profile.data)

    def test_files_once_and_a_repeat_while_pending_changes_nothing(self):
        with mock.patch.object(account_deletion_service, "notify") as notify:
            first = self._ask()
            second = self._ask()

        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(first.get_json(), {"status": "pending", "created": True})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json(), {"status": "pending", "created": False})
        rows = self._requests()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].requested_via, "web")
        self.assertEqual(notify.call_count, 1)
        events = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == account_deletion_service.REQUEST_EVENT,
            AuthSecurityEvent.user_id == self.base_coder_user.user_id)).all()
        self.assertEqual([e.detail for e in events], [{"via": "web"}])

    def test_a_mail_outage_still_files_the_request_and_answers_201(self):
        with mock.patch.object(account_deletion_service, "notify", side_effect=RuntimeError("broker down")):
            response = self._ask()

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(len(self._requests()), 1)

    def test_a_request_without_the_csrf_header_is_refused(self):
        self._login(self.base_coder_id)
        response = self.client.post(REQUEST_URL)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._requests(), [])

    def test_signed_out_is_refused(self):
        response = self.client.post(REQUEST_URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 401)

    def test_notifies_the_contact_mailbox_when_mail_goes_out(self):
        with mock.patch.dict(self.app.config, PUBLIC_CONTACT_EMAIL="team@example.org"), \
                mock.patch("app.services.email_service.can_send_mail", return_value=True), \
                mock.patch("app.services.email_service.send_account_deletion_request_notice") as send:
            self._ask()
            self._ask()
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["to"], "team@example.org")
        with mock.patch.dict(self.app.config, PUBLIC_CONTACT_EMAIL=""), \
                mock.patch("app.services.email_service.send_account_deletion_request_notice") as unset:
            account_deletion_service.notify(self.base_coder_user)
        unset.assert_not_called()

    def test_an_admin_lists_pending_requests_and_marks_one_handled(self):
        with mock.patch.object(account_deletion_service, "notify"):
            self._ask()
        request_id = str(self._requests()[0].id)

        self._login(self.base_admin_id)
        listed = self.client.get("/admin/api/deletion-requests")
        self.assertEqual(listed.status_code, 200, listed.get_json())
        body = listed.get_json()
        self.assertEqual(body["total"], 1)
        self.assertEqual([r["id"] for r in body["requests"]], [request_id])
        self.assertEqual(body["requests"][0]["user_id"], self.base_coder_id)

        handled = self.client.post(f"/admin/api/deletion-requests/{request_id}/handled",
                                   headers=self._csrf_headers())
        self.assertEqual(handled.status_code, 200, handled.get_json())
        db.session.expire_all()
        row = db.session.get(AuthAccountDeletionRequest, uuid.UUID(request_id))
        self.assertIsNotNone(row.handled_at)
        self.assertEqual(row.handled_by, self.base_admin_user.user_id)
        self.assertEqual(self.client.get("/admin/api/deletion-requests").get_json()["total"], 0)
        again = self.client.post(f"/admin/api/deletion-requests/{request_id}/handled", headers=self._csrf_headers())
        self.assertEqual(again.status_code, 404)
        # Nothing was deleted: deletion stays manual.
        self.assertIsNotNone(db.session.get(VaUsers, self.base_coder_user.user_id))

        # Once handled, the account may ask again.
        with mock.patch.object(account_deletion_service, "notify"):
            self.assertEqual(self._ask().status_code, 201)
        self.assertEqual(len(self._requests()), 2)

    def test_listing_and_handling_are_admin_only(self):
        with mock.patch.object(account_deletion_service, "notify"):
            self._ask()
        request_id = self._requests()[0].id
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/admin/api/deletion-requests").status_code, 403)
        response = self.client.post(f"/admin/api/deletion-requests/{request_id}/handled",
                                    headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        db.session.expire_all()
        self.assertIsNone(db.session.get(AuthAccountDeletionRequest, request_id).handled_at)

    def test_handling_without_the_csrf_header_is_refused(self):
        with mock.patch.object(account_deletion_service, "notify"):
            self._ask()
        request_id = self._requests()[0].id
        self._login(self.base_admin_id)
        response = self.client.post(f"/admin/api/deletion-requests/{request_id}/handled")
        self.assertEqual(response.status_code, 400)
        db.session.expire_all()
        self.assertIsNone(db.session.get(AuthAccountDeletionRequest, request_id).handled_at)
