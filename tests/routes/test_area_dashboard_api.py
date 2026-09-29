"""GET /area/ and GET /api/v1/area/{projects,summary}.

Routes: app/routes/area.py, app/routes/api/area.py. Fixture and scope rules:
tests/services/test_area_dashboard_service.py. GET only: posting to these
routes would 405 and trip the IP ban. Policy: docs/policy/area-dashboard.md.
"""
from urllib.parse import parse_qs, urlsplit

from app.services import area_dashboard_service as area
from tests.services.test_area_dashboard_service import AreaDashboardFixture, AreaStaffFixture

PAGE = "/area/"
PROJECTS = "/api/v1/area/projects"
SUMMARY = "/api/v1/area/summary"
STAFF = "/api/v1/area/staff"


class AreaDashboardRouteTests(AreaDashboardFixture):
    def _as(self, user):
        self._login(str(user.user_id))

    def test_interviewer_loads_page_and_api(self):
        self._as(self.interviewer)
        page = self.client.get(PAGE)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Area Dashboard", page.data)
        projects = self.client.get(PROJECTS).get_json()["projects"]
        self.assertEqual([p["project_id"] for p in projects], [self.TREE])
        summary = self.client.get(SUMMARY, query_string={"project": self.TREE})
        self.assertEqual(summary.status_code, 200)
        rows = {row["key"]: row for row in summary.get_json()["rows"]}
        self.assertEqual(set(rows), {str(self.chc_b.org_unit_id)})

    def test_coder_loads_page_and_summary_with_freshness(self):
        self._as(self.unit_user)
        self.assertEqual(self.client.get(PAGE).status_code, 200)
        response = self.client.get(
            SUMMARY, query_string={"project": self.TREE, "unit": str(self.chc_a.org_unit_id)}
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["unit"]["code"], "ACA")
        self.assertIn("freshness", body)
        self.assertTrue(body["freshness"]["live_at_display"])

    def test_navbar_link_follows_grants(self):
        self._as(self.unit_user)
        self.assertIn(b'href="/area/"', self.client.get(PAGE).data)
        self._as(self.no_grant_user)
        page = self.client.get(PAGE)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'href="/area/"', page.data)

    def test_no_grant_user_gets_empty_list_not_error(self):
        self._as(self.no_grant_user)
        response = self.client.get(PROJECTS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["projects"], [])

    def test_outside_scope_is_404(self):
        self._as(self.unit_user)
        inside = self.client.get(
            SUMMARY, query_string={"project": self.TREE, "unit": str(self.phc_a1.org_unit_id)}
        )
        self.assertEqual(inside.status_code, 200)
        for params in (
            {"project": self.TREE, "unit": str(self.chc_b.org_unit_id)},
            {"project": self.TREE, "unit": "garbage"},
            {"project": self.SITES},
            {"project": "NOPE01"},
        ):
            self.assertEqual(self.client.get(SUMMARY, query_string=params).status_code, 404, params)

    def test_project_card_links_are_data_manager_urls_without_pii(self):
        self._as(self.project_user)
        body = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()
        card = body["project_card"]
        self.assertIsNotNone(card)
        self.assertEqual(card["total_submissions"], 7)
        url = urlsplit(card["links"]["reviewer_eligible"])
        self.assertEqual(url.path, "/data-management/")
        query = parse_qs(url.query, keep_blank_values=True)
        self.assertTrue(set(query) <= set(area.DM_URL_FILTERS))
        self.assertEqual(query["project"], [self.TREE])
        self.assertEqual(query["workflow"], ["reviewer_eligible"])
        self.assertNotIn("pending_or_active", card["links"])

    def test_unit_scoped_user_gets_no_card(self):
        self._as(self.interviewer)
        body = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()
        self.assertTrue(body["rows"])
        self.assertIsNone(body["project_card"])

    def test_sites_mode_row_links_carry_site_filter(self):
        self._as(self.base_admin_user)
        body = self.client.get(SUMMARY, query_string={"project": self.SITES}).get_json()
        self.assertIsNotNone(body["project_card"])
        rows = {row["key"]: row for row in body["rows"]}
        query = parse_qs(urlsplit(rows[self.SITE_TWO]["links"]["total_submissions"]).query,
                         keep_blank_values=True)
        self.assertEqual((query["project"], query["site"]), ([self.SITES], [self.SITE_TWO]))

    def test_project_is_required(self):
        self._as(self.unit_user)
        self.assertEqual(self.client.get(SUMMARY).status_code, 400)

    def test_unauthenticated_is_refused(self):
        response = self.client.get(SUMMARY, query_string={"project": self.TREE})
        self.assertIn(response.status_code, (302, 401))


class AreaStaffRouteTests(AreaStaffFixture):
    def _as(self, user):
        self._login(str(user.user_id))

    def test_coder_gets_named_staff_and_collaborator_gets_none(self):
        params = {"project": self.TREE, "unit": str(self.chc_a.org_unit_id)}
        self._as(self.unit_user)
        shown = self.client.get(STAFF, query_string=params)
        self.assertEqual(shown.status_code, 200)
        names = [row["name"] for row in shown.get_json()["interviewers"]]
        self.assertIn(self.interviewer.name, names)

        self._as(self.collaborator)
        hidden = self.client.get(STAFF, query_string=params)
        self.assertEqual(hidden.status_code, 200)
        body = hidden.get_json()
        self.assertTrue(body["staff_identity_redacted"])
        self.assertEqual((body["interviewers"], body["coders"]), ([], []))
        self.assertNotIn(self.interviewer.name.encode(), hidden.data)

    def test_same_not_found_rules_as_summary(self):
        self._as(self.unit_user)
        self.assertEqual(self.client.get(STAFF).status_code, 400)
        for params in (
            {"project": self.TREE, "unit": str(self.chc_b.org_unit_id)},
            {"project": self.TREE, "unit": "garbage"},
            {"project": self.TREE, "unit": "x" * 65},
            {"project": self.SITES},
            {"project": "NOPE01"},
        ):
            self.assertEqual(self.client.get(STAFF, query_string=params).status_code, 404, params)

    def test_page_carries_the_staff_endpoint(self):
        self._as(self.unit_user)
        self.assertIn(STAFF.encode(), self.client.get(PAGE).data)
