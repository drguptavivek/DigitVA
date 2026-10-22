"""GET /area/ and GET /api/v1/area/{projects,summary}.

Routes: app/routes/area.py, app/routes/api/area.py. Fixture and scope rules:
tests/services/test_area_dashboard_service.py. GET only: posting to these
routes would 405 and trip the IP ban. Policy: docs/policy/area-dashboard.md.
"""
from urllib.parse import parse_qs, urlsplit

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes
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

    def test_card_links_are_data_manager_urls_without_pii(self):
        self._as(self.project_user)
        body = self.client.get(SUMMARY, query_string={"project": self.TREE, "period": "30d"}).get_json()
        self.assertEqual(body["period"], "30d")
        card = body["card"]
        self.assertEqual(set(card["counts"]), set(area.COUNT_KEYS))
        url = urlsplit(card["links"]["submitted"])
        self.assertEqual(url.path, "/data-management/")
        query = parse_qs(url.query, keep_blank_values=True)
        self.assertTrue(set(query) <= set(area.DM_URL_FILTERS))
        self.assertEqual(query["project"], [self.TREE])
        self.assertEqual(query["date_from"], [area.period_start("30d").date().isoformat()])
        self.assertNotIn("awaiting_coding", card["links"])
        stations = body["project_card"]["stations"]
        self.assertEqual(stations["active"], 0)
        self.assertIsNone(stations["latest_bundle_at_display"])

    def test_card_and_rows_carry_final_cod(self):
        self._give_authority("uuid:area-ca1")
        self._as(self.project_user)
        body = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()
        self.assertEqual(body["card"]["counts"]["final_cod"], 1)
        self.assertTrue(body["rows"])
        district_1 = next(r for r in body["rows"] if r["key"] == str(self.district_1.org_unit_id))
        self.assertEqual(district_1["counts"]["final_cod"], 1)
        self.assertNotIn("coded", district_1["counts"])

    def test_collaborator_card_links_to_the_data_manager_dashboard(self):
        user = self._get_or_make_user("area.api.collab@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.collaborator, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        db.session.commit()
        self._as(user)
        card = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()["card"]
        self.assertEqual(urlsplit(card["links"]["submitted"]).path, "/data-management/")
        # A reviewer reaches the card but no data manager link (the subject exists first).
        self._as(self.site_user)
        reviewer_card = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()["card"]
        self.assertEqual(reviewer_card["counts"]["submitted"], 7)
        self.assertEqual(reviewer_card["links"], {})

    def test_bad_period_or_format_is_400(self):
        self._as(self.project_user)
        for params in ({"period": "7d"}, {"format": "xml"}):
            response = self.client.get(SUMMARY, query_string={"project": self.TREE, **params})
            self.assertEqual(response.status_code, 400, params)

    def test_csv_export_is_aggregates_for_the_users_area(self):
        self._as(self.unit_user)
        response = self.client.get(
            SUMMARY, query_string={"project": self.TREE, "period": "90d", "format": "csv"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        text = response.get_data(as_text=True)
        self.assertTrue(text.startswith(",".join(area.CSV_HEADER)))
        self.assertIn("row,ACA,Unit ACA,submitted,", text)
        self.assertIn("period,ARDT01,Area ARDT01,period,90d", text)
        # Outside the unit user's subtree, and never a submission id.
        self.assertNotIn("ACB", text)
        self.assertNotIn("uuid:", text)
        # Out of scope is still a 404, not an empty file.
        outside = self.client.get(SUMMARY, query_string={
            "project": self.TREE, "unit": str(self.chc_b.org_unit_id), "format": "csv",
        })
        self.assertEqual(outside.status_code, 404)

    def test_unit_scoped_user_gets_no_card(self):
        self._as(self.interviewer)
        body = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()
        self.assertTrue(body["rows"])
        self.assertIsNone(body["project_card"])
        self.assertIsNotNone(body["card"])

    def test_sites_mode_row_links_carry_site_filter(self):
        self._as(self.base_admin_user)
        body = self.client.get(SUMMARY, query_string={"project": self.SITES}).get_json()
        self.assertIsNotNone(body["project_card"])
        rows = {row["key"]: row for row in body["rows"]}
        query = parse_qs(urlsplit(rows[self.SITE_TWO]["links"]["submitted"]).query,
                         keep_blank_values=True)
        self.assertEqual((query["project"], query["site"]), ([self.SITES], [self.SITE_TWO]))

    def test_project_is_required(self):
        self._as(self.unit_user)
        self.assertEqual(self.client.get(SUMMARY).status_code, 400)

    def test_unauthenticated_is_refused(self):
        response = self.client.get(SUMMARY, query_string={"project": self.TREE})
        self.assertIn(response.status_code, (302, 401))


    def test_rows_carry_deaths_reported_without_a_link(self):
        self._as(self.project_user)
        self.assertIn(b"Deaths reported", self.client.get(PAGE).data)
        rows = self.client.get(SUMMARY, query_string={"project": self.TREE}).get_json()["rows"]
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("deaths_reported", row["counts"])
            # No data manager filter selects death-register cases, so no link.
            self.assertNotIn("deaths_reported", row.get("links", {}))


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
        self.assertEqual(body["interviewers"], [])
        self.assertNotIn(self.interviewer.name.encode(), hidden.data)
        # The summary and its CSV carry no names for anyone.
        for output in ("json", "csv"):
            summary = self.client.get(SUMMARY, query_string={**params, "format": output})
            self.assertEqual(summary.status_code, 200)
            self.assertNotIn(self.interviewer.name.encode(), summary.data)
            self.assertNotIn(self.coder_a.name.encode(), summary.data)

    def test_a_death_reporter_reaches_its_area_with_staff_identity_redacted(self):
        from app.models import VaAccessRoles, VaAccessScopeTypes

        reporter = self._get_or_make_user("area.reporter@test.local", "AreaUser123")
        self._grant(reporter, VaAccessRoles.death_reporter, VaAccessScopeTypes.org_unit,
                    org_unit_id=self.chc_a.org_unit_id)
        db.session.commit()
        params = {"project": self.TREE, "unit": str(self.chc_a.org_unit_id)}
        # Present first: a coder in the same area is shown the interviewer's name.
        self._as(self.unit_user)
        self.assertIn(self.interviewer.name, [r["name"] for r in self.client.get(STAFF, query_string=params).get_json()["interviewers"]])
        self._as(reporter)
        response = self.client.get(STAFF, query_string=params)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["staff_identity_redacted"])
        self.assertEqual(body["interviewers"], [])
        self.assertNotIn(self.interviewer.name.encode(), response.data)

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
