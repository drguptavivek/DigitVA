"""`flask ai-catalog generate` (digitva-qwvt): only valid, EXPLAIN-checked
questions are written; the request carries only the fixed instruction."""

import json
import pathlib
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_planner as planner
from app.services import ai_analytics_providers as providers
from tests.ai_analytics_fixtures import AiAnalyticsFixtures, sandbox_on_session_connection
from tests.base import BaseTestCase

CHART = {"type": "bar", "x_column": "site_id", "series_columns": ["cases"], "value_column": "cases",
         "x_dimension": "site_id"}


def _question(key, sql):
    return {"key": key, "question": f"Question {key}?", "description": "d", "keywords": ["k"],
            "sql": sql, "chart": CHART}


class AiCatalogGenerateTests(AiAnalyticsFixtures, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_ai_fixtures()

    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.claude = mock.Mock()
        reply = json.dumps({"questions": [
            _question("cases_by_site", "SELECT site_id, sum(n) AS cases FROM ai_cube GROUP BY site_id"),
            _question("bomb", "SELECT repeat('a', 900000000) AS cases"),
            _question("missing_column", "SELECT nope FROM ai_cube"),
            _question("Bad Key!", "SELECT sum(n) AS cases FROM ai_cube"),
            _question("cases_by_site", "SELECT sum(n) AS cases FROM ai_cube"),
        ]})
        self.claude.beta.messages.create.return_value = SimpleNamespace(
            stop_reason="end_turn", model="claude-sonnet-5-5",
            content=[SimpleNamespace(type="text", text=reply)],
            usage=SimpleNamespace(input_tokens=1, cache_read_input_tokens=0, output_tokens=1),
        )
        for patcher in (
            sandbox_on_session_connection(),
            mock.patch.object(providers, "_client", return_value=self.claude),
            mock.patch.dict(self.app.config, {"AI_ANALYTICS_ENABLED": True, "ANTHROPIC_API_KEY": "k"}),
            mock.patch.object(catalog, "CATALOG_PATH", self.tmp / "catalog.json"),
            mock.patch.object(catalog, "CATALOG_DOC_PATH", self.tmp / "catalog.md"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_generate_keeps_only_checked_questions(self):
        result = self.runner.invoke(args=["ai-catalog", "generate", "--count", "6",
                                          "--as", self.base_admin_user.email])
        self.assertEqual(result.exit_code, 0, result.output)
        written = json.loads((self.tmp / "catalog.json").read_text())["questions"]
        self.assertEqual([e["key"] for e in written], ["cases_by_site"])
        self.assertIn("dropped missing_column", result.output)
        doc = (self.tmp / "catalog.md").read_text()
        self.assertTrue(doc.startswith("---\ntitle: AI question catalog\ndoc_type: kb\n"))
        for call in self.claude.beta.messages.create.call_args_list:
            self.assertEqual(call.kwargs["system"][0]["text"], planner.SYSTEM_INSTRUCTION)
            self.assertNotIn("AQ0", call.kwargs["messages"][0]["content"])

    def test_generate_refuses_a_disabled_provider(self):
        result = self.runner.invoke(args=["ai-catalog", "generate", "--provider", "gemini"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not available", result.output)
        self.assertFalse((self.tmp / "catalog.json").exists())
