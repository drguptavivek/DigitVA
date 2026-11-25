"""Characterization of the auth/CSRF gate on every URL rule (digitva-r8nh.6, step 1).

Written on unchanged code before the request-principal refactor, so that
refactor can be shown to answer every route exactly as before. For every
``METHOD rule`` of the session app (HEAD and OPTIONS skipped) it records what
one ordinary user gets with three credentials:

- ``bearer``: a live device access token (``Authorization: Bearer``);
- ``cookie``: a signed-in browser session, no ``X-CSRFToken``;
- ``cookie_csrf``: the same session with a valid ``X-CSRFToken``
  (state-changing methods only);
- ``none``: no credential at all.

Rules under ``/api/v1/`` also record the same credentials for an account
holding a global admin grant and a collection grant (``admin_bearer``,
``admin_cookie``, ``admin_cookie_csrf``). Each bearer is minted for its row
inside the row's savepoint, so the 15-minute access TTL cannot expire mid-sweep.

Each outcome is ``<status> <mimetype>`` plus the JSON ``code`` (or a short
``error``), the redirect target's path and query keys, or an HTML page's
``<title>``; then, for a 2xx JSON object, its sorted top-level keys
(``keys=``); then ``xcsrf`` when the response carries an ``X-CSRFToken``
header. Values are not fingerprinted: ids, timestamps, nonces and CSRF tokens
vary. The goal is the gate, not
each handler's business answer; a deterministic 400/404 from a handler that
received dummy URL values is recorded as is.

The expected matrix is ``tests/fixtures/route_auth_matrix.json``. Rewrite it
with ``REGEN_ROUTE_AUTH_MATRIX=1`` only for a reviewed behaviour change.
``ROUTE_AUTH_MATRIX_REVERSED=1`` sweeps in reverse order; regenerating with it
must give a byte-identical file (no row depends on an earlier one).

Isolation: every request runs inside its own savepoint, on a fresh client,
with a fresh ``g``, an emptied rate limiter and a null cache, so a route that
signs out or deletes something cannot change the next row. Python-level
network access (sockets, DNS) is refused and recorded, and Celery sends are
swallowed; the sweep fails if any network attempt was made.

Also pinned: bundle ingest's ``_device_projection`` effect on ``is_admin()``
for a mixed admin/interviewer account on a bearer request, and the
digitva-r8nh.32 stale-bearer gaps as they are today. The other r8nh.32 gap (a
revoked device's refresh is 401 ``session_revoked`` with no audit row) is
already pinned by
``tests/routes/test_device_auth_contract.py::DeviceAuthRouteContractTests::test_revoked_device_is_audited_at_sign_in_only``.

Governing docs: docs/policy/api-v1.md, docs/policy/access-control-model.md,
docs/policy/auth-decorator-rbac.md, docs/policy/mobile-sign-in.md,
docs/current-state/authentication-and-onboarding.md (section 6, "One
credential rule for /api/v1/").
"""

import json
import os
import re
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

import sqlalchemy as sa
from celery import Celery
from celery.app.task import Task
from flask import g
from flask_caching.backends import NullCache

from app import cache, db, limiter
from app.models import VaAccessRoles, VaAccessScopeTypes, VaStatuses, VaUserAccessGrants
from app.services import bundle_ingest_service
from app.services import device_auth_service as devices
from app.services.submission_analytics_mv import (
    CORE_MV_NAME,
    build_submission_analytics_core_mv_sql,
)
from app.services.submission_payload_version_service import clear_payload_pii_request_cache
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests
from tests.test_public_demo import PublicDemoBase

GOLDEN = Path(__file__).parent / "fixtures" / "route_auth_matrix.json"
REGEN = "REGEN_ROUTE_AUTH_MATRIX"
#: Development check: sweep in reverse order; the matrix must not change.
REVERSED = "ROUTE_AUTH_MATRIX_REVERSED"
EXPECTED_RULE_COUNT = 711
EXPECTED_KEY_COUNT = 726

SKIPPED_METHODS = {"HEAD", "OPTIONS"}
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
JSON_BODY_METHODS = {"POST", "PUT", "PATCH"}
#: Only these rules get the admin columns, to keep the sweep's runtime sane.
ADMIN_PREFIX = "/api/v1/"

