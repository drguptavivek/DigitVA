"""WHO ICD-11 licence text (digitva-zde8): one citation, shown where ICD-11 is used."""

import json
from pathlib import Path

from flask import render_template, render_template_string

from app.services.icd11_licence import DIGITVA_ADDITION_LABEL, ICD11_CITATION
from tests.base import BaseTestCase

STRINGS = Path(__file__).resolve().parents[1] / "mobile/digitva-collect/src/strings"


class Icd11LicenceTests(BaseTestCase):
    def test_server_and_expo_citations_are_the_same_text(self):
        for language in ("en", "hi"):
            strings = json.loads((STRINGS / f"{language}.json").read_text(encoding="utf-8"))
            self.assertEqual(strings["icd11Citation"], ICD11_CITATION)
            self.assertEqual(strings["digitvaAddition"], DIGITVA_ADDITION_LABEL)

    def test_notice_partial_renders_the_citation(self):
        with self.app.test_request_context("/"):
            html = render_template("va_form_partials/_icd11_notice.html")
        self.assertIn("https://icd.who.int/browse11", html)
        self.assertIn("CC BY-ND 3.0 IGO", html)

    def test_va_definitions_label_is_a_template_global(self):
        with self.app.test_request_context("/"):
            html = render_template_string("{{ digitva_addition_label }}")
        self.assertEqual(html, DIGITVA_ADDITION_LABEL)

    def test_public_doris_demo_template_includes_the_notice(self):
        page = Path(self.app.root_path, "templates/help/pages/doris-demo.html").read_text(encoding="utf-8")
        self.assertIn("va_form_partials/_icd11_notice.html", page)
