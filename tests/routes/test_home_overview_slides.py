"""Public home page: the two-minute overview carousel and the GitHub footer link."""

from tests.base import BaseTestCase


class HomeOverviewSlidesTests(BaseTestCase):
    def test_anonymous_home_has_eight_slides_of_fifteen_seconds(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="digitva-overview"', html)
        self.assertEqual(html.count('aria-roledescription="slide"'), 8)
        self.assertEqual(html.count('class="carousel-item'), 8)
        self.assertIn('data-bs-interval="15000"', html)
        self.assertIn('id="overview-toggle"', html)
        self.assertIn("prefers-reduced-motion", html)

    def test_footer_links_to_github(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('<footer', html)
        self.assertIn('href="https://github.com/drguptavivek/DigitVA"', html.split("<footer", 1)[1])


class HomeStatsTests(BaseTestCase):
    def test_no_stats_section_when_no_project_is_included(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="digitva-overview"', html)
        self.assertNotIn('id="home-stats-heading"', html)

    def test_rows_fold_small_and_unknown_cells(self):
        from app.services.public_home_stats_service import OTHER, SEXES, _rows

        rows = _rows({"male": 60, "female": 37, "unknown": 2, "undetermined": 1}, SEXES, 100)
        self.assertEqual([r["label"] for r in rows], ["Female", "Male", OTHER])
        self.assertEqual(rows[-1]["n"], 3)
        self.assertEqual(rows[0]["pct"], 37.0)

    def test_section_renders_for_configured_projects(self):
        from unittest import mock

        stats = {"interviews": 1200, "coded": 1100, "coders": 12, "smartva": 1190, "smartva_pct": 99.2,
                 "language_count": 3, "languages": [{"label": "Hindi", "n": 900, "pct": 75.0}],
                 "ages": [{"label": "65 years and over", "n": 600, "pct": 50.0}],
                 "sexes": [{"label": "Male", "n": 700, "pct": 58.3}]}
        with mock.patch("app.services.public_home_stats_service.public_home_stats", return_value=stats):
            html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="home-stats-heading"', html)
        self.assertIn("1,200", html)
        self.assertIn("Physician coders", html)
        self.assertIn("Hindi", html)


class HomeKpisProjectSettingTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from app import cache
        cache.clear()

    def _project(self, pid, **kw):
        from app import db
        from app.models import VaProjectMaster

        p = db.session.get(VaProjectMaster, pid)
        for k, v in kw.items():
            setattr(p, k, v)
        db.session.commit()
        return p

    def test_only_included_non_training_projects_count(self):
        from app.models import VaProjectMaster
        from app import db
        from app.services.public_home_stats_service import included_projects

        pid = db.session.scalars(db.select(VaProjectMaster.project_id).limit(1)).first()
        self.assertIsNotNone(pid)
        self._project(pid, home_kpis_included=True, demo_training_enabled=False, synthetic_demo_reset_enabled=False)
        self.assertIn(pid, included_projects())
        self._project(pid, demo_training_enabled=True)
        self.assertNotIn(pid, included_projects())
        self.app.config["DIGITVA_TRAINING_PROJECT_ID"] = pid
        self._project(pid, demo_training_enabled=False)
        self.addCleanup(self.app.config.__setitem__, "DIGITVA_TRAINING_PROJECT_ID", "TRN01")
        self.assertNotIn(pid, included_projects())


class HomeCacheHeaderTests(BaseTestCase):
    def test_logged_out_home_is_cacheable_for_an_hour(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=3600", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])
        self.assertIn("Cookie", response.headers.get("Vary", ""))

    def test_page_with_a_flash_is_not_cached(self):
        with self.client.session_transaction() as sess:
            sess["_flashes"] = [("info", "You have been logged out.")]
        response = self.client.get("/")
        self.assertIn("You have been logged out.", response.get_data(as_text=True))
        self.assertNotIn("max-age=3600", response.headers.get("Cache-Control", ""))
