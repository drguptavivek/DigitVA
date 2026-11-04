"""Dedicated-Redis cache around proxy_who_icd_request: what is and is not cached."""

import json
import pickle
from unittest.mock import patch

import requests
from requests import Response

from app.services import who_icd_api
from app.services.who_icd_api import (
    WhoIcdApiUnavailable,
    WhoIcdApiTimeout,
    post_mortality_processor,
    proxy_who_icd_request,
)
from tests.base import BaseTestCase

_REAL_CLIENT = who_icd_api._cache_client
SEARCH = "icd/release/11/2026-01/mms/search"
ENTITY = "icd/entity/123"


def _upstream(status=200, payload=b'{"ok":true}'):
    response = Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    response.headers["API-Version"] = "v2"
    response.raw = type(
        "Raw", (), {"read": lambda self, n: payload, "close": lambda self: None}
    )()
    return response


class _FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttls[key] = ex

    def clear(self):
        self.data.clear()


class _BrokenRedis:
    def get(self, key):
        raise RuntimeError("redis down")

    def set(self, *args, **kwargs):
        raise RuntimeError("redis down")


class TestWhoIcdApiCache(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["ICD11_API_CACHE_TIMEOUT"] = 3600
        self.app.config["ICD11_API_CACHE_REDIS_URL"] = "redis://fake/0"
        self.cache = _FakeRedis()
        patcher = patch.object(who_icd_api, "_cache_client", lambda: self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_get_is_served_from_cache(self):
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            first = proxy_who_icd_request(ENTITY, query_string=b"q=a")
            second = proxy_who_icd_request(ENTITY, query_string=b"q=a")
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(second.status_code, first.status_code)
        self.assertEqual(second.content, b'{"ok":true}')
        self.assertEqual(second.json(), {"ok": True})
        self.assertEqual(second.headers["API-Version"], "v2")
        self.assertEqual(second.headers["Content-Type"], "application/json")
        self.assertEqual(list(self.cache.ttls.values()), [3600])

    def test_stored_value_is_json_not_pickle(self):
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream(200, b"\xff\x00bin")
            first = proxy_who_icd_request(ENTITY)
            second = proxy_who_icd_request(ENTITY)
        (raw,) = self.cache.data.values()
        self.assertEqual(json.loads(raw)["status"], 200)
        with self.assertRaises(Exception):
            pickle.loads(raw)
        self.assertEqual(second.content, first.content)
        self.assertEqual(mock.call_count, 1)

    def test_empty_redis_url_turns_cache_off(self):
        self.app.config["ICD11_API_CACHE_REDIS_URL"] = ""
        with patch.object(who_icd_api, "_cache_client", _REAL_CLIENT), patch(
            "app.services.who_icd_api.requests.request"
        ) as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            proxy_who_icd_request(ENTITY)
            proxy_who_icd_request(ENTITY)
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(self.cache.data, {})

    def test_different_query_or_resource_misses(self):
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            proxy_who_icd_request(ENTITY, query_string=b"q=a")
            proxy_who_icd_request(ENTITY, query_string=b"q=b")
            proxy_who_icd_request("icd/entity/456", query_string=b"q=a")
        self.assertEqual(mock.call_count, 3)

    def test_404_is_cached(self):
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream(404, b"{}")
            proxy_who_icd_request(ENTITY)
            second = proxy_who_icd_request(ENTITY)
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(second.status_code, 404)

    def test_errors_are_not_cached(self):
        for outcome in (
            _upstream(503),
            _upstream(400),
            requests.Timeout(),
        ):
            with self.subTest(outcome=repr(outcome)):
                self.cache.clear()
                with patch("app.services.who_icd_api.requests.request") as mock:
                    mock.side_effect = [outcome, _upstream()]
                    try:
                        proxy_who_icd_request(ENTITY)
                    except (WhoIcdApiUnavailable, WhoIcdApiTimeout):
                        pass
                    result = proxy_who_icd_request(ENTITY)
                self.assertEqual(mock.call_count, 2)
                self.assertEqual(result.status_code, 200)

    def test_search_post_is_cached_by_body_and_ignores_multipart_boundary(self):
        def body(boundary, term):
            return (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"q\"\r\n\r\n"
                f"{term}\r\n--{boundary}--\r\n"
            ).encode()

        def post(boundary, term):
            return proxy_who_icd_request(
                SEARCH,
                method="POST",
                body=body(boundary, term),
                content_type=f"multipart/form-data; boundary={boundary}",
            )

        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            post("----A1", "cough")
            post("----B2", "cough")
            self.assertEqual(mock.call_count, 1)
            post("----C3", "fever")
            self.assertEqual(mock.call_count, 2)

    def test_search_terms_repeat_hits_cache_and_errors_do_not(self):
        from app.services.icd11_postcoordination import search_terms

        payload = b'{"destinationEntities": [], "resultChopped": false}'
        subtree = ["http://id.who.int/icd/entity/1234"]
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream(200, payload)
            search_terms("sepsis")
            search_terms("sepsis")
            self.assertEqual(mock.call_count, 1)
            search_terms("malaria")
            search_terms("sepsis", subtree_uris=subtree)
            self.assertEqual(mock.call_count, 3)
        self.cache.clear()
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = [_upstream(503), _upstream(200, payload)]
            with self.assertRaises(WhoIcdApiUnavailable):
                search_terms("sepsis")
            search_terms("sepsis")
            self.assertEqual(mock.call_count, 2)

    def test_other_post_is_never_cached(self):
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            for _ in range(2):
                proxy_who_icd_request(
                    "icd/release/11/2026-01/mms/other",
                    method="POST",
                    body=b"x=1",
                    content_type="application/x-www-form-urlencoded",
                )
        self.assertEqual(mock.call_count, 2)

    def test_mortality_processor_is_never_cached(self):
        with patch("app.services.who_icd_api.requests.post") as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            post_mortality_processor("doris", {"a": 1})
            post_mortality_processor("doris", {"a": 1})
        self.assertEqual(mock.call_count, 2)

    def test_timeout_zero_turns_cache_off(self):
        self.app.config["ICD11_API_CACHE_TIMEOUT"] = 0
        with patch("app.services.who_icd_api.requests.request") as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            proxy_who_icd_request(ENTITY)
            proxy_who_icd_request(ENTITY)
        self.assertEqual(mock.call_count, 2)

    def test_cache_backend_error_falls_through(self):
        with patch.object(who_icd_api, "_cache_client", lambda: _BrokenRedis()), patch(
            "app.services.who_icd_api.requests.request"
        ) as mock:
            mock.side_effect = lambda *a, **k: _upstream()
            result = proxy_who_icd_request(ENTITY)
            proxy_who_icd_request(ENTITY)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock.call_count, 2)

    def test_validation_runs_before_lookup(self):
        with self.assertRaises(ValueError):
            proxy_who_icd_request("admin/secret")