#: Config that Config reads from the environment (.env included) and that
#: reaches a recorded part: a page title, a status or a JSON key set. Pinned
#: to neutral values in the set/unset state the golden was recorded under.
PINNED_CONFIG = {
    "SITE_ENV_LABEL": "",
    "PUBLIC_DEMO_ENABLED": False,
    "PUBLIC_DEMO_PROJECT_ID": "PUB01",
    "PUBLIC_BASE_URL": "https://matrix.example.test",
    "DEVICE_PUBLIC_URL": "https://matrix.example.test",
    "DIGITVA_ANDROID_APK_URL": "",
    "DIGITVA_PLUS_ANDROID_APK_TAG": "",
    "DIGITVA_BUILD_REVISION": "",
    "DIGITVA_TRAINING_PROJECT_ID": "TRN01",
    "DIGITVA_WEEKLY_DEMO_PROJECT_ID": "DEMO01",
    "METHOD_NOT_ALLOWED_BAN_ENABLED": True,
    "EMAIL_DELIVERY_ENABLED": True,
}

#: Rules left out of the sweep, by endpoint, each with its reason. Keep it
#: minimal; an entry for an endpoint that no longer exists fails the sweep.
EXCLUDED_ENDPOINTS = {}

#: Dummy URL values per converter: deterministic and present in no table.
DUMMY_UUID = "00000000-0000-4000-8000-00000000d0d0"
DUMMY_INT = 987654
DUMMY_PATH = "no-such-dir/no-such-file.txt"
DUMMY_STRING = "zzdummy"

PASSWORD = device_tests.PASSWORD
PROJECT_ID = "RAM01"
SITE_ID = "RM01"


# ── Building requests ───────────────────────────────────────────────────────

def _dummy_value(converter):
    kind = type(converter).__name__
    if kind == "UUIDConverter":
        return DUMMY_UUID
    if kind == "IntegerConverter":
        return DUMMY_INT
    if kind == "PathConverter":
        return DUMMY_PATH
    if kind == "UnicodeConverter":
        return DUMMY_STRING
    raise AssertionError(f"no dummy value for converter {kind}")


def _rule_path(app, rule, method):
    """The path for *rule* with dummy values, checked to route back to it."""
    values = {name: _dummy_value(conv) for name, conv in rule._converters.items()}
    _domain, path = rule.build(values, append_unknown=False)
    endpoint, _args = app.url_map.bind("localhost").match(path, method)
    assert endpoint == rule.endpoint, f"{method} {rule} built {path!r}, which routes to {endpoint}"
    return path


def _sweep_keys(app):
    """``[(key, rule, method)]`` for every rule and method, sorted by key."""
    keys = []
    for rule in app.url_map.iter_rules():
        for method in sorted((rule.methods or set()) - SKIPPED_METHODS):
            keys.append((f"{method} {rule.rule}", rule, method))
    return sorted(keys, key=lambda item: item[0])


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _outcome(response):
    """Status, mimetype and the JSON code (or error) or the redirect target,
    then a 2xx JSON object's sorted top-level keys and the ``X-CSRFToken``
    header flag."""
    parts = [str(response.status_code), response.mimetype or "-"]
    location = response.headers.get("Location")
    if location:
        target = urlsplit(location)
        query = ",".join(sorted({key for key, _ in parse_qsl(target.query, keep_blank_values=True)}))
        parts.append(f"-> {target.path}" + (f"?{query}" if query else ""))
    elif response.is_json:
        body = response.get_json(silent=True)
        if isinstance(body, dict) and "code" in body:
            parts.append(f"code={body['code']}")
        elif isinstance(body, dict) and isinstance(body.get("error"), str):
            parts.append(f"error={body['error'][:60]}")
        if 200 <= response.status_code < 300 and isinstance(body, dict):
            parts.append("keys=" + ",".join(sorted(body)))
    elif response.mimetype == "text/html":
        # The page title tells an HTML CSRF refusal (400 "Access Denied") from
        # a handler's abort(400); the rest of the body carries nonces.
        title = _TITLE.search(response.get_data(as_text=True))
        if title:
            parts.append(f"title={' '.join(title.group(1).split())[:60]}")
    if "X-CSRFToken" in response.headers:
        parts.append("xcsrf")
    response.close()
    return " ".join(parts)


# ── Network guard ───────────────────────────────────────────────────────────

class NetworkAttempt(RuntimeError):
    pass


def _network_guard(attempts):
    """Patches refusing every Python-level socket connect and DNS lookup.

    The database is reached through libpq (C), which these do not touch.
    Attempts are recorded, because a handler's broad ``except`` could swallow
    the raise.
    """
    def refuse_connect(sock, address, *args, **kwargs):
        attempts.append(f"connect {address!r}")
        raise NetworkAttempt(f"network access refused in the auth matrix: {address!r}")

    def refuse_lookup(host, *args, **kwargs):
        attempts.append(f"getaddrinfo {host!r}")
        raise NetworkAttempt(f"DNS lookup refused in the auth matrix: {host!r}")

    return [
        mock.patch.object(socket.socket, "connect", refuse_connect),
        mock.patch.object(socket.socket, "connect_ex", refuse_connect),
        mock.patch.object(socket, "getaddrinfo", refuse_lookup),
    ]


