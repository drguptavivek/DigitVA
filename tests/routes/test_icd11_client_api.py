"""ICD-11 client API (/api/icd11-client/v1/): token authentication, scopes,
isolation from every other credential, rate limits, bounded input and the
terminology answers over a faked WHO API (no network).
Policy: docs/policy/icd11-client-api.md."""

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock
from urllib.parse import parse_qs, unquote

import sqlalchemy as sa
from flask import g
from flask.testing import FlaskClient
from requests import Response
from sqlalchemy.orm import Session

from app import db, limiter
from app.models import AuthDeviceSession, AuthIcd11ApiClient
from app.services import device_auth_service as devices
from app.services import icd11_client_api as terms
from app.services import icd11_client_auth as clients
from app.services.icd11_postcoordination import guidance_request
from app.services.who_icd_api import WhoIcdApiTimeout, WhoIcdApiUnavailable
from tests.base import BaseTestCase

API = "/api/icd11-client/v1"
MMS = "http://id.who.int/icd/release/11/2026-01/mms"
TB = f"{MMS}/882244568/unspecified"   # 1B10.Z, a leaf
STEM = f"{MMS}/100"                    # 1B12.2, a category with one axis
LEFT = f"{MMS}/200"
CHILD = f"{MMS}/300"                   # XA3MS6
FOREIGN = f"{MMS}/400"
AXIS = "http://id.who.int/icd/schema/specificAnatomy"
QUERY = "zqxjtubercmarker"  # distinctive: must never reach a log

CODEINFO = {
    "1B10.Z": {"code": "1B10.Z", "stemId": TB},
    "1B12.2": {"code": "1B12.2", "stemId": STEM},
    "XA3MS6": {"code": "XA3MS6", "stemId": CHILD},
    "1B12.2&XA3MS6": {"code": "1B12.2&XA3MS6", "stemId": STEM, "stemCode": "1B12.2"},
}
ENTITIES = {
    TB: {"code": "1B10.Z", "title": {"@value": "Respiratory tuberculosis"}, "child": [], "parent": []},
    STEM: {
        "code": "1B12.2", "classKind": "category", "title": {"@value": "Tuberculosis of ear"},
        "definition": {"@value": "TB of the ear."},
        "postcoordinationScale": [{
            "axisName": AXIS, "requiredPostcoordination": "false",
            "allowMultipleValues": "AllowedExceptFromSameBlock", "scaleEntity": [LEFT],
        }],
        "parent": [], "child": [FOREIGN],
    },
    LEFT: {"code": "", "title": {"@value": "Inner ear"}, "parent": [], "child": [CHILD]},
    CHILD: {"code": "XA3MS6", "title": {"@value": "Cochlea"}, "parent": [LEFT], "child": []},
    FOREIGN: {"code": "1B12.20", "title": {"@value": "Foreign"}, "parent": [STEM], "child": []},
}
SEARCH = {
    "destinationEntities": [{
        "theCode": "1B10.Z", "id": TB, "title": "Respiratory <em>tuberculosis</em>",
        "postcoordinationAvailability": 0, "chapter": "01", "isLeaf": True,
    }],
    "resultChopped": False,
}
WORDS = {"words": [{"label": "tuberculosis", "dontChangeResult": False}], "wordSuggestionsChopped": False}


def _response(payload, status=200):
    response = Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    return response


def fake_who(resource, *, method="GET", query_string=b"", body=b"", content_type=None):
    """The WHO API this suite needs, keyed by resource."""
    if resource.endswith("/mms/search"):
        form = parse_qs(body.decode())
        return _response(WORDS if form.get("includeKeywordResult") == ["true"] else SEARCH)
    if "/mms/codeinfo/" in resource:
        info = CODEINFO.get(unquote(resource.rsplit("/", 1)[1]))
        return _response(info) if info else _response({}, 404)
    uri = "http://id.who.int/" + resource
    return _response(ENTITIES[uri]) if uri in ENTITIES else _response({}, 404)


@contextmanager
def who(side_effect=fake_who):
    with (
        mock.patch("app.services.who_icd_api.proxy_who_icd_request", side_effect=side_effect),
        mock.patch("app.services.icd11_postcoordination.proxy_who_icd_request", side_effect=side_effect),
        mock.patch("app.services.icd11_client_api.proxy_who_icd_request", side_effect=side_effect),
    ):
        yield


