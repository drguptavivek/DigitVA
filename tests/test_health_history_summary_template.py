from pathlib import Path
from types import SimpleNamespace
import unittest

from jinja2 import Environment, FileSystemLoader


class TestHealthHistorySummaryTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_root = (
            Path(__file__).resolve().parents[1] / "app" / "templates"
        )
        cls.env = Environment(loader=FileSystemLoader(str(template_root)))

    def test_health_history_summary_groups_yes_no_and_renders_remaining_rows(self):
        category_config = SimpleNamespace(
            display_label="Disease / Co-morbidity",
            icon_name="fa-history",
        )
        category_data = {
            "medical_history": {
                "Tuberculosis": "Yes",
                "Diabetes": "No",
                "Other Condition": "Chronic",
            },
            "neonate": {
                "Neonate Specific": "Yes",
            },
        }
        subcategory_labels = {
            "medical_history": "Medical History",
            "neonate": "Neonate Specific",
        }

        rendered = self.env.get_template(
            "va_formcategory_partials/category_health_history_summary.html"
        ).render(
            category_config=category_config,
            category_data=category_data,
            subcategory_labels=subcategory_labels,
            flip_list=[],
            info_list=[],
            instance_name="CASE-1",
            va_previouscategory=None,
            va_nextcategory=None,
            va_action="vacode",
            va_actiontype="vaview",
            va_sid="SID-1",
        )

        self.assertIn("DISEASE / CO-MORBIDITY", rendered)
        self.assertIn("Diagnosed by Health Professional", rendered)
        self.assertIn("Tuberculosis", rendered)
        self.assertIn("Absent", rendered)
        self.assertIn("Diabetes", rendered)
        self.assertIn("Medical History (Responses)", rendered)
        self.assertIn("Other Condition", rendered)
        self.assertIn("Neonate Specific", rendered)
