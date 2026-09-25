"""Anonymous, read-only Help browser for the ICD-10 catalogue."""

import csv
import io
from unittest import mock

from app.routes import help as help_routes
from app.services import va_code_mapping_public_service as service
from tests.base import BaseTestCase


class HelpIcd10CodesRouteTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.catalogue = {
            "QXZ": {
                "title": "Test parent condition",
                "semantic_level": "three_character",
                "parent_code": None,
                "chapter": ("X", "Test chapter"),
                "block": ("QXZ-QXZ", "Test block"),
                "selectable": True,
                "sex_selectable": "both",
                "age_group_selectable": "all",
                "policy_status": "reviewed",
                "restriction_note": "",
                "_search": "qxz test parent condition test chapter test block",
            },
            "QXZ.1": {
                "title": "Infant test condition",
                "semantic_level": "detailed_code",
                "parent_code": "QXZ",
                "chapter": ("X", "Test chapter"),
                "block": ("QXZ-QXZ", "Test block"),
                "selectable": False,
                "sex_selectable": "female",
                "age_group_selectable": "infant",
                "policy_status": "unreviewed",
                "restriction_note": "Infants only",
                "_search": "qxz.1 infant test condition test chapter test block",
            },
        }
        self.rows = [{
            "classification": "icd10",
            "code": "QXZ",
            "va_code": "VAs-01.01",
            "va_title": "Sepsis",
            "origin": service.ORIGIN_DIFFERS,
            "rule": "WHO lists this code for another cause; expert review chose this cause.",
            "note": "Owner decision 12 (2026-09-25): internal crosswalk 10To11 override",
        }]
        self.children = {
            None: [{
                "code": "X", "title": "Test chapter", "semantic_level": "chapter",
                "child_count": 1, "is_coding_selectable": None,
            }],
            "X": [{
                "code": "QXZ-QXZ", "title": "Test block", "semantic_level": "block",
                "child_count": 1, "is_coding_selectable": None,
            }],
            "QXZ-QXZ": [{
                "code": "QXZ", "title": "Test parent condition", "semantic_level": "three_character",
                "child_count": 1, "is_coding_selectable": True, "status_indicator": "green",
            }],
            "QXZ": [{
                "code": "QXZ.1", "title": "Infant test condition", "semantic_level": "detailed_code",
                "child_count": 0, "is_coding_selectable": False, "status_indicator": "red",
                "sex_selectable": "female", "age_group_selectable": "infant",
                "restriction_note": "Infants only",
            }],
        }
        self.node = {
            "code": "QXZ",
            "title": "Test parent condition",
            "semantic_level": "three_character",
            "child_count": 1,
            "is_coding_selectable": True,
            "sex_selectable": "both",
            "age_group_selectable": "all",
            "restriction_note": "",
            "is_policy_editable": True,
            "ancestors": [{"code": "QXZ-QXZ", "title": "Test block", "semantic_level": "block"}],
        }
        patchers = (
            mock.patch.object(help_routes, "get_public_mappings", return_value=(self.rows, [])),
            mock.patch.object(help_routes, "get_icd10_catalogue", return_value=self.catalogue),
            mock.patch.object(
                help_routes,
                "list_icd10_2019_2_children",
                side_effect=lambda parent, **_filters: self.children.get(parent, []),
            ),
            mock.patch.object(help_routes, "get_icd10_2019_2_node_details", return_value=self.node),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_public_page_reuses_panes_without_edit_controls(self):
        response = self.client.get("/help/icd10-codes")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("ICD-10 2019 Browser", body)
        self.assertIn('id="icd10-browser-columns"', body)
        self.assertIn("Chapters", body)
        self.assertIn("Blocks", body)
        self.assertIn("3-Character Codes", body)
        self.assertIn("Detailed Codes", body)
        self.assertIn("Policy review", body)
        self.assertIn("VA mapping origin", body)
        self.assertIn("icd10-browser-search", body)
        self.assertIn('value="infant">Infant</option>', body)
        self.assertIn("The server returned an invalid response.", body)
        self.assertIn("Search failed. Please try again.", body)
        self.assertIn("2 of 2 ICD-10 codes match these filters", body)
        self.assertIn('href="/help/icd10-codes.csv"', body)
        self.assertNotIn("data-tree-table", body)
        self.assertNotIn("Save Policy", body)
        self.assertNotIn("Import JSON", body)
        self.assertNotIn("Export JSON", body)
        self.assertNotIn("Legacy ICD Reporting Aliases", body)
        self.assertNotIn("/admin/api/icd10/2019-2", body)
        self.assertNotIn("/policy-import", body)
        self.assertNotIn("/reporting-aliases", body)
        self.assertNotIn("method: 'PATCH'", body)
        self.assertNotIn("method: 'POST'", body)
        self.assertNotIn("method: 'DELETE'", body)
        self.assertNotIn("Owner decision", body)
        self.assertNotIn("internal crosswalk", body)

    def test_help_navigation_exposes_browser_to_anonymous_users(self):
        body = self.client.get("/help").get_data(as_text=True)
        self.assertIn('href="/help/icd10-codes"', body)
        self.assertIn("ICD-10 Code Browser", body)

    def test_public_children_retain_matching_ancestor_path_and_safe_fields(self):
        response = self.client.get("/help/icd10-codes/children?origin=digitva")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["matching_code_count"], 1)
        self.assertEqual([row["code"] for row in payload["children"]], ["X"])
        self.assertEqual(payload["children"][0]["child_count"], 1)
        self.assertNotIn("is_active", payload["children"][0])
        self.assertNotIn("is_policy_editable", payload["children"][0])

        response = self.client.get(
            "/help/icd10-codes/children?parent_code=QXZ-QXZ&origin=digitva"
        )
        code_row = response.get_json()["children"][0]
        self.assertEqual(code_row["code"], "QXZ")
        self.assertEqual(code_row["child_count"], 0)

    def test_sex_age_and_review_filters_keep_the_matching_detail_path(self):
        response = self.client.get(
            "/help/icd10-codes/children?parent_code=QXZ&selectable=no"
            "&sex_filter=female&age_filter=infant&policy_status=unreviewed"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["code"] for row in payload["children"]], ["QXZ.1"])
        self.assertEqual(payload["children"][0]["restriction_note"], "Infants only")

    def test_public_node_details_include_read_only_state_and_sanitized_origin(self):
        response = self.client.get("/help/icd10-codes/node/QXZ")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["ancestors"][0]["code"], "QXZ-QXZ")
        self.assertTrue(payload["is_coding_selectable"])
        self.assertEqual(payload["sex_selectable"], "both")
        self.assertEqual(payload["age_group_selectable"], "all")
        self.assertEqual(payload["policy_status"], "reviewed")
        self.assertEqual(payload["va_code"], "VAs-01.01")
        self.assertEqual(payload["origin_badge"], "Differs from WHO")
        self.assertIn("expert review chose this cause", payload["origin_reason"])
        self.assertEqual(payload["origin_tooltip"], "Expert review decision 12 (2026-09-25)")
        self.assertNotIn("note", payload)
        self.assertNotIn("is_policy_editable", payload)
        self.assertNotIn("Owner decision", repr(payload))
        self.assertNotIn("internal crosswalk", repr(payload))

        detail = {
            **self.node,
            "code": "QXZ.1",
            "title": "Infant test condition",
            "semantic_level": "detailed_code",
            "is_coding_selectable": False,
            "sex_selectable": "female",
            "age_group_selectable": "infant",
            "restriction_note": "Infants only",
            "ancestors": [{"code": "QXZ", "title": "Test parent condition", "semantic_level": "three_character"}],
        }
        with mock.patch.object(help_routes, "get_icd10_2019_2_node_details", return_value=detail):
            response = self.client.get("/help/icd10-codes/node/QXZ.1")
        detail_payload = response.get_json()
        self.assertFalse(detail_payload["is_coding_selectable"])
        self.assertEqual(detail_payload["sex_selectable"], "female")
        self.assertEqual(detail_payload["age_group_selectable"], "infant")
        self.assertEqual(detail_payload["restriction_note"], "Infants only")
        self.assertEqual(detail_payload["origin_badge"], "Unmapped")

    def test_search_returns_bounded_public_code_results(self):
        response = self.client.get("/help/icd10-codes/search?q=infant&origin=digitva")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"], [])

        response = self.client.get("/help/icd10-codes/search?q=QXZ&origin=digitva")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"], [{
            "code": "QXZ",
            "title": "Test parent condition",
            "semantic_level": "three_character",
        }])

        larger_catalogue = {
            f"QX{index:02d}": {
                **self.catalogue["QXZ"],
                "title": f"Test condition {index}",
                "_search": f"qx{index:02d} test condition",
            }
            for index in range(35)
        }
        with mock.patch.object(help_routes, "get_icd10_catalogue", return_value=larger_catalogue):
            response = self.client.get("/help/icd10-codes/search?q=QX")
        self.assertEqual(len(response.get_json()["results"]), 30)
        self.assertEqual(response.get_json()["total"], 35)

    def test_filters_and_csv_share_public_rows_without_internal_notes(self):
        response = self.client.get("/help/icd10-codes.csv?origin=digitva")
        self.assertEqual(response.status_code, 200)
        reader = csv.DictReader(io.StringIO(response.get_data(as_text=True)))
        rows = list(reader)
        self.assertEqual([row["code"] for row in rows], ["QXZ"])
        self.assertNotIn("note", reader.fieldnames)
        self.assertEqual(rows[0]["origin"], service.ORIGIN_DIFFERS)
        self.assertNotIn("Owner decision", response.get_data(as_text=True))

    def test_public_routes_are_get_only(self):
        expected = {
            "/help/icd10-codes": "help.icd10_codes_browser",
            "/help/icd10-codes.csv": "help.icd10_codes_browser_csv",
            "/help/icd10-codes/children": "help.icd10_codes_browser_children",
            "/help/icd10-codes/search": "help.icd10_codes_browser_search",
            "/help/icd10-codes/node/<code>": "help.icd10_codes_browser_node",
        }
        rules = {
            rule.rule: rule.methods
            for rule in self.app.url_map.iter_rules()
            if rule.endpoint in set(expected.values())
        }
        for path, endpoint in expected.items():
            self.assertEqual(rules[path], {"GET", "HEAD", "OPTIONS"}, endpoint)

    def test_unknown_node_returns_not_found(self):
        with mock.patch.object(help_routes, "get_icd10_2019_2_node_details", return_value=None):
            response = self.client.get("/help/icd10-codes/node/NOT-A-CODE")
        self.assertEqual(response.status_code, 404)