class _FreshGClient(FlaskClient):
    """Production pushes a fresh ``g`` per request; the suite's app context
    outlives requests, so drop the cached user and device session here."""

    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        g.pop("device_session", None)
        return super().open(*args, **kwargs)


class Icd11ClientApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        limiter.reset()  # in-memory buckets outlive a test
        self.row, self.token = self._issue(list(clients.SCOPES))

    def _issue(self, scopes, name="DeathNote test"):
        row, token = clients.issue_client(name, scopes, 30, self.base_admin_user)
        db.session.commit()
        return row, token

    def _post(self, path, body=None, token=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if token is not False:
            headers.setdefault("Authorization", f"Bearer {token or self.token}")
        return self.client.post(f"{API}{path}", json={"schema_version": 1, **(body or {})},
                                headers=headers, **kwargs)

    def _error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["error"]["code"], code)
        self.assertIn("message", payload["error"])
        return payload

    def _config(self, **values):
        for key, value in values.items():
            previous = self.app.config.get(key)
            self.app.config[key] = value
            self.addCleanup(self.app.config.__setitem__, key, previous)

    # -- each operation with a valid token -------------------------------------

    def test_client_identifies_the_token(self):
        response = self._post("/client")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["release"], "2026-01")
        self.assertEqual(payload["client"], {
            "name": "DeathNote test", "key_id": self.row.key_id,
            "scopes": list(clients.SCOPES), "expires_at": self.row.expires_at.isoformat(),
        })
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_search_and_words(self):
        with who():
            search = self._post("/search", {"query": "tuberculosis", "limit": 5})
            words = self._post("/words", {"query": "tuber"})
        self.assertEqual(search.status_code, 200, search.get_data(as_text=True))
        payload = search.get_json()
        self.assertEqual(payload["release"], "2026-01")
        self.assertEqual(payload["items"][0]["code"], "1B10.Z")
        self.assertEqual(payload["items"][0]["browser_url"],
                         "https://icd.who.int/browse/2026-01/mms/en#882244568%2Funspecified")
        self.assertFalse(payload["truncated"])
        self.assertEqual(words.status_code, 200)
        self.assertEqual(words.get_json(), {
            "schema_version": 1, "release": "2026-01", "words": ["tuberculosis"], "truncated": False,
        })

    def test_lookup_and_details(self):
        with who():
            lookup = self._post("/codes/lookup", {"code": "1B10.Z"})
            expression = self._post("/codes/lookup", {"code": "1B12.2&XA3MS6"})
            missing = self._post("/codes/lookup", {"code": "ZZ99"})
            details = self._post("/codes/details", {"code": "1B12.2"})
            missing_details = self._post("/codes/details", {"code": "ZZ99"})
            missing_expression = self._post("/codes/details", {"code": "ZZ99&XA3MS6"})
            expression_details = self._post("/codes/details", {"code": "1B12.2&XA3MS6"})
        self.assertEqual(lookup.status_code, 200, lookup.get_data(as_text=True))
        item = lookup.get_json()["item"]
        self.assertEqual(lookup.get_json()["release"], "2026-01")
        self.assertEqual((item["code"], item["uri"], item["leaf"]), ("1B10.Z", TB, True))
        self.assertEqual(item["browser_url"], "https://icd.who.int/browse/2026-01/mms/en#882244568%2Funspecified")
        # An expression's URI is the expression; its browser link is its stem's page.
        expression_item = expression.get_json()["item"]
        self.assertEqual(expression_item["uri"], f"{STEM} & {CHILD}")
        self.assertIsNone(terms.browser_url(expression_item["uri"]))
        self.assertEqual(expression_item["browser_url"], "https://icd.who.int/browse/2026-01/mms/en#100")
        self._error(missing, 404, "CODE_NOT_FOUND")
        self.assertEqual(details.status_code, 200, details.get_data(as_text=True))
        self.assertEqual(details.get_json()["definition"], "TB of the ear.")
        self.assertEqual(details.get_json()["browser_url"], "https://icd.who.int/browse/2026-01/mms/en#100")
        self._error(missing_details, 404, "CODE_NOT_FOUND")
        self._error(missing_expression, 404, "CODE_NOT_FOUND")
        # An expression's details are its stem's.
        self.assertEqual(expression_details.get_json()["selected"]["code"], "1B12.2")

    def test_postcoordination_axes_and_values(self):
        with who():
            axes = self._post("/postcoordination/axes", {"code": "1B12.2"})
            values = self._post("/postcoordination/values",
                                {"stem_code": "1B12.2", "axis_id": "specificAnatomy", "parent_uri": LEFT})
            outside = self._post("/postcoordination/values",
                                 {"stem_code": "1B12.2", "axis_id": "specificAnatomy", "parent_uri": FOREIGN})
        self.assertEqual(axes.status_code, 200, axes.get_data(as_text=True))
        payload = axes.get_json()
        self.assertEqual(payload["release"], "2026-01")
        self.assertEqual(payload["axes"][0]["id"], "specificAnatomy")
        self.assertEqual(payload["stem"]["browser_url"], "https://icd.who.int/browse/2026-01/mms/en#100")
        self.assertEqual(values.status_code, 200, values.get_data(as_text=True))
        self.assertEqual([option["code"] for option in values.get_json()["items"]], ["XA3MS6"])
        # A PostcoordinationError keeps its own code and status.
        self._error(outside, 422, "INVALID_PARENT")

    def test_validate_expression(self):
        with who():
            valid = self._post("/expressions/validate", {"code": "1B10.Z"})
            category = self._post("/expressions/validate", {"code": "1B12.2&XA3MS6"})
            missing = self._post("/expressions/validate", {"code": "ZZ99"})
            repeated = self._post("/expressions/validate", {"code": "1B12.2&1B12.2"})
            invalid = self._post("/expressions/validate", {"code": "not a code"})
        self.assertEqual(valid.status_code, 200, valid.get_data(as_text=True))
        payload = valid.get_json()
        self.assertEqual((payload["release"], payload["valid"], payload["certificate_refusal"]),
                         ("2026-01", True, None))
        self.assertEqual(payload["item"]["browser_url"],
                         "https://icd.who.int/browse/2026-01/mms/en#882244568%2Funspecified")
        not_final = category.get_json()
        self.assertTrue(not_final["valid"])
        self.assertEqual(not_final["certificate_refusal"]["code"], "NOT_CERTIFIABLE")
        self.assertEqual(missing.get_json()["valid"], False)
        self.assertEqual(missing.get_json()["refusal"]["code"], "CODE_NOT_FOUND")
        self.assertEqual(repeated.get_json()["refusal"]["code"], "REPEATED_PART")
        self._error(invalid, 422, "INVALID_INPUT")

    # -- scopes and token states ---------------------------------------------

    def test_each_scope_is_required(self):
        calls = {
            "icd11:search": [("/search", {"query": "tuberculosis"}), ("/words", {"query": "tuber"})],
            "icd11:lookup": [("/codes/lookup", {"code": "1B10.Z"}), ("/codes/details", {"code": "1B10.Z"})],
            "icd11:postcoordination": [
                ("/postcoordination/axes", {"code": "1B12.2"}),
                ("/postcoordination/values", {"stem_code": "1B12.2", "axis_id": "specificAnatomy",
                                              "parent_uri": LEFT}),
            ],
            "icd11:validate": [("/expressions/validate", {"code": "1B10.Z"})],
        }
        for scope, requests in calls.items():
            others = [s for s in clients.SCOPES if s != scope]
            _row, without = self._issue(others, name=f"No {scope}")
            _row, only = self._issue([scope], name=f"Only {scope}")
            for path, body in requests:
                with self.subTest(scope=scope, path=path), who():
                    self.assertEqual(self._post(path, body, token=only).status_code, 200)
                    self._error(self._post(path, body, token=without), 403, "INSUFFICIENT_SCOPE")
        # Any valid token may call /client.
        self.assertEqual(self._post("/client", token=only).status_code, 200)

    def test_missing_malformed_unknown_expired_and_revoked_tokens(self):
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer garbage"},
                        {"Authorization": f"Bearer dvicd_{self.row.key_id}_{'A' * 43}"}):
            with self.subTest(headers=headers):
                response = self._post("/client", token=False, headers=dict(headers))
                self._error(response, 401, "INVALID_TOKEN")
                self.assertEqual(response.headers["WWW-Authenticate"], 'Bearer error="invalid_token"')
        self.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.session.commit()
        expired = self._post("/client")
        self._error(expired, 401, "TOKEN_EXPIRED")
        self.assertIn("WWW-Authenticate", expired.headers)
        clients.revoke_client(self.row.id, self.base_admin_user)
        db.session.commit()
        self._error(self._post("/client"), 401, "TOKEN_REVOKED")

    def test_revocation_by_another_worker_holds_on_the_next_request(self):
        self.assertEqual(self._post("/client").status_code, 200)
        db.session.refresh(self.row)
        # Another worker: its own session (on the class connection, the only
        # one that sees the class transaction) commits the revocation; this
        # session's identity map is not told.
        other = Session(bind=db.session.connection(), join_transaction_mode="create_savepoint")
        other.execute(sa.update(AuthIcd11ApiClient)
                      .where(AuthIcd11ApiClient.id == self.row.id)
                      .values(revoked_at=datetime.now(UTC), revoked_by=self.base_admin_user.user_id))
        other.commit()
        other.close()
        # Present first: this session still holds the row as live.
        self.assertIsNone(self.row.revoked_at)
        self._error(self._post("/client"), 401, "TOKEN_REVOKED")

    def test_last_used_is_set_on_first_use_and_not_rewritten_within_a_minute(self):
        self.assertIsNone(self.row.last_used_at)
        self.assertEqual(self._post("/client").status_code, 200)
        db.session.refresh(self.row)
        first = self.row.last_used_at
        self.assertIsNotNone(first)
        self.assertEqual(self._post("/client").status_code, 200)
        db.session.refresh(self.row)
        self.assertEqual(self.row.last_used_at, first)

    # -- isolation -------------------------------------------------------------

    def _device_token(self, user):
        project_id = self.BASE_PROJECT_ID
        _row, code = devices.create_enrolment_code(project_id, actor=self.base_admin_user)
        device, _secret = devices.enrol_device(code, device_name="icdclient", platform="android",
                                               app_version="0.1.0")
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=user.user_id,
            user_session_version=user.auth_session_version or 0, created_at=datetime.now(UTC),
        )
        issued = devices._issue(session)
        db.session.add(session)
        db.session.commit()
        return issued.access_token

    def test_a_device_token_is_refused_on_the_client_api(self):
        access = self._device_token(self.base_coder_user)
        # Present first: the device token works where it belongs.
        self.assertEqual(self.client.get("/api/v1/me/access",
                                         headers={"Authorization": f"Bearer {access}"}).status_code, 200)
        self._error(self._post("/client", token=access), 401, "INVALID_TOKEN")

    def test_a_client_token_is_refused_on_the_device_api(self):
        self.assertEqual(self._post("/client").status_code, 200)
        response = self.client.get("/api/v1/me/access", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(response.status_code, 401)

    def test_an_admin_browser_session_grants_nothing(self):
        self._login(self.base_admin_id)
        # Present first: the session is a working admin session.
        self.assertEqual(self.client.get("/admin/api/icd11-api-clients").status_code, 200)
        response = self._post("/client", token=False)
        self._error(response, 401, "INVALID_TOKEN")
        self.assertNotIn("Set-Cookie", response.headers)

    def test_a_session_cookie_beside_a_valid_token_is_ignored(self):
        self._config(AUTHZ_ENFORCE_CONSULTED=True)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get("/admin/api/icd11-api-clients").status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("_user_id"))
        from flask import session
        from flask_login import current_user

        seen, limits = [], []

        def spy(client, scope):
            seen.append((current_user.is_authenticated, session.get("_user_id")))
            session["icd11_probe"] = "written"  # must never reach a cookie
            limits.extend(limit.key for limit in limiter.current_limits)
            return clients.require_scope(client, scope)

        with mock.patch("app.routes.icd11_client_api.require_scope", side_effect=spy), who():
            response = self._post("/search", {"query": "tuberculosis"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertNotIn("Set-Cookie", response.headers)
        # Inside the view the cookie's session is unread and the user anonymous.
        self.assertEqual(seen, [(False, None)])
        # Only the API's two shared limits applied, not the app's defaults.
        self.assertEqual(len(limits), 2, limits)
        self.assertTrue(any("icd11_client_ip" in key for key in limits), limits)
        self.assertTrue(any("icd11_client_token" in key for key in limits), limits)

    # -- rate limits and capacity --------------------------------------------

    def test_default_per_token_limit_is_120_per_minute(self):
        # Owner decision 2026-11-27: 120 requests a minute per token.
        from config import Config

        self.assertEqual(Config.ICD11_CLIENT_RATE_LIMIT, "120 per minute")
        self._config(ICD11_CLIENT_RATE_LIMIT="")
        with self.app.test_request_context():
            from app.routes.icd11_client_api import _token_rate_limit

            self.assertEqual(_token_rate_limit(), "120 per minute")

    def test_one_token_is_limited_without_touching_another(self):
        self._config(ICD11_CLIENT_RATE_LIMIT="2 per minute", ICD11_CLIENT_IP_RATE_LIMIT="100 per minute")
        _row, second = self._issue(["icd11:search"], name="Second app")
        # One bucket across operations, not one per endpoint.
        self.assertEqual(self._post("/client").status_code, 200)
        with who():
            self.assertEqual(self._post("/words", {"query": "tuber"}).status_code, 200)
        limited = self._post("/client")
        self._error(limited, 429, "RATE_LIMITED")
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)
        self.assertEqual(self._post("/client", token=second).status_code, 200)

    def test_forged_secret_behind_a_real_key_id_cannot_spend_its_bucket(self):
        self._config(ICD11_CLIENT_RATE_LIMIT="2 per minute", ICD11_CLIENT_IP_RATE_LIMIT="100 per minute")
        self.assertEqual(self._post("/client").status_code, 200)
        key_id = self.token.split("_")[1]
        forged = f"dvicd_{key_id}_{'A' * 43}"
        self.assertNotEqual(forged, self.token)
        for _ in range(2):
            self._error(self._post("/client", token=forged), 401, "INVALID_TOKEN")
        # The forged token spent a bucket of its own, not the real holder's.
        self._error(self._post("/client", token=forged), 429, "RATE_LIMITED")
        # The real holder still has the second of its two calls.
        self.assertEqual(self._post("/client").status_code, 200)
        self._error(self._post("/client"), 429, "RATE_LIMITED")

    def test_garbage_tokens_from_one_ip_hit_the_ip_limit(self):
        self._config(ICD11_CLIENT_RATE_LIMIT="100 per minute", ICD11_CLIENT_IP_RATE_LIMIT="3 per minute")
        for index in range(3):
            self._error(self._post("/client", token=f"garbage-{index}"), 401, "INVALID_TOKEN")
        self._error(self._post("/client", token="garbage-again"), 429, "RATE_LIMITED")
        # The IP limit covers valid tokens from that IP too.
        self._error(self._post("/client"), 429, "RATE_LIMITED")

    def test_guidance_busy_when_the_client_slots_are_taken(self):
        held = []
        try:
            for _ in range(4):
                slot = terms.client_slot()
                slot.__enter__()
                held.append(slot)
            with who():
                busy = self._post("/search", {"query": "tuberculosis"})
                # The coders' slots are unaffected.
                with guidance_request():
                    pass
        finally:
            for slot in reversed(held):
                slot.__exit__(None, None, None)
        payload = self._error(busy, 429, "GUIDANCE_BUSY")
        self.assertNotEqual(payload["error"]["code"], "RATE_LIMITED")

    # -- upstream failures and bounded input ---------------------------------

    def test_who_unavailable_or_timed_out_is_503(self):
        for failure in (WhoIcdApiUnavailable("down"), WhoIcdApiTimeout("slow")):
            with self.subTest(failure=type(failure).__name__), who(side_effect=failure):
                self._error(self._post("/search", {"query": "tuberculosis"}), 503, "WHO_UNAVAILABLE")
                self._error(self._post("/codes/lookup", {"code": "1B10.Z"}), 503, "WHO_UNAVAILABLE")
                self._error(self._post("/postcoordination/axes", {"code": "1B12.2"}), 503, "WHO_UNAVAILABLE")

    def test_bounded_input(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        big = self.client.post(f"{API}/search", headers=headers, content_type="application/json",
                               data=json.dumps({"schema_version": 1, "query": "x" * 9000}))
        self._error(big, 413, "PAYLOAD_TOO_LARGE")
        not_json = self.client.post(f"{API}/search", headers=headers, data="query=tb",
                                    content_type="application/x-www-form-urlencoded")
        self._error(not_json, 400, "MALFORMED_JSON")
        broken = self.client.post(f"{API}/search", headers=headers, data="{",
                                  content_type="application/json")
        self._error(broken, 400, "MALFORMED_JSON")
        for body in ({"query": "tuberculosis", "extra": 1}, {"query": "t"}, {"query": "x" * 81},
                     {"query": "tuberculosis", "limit": 0}, {"query": "tuberculosis", "limit": 21},
                     {"query": "tuberculosis", "limit": True},
                     {"query": "tuberculosis", "subtree_uris": ["https://evil.example/"]},
                     {"query": 12}, {}):
            with self.subTest(body=body):
                self._error(self._post("/search", body), 422, "INVALID_INPUT")
        wrong_version = self.client.post(f"{API}/client", headers=headers, json={"schema_version": 2})
        self._error(wrong_version, 422, "INVALID_INPUT")
        self._error(self._post("/codes/lookup", {"code": "x" * 129}), 422, "INVALID_INPUT")
        self._error(self._post("/postcoordination/values",
                               {"stem_code": "1B12.2", "axis_id": 1, "parent_uri": LEFT}), 422, "INVALID_INPUT")

    def test_unknown_path_and_wrong_method_answer_json(self):
        wrong_method = self.client.get(f"{API}/search", headers={"Authorization": f"Bearer {self.token}"})
        self._error(wrong_method, 405, "METHOD_NOT_ALLOWED")
        unknown = self._post("/nothing-here")
        self._error(unknown, 404, "NOT_FOUND")
        self.assertEqual(unknown.headers["Cache-Control"], "no-store")

    def test_an_unexpected_error_is_a_generic_500(self):
        with mock.patch("app.routes.icd11_client_api.search_terms", side_effect=RuntimeError("secret detail")):
            response = self._post("/search", {"query": "tuberculosis"})
        payload = self._error(response, 500, "INTERNAL_ERROR")
        self.assertNotIn("secret detail", json.dumps(payload))

    # -- the token never leaves its issuance response ------------------------

    def test_no_token_query_or_header_reaches_the_logs(self):
        lines = []

        class Capture(logging.Handler):
            def emit(self, record):
                lines.append(record.getMessage())

        handler = Capture(logging.DEBUG)
        loggers = [logging.getLogger()] + [
            logger for logger in logging.Logger.manager.loggerDict.values()
            if isinstance(logger, logging.Logger) and not logger.propagate
        ]
        for logger in loggers:
            logger.addHandler(handler)
            self.addCleanup(logger.removeHandler, handler)

        self._login(self.base_admin_id)
        issued = self.client.post("/admin/api/icd11-api-clients", headers=self._csrf_headers(),
                                  json={"name": "Logged app", "scopes": ["icd11:search"]})
        self.assertEqual(issued.status_code, 201)
        token = issued.get_json()["token"]
        with who():
            used = self._post("/search", {"query": QUERY}, token=token)
            self.assertEqual(used.status_code, 200)
            self._post("/search", {"query": QUERY}, token=token + "x")
        self._login(self.base_admin_id)
        client_id = issued.get_json()["client"]["id"]
        revoked = self.client.post(f"/admin/api/icd11-api-clients/{client_id}/revoke",
                                   headers=self._csrf_headers())
        self.assertEqual(revoked.status_code, 200)

        text = "\n".join(lines)
        # Present first: the request log saw the client API call and its keys.
        self.assertIn(f"path={API}/search", text)
        # The logger never parses this namespace's body (8 KiB cap is the API's).
        self.assertIn(f"path={API}/search query= payload=-", text)
        for secret in (token, token.rsplit("_", 1)[1], f"Bearer {token}", QUERY):
            self.assertNotIn(secret, text)
