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
        self.assertIn('id="doris-summary"', body)
        self.assertIn('id="doris-maternal-section"', body)
        self.assertIn('role="status" aria-live="polite"', body)
        self.assertIn("Add as uncoded text", body)
        self.assertIn("data-who-api-url", body)
        self.assertIn("data-postcoordination-url", body)
        self.assertIn("data-postcoordination-options-url", body)
        self.assertIn("data-hierarchy-url", body)
        self.assertIn("data-doris-guided-panel", body)
        self.assertIn("data-interval-value", body)
        self.assertIn("data-interval-unit", body)
        self.assertIn("WHO Coding Tool", body)

    def test_demo_loads_the_picker_host_as_a_module_and_not_the_retired_files(self):
        body = (Path(__file__).resolve().parents[2] / "app/templates/help/pages/doris-demo.html").read_text(encoding="utf-8")

        self.assertIn('<script type="module" src="', body)
        self.assertIn("js/doris_demo.js", body)
        self.assertNotIn("doris_search_modal.js", body)
        self.assertNotIn("doris_postcoordination.js", body)
        self.assertNotIn("doris_interval.js", body)

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

    @staticmethod
    def _picker():
        root = Path(__file__).resolve().parents[2]
        return (root / "app/static/js/digitva_icd11_picker.js").read_text(encoding="utf-8")

    def test_json_posts_include_csrf_and_same_origin_credentials(self):
        script = self._script()

        self.assertIn("'X-CSRFToken': app.dataset.csrf", script)
        self.assertIn("credentials: 'same-origin'", script)

    def test_any_certificate_edit_invalidates_results(self):
        script = self._script()

        self.assertIn("function changed(message)", script)
        self.assertIn("clearResults();", script)
        self.assertIn("if (revision !== expectedRevision", script)

    def test_search_and_selection_ignore_stale_or_removed_line_responses(self):
        script = self._script()

        self.assertGreaterEqual(script.count("var sentRevision = revision"), 2)
        self.assertIn("sentRevision !== revision || !line.isConnected", script)
        self.assertIn("sentRevision === revision && line.isConnected", script)

    def test_rule_views_keep_raw_fallback_and_strict_mermaid(self):
        script = self._script()

        self.assertIn("securityLevel: 'strict'", script)
        self.assertIn("No parseable rule rows were returned", script)
        self.assertIn("doris-raw-tabular", script)

    def test_search_results_offer_guided_expression_and_hierarchy(self):
        script = self._script()
        picker = self._picker()

        self.assertIn("+ Build", picker)
        self.assertIn("See in hierarchy", picker)
        self.assertIn("postcoordinationOptions", script)
        self.assertIn("isCompleteExpression", script)

    def test_blank_certificate_has_three_lines_and_omits_empty_rows(self):
        script = self._script()

        self.assertIn("{Conditions: []}, {Conditions: []}, {Conditions: []}", script)
        self.assertIn("filter(function (line) { return line._conditions.length; })", script)
        self.assertIn("blank lines cannot separate causes", script)

    def test_interval_controls_are_lossless_and_validate_before_processing(self):
        script = self._script()

        self.assertIn("mountInterval(", script)
        self.assertIn("intervalError()", script)
        self.assertIn("invalidInterval.message", script)
        interval = (Path(__file__).resolve().parents[2] / "app/static/js/doris_interval.js").read_text(encoding="utf-8")
        self.assertIn("representable: false", interval)
        self.assertIn("selected === 'MI' ? 'M'", interval)
        self.assertIn("value === 'P' || value === 'PT'", interval)

    def test_host_never_reads_or_verifies_selections_itself(self):
        script = self._script()

        # Selection-check is the picker's job now; the host only reacts to
        # onSelect once the picker has already verified the choice.
        self.assertNotIn("dataset.selectionUrl", script)
        self.assertIn("function handleSelect(choice, line)", script)


class Icd11PickerModuleContractTests(BaseTestCase):
    @staticmethod
    def _picker():
        root = Path(__file__).resolve().parents[2]
        return (root / "app/static/js/digitva_icd11_picker.js").read_text(encoding="utf-8")

    def test_picker_is_a_global_free_es_module(self):
        picker = self._picker()

        self.assertIn("export function createIcd11Picker(options)", picker)
        self.assertNotIn("window.DigitvaDoris", picker)
        self.assertNotIn("root.DigitvaDoris", picker)

    def test_picker_owns_selection_verification(self):
        picker = self._picker()

        self.assertIn("transport.post('selection-check'", picker)
        self.assertIn("options.onSelect(choice, container)", picker)

    def test_backdrop_mounts_into_the_host_element_not_document_body(self):
        picker = self._picker()

        self.assertIn("mount.appendChild(backdrop)", picker)
        self.assertNotIn("document.body.appendChild(backdrop)", picker)