# ── Shared fixtures ─────────────────────────────────────────────────────────

class _FreshClient(device_tests._FreshGClient):
    """Each request starts on an empty ``g``, as production pushes a fresh
    one per request; whatever earlier tests or rows left there is dropped."""

    def open(self, *args, **kwargs):
        for key in list(vars(g)):
            g.pop(key, None)
        clear_payload_pii_request_cache()
        limiter.reset()
        return super().open(*args, **kwargs)


def _device_tokens(user, project_id):
    """A live device session for *user*; the caller commits."""
    device, _secret = devices._add_device(project_id, "Matrix phone", "android", "1.0.0", None)
    tokens, _user = devices._open_authorized_session(device, user)
    return tokens


class _MatrixBase(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        device_tests.DeviceApiTests._make_project(PROJECT_ID, SITE_ID, now)
        cls.user = cls._get_or_make_user("matrix.interviewer@test.local", PASSWORD)
        device_tests.DeviceApiTests._grant(cls.user, PROJECT_ID)
        db.session.commit()

    @classmethod
    def _make_mixed_admin(cls):
        """An account with a global admin grant and a collection grant."""
        mixed = cls._get_or_make_user("matrix.mixed.admin@test.local", PASSWORD)
        device_tests.DeviceApiTests._grant(mixed, PROJECT_ID)
        db.session.add(VaUserAccessGrants(
            user_id=mixed.user_id, role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope, notes="matrix mixed admin",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()
        return mixed

    def _client(self):
        return _FreshClient(self.app, self.app.response_class, use_cookies=True)

    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}


# ── The sweep ───────────────────────────────────────────────────────────────

class RouteAuthMatrixTests(_MatrixBase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # GET /api/v1/me/kpis reads the core analytics MV, which create_all
        # does not build; built in the class transaction and rolled back with
        # it (docs/policy/test-harness.md), else that row would pin a 500.
        db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {CORE_MV_NAME} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True, project_clock=True)))
        cls.admin = cls._make_mixed_admin()
        db.session.commit()

    def _expo_dist(self):
        """A stand-in Expo web export: just an ``index.html``."""
        root = tempfile.TemporaryDirectory(prefix="route_auth_matrix_expo_")
        self.addCleanup(root.cleanup)
        Path(root.name, "index.html").write_text("<html><title>Matrix export</title></html>")
        return root.name

    def _isolated_request(self, credential, method, path):
        """One request in its own savepoint, on a fresh client. An
        ``admin_`` credential is the mixed admin's; a bearer is minted here,
        inside the savepoint, so no access token outlives its TTL."""
        self.tearDown()
        self.setUp()
        client = self.client = self._client()
        user = self.admin if credential.startswith("admin_") else self.user
        kind = credential.removeprefix("admin_")
        headers = {}
        if kind == "bearer":
            headers.update(self._bearer(_device_tokens(user, PROJECT_ID).access_token))
        elif kind in ("cookie", "cookie_csrf"):
            self._login(str(user.user_id))
            if kind == "cookie_csrf":
                headers.update(self._csrf_headers())
        kwargs = {"json": {}} if method in JSON_BODY_METHODS else {}
        return _outcome(client.open(path, method=method, headers=headers, **kwargs))

    def _row(self, rule, method):
        path = _rule_path(self.app, rule, method)
        credentials = ["bearer", "cookie", "none"]
        if method in STATE_CHANGING:
            credentials.insert(2, "cookie_csrf")
        if rule.rule.startswith(ADMIN_PREFIX):
            credentials += [f"admin_{credential}" for credential in credentials if credential != "none"]
        row = {"endpoint": rule.endpoint}
        for credential in credentials:
            row[credential] = self._isolated_request(credential, method, path)
        return row

    def _anchor(self):
        """``/api/v1/me/access`` answers each credential: proof both users
        are live and not stopped by a gate before or after the sweep."""
        return {
            credential: self._isolated_request(credential, "GET", "/api/v1/me/access")
            for credential in ("bearer", "cookie", "none", "admin_bearer", "admin_cookie")
        }

    def _sweep(self, keys):
        matrix = {}
        for key, rule, method in keys:
            matrix[key] = self._row(rule, method)
        return matrix

    def test_every_rule_matches_the_golden_matrix(self):
        rules = list(self.app.url_map.iter_rules())
        self.assertEqual(len(rules), EXPECTED_RULE_COUNT)
        keys = _sweep_keys(self.app)
        self.assertEqual(len({key for key, _r, _m in keys}), EXPECTED_KEY_COUNT)
        self.assertEqual(len(keys), EXPECTED_KEY_COUNT)
        endpoints = {rule.endpoint for rule in rules}
        self.assertEqual(sorted(set(EXCLUDED_ENDPOINTS) - endpoints), [])
        keys = [item for item in keys if item[1].endpoint not in EXCLUDED_ENDPOINTS]

        access = "200 application/json keys=account,admin_actions,demo_coding,is_admin,projects,roles,training,user"
        expected_anchor = {
            "bearer": access,
            "cookie": f"{access} xcsrf",
            "none": "401 application/json code=unauthorized",
            "admin_bearer": access,
            "admin_cookie": f"{access} xcsrf",
        }
        attempts, celery_sends = [], []
        patches = _network_guard(attempts) + [
            mock.patch.dict(self.app.extensions["cache"], {cache: NullCache()}),
            mock.patch.object(Task, "apply_async", lambda task, *a, **k: celery_sends.append(task.name)),
            mock.patch.object(Celery, "send_task", lambda app, name, *a, **k: celery_sends.append(name)),
            # What is on disk must not decide a row: the Expo web export (and
            # export_ready's per-process memo of it) and the hosted APK.
            # Environment-read config is pinned too (PINNED_CONFIG).
            mock.patch.dict(self.app.config, {"EXPO_CLIENT_DIST": self._expo_dist(),
                                              "DIGITVA_ANDROID_APK_DIR": "",
                                              **PINNED_CONFIG}),
            mock.patch("app.routes.expo_client.export_ready", return_value=True),
            mock.patch("app.routes.training_demo.export_ready", return_value=True),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        # Positive control: the guard bites (else the empty list below is vacuous).
        with self.assertRaises(NetworkAttempt):
            socket.create_connection(("192.0.2.1", 9), timeout=1)
        self.assertEqual(attempts, ["getaddrinfo '192.0.2.1'"])
        attempts.clear()

        self.assertEqual(self._anchor(), expected_anchor)
        if os.environ.get(REVERSED):
            keys = list(reversed(keys))
        matrix = self._sweep(keys)
        self.assertEqual(self._anchor(), expected_anchor)
        self.assertEqual(attempts, [], "a route tried to reach the network")
        self.assertEqual(celery_sends, [], "a route queued a Celery task")
        # Positive control: the admin columns reach past the interviewer's
        # gate somewhere, else a sign-in gate could make them a silent copy.
        self.assertTrue(any(row["admin_cookie"] != row["cookie"]
                            for row in matrix.values() if "admin_cookie" in row))

        if os.environ.get(REGEN):
            # Re-blessing must be a deliberate local act: never in CI or an xdist worker,
            # where it would silently accept a changed reply.
            if os.environ.get("CI") or os.environ.get("PYTEST_XDIST_WORKER"):
                self.fail(f"{REGEN} is refused under CI or pytest -n; run it serially by hand")
            GOLDEN.write_text(json.dumps(matrix, indent=1, sort_keys=True) + "\n")
        expected = json.loads(GOLDEN.read_text())
        changed = {
            key: {"expected": expected.get(key), "actual": matrix.get(key)}
            for key in sorted(set(expected) | set(matrix))
            if expected.get(key) != matrix.get(key)
        }
        self.assertEqual(changed, {}, "route auth outcomes differ from the golden matrix "
                         f"({len(changed)} keys); set {REGEN}=1 only for a reviewed change")

    def test_dummy_values_route_back_to_their_own_rule(self):
        """Guards the sweep: no dummy URL is shadowed by a sibling rule."""
        for _key, rule, method in _sweep_keys(self.app):
            _rule_path(self.app, rule, method)


# ── _device_projection ──────────────────────────────────────────────────────

class DeviceProjectionAdminCheckTests(_MatrixBase):
    """``bundle_ingest_service._device_projection`` flips ``g.bearer_auth``
    for the calls inside it, which changes what ``is_admin()`` answers for an
    account holding both a global admin grant and a collection grant."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mixed = cls._make_mixed_admin()
        cls.mixed_tokens = _device_tokens(cls.mixed, PROJECT_ID)
        db.session.commit()

    def _admin_checks(self, headers):
        from flask_login import current_user

        g.pop("_login_user", None)
        with self.app.test_request_context("/api/v1/me/access", headers=headers):
            previous = g.get("bearer_auth")
            try:
                self.assertIsNone(self.app.preprocess_request())
                user = current_user._get_current_object()
                self.assertEqual(user.user_id, self.mixed.user_id)
                outside = (g.bearer_auth, user.is_admin())
                with bundle_ingest_service._device_projection(True):
                    inside_on = (g.bearer_auth, user.is_admin())
                with bundle_ingest_service._device_projection(False):
                    inside_off = (g.bearer_auth, user.is_admin())
                after = (g.bearer_auth, user.is_admin())
            finally:
                g.bearer_auth = previous
                g.pop("_login_user", None)
        return {"outside": outside, "on": inside_on, "off": inside_off, "after": after}

    def test_bearer_request(self):
        checks = self._admin_checks({"Authorization": f"Bearer {self.mixed_tokens.access_token}"})
        self.assertEqual(checks, {
            "outside": (True, False),
            "on": (True, False),
            "off": (False, True),
            "after": (True, False),
        })

    def test_cookie_request(self):
        self.client = self._client()
        self._login(str(self.mixed.user_id))
        cookie = self.client.get_cookie(self.app.config.get("SESSION_COOKIE_NAME", "session"))
        self.assertIsNotNone(cookie)
        checks = self._admin_checks({"Cookie": f"{cookie.key}={cookie.value}"})
        self.assertEqual(checks, {
            "outside": (False, True),
            "on": (True, False),
            "off": (False, True),
            "after": (False, True),
        })


# ── r8nh.32 gaps, pinned as they are ────────────────────────────────────────

STALE = {"Authorization": "Bearer stale-token-from-an-old-session"}
UNAUTHORIZED = {"error": "Authentication required.", "code": "unauthorized"}


class StaleBearerProfileDeletionTests(_MatrixBase):
    """``record_profile_deletion`` takes device credentials, not a bearer, but
    is not in ``UNAUTHENTICATED_ENDPOINTS``: a stale bearer is refused by
    ``authenticate_bearer`` before the view runs."""

    def _delete(self, headers):
        device = self._enrolled
        self.client = self._client()
        return self.client.post(f"{device_tests.API}/profile-deletions", headers=headers, json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "user_id": str(self.user.user_id), "unsent_count": 0, "loss_confirmed": False})

    def setUp(self):
        super().setUp()
        limiter.reset()
        row, secret = devices._add_device(PROJECT_ID, "Deleting phone", "android", "1.0.0", None)
        devices._open_authorized_session(row, self.user)
        db.session.commit()
        self._enrolled = {"device_id": str(row.device_id), "device_secret": secret}

    def test_without_a_bearer_it_records(self):
        response = self._delete({})
        self.assertEqual((response.status_code, response.get_json()), (201, {"recorded": True}))

    def test_with_a_stale_bearer_it_is_refused(self):
        self.assertNotIn("api_v1.auth_api.record_profile_deletion", devices.UNAUTHENTICATED_ENDPOINTS)
        response = self._delete(STALE)
        self.assertEqual((response.status_code, response.get_json()), (401, UNAUTHORIZED))


class StaleBearerDemoSignupTests(PublicDemoBase):
    """The demo sign-up endpoints, with the public demo on, are not in
    ``UNAUTHENTICATED_ENDPOINTS``: a stale bearer is 401 before the view."""

    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def test_challenge(self):
        self.assertNotIn("api_v1.auth_api.demo_signup_challenge", devices.UNAUTHENTICATED_ENDPOINTS)
        plain = self.client.get("/api/v1/auth/demo-signup/challenge")
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(set(plain.get_json()), {"salt", "difficulty", "expires", "signature"})
        stale = self.client.get("/api/v1/auth/demo-signup/challenge", headers=STALE)
        self.assertEqual((stale.status_code, stale.get_json()), (401, UNAUTHORIZED))

    def test_signup(self):
        self.assertNotIn("api_v1.auth_api.demo_signup", devices.UNAUTHENTICATED_ENDPOINTS)
        body = {"username": "matrix.demo", "password": "x", "captcha": {}}
        plain = self.client.post("/api/v1/auth/demo-signup", json=body)
        self.assertEqual((plain.status_code, plain.get_json()["code"]), (400, "captcha_failed"))
        stale = self.client.post("/api/v1/auth/demo-signup", json=body, headers=STALE)
        self.assertEqual((stale.status_code, stale.get_json()), (401, UNAUTHORIZED))
