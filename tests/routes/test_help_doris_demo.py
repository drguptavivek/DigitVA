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

    def test_demo_page_renders_the_shared_coder_editor_with_demo_urls(self):
        from app.public_doris import create_public_doris_app

        app = create_public_doris_app(
            {"TESTING": True, "SECRET_KEY": "demo-render", "SESSION_COOKIE_SECURE": False}
        )
        page = app.test_client().get(self.URL).get_data(as_text=True)

        self.assertIn("data-doris-editor", page)
        self.assertIn('data-process-url="/api/v1/doris-demo/process"', page)
        self.assertIn('data-terms-url="/api/v1/doris-demo/terms"', page)
        self.assertIn('data-selection-url="/api/v1/doris-demo/selection-check"', page)
        self.assertIn('data-final-cod-input="doris-demo-final-cod"', page)
        self.assertIn('id="doris-demo-final-cod"', page)
        for label in ("Date of birth", "Manner of death", "Was surgery performed within the last 4 weeks?",
                      "Was an autopsy requested?", "For women, was the deceased pregnant?",
                      "Frame A: Medical data"):
            self.assertIn(label, page)
        self.assertIn("js/doris_clinical.js", page)
        self.assertIn("Synthetic example", page)
        self.assertIn("Start blank", page)
        self.assertIn("data-icd11-citation", page)
        # The VA definitions API is not served publicly, so the panel is left out.
        self.assertNotIn("VA Definitions", page)
        self.assertNotIn("va-def-root", page)

    def test_demo_has_none_of_its_old_own_markup(self):
        body = (Path(__file__).resolve().parents[2] / "app/templates/help/pages/doris-demo.html").read_text(encoding="utf-8")

        for gone in ("doris-rule-table", "mermaid", "doris-ect-panel", "doris-raw-tabular",
                     "doris-line-template", "doris-fetal-section", "data-certificate-input",
                     "Versioned DORIS rule trace", "icd11ect"):
            self.assertNotIn(gone, body)
        self.assertIn('{% include "va_form_partials/_doris_certificate_editor.html" %}', body)
        self.assertIn("js/doris_demo.js", body)

    def test_icd11_help_links_to_demo(self):
        direct = self.client.get("/help/icd11-codes").get_data(as_text=True)
        ingress = self.client.get(
            "/help/icd11-codes", headers={"X-DigitVA-Public-Ingress": "1"}
        ).get_data(as_text=True)

        self.assertNotIn('href="/help/doris-demo"', direct)
        self.assertIn('href="/help/doris-demo"', ingress)


class DorisDemoStaticContractTests(BaseTestCase):
    @staticmethod
    def _read(path):
        return (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8")

    def test_demo_script_is_only_the_example_loader(self):
        script = self._read("app/static/js/doris_demo.js")

        self.assertIn("editor._dorisReload(", script)
        for gone in ("mermaid", "ECT", "process", "Rules."):
            self.assertNotIn(gone, script)

    def test_shared_editor_reloads_and_tolerates_a_tokenless_demo_reply(self):
        script = self._read("app/static/js/doris_clinical.js")

        self.assertIn("editor._dorisReload = function (certificate)", script)
        self.assertIn("pristine.cloneNode(true)", script)
        self.assertIn("(!result.data.process_token && !editor.hasAttribute('data-doris-demo'))", script)
        self.assertIn("state.savedOnly = !processing.process_token && !demo", script)


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
