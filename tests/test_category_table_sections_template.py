from types import SimpleNamespace
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class TestCategoryTableSectionsTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_root = (
            Path(__file__).resolve().parents[1] / "app" / "templates"
        )
        cls.env = Environment(loader=FileSystemLoader(str(template_root)))

    def test_generic_table_sections_template_renders_labels_and_badges(self):
        category_config = SimpleNamespace(
            display_label="Social Autopsy",
            icon_name="fa-users",
        )
        category_data = {
            "social-autopsy": {
                "Question One": "Yes",
                "Question Two": "No",
                "Question Three": "Informational",
            }
        }
        subcategory_labels = {"social-autopsy": "Social Autopsy"}

        rendered = self.env.get_template(
            "va_formcategory_partials/category_table_sections.html"
        ).render(
            category_config=category_config,
            category_data=category_data,
            subcategory_labels=subcategory_labels,
            flip_list=["Question Two"],
            info_list=["Question Three"],
            instance_name="CASE-1",
            va_previouscategory=None,
            va_nextcategory=None,
            va_action="vacode",
            va_actiontype="vaview",
            va_sid="SID-1",
        )

        self.assertIn("SOCIAL AUTOPSY", rendered)
        self.assertIn("Question One", rendered)
        self.assertIn('badge bg-danger px-3 py-2">Yes<', rendered)
        self.assertIn('badge bg-danger px-3 py-2">No<', rendered)
        self.assertIn('badge bg-info px-3 py-2">Informational<', rendered)
