"""/data-management/ai-questions routes (digitva-qwvt): guard, CSRF, ownership,
provider choice, built-in reports, catalog, breakdown drawer, links, limits."""

import json
from types import SimpleNamespace
from unittest import mock

import sqlalchemy as sa
from flask import url_for

from app import db, limiter
from app.models.va_ai_analytics import VaAiQueryAuditLog
from app.routes.ai_questions import QUESTION_WARNING
from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_planner as planner
from app.services import ai_analytics_providers as providers
from app.services import ai_search_service
from tests.ai_analytics_fixtures import AiAnalyticsFixtures, sandbox_on_session_connection
from tests.base import BaseTestCase

SQL = "SELECT site_id, sum(n) AS deaths FROM ai_cube GROUP BY site_id ORDER BY site_id"
CHART = {"type": "bar", "x_column": "site_id", "series_columns": ["deaths"], "value_column": "deaths",
         "x_dimension": "site_id"}


class AiQuestionsRouteTests(AiAnalyticsFixtures, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_ai_fixtures()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.genai = mock.Mock()
        self.genai.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"sql": SQL, "title": "Deaths by site", "chart": CHART,
                             "follow_ups": ["Deaths by month?"]}),
            usage_metadata=None,
        )
        self.claude = mock.Mock()
        for patcher in (
            sandbox_on_session_connection(),
            mock.patch.object(providers, "_client",
                              side_effect=lambda name: self.claude if name == providers.ANTHROPIC else self.genai),
            mock.patch.dict(self.app.config, {
                "AI_ANALYTICS_ENABLED": True, "GEMINI_API_KEY": "test-key", "ANTHROPIC_API_KEY": "",
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _post(self, path, data=None):
        return self.client.post(f"/data-management/ai-questions{path}", data=data or {},
                                headers=self._csrf_headers())

    def _saved_for_dm(self):
        self._login(str(self.dm_user.user_id))
        response = self._post("/ask", {"question": "Deaths by site", "turn": "1"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        audit_id = db.session.scalar(
            sa.select(sa.func.max(VaAiQueryAuditLog.id))
            .where(VaAiQueryAuditLog.user_id == self.dm_user.user_id)
        )
        response = self._post("/saved", {"audit_id": str(audit_id), "title": "Deaths", "chart": json.dumps(CHART)})
        self.assertEqual(response.status_code, 200)
        return planner.list_saved(self.dm_user)[0]

    def test_page_shows_the_warning_to_a_data_manager(self):
        self._login(str(self.dm_user.user_id))
        response = self.client.get("/data-management/ai-questions")
        self.assertEqual(response.status_code, 200)
        self.assertIn(QUESTION_WARNING, response.get_data(as_text=True))

    def test_coder_is_refused(self):
        self._login(str(self.base_coder_user.user_id))
        self.assertEqual(self.client.get("/data-management/ai-questions").status_code, 403)
        self.assertEqual(self._post("/ask", {"question": "x"}).status_code, 403)
        self.genai.models.generate_content.assert_not_called()

    def test_post_without_csrf_is_refused(self):
        self._login(str(self.dm_user.user_id))
        response = self.client.post("/data-management/ai-questions/ask", data={"question": "x"})
        self.assertEqual(response.status_code, 400)
        self.genai.models.generate_content.assert_not_called()

    def test_ask_renders_chart_table_and_follow_up_state(self):
        self._login(str(self.dm_user.user_id))
        response = self._post("/ask", {"question": "Deaths by site", "turn": "1"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn('data-ai-chart="ai-chart-canvas"', body)
        self.assertIn("<td>AQ01</td>", body)
        self.assertNotIn("<td>AQ02</td>", body)
        self.assertIn('name="turn" value="2"', body)

    def test_ask_at_the_turn_cap_is_refused(self):
        self._login(str(self.dm_user.user_id))
        response = self._post("/ask", {"question": "More", "turn": str(planner.MAX_TURNS + 1), "previous_sql": SQL})
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most", response.get_data(as_text=True))
        self.genai.models.generate_content.assert_not_called()

    def test_other_user_cannot_run_or_delete_my_saved_query(self):
        saved = self._saved_for_dm()
        self._login(str(self.other_dm_user.user_id))
        self.assertEqual(self._post(f"/saved/{saved.id}/run").status_code, 404)
        self.assertEqual(self._post(f"/saved/{saved.id}/delete").status_code, 404)
        self.assertNotIn("Deaths", self.client.get("/data-management/ai-questions").get_data(as_text=True).split("My saved queries")[1])
        self.assertEqual([s.id for s in planner.list_saved(self.dm_user)], [saved.id])

        self._login(str(self.dm_user.user_id))
        self.assertEqual(self._post(f"/saved/{saved.id}/delete").status_code, 200)
        self.assertEqual(planner.list_saved(self.dm_user), [])

    def test_disabled_refuses_asking_but_saved_queries_run(self):
        saved = self._saved_for_dm()
        self.app.config["AI_ANALYTICS_ENABLED"] = False
        self.genai.reset_mock()

        page = self.client.get("/data-management/ai-questions").get_data(as_text=True)
        self.assertIn("AI questions are turned off", page)
        response = self._post("/ask", {"question": "Deaths by site"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("turned off", response.get_data(as_text=True))

        response = self._post(f"/saved/{saved.id}/run")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<td>AQ01</td>", response.get_data(as_text=True))
        self.genai.models.generate_content.assert_not_called()

    def test_page_offers_only_enabled_providers_default_first(self):
        self._login(str(self.dm_user.user_id))
        body = self.client.get("/data-management/ai-questions").get_data(as_text=True)
        self.assertIn('<option value="gemini">', body)
        self.assertNotIn('<option value="anthropic">', body)
        self.app.config["ANTHROPIC_API_KEY"] = "test-key"
        body = self.client.get("/data-management/ai-questions").get_data(as_text=True)
        self.assertLess(body.index('<option value="anthropic">'), body.index('<option value="gemini">'))

    def test_server_refuses_a_provider_that_is_not_enabled(self):
        self._login(str(self.dm_user.user_id))
        response = self._post("/ask", {"question": "Deaths by site", "provider": "anthropic"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("not available", response.get_data(as_text=True))
        self.claude.beta.messages.create.assert_not_called()
        self.genai.models.generate_content.assert_not_called()

    def test_answer_carries_follow_up_chips_and_drill_hook(self):
        self._login(str(self.dm_user.user_id))
        body = self._post("/ask", {"question": "Deaths by site", "provider": "gemini"}).get_data(as_text=True)
        self.assertIn('data-ai-follow-up="Deaths by month?"', body)
        self.assertIn("data-ai-drill>", body)
        self.assertIn('data-ai-drill-value="AQ01"', body)

    def test_built_in_report_and_catalog_run_without_the_model(self):
        self._login(str(self.dm_user.user_id))
        self.app.config["AI_ANALYTICS_ENABLED"] = False
        page = self.client.get("/data-management/ai-questions").get_data(as_text=True)
        self.assertIn("Workflow funnel by state", page)
        response = self._post("/builtin/cases_by_site/run")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn("<td>AQ01</td>", body)
        self.assertNotIn("<td>AQ02</td>", body)
        key = catalog.load_catalog()[0]["key"]
        self.assertEqual(self._post(f"/catalog/{key}/run").status_code, 200)
        self.assertEqual(self._post("/builtin/nope/run").status_code, 404)
        self.assertEqual(self._post("/catalog/nope/run").status_code, 404)
        self.genai.models.generate_content.assert_not_called()

    def test_breakdown_drawer_is_scoped_and_whitelisted(self):
        self._login(str(self.dm_user.user_id))
        response = self._post("/breakdown", {"column": "site_id", "value": "AQ01"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn("ready_for_coding", body)
        self.assertIn("Age band", body)
        # Site B is outside the data manager's scope: no cases.
        self.assertNotIn("ready_for_coding", self._post("/breakdown", {"column": "site_id", "value": "AQ02"})
                         .get_data(as_text=True))
        self.assertEqual(self._post("/breakdown", {"column": "va_sid", "value": "x"}).status_code, 400)

    def test_breakdown_requires_csrf(self):
        self._login(str(self.dm_user.user_id))
        response = self.client.post("/data-management/ai-questions/breakdown",
                                    data={"column": "site_id", "value": "AQ01"})
        self.assertEqual(response.status_code, 400)

    def test_search_urls_point_at_this_page(self):
        with self.app.test_request_context("/"):
            page = url_for("data_management.ai_questions_page")
        self.assertEqual(ai_search_service.AI_PAGE_URL, page)
        self.assertEqual(ai_search_service.SAVED_QUERY_URL.format(id=7), f"{page}?saved=7")
        docs = ai_search_service._catalog_docs()
        self.assertTrue(docs)
        self.assertEqual(docs[0]["url"], f"{page}?catalog={catalog.load_catalog()[0]['key']}")

    def test_saved_and_catalog_links_run_once_on_load(self):
        saved = self._saved_for_dm()
        page = self.client.get(f"/data-management/ai-questions?saved={saved.id}").get_data(as_text=True)
        self.assertIn(f'hx-post="/data-management/ai-questions/saved/{saved.id}/run"', page)
        self.assertIn('hx-trigger="load"', page)
        self.assertIn("history.replaceState", page)
        key = catalog.load_catalog()[0]["key"]
        page = self.client.get(f"/data-management/ai-questions?catalog={key}").get_data(as_text=True)
        self.assertIn(f'hx-post="/data-management/ai-questions/catalog/{key}/run"', page)
        for junk in ("?saved=abc", "?catalog=nope", "?saved=1%20OR%201=1"):
            with self.subTest(junk):
                body = self.client.get(f"/data-management/ai-questions{junk}").get_data(as_text=True)
                self.assertNotIn('hx-trigger="load"', body)
        # Another user's link runs nothing of mine.
        self._login(str(self.other_dm_user.user_id))
        self.assertEqual(self._post(f"/saved/{saved.id}/run").status_code, 404)

    def test_ask_is_rate_limited(self):
        self._login(str(self.base_admin_user.user_id))
        headers = {**self._csrf_headers(), "HX-Request": "true"}
        responses = [
            self.client.post("/data-management/ai-questions/ask", data={"question": "Deaths by site"},
                             headers=headers)
            for _ in range(11)
        ]
        self.assertEqual([r.status_code for r in responses[:10]], [200] * 10)
        self.assertEqual(responses[10].status_code, 429)
        self.assertIn("Too many requests", responses[10].get_data(as_text=True))
        self.assertEqual(self.genai.models.generate_content.call_count, 10)
