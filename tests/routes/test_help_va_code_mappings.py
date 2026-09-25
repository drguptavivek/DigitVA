"""Public /help/va-code-mappings page and CSV (digitva-712.3), its compare
page, and the read-only ICD-11 browser.

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
from app.routes import help as help_routes
from app.services import va_code_mapping_public_service as service
from tests.base import BaseTestCase
from tests.services.test_va_code_mapping_public_service import (
    CATALOGUE,
    INNER_BLOCK_URI,
    RELEASE,
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
        self.assertIn('id="origin-legend"', body)
        self.assertNotIn('<th scope="col">Note</th>', body)

    def test_search_and_filters(self):
        body = self.client.get("/help/va-code-mappings?q=k70.2").get_data(as_text=True)
        self.assertIn("1 of 153 mappings", body)
        self.assertIn("K70.2", body)
        self.assertIn("WHO names this code directly for this cause", body)

        who_body = self.client.get("/help/va-code-mappings?q=1G40").get_data(as_text=True)
        self.assertIn("WHO lists this code for this cause.", who_body)

        body = self.client.get("/help/va-code-mappings?origin=digitva&classification=icd10").get_data(as_text=True)
        self.assertIn("1 of 153 mappings", body)
        self.assertIn("<code>K72</code>", body)
        self.assertNotIn("<code>K70.2</code>", body)
        self.assertNotIn('<option value="digitva"', body)
        self.assertIn("Differs from WHO", body)

        body = self.client.get("/help/va-code-mappings?classification=icd11").get_data(as_text=True)
        self.assertIn("<code>1G40</code>", body)
        self.assertNotIn("<code>K72</code>", body)

        body = self.client.get("/help/va-code-mappings?va_code=VAs-06.02").get_data(as_text=True)
        self.assertIn("2 of 153 mappings", body)

    def test_review_decision_metadata_is_only_in_a_plain_tooltip(self):
        rows, va_causes = service.get_public_mappings(scheme_code=self.scheme_code, release=RELEASE)
        rows = [dict(row) for row in rows]
        row = next(item for item in rows if item["code"] == "K72")
        row["note"] = "Owner decision 11 (2026-09-24): crosswalk vas_01_07 10To11 override"
        row["origin_tooltip"] = service._review_tooltip(row["note"])
        with mock.patch.object(help_routes, "get_public_mappings", return_value=(rows, va_causes)):
            body = self.client.get("/help/va-code-mappings?q=K72").get_data(as_text=True)
        self.assertIn('title="Expert review decision 11 (2026-09-24)"', body)
        self.assertNotIn("Owner decision 11", body)
        self.assertNotIn("crosswalk", body)
        self.assertNotIn("vas_01_07", body)
        self.assertNotIn("10To11", body)
        self.assertNotIn("override", body)

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
        self.assertEqual([(r["code"], r["va_code"], r["origin"]) for r in rows], [("K72", "VAs-06.02", "differs")])
        self.assertEqual(rows[0]["note"], "note for K72")

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
        release_patcher = mock.patch.object(help_routes, "ICD11_RELEASE", RELEASE)
        release_patcher.start()
        self.addCleanup(release_patcher.stop)
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
        self.assertIn('id="origin-legend"', response.get_data(as_text=True))
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

    def test_icd11_browser_uses_shared_panes_and_legacy_url_still_works(self):
        canonical = self.client.get("/help/icd11-codes?origin=who")
        legacy = self.client.get("/help/va-code-mappings/unmapped?origin=who")
        self.assertEqual(canonical.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        body = canonical.get_data(as_text=True)
        self.assertIn('id="panel-icd11-browser"', body)
        self.assertIn('id="icd11-browser-columns"', body)
        self.assertIn('id="icd11-browser-path"', body)
        self.assertIn('id="icd11-browser-details"', body)
        self.assertIn('id="origin-legend"', body)
        self.assertIn("WHO (overlap resolved)", body)
        for label in ("Not in WHO's list", "Differs from WHO", "Not a cause of death", "Unmapped"):
            self.assertIn(label, body)
        self.assertNotIn("/admin/api/icd11/mms", body)
        for admin_control in ("Import JSON", "Export JSON", "Save Policy", "policy-import"):
            self.assertNotIn(admin_control, body)
        self.assertIn("icd11-codes.csv?origin=who", body)
        self.assertIn('id="icd11-browser-columns"', legacy.get_data(as_text=True))

        alias = self.client.get("/help/icd11-codes?origin=digitva").get_data(as_text=True)
        self.assertIn("state.filters.origin = origin === 'digitva' ? origin", alias)
        self.assertIn("originEl.value = state.filters.origin === 'digitva' ? 'any'", alias)
        self.assertIn("params.set('origin', state.filters.origin)", alias)
        self.assertIn("async function updateFiltersFromInputs(event)", alias)

    def test_icd11_browser_children_are_filtered_and_include_policy_fields(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "KD3B.0")
        )
        row.sex_selectable = "female"
        row.age_group_selectable = "neonate"
        row.policy_status = "reviewed"
        row.restriction_note = "Neonate only"
        db.session.commit()

        response = self.client.get(
            f"/help/icd11-codes/children?parent_linearization_uri={INNER_BLOCK_URI}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        codes = {item["code"] for item in payload["children"]}
        self.assertIn("1G40", codes)
        self.assertIn("KD3B", codes)
        self.assertEqual(payload["matching_code_count"], len(CATALOGUE))

        active = self.client.get(
            f"/help/icd11-codes/children?parent_linearization_uri={INNER_BLOCK_URI}&coding_filter=active"
        ).get_json()
        self.assertEqual({item["code"] for item in active["children"]}, {"1G40", "KD3B"})
        restricted = self.client.get(
            "/help/icd11-codes/children?parent_linearization_uri=test712://KD3B"
            "&sex_filter=female&age_filter=neonate"
        ).get_json()
        self.assertEqual([item["code"] for item in restricted["children"]], ["KD3B.0"])
        self.assertIn("sex_selectable", restricted["children"][0])
        self.assertIn("age_group_selectable", restricted["children"][0])

    def test_icd11_node_detail_exposes_mapping_and_policy_but_not_internal_fields(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(
                MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "KD3B.1"
            )
        )
        row.sex_selectable = "female"
        row.age_group_selectable = "neonate"
        row.policy_status = "reviewed"
        row.restriction_note = "Neonate only"
        db.session.commit()

        response = self.client.get(
            "/help/icd11-codes/node?linearization_uri=test712://KD3B.1"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["sex_selectable"], "female")
        self.assertEqual(payload["age_group_selectable"], "neonate")
        self.assertEqual(payload["policy_status"], "reviewed")
        self.assertEqual(payload["restriction_note"], "Neonate only")
        self.assertTrue(payload["va_code"])
        self.assertTrue(payload["origin_badge"])
        for field in ("id", "source_version", "foundation_uri", "policy_editable"):
            self.assertNotIn(field, payload)

    def test_icd11_direct_who_mapping_has_a_plain_reason(self):
        response = self.client.get(
            "/help/icd11-codes/node?linearization_uri=test712://1G40"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["origin_reason"], "WHO lists this code for this cause.")

    def test_icd11_origin_and_policy_filters_cover_canonical_and_legacy_urls(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "1G40")
        )
        row.policy_status = "reviewed"
        db.session.commit()
        who = self.client.get("/help/icd11-codes/children?origin=who").get_json()
        self.assertEqual(who["matching_code_count"], 1)
        legacy_origin = self.client.get("/help/icd11-codes/children?origin=digitva").get_json()
        self.assertEqual(legacy_origin["matching_code_count"], 0)
        alias_search = self.client.get("/help/icd11-codes/search?q=sepsis&origin=digitva").get_json()
        self.assertEqual(alias_search["results"], [])
        reviewed = self.client.get("/help/icd11-codes/children?policy_status=reviewed")
        self.assertEqual(reviewed.get_json()["matching_code_count"], 1)
        reviewed = self.client.get("/help/va-code-mappings/unmapped?policy_status=reviewed")
        self.assertEqual(reviewed.status_code, 200)
        self.assertIn("icd11-codes", reviewed.get_data(as_text=True))
        self.assertIn("/help/icd11-codes", reviewed.get_data(as_text=True))
        self.assertNotIn('<option value="digitva"', reviewed.get_data(as_text=True))

    def test_legacy_page_and_csv_are_get_only(self):
        routes = {
            rule.rule: rule for rule in self.app.url_map.iter_rules()
        }
        for path in (
            "/help/icd11-codes", "/help/icd11-codes/children", "/help/icd11-codes/node",
            "/help/icd11-codes/search", "/help/icd11-codes.csv",
            "/help/va-code-mappings/unmapped", "/help/va-code-mappings/unmapped.csv",
        ):
            with self.subTest(path=path):
                self.assertEqual(routes[path].methods, {"GET", "HEAD", "OPTIONS"})

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
        self.assertEqual(lines[0][-2:], ["sex", "age_group"])
        by_code = {line[0]: line for line in lines[1:]}
        self.assertIn("KD3B.0", by_code)
        self.assertEqual(by_code["KD3B.0"][4], "no")
        self.assertNotIn("1G40", by_code)

    def test_csv_filters_on_sex_and_age_and_keeps_legacy_alias(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(
                MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "KD3B.0"
            )
        )
        row.sex_selectable = "female"
        row.age_group_selectable = "neonate"
        db.session.commit()
        query = "?sex_filter=female&age_filter=neonate"
        canonical = self.client.get("/help/icd11-codes.csv" + query)
        legacy = self.client.get("/help/va-code-mappings/unmapped.csv" + query)
        self.assertEqual(canonical.data, legacy.data)
        lines = list(csv.reader(io.StringIO(canonical.get_data(as_text=True))))
        by_code = {line[0]: line for line in lines[1:]}
        self.assertEqual(set(by_code), {"KD3B.0"})
        self.assertEqual(by_code["KD3B.0"][-2:], ["female", "neonate"])

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
        self.assertIn('href="/help/icd11-codes"', html)
