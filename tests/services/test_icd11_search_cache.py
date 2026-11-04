"""Redis cache around search_icd11_mms: hits, data-version misses, fall-through."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app import db
from app.commands.icd11 import icd11_group
from app.models import MasIcd11Mms
from app.services import icd11_mms_service
from app.services.icd11_mms_service import SEARCH_CACHE_PREFIX, search_icd11_mms
from app.services.icd_search_vocabulary_service import clear_cache, create_term
from tests.base import BaseTestCase


class _FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttls[key] = ex

    def scan_iter(self, match=None, count=None):
        prefix = match.rstrip("*")
        return [k for k in list(self.data) if k.startswith(prefix)]

    def delete(self, *keys):
        return sum(self.data.pop(k, None) is not None for k in keys)


class _BrokenRedis:
    def get(self, key):
        raise RuntimeError("redis down")

    def set(self, *args, **kwargs):
        raise RuntimeError("redis down")


def _row(code, title):
    return MasIcd11Mms(
        release="2026-01",
        linearization_uri=f"lin:{code}",
        code=code,
        title=title,
        class_kind="category",
        depth_in_kind=2,
        is_residual=False,
        is_leaf=True,
        is_coding_selectable=True,
        sex_selectable="both",
        age_group_selectable="all",
        source_version="ICD-11-MMS-2026-01",
        source_path="test",
        is_active=True,
    )


class TestIcd11SearchCache(BaseTestCase):
    def setUp(self):
        super().setUp()
        clear_cache()
        self.addCleanup(clear_cache)
        self.app.config["ICD11_API_CACHE_TIMEOUT"] = 3600
        self.app.config["ICD11_API_CACHE_REDIS_URL"] = "redis://fake/0"
        self.cache = _FakeRedis()
        patcher = patch.object(icd11_mms_service, "_cache_client", lambda: self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.row = _row("CA40", "Pneumonia, organism unspecified")
        db.session.add(self.row)
        db.session.commit()

    def _live(self):
        return patch.object(
            icd11_mms_service,
            "_search_icd11_mms_uncached",
            wraps=icd11_mms_service._search_icd11_mms_uncached,
        )

    def test_second_search_is_served_from_cache(self):
        with self._live() as live:
            first = search_icd11_mms("pneumonia", age_group="adult", sex="female")
            second = search_icd11_mms("  Pneumonia ", age_group="adult", sex="female")
        self.assertEqual([r["icd_code"] for r in first], ["CA40"])
        self.assertEqual(live.call_count, 1)
        self.assertEqual(second, first)
        self.assertEqual(list(self.cache.ttls.values()), [3600])
        self.assertTrue(all(k.startswith(SEARCH_CACHE_PREFIX) for k in self.cache.data))

    def test_policy_edit_is_a_miss(self):
        with self._live() as live:
            first = search_icd11_mms("pneumonia", sex="female")
            self.assertEqual(len(first), 1)
            self.row.is_coding_selectable = False
            db.session.commit()
            second = search_icd11_mms("pneumonia", sex="female")
        self.assertEqual(live.call_count, 2)
        self.assertEqual(second, [])

    def test_vocabulary_edit_is_a_miss(self):
        with self._live() as live:
            self.assertEqual(len(search_icd11_mms("chest infection")), 0)
            self.assertEqual(live.call_count, 1)
            create_term(term="chest infection", icd_classification="icd11", icd_code="CA40")
            db.session.commit()
            clear_cache()
            second = search_icd11_mms("chest infection")
        self.assertEqual(live.call_count, 2)
        self.assertEqual([r["icd_code"] for r in second], ["CA40"])

    def test_age_group_and_sex_make_distinct_entries(self):
        with self._live() as live:
            search_icd11_mms("pneumonia", age_group="adult", sex="female")
            search_icd11_mms("pneumonia", age_group="child", sex="female")
            search_icd11_mms("pneumonia", age_group="adult", sex="male")
            search_icd11_mms("pneumonia")
        self.assertEqual(live.call_count, 4)
        self.assertEqual(len(self.cache.data), 4)

    def test_same_context_va_sids_share_an_entry(self):
        context = {"age_group": "adult", "sex": "male"}
        with patch.object(
            icd11_mms_service, "coding_context_for_submission", return_value=context
        ), self._live() as live:
            first = search_icd11_mms("pneumonia", va_sid="sid-1")
            second = search_icd11_mms("pneumonia", va_sid="sid-2")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, first)
        self.assertEqual(live.call_count, 1)
        self.assertEqual(len(self.cache.data), 1)

    def test_unknown_submission_still_raises(self):
        with patch.object(
            icd11_mms_service, "coding_context_for_submission", return_value=None
        ):
            with self.assertRaises(LookupError):
                search_icd11_mms("pneumonia", va_sid="missing")
        self.assertEqual(self.cache.data, {})

    def test_empty_result_is_not_cached(self):
        with self._live() as live:
            self.assertEqual(search_icd11_mms("zzzzqq"), [])
            self.assertEqual(search_icd11_mms("zzzzqq"), [])
            present = search_icd11_mms("pneumonia")
        self.assertEqual(len(present), 1)
        self.assertEqual(live.call_count, 3)
        self.assertEqual(len(self.cache.data), 1)  # only the non-empty one

    def test_redis_error_falls_through(self):
        with patch.object(icd11_mms_service, "_cache_client", lambda: _BrokenRedis()):
            results = search_icd11_mms("pneumonia")
        self.assertEqual([r["icd_code"] for r in results], ["CA40"])

    def test_timeout_zero_skips_cache(self):
        self.app.config["ICD11_API_CACHE_TIMEOUT"] = 0
        self.assertEqual(len(search_icd11_mms("pneumonia")), 1)
        self.assertEqual(self.cache.data, {})

    def test_json_round_trip_is_lossless(self):
        search_icd11_mms("pneumonia", age_group="adult")
        (raw,) = self.cache.data.values()
        cached = json.loads(raw)
        self.assertEqual(len(cached), 1)
        with patch.object(icd11_mms_service, "_cache_client", lambda: None):
            live = search_icd11_mms("pneumonia", age_group="adult")
        self.assertEqual(cached, live)
        self.assertEqual(json.loads(json.dumps(live)), live)

    def test_clear_command_deletes_only_icd_prefixes(self):
        self.cache.data.update(
            {
                f"{SEARCH_CACHE_PREFIX}a": b"1",
                f"{SEARCH_CACHE_PREFIX}b": b"1",
                "icd11api:c": b"1",
                "celery:other": b"1",
            }
        )
        with patch("app.commands.icd11._cache_client", lambda: self.cache):
            result = self.app.test_cli_runner().invoke(icd11_group, ["clear-cache"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("search: deleted 2", result.output)
        self.assertIn("api: deleted 1", result.output)
        self.assertEqual(list(self.cache.data), ["celery:other"])
