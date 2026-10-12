"""GET /api/v1/me/kpis: the home KPI strip (docs/policy/area-dashboard.md, "Home KPIs").

Fixture and scope rules: tests/services/test_area_dashboard_service.py. Tree
ARDT01 is District 1 (AD1) > CHC A (ACA) > PHC A1 (APA), District 1 > CHC B
(ACB), District 2 (AD2); sites-mode ARDS01 has sites AS01 and AS02.
"""
from datetime import UTC, datetime
from unittest import mock

from cachelib import NullCache, SimpleCache

from app import db, limiter
from app.models import VaDeathRegister
from app.services import area_dashboard_service as area
from app.services import organization_service as org
from app.services.duplicate_exclusion import DUPLICATE_CASE_STATUS
from tests.authz.test_grants import count_queries
from tests.services.test_area_dashboard_service import AreaDashboardFixture

KPIS = "/api/v1/me/kpis"


class HomeKpiTests(AreaDashboardFixture):
    def setUp(self):
        super().setUp()
        limiter.reset()
        # Every test sees fresh counts; the cache test swaps in a real cache.
        patch = mock.patch.object(area, "cache", NullCache())
        patch.start()
        self.addCleanup(patch.stop)

    def _rows(self, user):
        self._login(str(user.user_id))
        response = self.client.get(KPIS)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return {project["project_id"]: project for project in response.get_json()["projects"]}

    def _death(self, number, status, unit=None, site=None, project=None):
        db.session.add(
            VaDeathRegister(
                project_id=project or self.TREE,
                site_id=site or self.TREE_SITE,
                org_unit_id=unit.org_unit_id if unit else None,
                death_number=number,
                unique_id=f"KPI-DEATH-{number}",
                deceased_name="Test Case",
                deceased_sex="female",
                date_of_death=datetime.now(UTC).date(),
                registered_by=self.interviewer.user_id,
                source="register",
                status=status,
            )
        )
        db.session.commit()

    def test_tree_project_counts_and_percentages(self):
        for number in range(8):
            self._death(990300 + number, "submitted", unit=self.phc_a1)
        self._death(990310, "submitted", unit=self.chc_b)
        self._death(990311, "submitted", unit=self.chc_b)
        # Duplicates and cancelled cases are not reported deaths.
        self._death(990312, DUPLICATE_CASE_STATUS, unit=self.phc_a1)
        self._death(990313, area.CANCELLED_CASE_STATUS, unit=self.phc_a1)
        self._give_authority("uuid:area-pa1")
        self._give_authority("uuid:area-ca1")

        row = self._rows(self.project_user)[self.TREE]

        self.assertEqual(row["deaths_reported"], 10)
        self.assertEqual(row["interviews_done"], 7)
        self.assertEqual(row["coded"], 2)
        self.assertEqual(row["interviews_pct"], 70)
        self.assertEqual(row["coded_pct"], 20)

    def test_percentages_are_null_without_deaths(self):
        row = self._rows(self.project_user)[self.TREE]

        self.assertEqual(row["interviews_done"], 7)
        self.assertEqual(row["deaths_reported"], 0)
        self.assertIsNone(row["interviews_pct"])
        self.assertIsNone(row["coded_pct"])

    def test_sites_mode_project(self):
        self._death(990400, "submitted", site=self.SITE_ONE, project=self.SITES)
        self._death(990401, "submitted", site=self.SITE_ONE, project=self.SITES)
        self._give_authority("uuid:area-s11")

        rows = self._rows(self.sites_mode_site_user)

        self.assertEqual(list(rows), [self.SITES])
        row = rows[self.SITES]
        self.assertEqual(row["deaths_reported"], 2)
        self.assertEqual(row["interviews_done"], 1)
        self.assertEqual(row["coded"], 1)
        self.assertEqual((row["interviews_pct"], row["coded_pct"]), (50, 50))

    def test_a_user_sees_only_their_subtree(self):
        for number in range(3):
            self._death(990500 + number, "submitted", unit=self.phc_a1)
        for number in range(4):
            self._death(990510 + number, "submitted", unit=self.chc_b)

        # The whole project counts the sibling's deaths; the unit user must not.
        self.assertEqual(self._rows(self.project_user)[self.TREE]["deaths_reported"], 7)
        row = self._rows(self.unit_user)[self.TREE]

        self.assertEqual(row["deaths_reported"], 3)
        self.assertEqual(row["interviews_done"], 3)

    def test_no_grants_is_an_empty_list(self):
        self.assertIn(self.TREE, self._rows(self.project_user))

        self._login(str(self.no_grant_user.user_id))
        response = self.client.get(KPIS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"projects": []})

    def test_signed_out_is_a_json_401(self):
        response = self.client.get(KPIS)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "unauthorized")

    def test_query_count_does_not_grow_with_units(self):
        self._login(str(self.project_user.user_id))
        with count_queries() as before:
            self.assertEqual(self.client.get(KPIS).status_code, 200)

        levels = {level.level_code: level for level in org.list_levels(self.TREE)}
        for number in range(5):
            org.create_unit(
                self.TREE,
                org_level_id=levels["phc"].org_level_id,
                parent_org_unit_id=self.chc_b.org_unit_id,
                unit_code=f"KPIX{number}",
                unit_name=f"Extra {number}",
            )
        db.session.flush()
        with count_queries() as after:
            self.assertEqual(self.client.get(KPIS).status_code, 200)

        self.assertGreater(len(before), 0)
        self.assertEqual(len(after), len(before))

    def test_second_call_within_a_minute_is_served_from_cache(self):
        with mock.patch.object(area, "cache", SimpleCache()):
            self._login(str(self.project_user.user_id))
            first = self.client.get(KPIS).get_json()
            self.assertEqual([p["project_id"] for p in first["projects"]], [self.TREE])
            self.assertEqual(first["projects"][0]["deaths_reported"], 0)

            self._death(990600, "submitted", unit=self.phc_a1)
            second = self.client.get(KPIS).get_json()

        self.assertEqual(second, first)
