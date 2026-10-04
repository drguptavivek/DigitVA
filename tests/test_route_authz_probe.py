"""Every non-public endpoint is decided by authz (digitva-5hmc).

Policy: docs/policy/access-control-model.md, "Every access goes through
authz". app/services/authz/consulted.py wraps every registered view that is
not on its reviewed ``EXEMPT_ENDPOINTS`` list and records whether an authz
decision ran. This module walks ``app.url_map`` and requests every rule, with
every method it accepts, as real users, with ``AUTHZ_ENFORCE_CONSULTED`` on,
and fails on any request whose view finished without authz deciding,
whatever its status (a 404 the view raised before asking authz counts).

Who is probed with what, and why that is the whole surface:

* The user with no grant: every rule, every method. ``role_required``
  decides through ``authz.effective_roles`` before the view body, so for a
  role-gated rule this proves the gate is the first thing that runs.
* One user per role (``ROLE_USERS``): every rule that is neither role-gated
  nor exempt (the ``login_required`` routes that decide in the body). A
  role-gated rule is not re-run per role: the gate marks the request decided
  before the view runs for every signed-in user, so a second role proves
  nothing more, and a POST that passes its gate would write to fixtures.
* Exempt endpoints are not probed; each is listed with its reason in
  consulted.py (and printed by ``test_exemptions_are_listed_with_reasons``).

Path parameters come from the authz fixture where the name is known
(``KNOWN_PARAMS``), else from the converter (a fresh uuid, ``1``, or a word):
a dummy id must still be refused by authz, never by a lookup that ran first.
CSRF and rate limits are switched off so every request reaches its view; the
device API is called with a bearer session, as the app calls it.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

import flask
import flask_login
from flask import g
from flask.testing import FlaskClient

from app import db, limiter
from app.decorators.role_required import ROLE_MARKER_ATTR
from app.models import AuthDeviceSession
from app.services import device_auth_service as devices
from app.services.authz import consulted
from tests.authz.fixture import FORMS, TA, AuthzFixtureMixin
from tests.base import BaseTestCase

ROLE_USERS = {
    "admin": "admin",
    "coder": "coder_ta",
    "coding_tester": "tester_ta",
    "reviewer": "reviewer_ta",
    "data_manager": "dm_ta",
    "site_pi": "sitepi_sp1",
    "project_pi": "pi_ta",
    "interviewer": "interviewer_p1",
    "interview_supervisor": "supervisor_c1",
    "mentor_institute_admin": "mentor",
    "collaborator": "collab_c1",
    "collaborator_pii": "collabpii_sp",
}

DEVICE_PREFIX = "/api/v1/device/"
_SKIP_METHODS = {"HEAD", "OPTIONS"}


class _FreshGClient(FlaskClient):
    """Production pushes a fresh ``g`` per request; the suite's app context
    outlives requests, so drop the cached user and device session here."""

    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        g.pop("device_session", None)
        return super().open(*args, **kwargs)


def _view_chain(view):
    seen = []
    while view is not None and len(seen) < 32:
        seen.append(view)
        view = getattr(view, "__wrapped__", None)
    return seen


def _role_gated(view) -> bool:
    return any(hasattr(f, ROLE_MARKER_ATTR) for f in _view_chain(view))


class RouteAuthzProbeTests(AuthzFixtureMixin, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.services import mentor_institute_service as mentors

        mentors.set_member_admin("AZMI", cls.users["mentor"].email, True)
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        for key, value in (("AUTHZ_ENFORCE_CONSULTED", True), ("WTF_CSRF_ENABLED", False)):
            previous = self.app.config.get(key)
            self.app.config[key] = value
            self.addCleanup(self.app.config.__setitem__, key, previous)
        limiter.enabled = False
        self.addCleanup(setattr, limiter, "enabled", True)

    # -- request building --------------------------------------------------

    def _known_params(self):
        return {
            "project_id": TA,
            "va_sid": "ta-p1",
            "sid": "ta-p1",
            "va_form_id": FORMS["ta1"][0],
            "form_id": FORMS["ta1"][0],
            "site_id": "AZS1",
            "org_unit_id": str(self.units["P1"].org_unit_id),
            "unit_id": str(self.units["P1"].org_unit_id),
        }

    def _path(self, rule) -> str:
        known = self._known_params()
        values = {}
        for name in rule.arguments:
            converter = type(rule._converters[name]).__name__
            if name in known and converter not in ("UUIDConverter", "IntegerConverter"):
                values[name] = known[name]
            elif converter == "UUIDConverter":
                values[name] = known.get(name) or str(uuid.uuid4())
            elif converter in ("IntegerConverter", "FloatConverter"):
                values[name] = 1
            else:
                values[name] = "probe"
        adapter = self.app.url_map.bind("localhost")
        return adapter.build(rule.endpoint, values, method=None, force_external=False)

    def _bearer(self, user) -> dict:
        """A device session for *user*, opened directly (device sign-in
        itself asks for an interviewer grant; the probe wants the gate)."""
        _row, code = devices.create_enrolment_code(TA, actor=self.users["admin"])
        device, _secret = devices.enrol_device(
            code, device_name="probe", platform="android", app_version="0.1.0",
        )
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=user.user_id,
            user_session_version=user.auth_session_version or 0,
            created_at=datetime.now(UTC),
        )
        issued = devices._issue(session)
        db.session.add(session)
        db.session.commit()
        return {"Authorization": f"Bearer {issued.access_token}"}

    def _probe(self, user, rules):
        """[(endpoint, method, status, outcome)] for every rule and method;
        outcome: True decided, False skipped authz, None view never ran."""
        self._login(str(user.user_id))
        bearer = None
        results = []
        for rule in rules:
            path = self._path(rule)
            for method in sorted(rule.methods - _SKIP_METHODS):
                kwargs = {"method": method}
                if method != "GET":
                    kwargs["json"] = {}
                client = self.client
                if path.startswith(DEVICE_PREFIX):
                    bearer = bearer or self._bearer(user)
                    client = _FreshGClient(self.app, self.app.response_class)
                    kwargs["headers"] = bearer
                with client:
                    response = client.open(path, **kwargs)
                    outcome = consulted.consulted()
                results.append((rule.endpoint, method, response.status_code, outcome))
                db.session.rollback()
        return results

    def _rules(self, *, role_gated: bool | None):
        rules = []
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint in consulted.EXEMPT_ENDPOINTS:
                continue
            gated = _role_gated(self.app.view_functions[rule.endpoint])
            if role_gated is None or gated == role_gated:
                rules.append(rule)
        return sorted(rules, key=lambda r: (r.endpoint, str(r)))

    # -- the probe -----------------------------------------------------------

    def test_a_user_with_no_grant_is_decided_by_authz_on_every_route(self):
        rules = self._rules(role_gated=None)
        self.assertGreater(len(rules), 300)
        results = self._probe(self.users["nobody"], rules)
        decided = [r for r in results if r[3] is True]
        self.assertTrue(decided)  # presence first
        gaps = [r for r in results if r[3] is False]
        never_ran = [r for r in results if r[3] is None]
        self.assertEqual(gaps, [], "views that finished without authz deciding")
        self.assertEqual(never_ran, [], "requests refused before their view ran")

    def test_every_role_is_decided_by_authz_on_the_body_decided_routes(self):
        rules = self._rules(role_gated=False)
        endpoints = {r.endpoint for r in rules}
        # Presence first: the body-decided routes this probe exists for.
        self.assertIn("api_v1.workflow.get_events", endpoints)
        self.assertIn("api_v1.organization_api.project_units", endpoints)
        self.assertIn("api_v1.area_api.summary", endpoints)
        gaps = []
        for role, key in sorted(ROLE_USERS.items()):
            for row in self._probe(self.users[key], rules):
                if row[3] is not True:
                    gaps.append((role, *row))
        self.assertEqual(gaps, [])

    # -- enforcement ---------------------------------------------------------

    PROBED = "api_v1.workflow.get_events"

    def _swap(self, view):
        """Serve PROBED through the real guard around *view* (restored after)."""
        guarded = self.app.view_functions[self.PROBED]
        self.app.view_functions[self.PROBED] = consulted._guard(self.PROBED, view)
        self.addCleanup(self.app.view_functions.__setitem__, self.PROBED, guarded)
        return next(r for r in self.app.url_map.iter_rules() if r.endpoint == self.PROBED)

    def test_the_probe_sees_a_gap_and_enforcement_refuses_it(self):
        """Vacuity guard for the probe, and the production refusal."""
        rule = self._swap(lambda va_sid: flask.jsonify({"ok": True}))
        user = self.users["coder_ta"]
        with self.assertLogs(consulted.log, level=logging.WARNING) as logs:
            results = self._probe(user, [rule])
        self.assertEqual(results, [(self.PROBED, "GET", 403, False)])
        line = logs.output[0]
        self.assertIn(self.PROBED, line)
        self.assertIn(str(user.user_id), line)
        self.assertNotIn(user.email, line)
        self.assertNotIn(user.name, line)

    def test_an_http_error_raised_before_authz_is_refused_too(self):
        rule = self._swap(lambda va_sid: flask.abort(404))
        with self.assertLogs(consulted.log, level=logging.WARNING):
            results = self._probe(self.users["coder_ta"], [rule])
        self.assertEqual(results, [(self.PROBED, "GET", 403, False)])

    def test_a_refusal_raised_before_authz_passes_through(self):
        """A route rate limit raises 429 inside the view chain, before the
        view decides: it is a refusal, not a gap, and keeps its status."""
        rule = self._swap(lambda va_sid: None)
        for code in (401, 403, 429):
            self.app.view_functions[self.PROBED] = consulted._guard(
                self.PROBED, lambda va_sid, code=code: flask.abort(code),
            )
            with self.assertNoLogs(consulted.log, level=logging.WARNING):
                results = self._probe(self.users["coder_ta"], [rule])
            self.assertEqual(results, [(self.PROBED, "GET", code, False)])

    def test_a_consulted_view_is_served_under_enforcement(self):
        from app.services.authz import effective_roles

        def view(va_sid):
            return flask.jsonify({"roles": sorted(effective_roles(flask_login.current_user))})

        rule = self._swap(view)
        results = self._probe(self.users["coder_ta"], [rule])
        self.assertEqual(results, [(self.PROBED, "GET", 200, True)])

    def test_with_enforcement_off_a_gap_is_logged_and_served(self):
        self.app.config["AUTHZ_ENFORCE_CONSULTED"] = False
        rule = self._swap(lambda va_sid: flask.jsonify({"ok": True}))
        with self.assertLogs(consulted.log, level=logging.WARNING) as logs:
            results = self._probe(self.users["coder_ta"], [rule])
        self.assertEqual(results, [(self.PROBED, "GET", 200, False)])
        self.assertIn(self.PROBED, logs.output[0])

    def test_an_anonymous_request_is_left_to_the_authentication_guard(self):
        """The wrapper has nothing to authorize for nobody signed in: the
        auth guards answer (and base.js depends on their 401)."""
        self.assertEqual(
            _FreshGClient(self.app).get("/api/v1/workflow/events/ta-p1").status_code, 401
        )
        self._swap(lambda va_sid: flask.jsonify({"ok": True}))
        with self.assertNoLogs(consulted.log, level=logging.WARNING):
            response = _FreshGClient(self.app).get("/api/v1/workflow/events/ta-p1")
        self.assertEqual(response.status_code, 200)

    def test_every_non_exempt_view_is_wrapped(self):
        wrapper_code = consulted._guard("x", lambda: None).__code__
        for endpoint, view in self.app.view_functions.items():
            if endpoint in consulted.EXEMPT_ENDPOINTS:
                self.assertIsNot(view.__code__, wrapper_code, endpoint)
            else:
                self.assertIs(view.__code__, wrapper_code, endpoint)

    def test_exemptions_are_listed_with_reasons(self):
        registered = {rule.endpoint for rule in self.app.url_map.iter_rules()}
        for name, table in (
            ("PUBLIC_ENDPOINTS", consulted.PUBLIC_ENDPOINTS),
            ("SELF_SERVICE_ENDPOINTS", consulted.SELF_SERVICE_ENDPOINTS),
        ):
            self.assertTrue(table, name)
            for endpoint, reason in table.items():
                self.assertIn(endpoint, registered, f"{name} entry no longer routed")
                self.assertGreater(len(reason.strip()), 10, endpoint)
        self.assertFalse(set(consulted.PUBLIC_ENDPOINTS) & set(consulted.SELF_SERVICE_ENDPOINTS))
        # Self-service routes require a session; only public ones may skip it.
        for endpoint in consulted.SELF_SERVICE_ENDPOINTS:
            self.assertNotIn(endpoint, consulted.PUBLIC_ENDPOINTS)

    # -- attachments are never static ----------------------------------------

    def test_no_attachment_is_reachable_under_static(self):
        static = os.path.realpath(self.app.static_folder)
        app_data = os.path.realpath(self.app.config["APP_DATA"])
        self.assertTrue(os.path.isdir(static))
        self.assertFalse(app_data.startswith(static + os.sep) or app_data == static)
        self.assertFalse(static.startswith(app_data + os.sep))

        from types import SimpleNamespace

        from app.services.attachment_store import LocalAttachmentStore

        record = SimpleNamespace(va_form_id="PROBE5HMC01", storage_name=f"{uuid.uuid4().hex}.jpg")
        store = LocalAttachmentStore()
        media_dir = store.media_dir(record)
        self.assertFalse(os.path.realpath(media_dir).startswith(static + os.sep))
        os.makedirs(media_dir, exist_ok=True)
        path = os.path.join(media_dir, record.storage_name)
        with open(path, "wb") as handle:
            handle.write(b"\xff\xd8probe")
        self.addCleanup(os.rmdir, os.path.dirname(media_dir))
        self.addCleanup(os.rmdir, media_dir)
        self.addCleanup(os.remove, path)
        self.assertTrue(os.path.isfile(path))  # presence first

        key = store.key_for(record)
        self.assertEqual(self.client.get("/static/css/base.css").status_code, 200)
        for url in (
            f"/static/{key}",
            f"/static/{record.storage_name}",
            f"/static/../data/{key}",
            f"/static/%2e%2e/data/{key}",
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)
