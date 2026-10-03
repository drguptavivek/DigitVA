"""Legacy (non-attachments) vanarrationanddocuments rendering: who sees the COD.

The partial is used only when an admin moves the category's render_mode away
from 'attachments'. Its read-only COD block (SmartVA, coder Not Codeable, the
initial and final COD) sits inside the template's ``va_action == "vacode"``
branch, matching the attachments-mode rule (_va_cod_assessment_panel.html
shows a vaview COD only under vacode): never a plain viewer (digitva-ap98).
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

FINAL_COD = "Ischaemic heart disease (legacy test)"


class TestNarrationLegacyFinalCod(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_root = Path(__file__).resolve().parents[1] / "app" / "templates"
        cls.env = Environment(loader=FileSystemLoader(str(template_root)))

    def _render(self, va_action):
        return self.env.get_template(
            "va_formcategory_partials/vanarrationanddocuments.html"
        ).render(
            category_data={"narration": {"Narrative Text": "Free text"}},
            va_action=va_action,
            va_actiontype="vaview",
            va_sid="SID-1",
            va_final_assess=SimpleNamespace(
                va_conclusive_cod=FINAL_COD, va_finassess_remark="legacy remark"
            ),
            va_initial_assess=None,
            va_coder_review=None,
            smartva=None,
            url_for=lambda *args, **kwargs: "/x",
            smartva_icd11_mapping=lambda code: None,
        )

    def test_coder_rendering_shows_final_cod(self):
        rendered = self._render("vacode")
        self.assertIn(FINAL_COD, rendered)
        self.assertIn("legacy remark", rendered)

    def test_other_renderings_hide_final_cod(self):
        self.assertIn(FINAL_COD, self._render("vacode"))
        for action in ("vaarea", "vadata", "vasitepi", "vareview"):
            with self.subTest(action=action):
                rendered = self._render(action)
                self.assertIn("Free text", rendered)
                self.assertNotIn(FINAL_COD, rendered)
                self.assertNotIn("legacy remark", rendered)


if __name__ == "__main__":
    unittest.main()
