"""Sign-in QR (digitva-3g19): docs/policy/mobile-sign-in.md section 8.

Issue (Users page API), redeem (public, from the phone), revoke and status.
Users and the AZTA01 tree come from the authz fixture; ``has_device_access``
and ``interviewer_context`` are patched because the fixture projects have no
web-intake setup (the grant rules under test are the QR's own): the fake
reaches every project the person holds a collector grant on.
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    AuthSecurityEvent,
    AuthSignInToken,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import device_auth_service as devices
from app.services.authz import resolve_grants
from app.services.sign_in_qr_service import COLLECTOR_ROLES
from app.services import sign_in_qr_service
from app.services import email_service
from app.services.email_service import mail
from tests.authz.fixture import AuthzFixtureMixin
from tests.base import BaseTestCase

USERS = "/api/v1/users"
REDEEM = "/api/v1/auth/sign-in-qr/redeem"
DEVICE = {"device_name": "Pixel 7", "platform": "android", "app_version": "1.2.3"}
MAIL = {"MAIL_SERVER": "smtp.test.invalid", "MAIL_SUPPRESS_SEND": True}


def _fake_context(user, roles=None, *, _grants=None):
    grants = _grants or resolve_grants(user)
    return [
        {"project_id": g.project_id, "web_intake_mode": "on"}
        for g in grants.of(COLLECTOR_ROLES, virtual=False)
    ]


class SignInQrTests(AuthzFixtureMixin, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A death reporter, and a verified/unverified email split.
        cls.users["nobody"].email_verified = False
        cls.users["interviewer_p1"].email_verified = True
        db.session.add(cls._grant_row(cls.users["nobody"], VaAccessRoles.death_reporter,
                                      VaAccessScopeTypes.org_unit, "P1"))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        patcher = patch.object(devices, "has_device_access", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Only the QR service sees the fake reach; the access summary keeps the real one.
        stub = SimpleNamespace(interviewer_context=_fake_context, register_death_context=lambda *a, **k: [])
        p = patch.object(sign_in_qr_service, "web_intake_service", stub)
        p.start()
        self.addCleanup(p.stop)
        for token in db.session.scalars(sa.select(AuthSignInToken)):
            db.session.delete(token)
        db.session.commit()

    # -- helpers -----------------------------------------------------------

    def _issue(self, actor, target, delivery="show"):
        self._login(str(self.users[actor].user_id))
        return self.client.post(
            f"{USERS}/{self.users[target].user_id}/sign-in-qr", json={"delivery": delivery},
            headers=self._csrf_headers(),
        )

    def _token(self, actor="admin", target="interviewer_p1"):
        res = self._issue(actor, target)
        self.assertEqual(res.status_code, 201, res.get_json())
        return res.get_json()["code"]

    def _redeem(self, token, **extra):
        return self.client.post(REDEEM, json={"token": token, **DEVICE, **extra})

    def _events(self, event_type):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == event_type)).all()

    def _row(self, target="interviewer_p1"):
        return db.session.scalars(sa.select(AuthSignInToken).where(
            AuthSignInToken.user_id == self.users[target].user_id
        ).order_by(AuthSignInToken.issued_at.desc())).first()

    def _add_grant(self, target, role, scope, where):
        row = self._grant_row(self.users[target], role, scope, where)
        db.session.add(row)
        db.session.commit()
        return row

    # -- issue -------------------------------------------------------------

    def test_show_returns_token_once_stores_only_its_hash_and_audits(self):
        res = self._issue("admin", "interviewer_p1")
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual(res.headers["Cache-Control"], "no-store")
        body = res.get_json()
        self.assertIn(body["code"], body["qr_payload"])
        self.assertIn('"sign_in"', body["qr_payload"])
        row = self._row()
        self.assertEqual(row.token_hash, devices.hash_token(body["code"]))
        self.assertNotEqual(row.token_hash, body["code"])
        self.assertAlmostEqual((row.expires_at - row.issued_at).total_seconds(), 6 * 3600, delta=2)
        [event] = self._events("sign_in_qr_issued")
        self.assertEqual(event.actor_user_id, self.users["admin"].user_id)
        self.assertNotIn(body["code"], str(event.detail))
        # The status list never carries the token.
        self._login(str(self.users["admin"].user_id))
        listing = self.client.get(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr")
        self.assertEqual(listing.get_json()["items"][0]["status"], "pending")
        self.assertNotIn(body["code"], listing.get_data(as_text=True))

    def test_issuer_rule(self):
        # In-scope data manager and PI may; a DM outside the person's subtree,
        # a coder and an interviewer may not (404 / 403).
        self.assertEqual(self._issue("dm_c1", "interviewer_p1").status_code, 201)
        self.assertEqual(self._issue("pi_ta", "interviewer_p1").status_code, 201)
        self.assertEqual(self._issue("dm_sp", "interviewer_p1").status_code, 404)
        self.assertEqual(self._issue("coder_p1", "interviewer_p1").status_code, 403)
        self.assertEqual(self._issue("interviewer_p1", "interviewer_p1").status_code, 403)

    def test_manager_must_manage_every_grant(self):
        # A second grant the DM cannot write (another project): partial authority is refused.
        self._add_grant("interviewer_p1", VaAccessRoles.interviewer, VaAccessScopeTypes.project, "AZSP01")
        self.assertEqual(self._issue("dm_c1", "interviewer_p1").status_code, 404)
        self.assertEqual(self._issue("admin", "interviewer_p1").status_code, 201)

    def test_privileged_or_other_role_people_are_not_eligible(self):
        for target in ("pi_ta", "dm_c1", "incharge_c1", "coder_p1", "reviewer_p1", "tester_ta",
                       "collab_c1", "supervisor_c1", "admin"):
            res = self._issue("admin", target)
            self.assertEqual(res.status_code, 400, target)
            self.assertEqual(res.get_json()["code"], "not_eligible", target)
        self.assertEqual(db.session.scalars(sa.select(AuthSignInToken)).all(), [])

    def test_any_other_grant_anywhere_makes_a_collector_ineligible(self):
        self._add_grant("interviewer_p1", VaAccessRoles.coder, VaAccessScopeTypes.project, "AZSP01")
        self.assertEqual(self._issue("admin", "interviewer_p1").get_json()["code"], "not_eligible")

    def test_inactive_account_is_not_eligible(self):
        user = self.users["interviewer_p1"]
        user.user_status = VaStatuses.deactive
        db.session.commit()
        self.addCleanup(lambda: (setattr(user, "user_status", VaStatuses.active), db.session.commit()))
        self.assertEqual(self._issue("admin", "interviewer_p1").get_json()["code"], "not_eligible")

    def test_email_goes_only_to_a_verified_address(self):
        with patch.dict(self.app.config, MAIL), mail.record_messages() as outbox:
            res = self._issue("dm_c1", "interviewer_p1", delivery="email")
            self.assertEqual(res.status_code, 201, res.get_json())
            self.assertEqual(set(res.get_json()), {"emailed", "expires_at"})
            [msg] = outbox
            self.assertEqual(msg.recipients, [self.users["interviewer_p1"].email])
            token_text = msg.body.split("Sign-in code: ")[1].split()[0]
            self.assertEqual(self._row().token_hash, devices.hash_token(token_text))
            self.assertIn("cid:sign-in-qr", msg.html)
            self.assertIn("did not expect", msg.body)
            # The unverified person gets nothing, and no token row.
            outbox.clear()
            self.assertEqual(db.session.scalars(sa.select(AuthSignInToken).where(
                AuthSignInToken.user_id == self.users["nobody"].user_id)).all(), [])
            res = self._issue("admin", "nobody", delivery="email")
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "no_verified_email")
            self.assertEqual(outbox, [])
        # ... but the on-screen delivery works for them.
        self.assertEqual(self._issue("admin", "nobody", delivery="show").status_code, 201)

    def test_email_failure_voids_the_token(self):
        with patch.dict(self.app.config, MAIL), \
                patch("app.services.email_service._actually_send_email", side_effect=OSError("smtp")):
            res = self._issue("admin", "interviewer_p1", delivery="email")
        self.assertEqual(res.status_code, 502)
        self.assertIsNotNone(self._row().revoked_at)

    def test_bad_delivery_and_unknown_user(self):
        self.assertEqual(self._issue("admin", "interviewer_p1", delivery="sms").status_code, 400)
        self._login(str(self.users["admin"].user_id))
        res = self.client.post(f"{USERS}/{uuid.uuid4()}/sign-in-qr", json={}, headers=self._csrf_headers())
        self.assertEqual(res.status_code, 404)
        res = self.client.post(f"{USERS}/not-a-uuid/sign-in-qr", json={}, headers=self._csrf_headers())
        self.assertEqual(res.status_code, 404)

    def test_issue_needs_csrf_and_is_rate_limited(self):
        self._login(str(self.users["admin"].user_id))
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            res = self.client.post(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr", json={})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._events("sign_in_qr_issued"), [])
        for _ in range(10):
            self.assertEqual(self._issue("admin", "interviewer_p1").status_code, 201)
        self.assertEqual(self._issue("admin", "interviewer_p1").status_code, 429)

    def test_reissue_voids_the_previous(self):
        first = self._token()
        second = self._token()
        self.assertEqual(self._redeem(first).status_code, 404)
        self.assertEqual(len(self._events("sign_in_qr_revoked")), 1)
        self.assertEqual(self._redeem(second).status_code, 201)

    # -- redeem ------------------------------------------------------------

    def test_redeem_enrols_and_opens_a_normal_device_session(self):
        token = self._token()
        with patch.dict(self.app.config, MAIL), mail.record_messages() as outbox, \
                self.assertLogs(level=logging.DEBUG) as logs:
            res = self._redeem(token)
            self.assertEqual(res.status_code, 201, res.get_json())
            body = res.get_json()
            for key in ("device_id", "device_secret", "project", "server_time", "access_token",
                        "refresh_token", "access"):
                self.assertIn(key, body)
            # The notice carries no token.
            self.assertEqual([m.recipients for m in outbox], [])  # queued, not sent inline
        self.assertNotIn(token, "\n".join(logs.output))
        row = self._row()
        device = db.session.get(AuthDevice, uuid.UUID(body["device_id"]))
        self.assertEqual(row.redeemed_device_id, device.device_id)
        self.assertEqual(device.enrolled_via_sign_in_token, row.id)
        self.assertIsNone(device.enrolled_via)
        self.assertEqual(device.project_id, "AZTA01")
        self.assertEqual(devices.hash_token(body["device_secret"]), device.secret_hash)
        session = db.session.scalars(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.device_id == device.device_id)).one()
        self.assertEqual(session.user_id, self.users["interviewer_p1"].user_id)
        self.assertAlmostEqual((session.access_expires_at - session.created_at).total_seconds(),
                               devices.ACCESS_TTL.total_seconds(), delta=2)
        [event] = self._events("sign_in_qr_redeemed")
        self.assertEqual(event.detail, {"device_id": str(device.device_id)})
        self.assertEqual(len(self._events("device_session_opened")), 1)
        # The bearer works on the device API only, as the person.
        me = self.client.get("/api/v1/me/access", headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual(me.status_code, 200, me.get_json())
        web = self.client.get(USERS, headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertIn(web.status_code, (401, 403))

    def test_single_use(self):
        token = self._token()
        self.assertEqual(self._redeem(token).status_code, 201)
        again = self._redeem(token)
        self.assertEqual(again.status_code, 404)
        self.assertEqual(again.get_json()["code"], "sign_in_qr_invalid")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthDevice).where(
            AuthDevice.enrolled_via_sign_in_token == self._row().id)), 1)

    def test_expiry_after_six_hours_is_audited_once(self):
        token = self._token()
        row = self._row()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.session.commit()
        for _ in range(2):
            res = self._redeem(token)
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "sign_in_qr_invalid"))
        self.assertEqual(len(self._events("sign_in_qr_expired")), 1)
        self._login(str(self.users["admin"].user_id))
        items = self.client.get(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr").get_json()["items"]
        self.assertEqual(items[0]["status"], "expired")

    def test_every_failure_is_the_same_answer(self):
        token = self._token()
        answers = {self._redeem("nonsense").get_data(as_text=True)}
        answers.add(self._redeem(None).get_data(as_text=True))
        answers.add(self._redeem("x" * 5000).get_data(as_text=True))
        self._redeem(token)
        answers.add(self._redeem(token).get_data(as_text=True))
        self.assertEqual(len(answers), 1, answers)

    def test_revoked_token_does_not_redeem(self):
        token = self._token()
        self._login(str(self.users["dm_c1"].user_id))
        res = self.client.delete(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr",
                                 headers=self._csrf_headers())
        self.assertEqual(res.get_json(), {"revoked": True})
        [event] = self._events("sign_in_qr_revoked")
        self.assertEqual(event.actor_user_id, self.users["dm_c1"].user_id)
        self.assertEqual(self._redeem(token).status_code, 404)
        again = self.client.delete(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr",
                                   headers=self._csrf_headers())
        self.assertEqual(again.get_json(), {"revoked": False})
        # A manager out of scope sees a 404; a coder a 403.
        self._login(str(self.users["dm_sp"].user_id))
        self.assertEqual(self.client.delete(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr",
                                            headers=self._csrf_headers()).status_code, 404)
        self._login(str(self.users["coder_p1"].user_id))
        self.assertEqual(self.client.get(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr"
                                         ).status_code, 403)

    def test_redeem_rechecks_eligibility(self):
        token = self._token()
        self._add_grant("interviewer_p1", VaAccessRoles.coder, VaAccessScopeTypes.project, "AZSP01")
        res = self._redeem(token)
        self.assertEqual((res.status_code, res.get_json()["code"]), (404, "sign_in_qr_invalid"))
        self.assertEqual(db.session.scalars(sa.select(AuthDevice).where(
            AuthDevice.enrolled_via_sign_in_token.is_not(None))).all(), [])
        self.assertIsNotNone(self._row().revoked_at)
        self.assertIsNone(self._row().redeemed_at)

    def test_revoke_and_reissue_leave_a_redeemed_token_alone(self):
        token = self._token()
        self.assertEqual(self._redeem(token).status_code, 201)
        redeemed = self._row()
        self.assertIsNotNone(redeemed.redeemed_at)
        self._login(str(self.users["admin"].user_id))
        res = self.client.delete(f"{USERS}/{self.users['interviewer_p1'].user_id}/sign-in-qr",
                                 headers=self._csrf_headers())
        self.assertEqual(res.get_json(), {"revoked": False})
        self._token()  # reissue
        db.session.refresh(redeemed)
        self.assertIsNone(redeemed.revoked_at)
        self.assertEqual(self._events("sign_in_qr_revoked"), [])

    def test_session_reset_after_issue_voids_the_token(self):
        token = self._token()
        user = self.users["interviewer_p1"]
        user.bump_session_version()
        db.session.commit()
        res = self._redeem(token)
        self.assertEqual((res.status_code, res.get_json()["code"]), (404, "sign_in_qr_invalid"))
        self.assertIsNotNone(self._row().revoked_at)
        self.assertIsNone(self._row().redeemed_at)
        [event] = self._events("sign_in_qr_refused")
        self.assertEqual((event.user_id, event.detail), (user.user_id, {"reason": "session_changed"}))
        self.assertNotIn(token, str(event.detail))
        self.assertEqual(self._redeem(token).status_code, 404)

    def test_ineligible_at_redeem_audits_a_refusal(self):
        token = self._token()
        self._add_grant("interviewer_p1", VaAccessRoles.coder, VaAccessScopeTypes.project, "AZSP01")
        self.assertEqual(self._redeem(token).status_code, 404)
        [event] = self._events("sign_in_qr_refused")
        self.assertEqual(event.detail, {"reason": "not_eligible"})

    def test_a_closed_project_is_never_the_enrolment_project(self):
        user = self.users["interviewer_p1"]
        # AZCL01 sorts before AZTA01 but is closed.
        self._add_grant("interviewer_p1", VaAccessRoles.interviewer, VaAccessScopeTypes.project, "AZCL01")
        self.assertEqual(sign_in_qr_service.eligible_project(user), "AZTA01")
        res = self._redeem(self._token())
        self.assertEqual(res.get_json()["project"]["project_id"], "AZTA01")
        for grant in db.session.scalars(sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user.user_id,
                VaUserAccessGrants.project_id.is_distinct_from("AZCL01"))):
            grant.grant_status = VaStatuses.deactive
        db.session.commit()
        self.assertIsNone(sign_in_qr_service.eligible_project(user))

    def test_redeem_notice_goes_only_to_a_verified_address(self):
        for key, expected in (("interviewer_p1", True), ("nobody", False)):
            with patch.dict(self.app.config, MAIL), \
                    patch("app.services.email_service._should_attempt_email_delivery", return_value=True), \
                    patch("app.services.email_service._dispatch_email") as dispatch:
                user = self.users[key]
                user.email = user.email or "x@example.test"
                self.assertIs(email_service.send_sign_in_qr_redeemed_notice(user), expected)
                self.assertEqual(dispatch.delay.called, expected)

    def test_redeem_bad_device_data_does_not_burn_the_token(self):
        token = self._token()
        res = self.client.post(REDEEM, json={"token": token, "device_name": "", "platform": "android"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._redeem(token).status_code, 201)

    def test_redeem_is_rate_limited_per_ip_and_per_token(self):
        for _ in range(5):
            self.assertEqual(self._redeem("same-token").status_code, 404)
        self.assertEqual(self._redeem("same-token").status_code, 429)
        limiter.reset()
        for _ in range(10):
            self._redeem(f"t{uuid.uuid4().hex}")
        self.assertEqual(self._redeem(f"t{uuid.uuid4().hex}").status_code, 429)

    def test_pending_terms_do_not_refuse_the_redeem(self):
        # Same behaviour as a password sign-in: tokens carry terms_required.
        token = self._token()
        res = self._redeem(token)
        self.assertEqual(res.status_code, 201)
        self.assertIn("terms_required", res.get_json())
