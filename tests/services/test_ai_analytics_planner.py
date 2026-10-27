"""AI analytics planner: providers, quota, turn cap, retry, saved reruns,
built-in reports and catalog (digitva-qwvt).

Both provider clients are mocked (``providers._client``); the sandbox runs
for real on the session's connection (tests/ai_analytics_fixtures.py).
"""

import json
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx2
import requests
import sqlalchemy as sa

from app import db
from app.models.va_ai_analytics import AI_MODE_LLM, AI_MODE_SAVED_RERUN, VaAiQueryAuditLog
from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_planner as planner
from app.services import ai_analytics_providers as providers
from app.services import ai_analytics_sandbox as sandbox
from app.services.ai_analytics_render import render
from tests.ai_analytics_fixtures import AiAnalyticsFixtures, sandbox_on_session_connection
from tests.base import BaseTestCase

GOOD_SQL = "SELECT site_id, sum(n) AS deaths FROM ai_cube GROUP BY site_id ORDER BY site_id"
CHART = {"type": "bar", "x_column": "site_id", "series_columns": ["deaths"], "value_column": "deaths",
         "x_dimension": "site_id"}
FOLLOW_UPS = ["By month?", "By sex?", "By age band?", "One too many"]


def _plan_json(sql):
    return json.dumps({"sql": sql, "title": "Deaths by site", "chart": CHART, "follow_ups": FOLLOW_UPS})


def _claude_response(sql, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason, model="claude-sonnet-5-5",
        content=[SimpleNamespace(type="fallback"), SimpleNamespace(type="text", text=_plan_json(sql))],
        usage=SimpleNamespace(input_tokens=120, cache_read_input_tokens=1500, output_tokens=60),
    )


def _response(sql):
    return SimpleNamespace(
        text=_plan_json(sql),
        usage_metadata=SimpleNamespace(
            prompt_token_count=900, cached_content_token_count=800,
            candidates_token_count=40, thoughts_token_count=10,
        ),
    )


