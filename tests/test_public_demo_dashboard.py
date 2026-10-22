"""Public demo dashboard (digitva-77v5.4; docs/policy/public-demo.md section 7)."""
import json
from unittest import mock

import sqlalchemy as sa

from app import cache, db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaReviewerFinalAssessments,
    VaResearchProjects,
    VaSites,
    VaSmartvaResults,
    VaStatuses,
)
from app.services import public_demo_dashboard_service as dashboard
from tests import test_public_demo as base
from tests.test_public_demo_purge import make
from tests.test_public_demo_report import DemoSeedMixin

PAGE = "/public-demo/dashboard"
API = "/api/v1/public-demo/dashboard.json"
SECRET_TEXT = "my private typed words"


class DashboardBase(DemoSeedMixin, base.PublicDemoBase):
    def setUp(self):
        super().setUp()
        cache.delete(dashboard.CACHE_KEY)  # Redis outlives a test

    def tearDown(self):
        cache.delete(dashboard.CACHE_KEY)
        super().tearDown()

    def _anonymous(self):
        with self.client.session_transaction() as session:
            session.clear()


class DashboardFigureTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.alice = self._account("dash.alice")
        self.bob = self._account("dash.bob")
        self._full(self.alice, "dash-1", state="reviewer_finalized", smartva=("Sepsis", "0.6"),
                   coder={"code": "1G40", "title": "Sepsis", "typed": SECRET_TEXT},
                   reviewer={"code": "BA41", "title": "AMI"}, age_years=0.5, sex="male")
        self._full(self.alice, "dash-2", state="coder_finalized", smartva=("Sepsis", "0.5"),
                   coder={"code": "1G40", "title": "Sepsis"}, age_years=42, sex="female")
        self._full(self.bob, "dash-3", state="reviewer_eligible", smartva=("Stroke", "0.7"),
                   coder={"code": "8B20", "title": "Stroke"}, age_years=75, sex="female")
        self._full(self.bob, "dash-4", state="ready_for_coding", smartva=("Stroke", "0.4"), sex="other")
        self._full(self.bob, "dash-5", state="consent_refused")

    def test_anonymous_gets_the_page_and_the_json(self):
        self._anonymous()
        page = self.client.get(PAGE)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Demo dashboard", page.get_data(as_text=True))
        self.assertEqual(self.client.get(API).status_code, 200)

    def test_counts_match_the_fixture(self):
        self._anonymous()
        data = self.client.get(API).get_json()
        self.assertEqual(data["totals"], {"accounts": 2, "submissions": 5, "coded": 3, "reviewed": 1})
        self.assertEqual(data["smartva"]["total"], 4)
        self.assertEqual([(c["cause"], c["count"], c["percent"]) for c in data["smartva"]["causes"]],
                         [("Sepsis", 2, 50.0), ("Stroke", 2, 50.0)])
        self.assertEqual(data["smartva"]["other"], {"count": 0, "percent": 0.0})
        self.assertEqual(data["coder"]["total"], 3)
        self.assertEqual([(c["code"], c["title"], c["count"]) for c in data["coder"]["causes"]],
                         [("1G40", "Sepsis", 2), ("8B20", "Stroke", 1)])
        bands = {b["band"]: b["count"] for b in data["age_bands"]}
        self.assertEqual((bands["Under 1 year"], bands["30-44 years"], bands["70 years and over"], bands["Not stated"]),
                         (1, 1, 1, 2))
        self.assertEqual(sum(bands.values()), 5)
        sexes = {s["sex"]: s["count"] for s in data["sex"]}
        self.assertEqual(sexes, {"Male": 2, "Female": 2, "Other or not stated": 1})

    def test_top_n_and_other(self):
        for n in range(dashboard.TOP_N + 2):
            self._full(self.alice, f"dash-t{n}", smartva=(f"Cause {n:02d}", "0.5"))
        self._anonymous()
        smartva = self.client.get(API).get_json()["smartva"]
        self.assertEqual(len(smartva["causes"]), dashboard.TOP_N)
        self.assertEqual(sum(c["count"] for c in smartva["causes"]) + smartva["other"]["count"], smartva["total"])
        self.assertGreater(smartva["other"]["count"], 0)

    def test_no_username_id_or_free_text_anywhere(self):
        self._anonymous()
        page = self.client.get(PAGE).get_data(as_text=True)
        body = self.client.get(API).get_data(as_text=True)
        self.assertIn("Sepsis", page)  # the cause is shown...
        self.assertIn("Sepsis", body)
        for text in (page, body):
            for secret in ("dash.alice", "dash.bob", "dash-1", "dash-3", SECRET_TEXT, "Asha"):
                self.assertNotIn(secret, text)

    def test_the_figures_are_cached(self):
        self._anonymous()
        first = self.client.get(API).get_json()
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        self._full(self.bob, "dash-6", smartva=("Stroke", "0.3"))
        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            page = self.client.get(PAGE)
            second = self.client.get(API).get_json()
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(second, first)  # the new case is not in the cached figures
        self.assertEqual([s for s in statements if "va_" in s], [])
        cache.delete(dashboard.CACHE_KEY)
        self.assertEqual(self.client.get(API).get_json()["totals"]["submissions"], 6)

    def test_a_fixed_number_of_aggregate_queries(self):
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("SELECT"):
                statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            dashboard.compute()
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 5)

    def test_flag_off_is_404_and_nothing_is_cached(self):
        self._anonymous()
        self.assertEqual(self.client.get(API).status_code, 200)
        cache.delete(dashboard.CACHE_KEY)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(self.client.get(PAGE).status_code, 404)
            self.assertEqual(self.client.get(API).status_code, 404)
        self.assertIsNone(cache.get(dashboard.CACHE_KEY))

    def test_json_is_valid_and_public_cacheable(self):
        self._anonymous()
        response = self.client.get(API)
        self.assertIn("public", response.headers["Cache-Control"])
        json.loads(response.get_data(as_text=True))


