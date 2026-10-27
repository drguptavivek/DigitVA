"""Suggestions search: in-process fallback, Typesense request shape, role filter."""

import json
import os
from unittest import mock

import requests

from app import db
from app.models.mas_va_cause_definitions import MasVaCauseDefinition
from app.services import ai_search_service as svc
from tests.base import BaseTestCase

NO_TYPESENSE = {"TYPESENSE_HOST": "", "TYPESENSE_API_KEY": ""}
WITH_TYPESENSE = {
    "TYPESENSE_HOST": "ts.test", "TYPESENSE_PORT": "8108", "TYPESENSE_API_KEY": "k",
}


def titles(results):
    return [r["title"] for r in results]


class AiSearchFallbackTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        svc.clear_fallback_cache()
        patcher = mock.patch.dict(os.environ, NO_TYPESENSE)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(svc.clear_fallback_cache)

    def test_misspelled_help_title_finds_the_page(self):
        results = svc.search(self.base_coder_user, "pasword resett")
        self.assertIn("Password Reset", titles(results))
        hit = next(r for r in results if r["title"] == "Password Reset")
        self.assertEqual((hit["kind"], hit["url"]), ("help", "/help/password-reset"))

    def test_admin_only_page_is_hidden_from_a_coder(self):
        self.assertIn("Admin Panel Overview", titles(svc.search(self.base_admin_user, "admin panel overview")))
        self.assertNotIn("Admin Panel Overview", titles(svc.search(self.base_coder_user, "admin panel overview")))

    def test_va_definition_found_by_typo_of_its_title(self):
        db.session.add(MasVaCauseDefinition(
            va_code="VAs-77.77", title="Zygomatic sarcoidosis",
            definition_html="<p>A <b>rare</b> condition.</p>",
        ))
        db.session.flush()
        svc.clear_fallback_cache()

        results = svc.search(self.base_admin_user, "zygomatik sarcoidosis")

        hit = next(r for r in results if r["kind"] == "va_definition")
        self.assertEqual(hit["url"], "/help/va-definitions")
        self.assertIn("rare", hit["snippet"])
        self.assertNotIn("<b>", hit["snippet"])

    def test_short_query_returns_nothing(self):
        self.assertEqual(svc.search(self.base_coder_user, "a"), [])


class AiSearchTypesenseTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        svc.clear_fallback_cache()
        patcher = mock.patch.dict(os.environ, WITH_TYPESENSE)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(svc.clear_fallback_cache)

    def test_request_filters_to_the_users_roles_and_own_saved_queries(self):
        reply = mock.Mock()
        reply.json.return_value = {"hits": [{"document": {
            "kind": "help", "title": "T", "url": "/help/x", "body": "b" * 300}}]}
        with mock.patch("app.services.ai_search_service.requests.request", return_value=reply) as call:
            results = svc.search(self.base_coder_user, "turnaround")

        self.assertEqual(results[0]["url"], "/help/x")
        self.assertTrue(results[0]["snippet"].endswith("..."))
        args, kwargs = call.call_args
        self.assertEqual(args[0], "GET")
        self.assertTrue(args[1].startswith("http://ts.test:8108/collections/digitva_search/"))
        self.assertEqual(kwargs["timeout"], (0.5, 1))
        params = kwargs["params"]
        self.assertEqual((params["num_typos"], params["prefix"]), (2, "true"))
        self.assertEqual(params["query_by"], "title,keywords,body")
        self.assertIn("`authenticated`", params["filter_by"])
        self.assertIn("`public`", params["filter_by"])
        self.assertNotIn("`admin`", params["filter_by"])
        self.assertIn(f"owner_user_id:=`{self.base_coder_id}`", params["filter_by"])

    def test_admin_filter_carries_the_admin_and_page_roles(self):
        reply = mock.Mock()
        reply.json.return_value = {"hits": []}
        with mock.patch("app.services.ai_search_service.requests.request", return_value=reply) as call:
            svc.search(self.base_admin_user, "overview")
        filter_by = call.call_args.kwargs["params"]["filter_by"]
        self.assertIn("`admin`", filter_by)
        self.assertIn("`coder`", filter_by)

    def test_typesense_error_uses_the_fallback(self):
        with mock.patch(
            "app.services.ai_search_service.requests.request",
            side_effect=requests.ConnectionError("down"),
        ):
            results = svc.search(self.base_coder_user, "password reset")
        self.assertIn("Password Reset", titles(results))


class AiSearchCatalogAndSavedQueryTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        svc.clear_fallback_cache()
        self.addCleanup(svc.clear_fallback_cache)

    def test_catalog_questions_are_found_by_data_managers_only(self):
        from app.services.ai_analytics_catalog import load_catalog

        entry = next(e for e in load_catalog() if e["key"] == "top_causes_neonates")
        with mock.patch.dict(os.environ, NO_TYPESENSE):
            admin_hits = svc.search(self.base_admin_user, "neonatl deaths causes")
            coder_hits = svc.search(self.base_coder_user, "neonatl deaths causes")
        hit = next(r for r in admin_hits if r["kind"] == "catalog")
        self.assertEqual(hit["title"], entry["question"])
        self.assertEqual(hit["url"], "/data-management/ai-questions?catalog=top_causes_neonates")
        self.assertNotIn("catalog", [r["kind"] for r in coder_hits])

    def test_reindex_includes_every_saved_query_and_drops_stale_documents(self):
        from app.models.va_ai_analytics import VaAiSavedQuery

        saved = VaAiSavedQuery(owner_user_id=self.base_admin_user.user_id, title="Weekly deaths",
                               description="by site", original_prompt="q", validated_sql="SELECT 1 AS one",
                               layout_recipe={"type": "table"})
        db.session.add(saved)
        db.session.flush()
        calls = []

        def fake_call(method, path, **kwargs):
            calls.append((method, path, kwargs))
            reply = mock.Mock()
            reply.text = ""
            return reply

        with mock.patch.dict(os.environ, WITH_TYPESENSE), mock.patch.object(svc, "_call", side_effect=fake_call):
            svc.reindex_all()
        imported = [json.loads(line) for m, p, kw in calls if p.endswith("/import")
                    for line in kw["data"].decode().splitlines()]
        doc = next(d for d in imported if d["id"] == f"saved_query:{saved.id}")
        self.assertEqual((doc["title"], doc["keywords"], doc["owner_user_id"]),
                         ("Weekly deaths", "by site", str(self.base_admin_user.user_id)))
        self.assertEqual(doc["url"], f"/data-management/ai-questions?saved={saved.id}")
        delete_filter = next(kw["params"]["filter_by"] for m, p, kw in calls if m == "DELETE")
        self.assertIn(f"`saved_query:{saved.id}`", delete_filter)
        self.assertNotIn("kind:", delete_filter)

    def test_saved_query_index_calls_are_skipped_without_typesense(self):
        with mock.patch.dict(os.environ, NO_TYPESENSE), \
                mock.patch("app.services.ai_search_service.requests.request") as request:
            svc.upsert_saved_query(1, self.base_admin_user.user_id, "t")
            svc.delete_saved_query(1)
        request.assert_not_called()
