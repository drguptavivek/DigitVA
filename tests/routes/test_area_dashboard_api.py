"""GET /area/ and GET /api/v1/area/{projects,summary}.

Routes: app/routes/area.py, app/routes/api/area.py. Fixture and scope rules:
tests/services/test_area_dashboard_service.py. GET only: posting to these
routes would 405 and trip the IP ban. Policy: docs/policy/area-dashboard.md.
"""
from tests.services.test_area_dashboard_service import AreaDashboardFixture

PAGE = "/area/"
PROJECTS = "/api/v1/area/projects"
SUMMARY = "/api/v1/area/summary"


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

    def test_project_is_required(self):
        self._as(self.unit_user)
        self.assertEqual(self.client.get(SUMMARY).status_code, 400)

    def test_unauthenticated_is_refused(self):
        response = self.client.get(SUMMARY, query_string={"project": self.TREE})
        self.assertIn(response.status_code, (302, 401))
