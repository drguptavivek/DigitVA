"""Public synthetic DORIS and CoDEdit Help editor."""

from pathlib import Path

from tests.base import BaseTestCase


class HelpDorisDemoRouteTests(BaseTestCase):
    URL = "/help/doris-demo"

    def test_main_service_does_not_serve_demo_without_its_api(self):
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 404)

    def test_help_index_only_advertises_demo_behind_public_ingress(self):
        direct = self.client.get("/help").get_data(as_text=True)
        ingress = self.client.get(
            "/help", headers={"X-DigitVA-Public-Ingress": "1"}
        ).get_data(as_text=True)

        self.assertNotIn('href="/help/doris-demo"', direct)
        self.assertIn('href="/help/doris-demo"', ingress)

    def test_demo_exposes_bounded_accessible_editor_controls(self):
        body = (Path(__file__).resolve().parents[2] / "app/templates/help/pages/doris-demo.html").read_text(encoding="utf-8")

        self.assertIn('id="doris-add-line"', body)
        self.assertIn('id="doris-part2-line"', body)
        self.assertIn('id="doris-fetal-section"', body)
        self.assertIn('id="doris-maternal-section"', body)
        self.assertIn('role="status" aria-live="polite"', body)
        self.assertIn("Add as uncoded text", body)
        self.assertIn("data-who-api-url", body)
        self.assertIn("WHO Coding Tool", body)

    def test_icd11_help_links_to_demo(self):
        direct = self.client.get("/help/icd11-codes").get_data(as_text=True)
        ingress = self.client.get(
            "/help/icd11-codes", headers={"X-DigitVA-Public-Ingress": "1"}
        ).get_data(as_text=True)

        self.assertNotIn('href="/help/doris-demo"', direct)
        self.assertIn('href="/help/doris-demo"', ingress)


class DorisDemoStaticContractTests(BaseTestCase):
    @staticmethod
    def _script():
        root = Path(__file__).resolve().parents[2]
        return (root / "app/static/js/doris_demo.js").read_text(encoding="utf-8")

    def test_json_posts_include_csrf_and_same_origin_credentials(self):
        script = self._script()

        self.assertIn("'X-CSRFToken': app.dataset.csrf", script)
        self.assertIn("credentials: 'same-origin'", script)

    def test_any_certificate_edit_invalidates_results(self):
        script = self._script()

        self.assertIn("function changed(message)", script)
        self.assertIn("clearResults();", script)
        self.assertIn("if (revision !== expectedRevision", script)

    def test_rule_views_keep_raw_fallback_and_strict_mermaid(self):
        script = self._script()

        self.assertIn("securityLevel: 'strict'", script)
        self.assertIn("No parseable rule rows were returned", script)
        self.assertIn("doris-raw-tabular", script)
