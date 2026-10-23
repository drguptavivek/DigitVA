"""The cookie session is re-saved to the store at most once a minute.

Rules under test: app/utils/bearer_session.py, policy in
docs/policy/auth-decorator-rbac.md section 5. The wrapper is backend
agnostic, so the wrapped interface here is a spy.
"""
from unittest import mock

from flask import Response
from flask.sessions import SecureCookieSession

from app.utils.bearer_session import SESSION_REFRESH_WINDOW_SECONDS, BearerBlindSessionInterface
from tests.base import BaseTestCase


class SessionRefreshWindowTests(BaseTestCase):
    NOW = 1_000_000

    def _save(self, session, *, now, headers=None):
        """Run the wrapper's save_session at *now*; return (inner spy, response)."""
        inner = mock.Mock()
        wrapper = BearerBlindSessionInterface(inner)
        response = Response()
        with self.app.test_request_context("/", headers=headers or {}):
            with mock.patch("app.utils.bearer_session.time.time", return_value=now):
                wrapper.save_session(self.app, session, response)
        return inner, response

    def _loaded(self, **data):
        """A session as open_session hands it over: data in, not modified."""
        session = SecureCookieSession(data)
        session.modified = False
        return session

    def test_first_save_stamps_and_writes(self):
        session = SecureCookieSession({"_user_id": "u"})
        inner, _ = self._save(session, now=self.NOW)
        inner.save_session.assert_called_once()
        self.assertEqual(session["_refreshed_at"], self.NOW)

    def test_unchanged_session_inside_window_is_not_written(self):
        session = self._loaded(_user_id="u", _refreshed_at=self.NOW)
        inner, _ = self._save(session, now=self.NOW + SESSION_REFRESH_WINDOW_SECONDS - 1)
        inner.save_session.assert_not_called()
        self.assertEqual(session["_refreshed_at"], self.NOW)

    def test_unchanged_session_past_window_is_written_and_restamped(self):
        later = self.NOW + SESSION_REFRESH_WINDOW_SECONDS
        session = self._loaded(_user_id="u", _refreshed_at=self.NOW)
        inner, _ = self._save(session, now=later)
        inner.save_session.assert_called_once()
        self.assertEqual(session["_refreshed_at"], later)

    def test_modified_session_inside_window_is_written(self):
        session = self._loaded(_user_id="u", _refreshed_at=self.NOW)
        session["flash"] = "x"
        inner, _ = self._save(session, now=self.NOW + 1)
        inner.save_session.assert_called_once()

    def test_legacy_session_without_stamp_is_written(self):
        inner, _ = self._save(self._loaded(_user_id="u"), now=self.NOW)
        inner.save_session.assert_called_once()

    def test_empty_session_is_delegated_and_never_stamped(self):
        session = SecureCookieSession()
        session.modified = True  # logout cleared it: the store must hear of it
        inner, _ = self._save(session, now=self.NOW)
        inner.save_session.assert_called_once()
        self.assertNotIn("_refreshed_at", session)

    def test_session_left_with_only_the_stamp_is_emptied_and_delegated(self):
        session = self._loaded(_refreshed_at=self.NOW)
        self.assertIn("_refreshed_at", session)
        inner, _ = self._save(session, now=self.NOW + 1)
        inner.save_session.assert_called_once()
        self.assertNotIn("_refreshed_at", session)
        self.assertTrue(session.modified)

    def test_stamp_from_the_future_does_not_suppress_the_save(self):
        session = self._loaded(_user_id="u", _refreshed_at=self.NOW + 3600)
        inner, _ = self._save(session, now=self.NOW)
        inner.save_session.assert_called_once()
        self.assertEqual(session["_refreshed_at"], self.NOW)

    def test_skipped_save_keeps_vary_cookie_when_session_was_read(self):
        session = self._loaded(_user_id="u", _refreshed_at=self.NOW)
        session["_user_id"]  # marks the session accessed
        _, response = self._save(session, now=self.NOW + 1)
        self.assertIn("Cookie", response.vary)

    def test_bearer_request_never_saves_or_stamps(self):
        session = SecureCookieSession({"_user_id": "u"})
        inner = mock.Mock()
        wrapper = BearerBlindSessionInterface(inner)
        with self.app.test_request_context("/api/v1/area/summary", headers={"Authorization": "Bearer abc"}):
            wrapper.save_session(self.app, session, Response())
        inner.save_session.assert_not_called()
        self.assertNotIn("_refreshed_at", session)

    def test_regenerate_passes_through_to_the_wrapped_interface(self):
        inner = mock.Mock()
        BearerBlindSessionInterface(inner).regenerate("session")
        inner.regenerate.assert_called_once_with("session")
