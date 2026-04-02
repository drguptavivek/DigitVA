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

    def test_social_autopsy_category_renders_analysis_panel(self):
        category_config = SimpleNamespace(
            display_label="Social Autopsy",
            icon_name="fa-users",
        )
        category_data = {
            "social-autopsy": {
                "Question One": "Yes",
            }
        }

        rendered = self.env.get_template(
            "va_formcategory_partials/category_table_sections.html"
        ).render(
            category_config=category_config,
            category_data=category_data,
            subcategory_labels={"social-autopsy": "Social Autopsy"},
            social_autopsy_enabled=True,
            social_autopsy_analysis_questions=[
                {
                    "delay_level": "delay_1_decision",
                    "title": "Delay 1",
                    "options": [
                        {
                            "option_code": "recognition",
                            "label": "Recognition",
                            "description": "Recognised late",
                        }
                    ],
                }
            ],
            social_autopsy_selected_pairs=[],
            va_social_autopsy_analysis=None,
            flip_list=[],
            info_list=[],
            instance_name="CASE-1",
            va_previouscategory=None,
            va_nextcategory=None,
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            va_partial="social_autopsy",
            csrf_token=lambda: "token",
            url_for=lambda *args, **kwargs: "/vacode/vademo_start_coding/SID-1/social-autopsy-analysis",
        )

        self.assertIn("Social Autopsy Analysis", rendered)
        self.assertIn("Recognition", rendered)

    def test_social_autopsy_category_renders_none_option(self):
        category_config = SimpleNamespace(
            display_label="Social Autopsy",
            icon_name="fa-users",
        )

        rendered = self.env.get_template(
            "va_formcategory_partials/category_table_sections.html"
        ).render(
            category_config=category_config,
            category_data={"social-autopsy": {"Question One": "Yes"}},
            subcategory_labels={"social-autopsy": "Social Autopsy"},
            social_autopsy_enabled=True,
            social_autopsy_analysis_questions=[
                {
                    "delay_level": "delay_1_decision",
                    "title": "Delay 1",
                    "options": [
                        {
                            "option_code": "none",
                            "label": "None",
                            "description": "No delay factor identified.",
                        }
                    ],
                }
            ],
            social_autopsy_selected_pairs=["delay_1_decision::none"],
            va_social_autopsy_analysis=None,
            flip_list=[],
            info_list=[],
            instance_name="CASE-1",
            va_previouscategory=None,
            va_nextcategory=None,
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            va_partial="social_autopsy",
            csrf_token=lambda: "token",
            url_for=lambda *args, **kwargs: "/vaapi/vacode/vademo_start_coding/SID-1/social-autopsy-analysis",
        )

        self.assertIn("None", rendered)
        self.assertIn("No delay factor identified.", rendered)

    def test_social_autopsy_category_blocks_next_when_required_form_missing(self):
        category_config = SimpleNamespace(
            display_label="Social Autopsy",
            icon_name="fa-users",
        )

        rendered = self.env.get_template(
            "va_formcategory_partials/category_table_sections.html"
        ).render(
            category_config=category_config,
            category_data={"social-autopsy": {"Question One": "Yes"}},
            subcategory_labels={"social-autopsy": "Social Autopsy"},
            social_autopsy_enabled=True,
            social_autopsy_analysis_questions=[],
            social_autopsy_selected_pairs=[],
            va_social_autopsy_analysis=None,
            flip_list=[],
            info_list=[],
            instance_name="CASE-1",
            va_previouscategory=None,
            va_nextcategory="vanarrationanddocuments",
            next_block_message="Save the Social Autopsy Analysis before proceeding to the next category.",
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            va_partial="social_autopsy",
            csrf_token=lambda: "token",
            url_for=lambda *args, **kwargs: "/vaapi/vacode/vademo_start_coding/SID-1/vanarrationanddocuments",
        )

        self.assertIn("Save the Social Autopsy Analysis before proceeding to the next category.", rendered)
        self.assertIn("disabled", rendered)
        self.assertIn('data-hx-get="/vaapi/vacode/vademo_start_coding/SID-1/vanarrationanddocuments"', rendered)
        self.assertIn('data-hx-target="#form-content"', rendered)
        self.assertIn('data-hx-swap="innerHTML"', rendered)

    def test_social_autopsy_category_hides_analysis_form_when_project_disabled(self):
        category_config = SimpleNamespace(
            display_label="Social Autopsy",
            icon_name="fa-users",
        )

        rendered = self.env.get_template(
            "va_formcategory_partials/category_table_sections.html"
        ).render(
            category_config=category_config,
            category_data={"social-autopsy": {"Question One": "Yes"}},
            subcategory_labels={"social-autopsy": "Social Autopsy"},
            social_autopsy_enabled=False,
            social_autopsy_analysis_questions=[
                {
                    "delay_level": "delay_1_decision",
                    "question_text": "Delay 1",
                    "options": [{"code": "none", "label": "None"}],
                }
            ],
            social_autopsy_selected_pairs=[],
            va_social_autopsy_analysis=None,
            flip_list=[],
            info_list=[],
            instance_name="CASE-1",
            va_previouscategory=None,
            va_nextcategory="vanarrationanddocuments",
            next_block_message=None,
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            va_partial="social_autopsy",
            csrf_token=lambda: "token",
            url_for=lambda *args, **kwargs: "/stub",
        )

        self.assertNotIn("Social Autopsy Analysis", rendered)

    def test_generic_category_uses_assign_cod_label_for_workflow_next_step(self):
        category_config = SimpleNamespace(
            display_label="Health Service Utilisation",
            icon_name="fa-hospital",
        )

        rendered = self.env.get_template(
            "va_formcategory_partials/category_table_sections.html"
        ).render(
            category_config=category_config,
            category_data={"service": {"Question One": "Yes"}},
            subcategory_labels={"service": "Service"},
            flip_list=[],
            info_list=[],
            instance_name="CASE-1",
            va_previouscategory="social_autopsy",
            va_nextcategory="vacodassessment",
            next_block_message=None,
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            va_partial="vahealthserviceutilisation",
            url_for=lambda *args, **kwargs: "/stub",
        )

        self.assertIn("Assign COD", rendered)
