"""Pins the email-change and language blocks of the admin and data-manager
update-user handlers (PUT /admin/api/users/<id> and
PUT /data-management/api/users/<id>): status, message, rows written, audit row
and verification email. Written before the shared logic moved into
user_account_service (digitva-r8nh.15); must stay green unedited after.
"""

import uuid
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import AuthSecurityEvent, MasLanguages
from tests.authz.fixture import AuthzFixtureMixin, R, U
from tests.test_mobile_sign_in import PASSWORD, MobileSignInTestBase


def _addr(tag="x"):
    return f"{tag}.{uuid.uuid4().hex[:8]}@example.com"


class UpdateUserProfileCharacterizationTests(AuthzFixtureMixin, MobileSignInTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code, name, active in (("english", "English", True), ("hindi", "Hindi", True),
                                   ("dormant", "Dormant", False)):
            row = db.session.get(MasLanguages, code)
            if row is None:
                db.session.add(MasLanguages(language_code=code, language_name=name, is_active=active))
            else:
                row.is_active = active
        db.session.commit()

    def _as(self, key):
        self._login(str(self.users[key].user_id))

    def _target(self, verified=False):
        """An email account the DM created and may edit. A DM may change the
        email only before first sign-in, so only the admin cases use a
        verified one."""
        user = self._make_user(_addr("target"), PASSWORD)
        user.email_verified = verified
        user.vacode_language = ["english"]
        user.other = {"created_by_user_id": str(self.users["dm_c1"].user_id)}
        db.session.add(self._grant_row(user, R.reviewer, U, "P1"))
        db.session.commit()
        return user

    def _put(self, who, user, body):
        self._as("admin" if who == "admin" else "dm_c1")
        base = "/admin/api/users/" if who == "admin" else "/data-management/api/users/"
        with patch("app.services.email_service._dispatch_email") as dispatch:
            response = self.client.put(f"{base}{user.user_id}", json=body,
                                       headers=self._csrf_headers())
        return response, dispatch

    def _events(self, user):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "coding_languages_changed")).all()

    # -- email ---------------------------------------------------------------

    def test_email_change_succeeds_unverifies_ends_sessions_and_mails(self):
        for who in ("admin", "dm"):
            with self.subTest(who=who):
                user = self._target(who == "admin")
                version = user.auth_session_version
                new = _addr("new")
                response, dispatch = self._put(who, user, {"email": f" {new.upper()} ", "email_confirm": new})
                self.assertEqual(response.status_code, 200, response.get_json())
                db.session.refresh(user)
                self.assertEqual(user.email, new)
                self.assertFalse(user.email_verified)
                self.assertEqual(user.auth_session_version, version + 1)
                self.assertEqual(dispatch.delay.call_args.kwargs["to"], new)
                self.assertEqual(response.get_json()["user"]["email"], new)

    def test_email_unchanged_writes_nothing(self):
        for who in ("admin", "dm"):
            with self.subTest(who=who):
                user = self._target(who == "admin")
                verified = user.email_verified
                version = user.auth_session_version
                response, dispatch = self._put(who, user, {"email": user.email.upper(),
                                                           "email_confirm": user.email})
                self.assertEqual(response.status_code, 200, response.get_json())
                db.session.refresh(user)
                self.assertEqual(user.email_verified, verified)
                self.assertEqual(user.auth_session_version, version)
                dispatch.delay.assert_not_called()

    def test_admin_resends_verification_for_an_unverified_account_even_if_unchanged(self):
        user = self._target()
        response, dispatch = self._put("admin", user, {"email": user.email, "email_confirm": user.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dispatch.delay.call_args.kwargs["to"], user.email)
        user2 = self._target()
        response, dispatch = self._put("dm", user2, {"email": user2.email, "email_confirm": user2.email})
        self.assertEqual(response.status_code, 200)
        dispatch.delay.assert_not_called()

    def test_duplicate_email_is_refused_and_nothing_changes(self):
        for who in ("admin", "dm"):
            with self.subTest(who=who):
                user, other = self._target(who == "admin"), self._target()
                version = user.auth_session_version
                original = user.email
                response, dispatch = self._put(who, user, {"email": other.email.upper(),
                                                           "email_confirm": other.email})
                self.assertEqual((response.status_code, response.get_json()["error"]),
                                 (400, "Email already in use."))
                db.session.refresh(user)
                self.assertEqual((user.email, user.email_verified, user.auth_session_version),
                                 (original, who == "admin", version))
                dispatch.delay.assert_not_called()

    def test_invalid_email_input_is_refused(self):
        cases = (
            ({"email": "a@example.com"}, "email and email_confirm are required."),
            ({"email": "", "email_confirm": ""}, "email and email_confirm are required."),
            ({"email": "a@example.com", "email_confirm": "b@example.com"},
             "Email confirmation does not match."),
        )
        for who in ("admin", "dm"):
            for body, message in cases:
                with self.subTest(who=who, body=body):
                    user = self._target(who == "admin")
                    original = user.email
                    response, dispatch = self._put(who, user, body)
                    self.assertEqual((response.status_code, response.get_json()["error"]),
                                     (400, message))
                    db.session.refresh(user)
                    self.assertEqual(user.email, original)
                    dispatch.delay.assert_not_called()

    # -- languages -----------------------------------------------------------

    def test_valid_languages_are_saved(self):
        for who in ("admin", "dm"):
            with self.subTest(who=who):
                user = self._target()
                response, _ = self._put(who, user, {"languages": ["english", "hindi"]})
                self.assertEqual(response.status_code, 200, response.get_json())
                db.session.refresh(user)
                self.assertEqual(user.vacode_language, ["english", "hindi"])
                self.assertEqual(response.get_json()["user"]["languages"], ["english", "hindi"])

    def test_invalid_empty_or_non_list_languages_are_refused(self):
        cases = (
            (["english", "klingon"], "Invalid language codes: ['klingon']"),
            (["dormant"], "Invalid language codes: ['dormant']"),
            ([], "At least one language must be selected."),
            (None, "At least one language must be selected."),
            ("english", "At least one language must be selected."),
        )
        for who in ("admin", "dm"):
            for languages, message in cases:
                with self.subTest(who=who, languages=languages):
                    user = self._target()
                    response, _ = self._put(who, user, {"languages": languages})
                    self.assertEqual((response.status_code, response.get_json()["error"]),
                                     (400, message))
                    db.session.refresh(user)
                    self.assertEqual(user.vacode_language, ["english"])
                    self.assertEqual(self._events(user), [])

    def test_dm_audits_a_language_change_and_skips_an_identical_list(self):
        user = self._target()
        response, _ = self._put("dm", user, {"languages": ["english"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._events(user), [])
        response, _ = self._put("dm", user, {"languages": ["hindi"]})
        self.assertEqual(response.status_code, 200)
        (event,) = self._events(user)
        self.assertEqual((event.actor_user_id, event.detail),
                         (self.users["dm_c1"].user_id, {"old": ["english"], "new": ["hindi"]}))

    def test_admin_language_change_writes_no_audit_row(self):
        user = self._target()
        response, _ = self._put("admin", user, {"languages": ["hindi"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._events(user), [])
