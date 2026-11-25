"""The KPI dashboard warns when a refresh could not rebuild its views.

``POST /api/v1/analytics/dm-kpi/refresh`` keeps answering 200 with
``mv_refreshed`` false when the materialized-view refresh fails; the page shows
"refresh failed, the numbers may be stale" instead (owner 2026-11-25,
digitva-r8nh.39 item 10).
"""

from pathlib import Path
from unittest import mock

from tests.base import BaseTestCase

JS = Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "dm_kpi_dashboard.js"


class DmKpiRefreshWarningTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)

    def test_failed_view_refresh_still_answers_200_with_mv_refreshed_false(self):
        with mock.patch(
            "app.services.submission_analytics_mv.refresh_submission_analytics_mv",
            side_effect=RuntimeError("refresh failed"),
        ):
            response = self.client.post(
                "/api/v1/analytics/dm-kpi/refresh", headers=self._csrf_headers(), json={}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.get_json()), ["cache_deleted", "mv_refreshed"])
        self.assertIs(response.get_json()["mv_refreshed"], False)

    def test_page_carries_the_warning_hidden_until_a_refresh_fails(self):
        body = self.client.get("/data-management/dashboard").get_data(as_text=True)

        self.assertIn('id="dm-kpi-refresh-stale"', body)
        tag = body.split('id="dm-kpi-refresh-stale"', 1)[0].rsplit("<div", 1)[1]
        self.assertIn("d-none", tag)
        self.assertIn("the numbers may be stale", body)

    def test_script_shows_the_warning_only_when_mv_refreshed_is_false(self):
        script = JS.read_text()

        self.assertIn("getElementById('dm-kpi-refresh-stale')", script)
        self.assertIn(
            "stale.classList.toggle('d-none', !(result && result.mv_refreshed === false))", script
        )