class AiAnalyticsPlannerTests(AiAnalyticsFixtures, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_ai_fixtures()

    def setUp(self):
        super().setUp()
        for patcher in (
            sandbox_on_session_connection(),
            mock.patch.dict(self.app.config, {
                "AI_ANALYTICS_ENABLED": True, "AI_ANALYTICS_WEEKLY_QUOTA": 3,
                "GEMINI_API_KEY": "test-key", "ANTHROPIC_API_KEY": "",
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client_mock = mock.Mock()
        self.claude_mock = mock.Mock()
        self.client_patch = mock.patch.object(
            providers, "_client",
            side_effect=lambda name: self.claude_mock if name == providers.ANTHROPIC else self.client_mock,
        )
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    def _model_returns(self, *sqls):
        self.client_mock.models.generate_content.side_effect = [_response(sql) for sql in sqls]

    def _calls(self):
        return self.client_mock.models.generate_content.call_args_list

    def _audit_rows(self, user):
        return db.session.scalars(
            sa.select(VaAiQueryAuditLog).where(VaAiQueryAuditLog.user_id == user.user_id)
            .order_by(VaAiQueryAuditLog.id)
        ).all()

    def test_ask_plans_runs_and_audits_one_call(self):
        self._model_returns(GOOD_SQL)
        plan, result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(result.rows, [{"site_id": "AQ01", "deaths": 1}])
        self.assertEqual(plan["chart"], {**CHART, "reference_column": None})
        rows = self._audit_rows(self.dm_user)
        self.assertEqual([(r.mode, r.used_retry, r.error_code) for r in rows], [(AI_MODE_LLM, False, None)])
        self.assertEqual((rows[0].prompt_tokens, rows[0].cached_tokens, rows[0].output_tokens), (900, 800, 50))
        self.assertEqual(rows[0].id, audit_id)
        self.assertEqual((rows[0].provider, rows[0].model), ("gemini", "gemini-3.5-flash"))
        self.assertEqual(plan["follow_ups"], FOLLOW_UPS[:3])
        config = self._calls()[0].kwargs["config"]
        self.assertEqual(config.thinking_config.thinking_level.value, "MINIMAL")
        self.assertEqual(json.loads(self._calls()[0].kwargs["contents"]), {"question": "Deaths by site"})

    def test_follow_up_sends_previous_sql_and_five_earlier_questions_only(self):
        self._model_returns(GOOD_SQL)
        planner.ask(self.dm_user, "And by month?", previous_sql=GOOD_SQL,
                    earlier_questions=[f"q{i}" for i in range(8)], turn=2)
        payload = json.loads(self._calls()[0].kwargs["contents"])
        self.assertEqual(payload, {
            "question": "And by month?", "previous_sql": GOOD_SQL,
            "earlier_questions": ["q3", "q4", "q5", "q6", "q7"],
        })

    def test_retries_once_on_a_db_error_without_sending_rows(self):
        self._model_returns("SELECT nope FROM ai_cube", GOOD_SQL)
        _plan, result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(result.rows, [{"site_id": "AQ01", "deaths": 1}])
        self.assertEqual(len(self._calls()), 2)
        retry = self._calls()[1].kwargs
        self.assertEqual(retry["config"].thinking_config.thinking_level.value, "LOW")
        payload = json.loads(retry["contents"])
        self.assertEqual(set(payload), {"question", "failed_sql", "database_error"})
        # SQLSTATE and the primary message only, with quoted values redacted.
        self.assertEqual(payload["database_error"], "42703: column <value> does not exist")
        self.assertNotIn("nope", payload["database_error"])
        rows = self._audit_rows(self.dm_user)
        self.assertEqual([(r.used_retry, r.error_code) for r in rows], [(False, "db_error"), (True, None)])
        self.assertEqual(rows[1].id, audit_id)

    def test_second_failure_is_not_retried_again(self):
        self._model_returns("SELECT nope FROM ai_cube", "SELECT still_nope FROM ai_cube", GOOD_SQL)
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(caught.exception.code, "db_error")
        self.assertEqual(len(self._calls()), 2)

    def test_a_result_too_large_is_not_retried(self):
        self._model_returns(GOOD_SQL, GOOD_SQL)
        too_large = sandbox.SandboxError("result_too_large", "The result is too large to show.")
        with mock.patch.object(sandbox, "run_query", side_effect=too_large):
            with self.assertRaises(planner.AiQuestionsError) as caught:
                planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(caught.exception.code, "result_too_large")
        self.assertEqual(len(self._calls()), 1)
        self.assertEqual([r.error_code for r in self._audit_rows(self.dm_user)], ["result_too_large"])

    def test_turn_cap(self):
        self._model_returns(GOOD_SQL)
        planner.ask(self.dm_user, "Last allowed", previous_sql=GOOD_SQL, turn=planner.MAX_TURNS)
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.ask(self.dm_user, "One too many", previous_sql=GOOD_SQL, turn=planner.MAX_TURNS + 1)
        self.assertEqual(caught.exception.code, "turn_cap")
        self.assertEqual(len(self._calls()), 1)

    def test_quota_blocks_asking_only(self):
        self._model_returns(GOOD_SQL, GOOD_SQL, GOOD_SQL, GOOD_SQL)
        audit_id = None
        for _ in range(3):
            _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(planner.quota_left(self.dm_user), 0)
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(caught.exception.code, "quota")
        self.assertEqual(len(self._calls()), 3)
        # Another user's quota is their own, and saving and rerunning still work.
        self.assertEqual(planner.quota_left(self.other_dm_user), 3)
        saved = planner.save_query(self.dm_user, audit_id=audit_id, title="Deaths", chart=CHART)
        _saved, result = planner.rerun_saved(self.dm_user, saved.id)
        self.assertEqual(result.rows, [{"site_id": "AQ01", "deaths": 1}])

    def test_admin_has_no_quota(self):
        self.assertIsNone(planner.quota_left(self.base_admin_user))

    def test_disabled_refuses_asking(self):
        self.app.config["AI_ANALYTICS_ENABLED"] = False
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(caught.exception.code, "disabled")
        self.assertEqual(len(self._calls()), 0)

    def test_saved_rerun_makes_no_model_call_and_uses_no_quota(self):
        self._model_returns(GOOD_SQL)
        _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        saved = planner.save_query(self.dm_user, audit_id=audit_id, title="Deaths", chart=CHART)
        self.assertEqual(saved.validated_sql, GOOD_SQL)
        left = planner.quota_left(self.dm_user)
        self.client_mock.reset_mock()
        self.client_patch.stop()
        mock.patch.object(providers, "_client", side_effect=AssertionError("no model call on a rerun")).start()

        saved, result = planner.rerun_saved(self.dm_user, saved.id)
        planner.rerun_saved(self.dm_user, saved.id)

        self.assertEqual(result.rows, [{"site_id": "AQ01", "deaths": 1}])
        self.assertEqual(len(self._calls()), 0)
        self.assertEqual(planner.quota_left(self.dm_user), left)
        db.session.refresh(saved)
        self.assertEqual(saved.run_count, 2)
        self.assertIsNotNone(saved.last_run_at)
        modes = [r.mode for r in self._audit_rows(self.dm_user)]
        self.assertEqual(modes, [AI_MODE_LLM, AI_MODE_SAVED_RERUN, AI_MODE_SAVED_RERUN])

    def test_saved_rerun_resolves_scope_for_the_caller(self):
        self._model_returns(GOOD_SQL)
        _plan, _result, audit_id = planner.ask(self.base_admin_user, "Deaths by site")
        saved = planner.save_query(self.base_admin_user, audit_id=audit_id, title="All", chart=CHART)
        _saved, result = planner.rerun_saved(self.base_admin_user, saved.id)
        self.assertIn({"site_id": "AQ02", "deaths": 2}, result.rows)

    def test_save_takes_sql_only_from_the_users_own_successful_call(self):
        self._model_returns(GOOD_SQL, "SELECT nope FROM ai_cube", "SELECT nope2 FROM ai_cube")
        _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.save_query(self.other_dm_user, audit_id=audit_id, title="Mine now", chart=CHART)
        self.assertEqual(caught.exception.code, "not_found")
        with self.assertRaises(planner.AiQuestionsError):
            planner.ask(self.dm_user, "Broken")
        failed_id = self._audit_rows(self.dm_user)[-1].id
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.save_query(self.dm_user, audit_id=failed_id, title="Broken", chart=CHART)
        self.assertEqual(caught.exception.code, "not_found")
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.save_query(self.dm_user, audit_id=audit_id, title="Bad chart", chart={"type": "pie"})
        self.assertEqual(caught.exception.code, "bad_chart")

    def test_other_user_cannot_run_or_delete_my_saved_query(self):
        self._model_returns(GOOD_SQL)
        _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        saved = planner.save_query(self.dm_user, audit_id=audit_id, title="Deaths", chart=CHART)
        for action in (planner.rerun_saved, planner.delete_saved):
            with self.subTest(action=action.__name__):
                with self.assertRaises(planner.AiQuestionsError) as caught:
                    action(self.other_dm_user, saved.id)
                self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual([s.id for s in planner.list_saved(self.dm_user)], [saved.id])
        self.assertEqual(planner.list_saved(self.other_dm_user), [])
        planner.delete_saved(self.dm_user, saved.id)
        self.assertEqual(planner.list_saved(self.dm_user), [])

    def test_bad_model_output_is_refused(self):
        self.client_mock.models.generate_content.side_effect = [SimpleNamespace(text="not json", usage_metadata=None)]
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(caught.exception.code, "bad_model_output")
        self.assertEqual(self._audit_rows(self.dm_user)[-1].error_code, "bad_model_output")

    def test_parser_refusal_is_retried_with_the_refusal_text(self):
        self._model_returns("SELECT repeat('a', 900000000) AS x", GOOD_SQL)
        _plan, result, _audit_id = planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(result.rows, [{"site_id": "AQ01", "deaths": 1}])
        payload = json.loads(self._calls()[1].kwargs["contents"])
        self.assertIn("repeat is not supported", payload["database_error"])
        self.assertEqual(self._audit_rows(self.dm_user)[0].error_code, "invalid_sql")

    def test_built_in_reports_and_catalog_make_no_model_call(self):
        self.client_patch.stop()
        mock.patch.object(providers, "_client", side_effect=AssertionError("no model call")).start()
        self.app.config["AI_ANALYTICS_ENABLED"] = False
        report, result = planner.run_builtin(self.dm_user, "cases_by_site")
        self.assertEqual(report["key"], "cases_by_site")
        self.assertEqual(result.rows, [{"site_id": "AQ01", "cases": 1}])
        entry = catalog.load_catalog()[0]
        entry, _result, chart = planner.run_catalog(self.dm_user, entry["key"])
        self.assertIn(chart["type"], planner.CHART_TYPES)
        self.assertEqual(self._audit_rows(self.dm_user), [])
        for action in (planner.run_builtin, planner.run_catalog):
            with self.subTest(action.__name__):
                with self.assertRaises(planner.AiQuestionsError) as caught:
                    action(self.dm_user, "no_such_key")
                self.assertEqual(caught.exception.code, "not_found")

    def test_save_and_delete_update_the_search_index(self):
        self._model_returns(GOOD_SQL)
        _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        with mock.patch.object(planner.ai_search_service, "upsert_saved_query") as upsert, \
                mock.patch.object(planner.ai_search_service, "delete_saved_query") as delete:
            saved = planner.save_query(self.dm_user, audit_id=audit_id, title="Deaths", chart=CHART,
                                       description="by site")
            upsert.assert_called_once_with(saved.id, self.dm_user.user_id, "Deaths", "by site")
            planner.delete_saved(self.dm_user, saved.id)
            delete.assert_called_once_with(saved.id)

    def test_index_failure_does_not_fail_the_save(self):
        self._model_returns(GOOD_SQL)
        _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        with mock.patch.dict("os.environ", {"TYPESENSE_HOST": "ts.test", "TYPESENSE_API_KEY": "k"}), \
                mock.patch("app.services.ai_search_service.requests.request",
                           side_effect=requests.ConnectionError("down")):
            saved = planner.save_query(self.dm_user, audit_id=audit_id, title="Deaths", chart=CHART)
            planner.delete_saved(self.dm_user, saved.id)
        self.assertEqual(planner.list_saved(self.dm_user), [])


class AiAnalyticsProviderTests(AiAnalyticsFixtures, BaseTestCase):
    """Claude and the provider choice; both clients mocked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_ai_fixtures()

    def setUp(self):
        super().setUp()
        self.claude = mock.Mock()
        self.gemini = mock.Mock()
        for patcher in (
            sandbox_on_session_connection(),
            mock.patch.dict(self.app.config, {
                "AI_ANALYTICS_ENABLED": True, "ANTHROPIC_API_KEY": "test-key", "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLOUD_PROJECT": "", "AI_ANALYTICS_MODEL_ANTHROPIC": "",
            }),
            mock.patch.object(providers, "_client",
                              side_effect=lambda name: self.claude if name == providers.ANTHROPIC else self.gemini),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _create(self):
        return self.claude.beta.messages.create

    def test_enabled_providers_follow_credentials(self):
        self.assertEqual(providers.enabled_providers(), ["anthropic", "gemini"])
        self.app.config["ANTHROPIC_API_KEY"] = ""
        self.assertEqual(providers.enabled_providers(), ["gemini"])
        self.app.config.update(GEMINI_API_KEY="", GOOGLE_CLOUD_PROJECT="proj")
        self.assertEqual(providers.enabled_providers(), ["gemini"])
        self.app.config["GOOGLE_CLOUD_PROJECT"] = ""
        self.assertEqual(providers.enabled_providers(), [])
        self.app.config.update(ANTHROPIC_API_KEY="k", AI_ANALYTICS_ENABLED=False)
        self.assertEqual(providers.enabled_providers(), [])

    def test_claude_is_the_default_and_is_called_as_specified(self):
        self._create().return_value = _claude_response(GOOD_SQL)
        plan, result, audit_id = planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(result.rows, [{"site_id": "AQ01", "deaths": 1}])
        self.gemini.models.generate_content.assert_not_called()
        kwargs = self._create().call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-sonnet-5-5")
        self.assertEqual(kwargs["max_tokens"], 4000)
        self.assertEqual(kwargs["system"], [{"type": "text", "text": planner.SYSTEM_INSTRUCTION,
                                              "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(kwargs["output_config"], {
            "effort": "low", "format": {"type": "json_schema", "schema": planner.RESPONSE_SCHEMA},
        })
        self.assertEqual(kwargs["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kwargs["fallbacks"], "default")
        for absent in ("temperature", "top_p", "top_k", "thinking", "budget_tokens"):
            self.assertNotIn(absent, kwargs)
        self.assertEqual(json.loads(kwargs["messages"][0]["content"]), {"question": "Deaths by site"})
        row = db.session.get(VaAiQueryAuditLog, audit_id)
        self.assertEqual((row.provider, row.model), ("anthropic", "claude-sonnet-5-5"))
        self.assertEqual((row.prompt_tokens, row.cached_tokens, row.output_tokens), (120, 1500, 60))
        self.assertEqual(plan["follow_ups"], FOLLOW_UPS[:3])

    def test_model_override(self):
        self.app.config["AI_ANALYTICS_MODEL_ANTHROPIC"] = "claude-other"
        self._create().return_value = _claude_response(GOOD_SQL)
        planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(self._create().call_args.kwargs["model"], "claude-other")

    def test_claude_retry_uses_medium_effort(self):
        self._create().side_effect = [_claude_response("SELECT nope FROM ai_cube"), _claude_response(GOOD_SQL)]
        planner.ask(self.dm_user, "Deaths by site")
        efforts = [c.kwargs["output_config"]["effort"] for c in self._create().call_args_list]
        self.assertEqual(efforts, ["low", "medium"])

    def test_user_may_pick_gemini(self):
        self.gemini.models.generate_content.return_value = _response(GOOD_SQL)
        _plan, _result, audit_id = planner.ask(self.dm_user, "Deaths by site", provider="gemini")
        self._create().assert_not_called()
        self.assertEqual(db.session.get(VaAiQueryAuditLog, audit_id).provider, "gemini")

    def test_a_provider_that_is_not_enabled_is_refused(self):
        self.app.config["ANTHROPIC_API_KEY"] = ""
        for provider in ("anthropic", "openai"):
            with self.subTest(provider):
                with self.assertRaises(planner.AiQuestionsError) as caught:
                    planner.ask(self.dm_user, "Deaths by site", provider=provider)
                self.assertEqual(caught.exception.code, "bad_provider")
        self._create().assert_not_called()

    def test_refusal_is_reported_before_reading_content(self):
        response = _claude_response(GOOD_SQL, stop_reason="refusal")
        response.content = None  # would raise if read
        self._create().return_value = response
        with self.assertRaises(planner.AiQuestionsError) as caught:
            planner.ask(self.dm_user, "Deaths by site")
        self.assertEqual(caught.exception.code, "refused")
        row = db.session.scalars(sa.select(VaAiQueryAuditLog).where(
            VaAiQueryAuditLog.user_id == self.dm_user.user_id)).one()
        self.assertEqual((row.error_code, row.provider), ("refused", "anthropic"))

    def test_typed_sdk_errors_become_safe_messages(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = (
            (anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request),
                                      body=None), "model_busy"),
            (anthropic.InternalServerError("boom", response=httpx2.Response(500, request=request),
                                           body=None), "model_error"),
            (anthropic.APIConnectionError(request=request), "model_error"),
        )
        for error, code in cases:
            with self.subTest(code=code, error=type(error).__name__):
                self._create().side_effect = error
                with self.assertRaises(planner.AiQuestionsError) as caught:
                    planner.ask(self.base_admin_user, "Deaths by site")
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("boom", caught.exception.message)


class AiAnalyticsRenderTests(BaseTestCase):
    def test_bar_chart_table_and_kpis(self):
        rows = [{"site_id": "A", "deaths": 3}, {"site_id": "B", "deaths": 5}]
        view = render(["site_id", "deaths"], rows, CHART)
        self.assertEqual(view["chart"]["type"], "bar")
        self.assertEqual(view["chart"]["data"]["labels"], ["A", "B"])
        self.assertEqual(view["chart"]["data"]["datasets"][0]["data"], [3, 5])
        self.assertEqual(view["kpis"][0], {"label": "Total deaths", "value": 8})
        self.assertEqual(view["kpis"][1], {"label": "B", "value": 5})
        self.assertEqual(view["table"]["rows"], [["A", "3"], ["B", "5"]])

    def test_horizontal_stacked_and_table_recipes(self):
        rows = [{"m": "2026-01-01", "male": 1, "female": 2}]
        stacked = render(["m", "male", "female"], rows, {"type": "stacked_bar", "x_column": "m",
                                                         "series_columns": ["male", "female"]})
        self.assertTrue(stacked["chart"]["options"]["scales"]["x"]["stacked"])
        self.assertEqual(len(stacked["chart"]["data"]["datasets"]), 2)
        horizontal = render(["m", "male"], rows, {"type": "horizontal_bar", "x_column": "m",
                                                  "series_columns": ["male"]})
        self.assertEqual(horizontal["chart"]["options"]["indexAxis"], "y")
        self.assertIsNone(render(["m", "male"], rows, {"type": "table"})["chart"])

    def test_drill_values_follow_the_chart_labels(self):
        rows = [{"site_id": "A", "deaths": 3}, {"site_id": None, "deaths": 1}]
        self.assertEqual(render(["site_id", "deaths"], rows, CHART)["drill"],
                         {"column": "site_id", "values": ["A", "(none)"]})
        self.assertIsNone(render(["site_id", "deaths"], rows, {**CHART, "x_dimension": None})["drill"])
        self.assertIsNone(render(["site_id", "deaths"], rows, {**CHART, "type": "table"})["drill"])

    def test_parse_chart_keeps_only_a_cube_dimension(self):
        self.assertEqual(planner.parse_chart(CHART)["x_dimension"], "site_id")
        self.assertIsNone(planner.parse_chart({**CHART, "x_dimension": "va_sid"})["x_dimension"])

    def test_empty_and_unknown_columns(self):
        self.assertEqual(render([], [], CHART),
                         {"chart": None, "table": {"columns": [], "rows": []}, "kpis": [], "drill": None})
        view = render(["message"], [{"message": "cannot answer"}], CHART)
        self.assertIsNone(view["chart"])
        self.assertEqual(view["kpis"], [])