class EmptyDashboardTests(DashboardBase):
    def test_an_empty_demo_renders(self):
        self._anonymous()
        data = self.client.get(API).get_json()
        self.assertEqual(data["totals"], {"accounts": 0, "submissions": 0, "coded": 0, "reviewed": 0})
        self.assertEqual((data["smartva"]["total"], data["smartva"]["causes"]), (0, []))
        self.assertEqual(self.client.get(PAGE).status_code, 200)


class DashboardExclusionTests(DashboardBase):
    """What must not reach the figures."""

    def setUp(self):
        super().setUp()
        self.alice = self._account("dash.excl")
        self._full(self.alice, "dx-base", state="coder_finalized", smartva=("Sepsis", "0.6"),
                   coder={"code": "1G40", "title": "Sepsis"}, age_years=42, sex="male")
        self._anonymous()

    def _figures(self):
        cache.delete(dashboard.CACHE_KEY)
        return self.client.get(API).get_json()

    def _other_project_case(self, sid):
        """A coded and reviewed case with a SmartVA result on another project's form."""
        db.session.add(make(VaResearchProjects, project_id="DXOP01"))
        db.session.add(make(VaSites, site_id="DXS1", project_id="DXOP01"))
        db.session.flush()
        db.session.add(make(VaForms, form_id="DXOF01", project_id="DXOP01", site_id="DXS1",
                            form_source="web", form_type="WHO_2022_VA"))
        db.session.commit()
        self.form_id = "DXOF01"  # _case builds the submission on self.form_id
        try:
            self._full(self.alice, sid, state="reviewer_finalized", smartva=("Stroke", "0.9"),
                       coder={"code": "8B20", "title": "Stroke"}, reviewer={"code": "8B20", "title": "Stroke"},
                       age_years=80, sex="female")
        finally:
            del self.form_id

    def test_another_projects_cases_finals_and_smartva_are_not_counted(self):
        before = self._figures()
        self.assertEqual((before["totals"]["submissions"], before["smartva"]["total"], before["coder"]["total"]),
                         (1, 1, 1))  # the demo's own case is counted: presence before absence
        self._other_project_case("dx-other")
        self.assertIsNotNone(db.session.scalar(sa.select(VaSmartvaResults.va_sid).where(
            VaSmartvaResults.va_sid == "dx-other")))
        after = self._figures()
        self.assertEqual({k: v for k, v in after.items() if k != "generated_at"},
                         {k: v for k, v in before.items() if k != "generated_at"})

    def test_tester_and_stale_payload_finals_are_not_counted(self):
        self._full(self.alice, "dx-tester", coder={"code": "8B20", "title": "Stroke"})
        self._full(self.alice, "dx-stale", coder={"code": "5A11", "title": "Diabetes"})
        self.assertEqual(self._figures()["coder"]["total"], 3)  # all three present
        db.session.execute(sa.update(VaFinalAssessments).where(VaFinalAssessments.va_sid == "dx-tester").values(
            is_tester=True))
        db.session.execute(sa.update(VaFinalAssessments).where(VaFinalAssessments.va_sid == "dx-stale").values(
            payload_version_id=None))
        db.session.commit()
        coder = self._figures()["coder"]
        self.assertEqual((coder["total"], [c["code"] for c in coder["causes"]]), (1, ["1G40"]))

    def test_inactive_smartva_rows_are_not_counted(self):
        self.assertEqual(self._figures()["smartva"]["total"], 1)
        db.session.execute(sa.update(VaSmartvaResults).where(VaSmartvaResults.va_sid == "dx-base").values(
            va_smartva_status=VaStatuses.deactive))
        db.session.commit()
        self.assertEqual(self._figures()["smartva"], {"total": 0, "causes": [], "other": {"count": 0, "percent": 0.0}})

    def test_a_final_without_a_provenance_code_counts_as_other(self):
        self._full(self.alice, "dx-nocode", coder={"code": "X", "title": "Y"})
        db.session.execute(sa.update(VaFinalAssessments).where(VaFinalAssessments.va_sid == "dx-nocode").values(
            icd11_provenance=None))
        db.session.commit()
        coder = self._figures()["coder"]
        self.assertEqual(coder["total"], 2)
        self.assertEqual([(c["code"], c["count"]) for c in coder["causes"]], [("1G40", 1)])
        self.assertEqual(coder["other"], {"count": 1, "percent": 50.0})


class DashboardCacheHeaderTests(DashboardBase):
    def test_a_signed_in_viewer_gets_a_private_page_but_the_json_stays_public(self):
        user = self._account("dash.hdr")
        self._login(str(user.user_id))
        page = self.client.get(PAGE)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["Cache-Control"], "private, no-store")
        self.assertIn("public", self.client.get(API).headers["Cache-Control"])
        from flask import g

        g.pop("_login_user", None)  # Flask-Login's cache outlives the request in tests
        self._anonymous()
        self.assertIn("public", self.client.get(PAGE).headers["Cache-Control"])
