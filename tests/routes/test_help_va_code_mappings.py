"""Public /help/va-code-mappings page and CSV (digitva-712.3).

Anonymous, GET only, validated and clamped query parameters.
"""

import csv
import io
import uuid
from unittest import mock

from app.services import va_code_mapping_public_service as service
from tests.base import BaseTestCase
from tests.services.test_va_code_mapping_public_service import RELEASE, seed_public_mapping_fixture


class HelpVaCodeMappingsRouteTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        rows = [
            ("icd10", "K70.2", "vas_06_02", "exact"),
            ("icd10", "K72", "vas_06_02", "range"),
            ("icd11", "1G40", "vas_01_01", "range"),
        ]
        # 150 more ICD-10 rows so the list has two pages.
        rows += [("icd10", f"A41.{n // 10}{n % 10}", "vas_01_01", "range") for n in range(100)]
        rows += [("icd10", f"A40.{n // 10}{n % 10}", "vas_01_01", "range") for n in range(50)]
        cls.scheme_code = seed_public_mapping_fixture(rows).scheme_code

    def setUp(self):
        super().setUp()
        patches = (
            mock.patch.object(service, "SCHEME_CODE", self.scheme_code),
            mock.patch.object(service, "ICD11_RELEASE", RELEASE),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_anonymous_page_lists_mappings(self):
        response = self.client.get("/help/va-code-mappings")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("ICD to VA Cause Mappings", body)
        self.assertIn("153 of 153 mappings", body)
        self.assertIn("Page 1 of 2", body)

    def test_search_and_filters(self):
        body = self.client.get("/help/va-code-mappings?q=k70.2").get_data(as_text=True)
        self.assertIn("1 of 153 mappings", body)
        self.assertIn("K70.2", body)
        self.assertIn("Specific code beats range", body)

        body = self.client.get("/help/va-code-mappings?origin=digitva&classification=icd10").get_data(as_text=True)
        self.assertIn("1 of 153 mappings", body)
        self.assertIn("<code>K72</code>", body)
        self.assertNotIn("<code>K70.2</code>", body)

        body = self.client.get("/help/va-code-mappings?classification=icd11").get_data(as_text=True)
        self.assertIn("<code>1G40</code>", body)
        self.assertNotIn("<code>K72</code>", body)

        body = self.client.get("/help/va-code-mappings?va_code=VAs-06.02").get_data(as_text=True)
        self.assertIn("2 of 153 mappings", body)

    def test_second_page(self):
        first = self.client.get("/help/va-code-mappings").get_data(as_text=True)
        second = self.client.get("/help/va-code-mappings?page=2").get_data(as_text=True)
        self.assertIn("<code>A40.00</code>", first)
        self.assertNotIn("<code>A40.00</code>", second)
        self.assertIn("Page 2 of 2", second)
        self.assertIn("<code>K72</code>", second)

    def test_bad_params_are_clamped_or_ignored(self):
        for query in (
            "page=abc", "page=-3", "page=0", "page=999999",
            "classification=icd9", "origin=<script>", "va_code=VAs-00.00", "q=" + "x" * 5000,
        ):
            with self.subTest(query=query):
                response = self.client.get(f"/help/va-code-mappings?{query}")
                self.assertEqual(response.status_code, 200)
        self.assertIn("Page 2 of 2", self.client.get("/help/va-code-mappings?page=999999").get_data(as_text=True))
        # An unknown filter value is dropped, not applied.
        self.assertIn("153 of 153", self.client.get("/help/va-code-mappings?origin=bogus").get_data(as_text=True))

    def test_search_text_is_escaped(self):
        body = self.client.get('/help/va-code-mappings?q="><img src=x>').get_data(as_text=True)
        self.assertIn("&#34;&gt;&lt;img src=x&gt;", body)
        self.assertNotIn('"><img src=x>', body)

    def test_csv_download(self):
        response = self.client.get("/help/va-code-mappings.csv?origin=digitva")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual([(r["code"], r["va_code"], r["origin"]) for r in rows], [("K72", "VAs-06.02", "digitva")])

        full = list(csv.reader(io.StringIO(self.client.get("/help/va-code-mappings.csv").get_data(as_text=True))))
        self.assertEqual(tuple(full[0]), service.CSV_HEADERS)
        self.assertEqual(len(full), 154)

    def test_post_is_not_allowed(self):
        # Keep these 405s from counting toward a ban on the shared test IP.
        suffix = uuid.uuid4().hex
        with mock.patch.dict(self.app.config, {
            "METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX": f"digitva_test_va_mappings:count:{suffix}:",
            "METHOD_NOT_ALLOWED_BAN_PREFIX": f"digitva_test_va_mappings:ban:{suffix}:",
        }):
            self._assert_post_not_allowed()

    def _assert_post_not_allowed(self):
        for path in ("/help/va-code-mappings", "/help/va-code-mappings.csv"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 405)

    def test_listed_in_help_nav_for_anonymous_visitors(self):
        body = self.client.get("/help").get_data(as_text=True)
        self.assertIn('href="/help/va-code-mappings"', body)
