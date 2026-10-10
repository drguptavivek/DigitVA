"""Public Data Collection help page and navigation order."""

from app.routes import help as help_routes
from tests.base import BaseTestCase


class HelpDataCollectionTests(BaseTestCase):
    def test_data_collection_is_between_roles_and_coding_in_help_navigation(self):
        response = self.client.get("/help")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        user_roles = html.index('href="/help/user-roles"')
        data_collection = html.index('href="/help/data-collection"')
        coding = html.index('data-category="Coding Workflow"')
        self.assertLess(user_roles, data_collection)
        self.assertLess(data_collection, coding)

        slugs = [page[0] for page in help_routes.HELP_PAGES]
        self.assertLess(slugs.index("user-roles"), slugs.index("data-collection"))
        self.assertLess(slugs.index("data-collection"), slugs.index("demo-coding"))

    def test_page_is_public_and_covers_form_sources_workflow_and_matrix(self):
        response = self.client.get("/help/data-collection")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for anchor in (
            'id="who-can-collect"',
            'id="interviewer-steps"',
            'id="odk-and-web"',
            'id="identifiers"',
            'id="form-matrix"',
            'id="form-field-legend"',
            'id="extensions"',
            'id="adaptations"',
        ):
            self.assertIn(anchor, html)

        for phrase in (
            "WHO_2022_VA",
            "2026081401",
            "interviewer",
            "death_reporter",
            "interview_supervisor",
            "org_&lt;level_code&gt;_code",
            "ND01_ICMRVA_WHOVA2022.xlsx",
            "UNSW01KA0101",
            "UNSW01KL0101",
            "UNSW01TR0101",
            "NC01 workbook was unavailable",
            "No JIPMER workbook is treated as an UNSW source",
            "Id10476",
            "DORIS",
            "sourceType",
            "no question-level relevance",
            "ancestor group's relevance gate",
        ):
            self.assertIn(phrase, html)
        self.assertNotIn("Answer-gated", html)
        self.assertNotIn("Workflow-gated", html)
        self.assertNotIn(">Conditional<", html)

        self.assertIn(
            'href="/static/help/digitva-form-field-matrix.xlsx"',
            html,
        )
        self.assertIn('href="/help/docs/who-form-overrides"', html)

    def test_override_policy_is_available_through_engineering_docs(self):
        response = self.client.get("/help/docs/who-form-overrides")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("DigitVA WHO Form Overrides", html)
        self.assertIn("DigitVA overrides and extensions to the WHO VA form", html)
