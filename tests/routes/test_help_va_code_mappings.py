"""Public /help/va-code-mappings page and CSV (digitva-712.3), and its compare
and ICD-11 state sub-pages (digitva-xud).

Anonymous, GET only, validated and clamped query parameters.
"""

import csv
import io
import json
import os
import tempfile
import uuid
from unittest import mock

from app import db
from app.models import MasIcd11Mms
from app.services import va_code_mapping_public_service as service
from tests.base import BaseTestCase
from tests.services.test_va_code_mapping_public_service import (
    CATALOGUE,
    RELEASE,
    SELECTABLE,
    seed_public_mapping_fixture,
)


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
        for path in (
            "/help/va-code-mappings", "/help/va-code-mappings.csv",
            "/help/va-code-mappings/compare", "/help/va-code-mappings/unmapped",
            "/help/va-code-mappings/unmapped.csv",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 405)

    def test_listed_in_help_nav_for_anonymous_visitors(self):
        body = self.client.get("/help").get_data(as_text=True)
        self.assertIn('href="/help/va-code-mappings"', body)


class PublicMappingRouteTests(BaseTestCase):
    """The compare and ICD-11 state pages and CSV, anonymous (digitva-xud)."""

    def setUp(self):
        super().setUp()
        self.scheme = seed_public_mapping_fixture([
            ("icd10", "K70.2", "vas_01_01", "exact"),
            ("icd11", "1G40", "vas_01_01", "range"),
            ("icd11", "KD3B.1", "vas_11_01", "range"),
            ("icd11", "1A00", "vas_01_01", "range"),  # not in the ICD-11 catalogue
        ])
        patcher = mock.patch.multiple(service, SCHEME_CODE=self.scheme.scheme_code, ICD11_RELEASE=RELEASE)
        patcher.start()
        self.addCleanup(patcher.stop)
        # CSV file cache in a directory of this test's own.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.app_data = tmp.name
        config_patch = mock.patch.dict(self.app.config, {"APP_DATA": self.app_data})
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def cache_files(self):
        cache_dir = os.path.join(self.app_data, "public_csv")
        return sorted(os.listdir(cache_dir)) if os.path.isdir(cache_dir) else []

    def page_json(self, response, element_id):
        """The tree-table JSON block the page embeds for `element_id`."""
        html = response.get_data(as_text=True)
        start = html.index(f'<script type="application/json" id="{element_id}-data">')
        start = html.index(">", start) + 1
        return json.loads(html[start:html.index("</script>", start)])

    def test_compare_renders_both_sides(self):
        response = self.client.get("/help/va-code-mappings/compare?va_code=VAs-01.01")
        self.assertEqual(response.status_code, 200)
        icd10 = self.page_json(response, "compare-icd10")
        icd11 = self.page_json(response, "compare-icd11")
        self.assertIn("K70.2", {node["id"] for node in icd10["nodes"]})
        self.assertIn("1G40", {node["id"] for node in icd11["nodes"]})
        self.assertNotIn("KD3B.1", {node["id"] for node in icd11["nodes"]})
        self.assertEqual([column["id"] for column in icd11["columns"]], ["code", "origin"])
        self.assertIn("vendor/wunderbaum/wunderbaum.umd.min.js", response.get_data(as_text=True))

    def test_compare_ignores_unknown_va_code(self):
        response = self.client.get("/help/va-code-mappings/compare?va_code=%3Cscript%3E")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Choose a VA cause", html)
        self.assertNotIn("compare-icd10-data", html)

    def test_state_view_lists_unmapped_code_and_splits_by_selectable(self):
        codes = lambda response: {  # noqa: E731
            node["id"] for node in self.page_json(response, "icd11-states")["nodes"] if "cells" in node
        }
        everything = codes(self.client.get("/help/va-code-mappings/unmapped"))
        self.assertIn("KD3B.0", everything)
        self.assertIn("1G40", everything)
        response = self.client.get("/help/va-code-mappings/unmapped?selectable=yes")
        self.assertEqual(codes(response), SELECTABLE)
        self.assertNotIn("KD3B.0", codes(response))
        not_selectable = codes(self.client.get("/help/va-code-mappings/unmapped?selectable=no"))
        self.assertIn("KD3B.0", not_selectable)
        self.assertNotIn("1G40", not_selectable)
        # An unknown filter value is ignored, not an error.
        self.assertEqual(codes(self.client.get("/help/va-code-mappings/unmapped?selectable=maybe")), everything)

    def test_state_view_shows_unmapped_badge_and_counts(self):
        response = self.client.get("/help/va-code-mappings/unmapped?q=KD3B.0")
        nodes = self.page_json(response, "icd11-states")["nodes"]
        leaf = next(node for node in nodes if node["id"] == "KD3B.0")
        self.assertEqual(leaf["cells"]["origin"], {"badge": "Unmapped", "tone": "secondary"})
        self.assertEqual(leaf["cells"]["selectable"], "Not selectable")
        self.assertIn(f"{len(CATALOGUE) - 2} unmapped", response.get_data(as_text=True))

    def test_state_view_renders_origin_and_policy_controls(self):
        body = self.client.get("/help/va-code-mappings/unmapped").get_data(as_text=True)
        self.assertIn('name="origin"', body)
        self.assertIn('name="policy_status"', body)
        self.assertIn("WHO, resolved by DigitVA rule", body)
        self.assertIn(">Unmapped<", body)
        self.assertIn(">Reviewed<", body)
        self.assertIn(">Unreviewed<", body)

    def test_state_view_origin_filter(self):
        codes = lambda response: {  # noqa: E731
            node["id"] for node in self.page_json(response, "icd11-states")["nodes"] if "cells" in node
        }
        who = codes(self.client.get("/help/va-code-mappings/unmapped?origin=who"))
        self.assertEqual(who, {"1G40"})
        resolved = codes(self.client.get("/help/va-code-mappings/unmapped?origin=who_resolved"))
        self.assertEqual(resolved, {"KD3B.1"})
        unmapped = codes(self.client.get("/help/va-code-mappings/unmapped?origin=unmapped"))
        self.assertIn("KD3B.0", unmapped)
        self.assertNotIn("1G40", unmapped)
        self.assertNotIn("KD3B.1", unmapped)
        # An unknown value is ignored, not an error.
        everything = codes(self.client.get("/help/va-code-mappings/unmapped"))
        self.assertEqual(codes(self.client.get("/help/va-code-mappings/unmapped?origin=bogus")), everything)

    def test_state_view_policy_status_filter(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "1G40")
        )
        row.policy_status = "reviewed"
        db.session.commit()
        codes = lambda response: {  # noqa: E731
            node["id"] for node in self.page_json(response, "icd11-states")["nodes"] if "cells" in node
        }
        reviewed = codes(self.client.get("/help/va-code-mappings/unmapped?policy_status=reviewed"))
        self.assertEqual(reviewed, {"1G40"})
        self.assertNotIn("1G40", codes(self.client.get("/help/va-code-mappings/unmapped?policy_status=unreviewed")))
        everything = codes(self.client.get("/help/va-code-mappings/unmapped"))
        self.assertEqual(codes(self.client.get("/help/va-code-mappings/unmapped?policy_status=bogus")), everything)

    def test_state_view_keeps_origin_and_policy_filters_in_links(self):
        body = self.client.get(
            "/help/va-code-mappings/unmapped?origin=who&policy_status=unreviewed"
        ).get_data(as_text=True)
        self.assertIn("unmapped.csv?origin=who&amp;policy_status=unreviewed", body)

    def test_csv_honours_origin_filter_and_streams_live(self):
        response = self.client.get("/help/va-code-mappings/unmapped.csv?origin=who")
        lines = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual({line[0] for line in lines[1:]}, {"1G40"})
        self.assertEqual(self.cache_files(), [])  # filtered: no cache file written

    def test_csv_honours_policy_status_filter_and_streams_live(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "1G40")
        )
        row.policy_status = "reviewed"
        db.session.commit()
        response = self.client.get("/help/va-code-mappings/unmapped.csv?policy_status=reviewed")
        lines = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual({line[0] for line in lines[1:]}, {"1G40"})
        self.assertEqual(self.cache_files(), [])

    def test_state_csv(self):
        response = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=no")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        lines = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual(tuple(lines[0]), service.ICD11_CSV_HEADERS)
        by_code = {line[0]: line for line in lines[1:]}
        self.assertIn("KD3B.0", by_code)
        self.assertEqual(by_code["KD3B.0"][4], "no")
        self.assertNotIn("1G40", by_code)

    def test_cached_csv_is_byte_identical_to_live(self):
        cached = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=no")
        files = self.cache_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("icd11_states_no_"))
        again = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=no")
        self.assertEqual(self.cache_files(), files)
        # Every fixture code shares the chapter title, so this search selects the
        # same codes but takes the live path.
        live = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=no&q=certain+infectious")
        self.assertIn(b"KD3B.0", cached.data)
        self.assertEqual(cached.data, live.data)
        self.assertEqual(again.data, live.data)
        self.assertEqual(cached.headers["Content-Disposition"], live.headers["Content-Disposition"])
        self.assertEqual(cached.mimetype, "text/csv")

    def test_search_creates_no_cache_file(self):
        response = self.client.get("/help/va-code-mappings/unmapped.csv?q=fetal")
        self.assertIn(b"KD3B.0", response.data)
        self.assertEqual(self.cache_files(), [])

    def test_catalogue_edit_replaces_the_cached_file(self):
        before = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=yes")
        self.assertNotIn(b"KD3B.0", before.data)
        old_files = self.cache_files()
        self.assertEqual(len(old_files), 1)
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "KD3B.0")
        )
        row.is_coding_selectable = True
        db.session.commit()
        after = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=yes")
        self.assertIn(b"KD3B.0", after.data)
        new_files = self.cache_files()
        self.assertEqual(len(new_files), 1)
        self.assertNotEqual(new_files, old_files)  # stale variant removed

    def test_unwritable_cache_dir_streams_live(self):
        not_a_dir = os.path.join(self.app_data, "file")
        with open(not_a_dir, "w") as handle:
            handle.write("x")
        with mock.patch.dict(self.app.config, {"APP_DATA": not_a_dir}):
            response = self.client.get("/help/va-code-mappings/unmapped.csv?selectable=no")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"KD3B.0", response.data)

    def test_state_view_keeps_a_block_whole_even_at_a_tiny_page_size(self):
        # The synthetic catalogue's codes all sit in one outermost block, so
        # block-aligned paging keeps them on a single page however small
        # MAPPINGS_PER_PAGE is -- a block is never split across pages.
        codes = lambda response: {  # noqa: E731
            node["id"] for node in self.page_json(response, "icd11-states")["nodes"] if "cells" in node
        }
        not_selectable = len(CATALOGUE) - len(SELECTABLE)
        with mock.patch("app.routes.help.MAPPINGS_PER_PAGE", 2):
            response = self.client.get("/help/va-code-mappings/unmapped?selectable=no")
            body = response.get_data(as_text=True)
            self.assertEqual(len(codes(response)), not_selectable)
            self.assertNotIn("pagination", body)  # one page: no nav rendered
            # An out-of-range page clamps to the only page that exists.
            clamped = self.client.get("/help/va-code-mappings/unmapped?selectable=no&page=999")
            self.assertEqual(clamped.status_code, 200)
            self.assertEqual(codes(clamped), codes(response))

    def test_icd11_block_pages_keeps_a_straddling_block_whole(self):
        # Route-level check that the page wires filtered codes and the
        # catalogue through icd11_block_pages unchanged: unit coverage of the
        # function itself (straddling/oversized blocks, totals) lives in
        # tests/services/test_va_code_mapping_public_service.py.
        catalogue = service.get_icd11_catalogue(RELEASE)
        codes = service.filter_icd11_catalogue(catalogue, selectable="no")
        pages = service.icd11_block_pages(codes, catalogue, 2)
        self.assertEqual(pages, [codes])  # one shared block, never split
        self.assertEqual(sum(len(p) for p in pages), len(codes))

    def test_compare_keeps_icd11_code_missing_from_catalogue(self):
        response = self.client.get("/help/va-code-mappings/compare?va_code=VAs-01.01")
        nodes = self.page_json(response, "compare-icd11")["nodes"]
        by_id = {node["id"]: node for node in nodes}
        self.assertIn("1G40", by_id)
        self.assertIn("1A00", by_id)
        self.assertEqual(by_id["1A00"]["parent_id"], "c:")
        self.assertEqual(by_id["c:"]["title"], "Not in the catalogue")
        self.assertIn("(2 codes)", response.get_data(as_text=True))

    def test_mapping_list_links_to_both_pages(self):
        html = self.client.get("/help/va-code-mappings").get_data(as_text=True)
        self.assertIn('href="/help/va-code-mappings/compare"', html)
        self.assertIn('href="/help/va-code-mappings/unmapped"', html)
