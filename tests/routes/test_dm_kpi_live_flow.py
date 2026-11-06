"""Live KPI flow, time to code and aging (digitva-0hul step 2, digitva-r5s0 2a/2b).

docs/policy/kpis.md: canonical definitions, C-01, C-04, C-19, C-07, C-08.
Every figure is computed live from workflow events; days are each event's
project's (docs/policy/kpis.md, "Days follow the project clock"): Asia/Kolkata
unless a project here says otherwise. The compute functions are
called directly, as MCP will; the C-09 window check goes through its route.

Each assertion of an absence is preceded by the subject's presence.
"""
import uuid
from unittest import mock
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
)
from app.routes.api.dm_kpi.dm_kpi_grid import compute_c01
from app.routes.api.dm_kpi.dm_kpi_pipeline import (
    compute_c04,
    compute_c07,
    compute_c08,
    compute_c19,
)
from app.routes.api.dm_kpi import dm_kpi_burndown, dm_kpi_workflow
from app.routes.api.dm_kpi.dm_kpi_scope import DmScope
from tests.base import BaseTestCase


IST = ZoneInfo("Asia/Kolkata")


def _ist(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), IST)


class DmKpiLiveFlowTests(BaseTestCase):
    #: SHORT has a 60-minute recode window, LONG the 24-hour default.
    SHORT, LONG = "KFL001", "KFL002"
    #: Project clocks other than the default, for the "days follow the project clock" tests.
    UTC_P, NY_P = "KFL003", "KFL004"
    SITES = {SHORT: "KF01", LONG: "KF02", UTC_P: "KF03", NY_P: "KF04"}
    FORMS = {
        SHORT: "KFL001KF0101", LONG: "KFL002KF0201",
        UTC_P: "KFL003KF0301", NY_P: "KFL004KF0401",
    }
    ZONES = {UTC_P: "UTC", NY_P: "America/New_York"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, site_id in cls.SITES.items():
            db.session.add(VaSiteMaster(
                site_id=site_id, site_abbr=site_id, site_name=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id,
                project_name=project_id, project_nickname=project_id,
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
                recode_window_minutes=60 if project_id == cls.SHORT else 1440,
                timezone=cls.ZONES.get(project_id, "Asia/Kolkata"),
            ))
            db.session.add(VaResearchProjects(
                project_id=project_id, project_code=project_id,
                project_name=project_id, project_nickname=project_id,
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.flush()
            db.session.add(VaSites(
                site_id=site_id, project_id=project_id, site_name=site_id,
                site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
            db.session.flush()
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.add(VaForms(
                form_id=cls.FORMS[project_id], project_id=project_id, site_id=site_id,
                odk_form_id=f"KF_{project_id}", odk_project_id="96",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _scope(self, *projects):
        projects = projects or (self.SHORT,)
        return DmScope(pairs=sorted((p, self.SITES[p]) for p in projects), unit_ids=[])

    def _case(self, state, *, created_at, events=(), updated_at=None, project=None):
        """A submission now in *state*; *events* are (transition, previous, current, at)."""
        sid = f"uuid:kfl-{uuid.uuid4()}"
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=self.FORMS[project or self.SHORT],
            va_submission_date=created_at, va_odk_updatedat=created_at,
            va_created_at=created_at.astimezone(UTC),
            va_data_collector="kfl", va_odk_reviewstate="approved", va_instance_name=sid,
            va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language="English", va_deceased_age=50, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state,
            workflow_updated_at=(updated_at or datetime.now(UTC)).astimezone(UTC),
        ))
        for transition, previous, current, at in events:
            db.session.add(VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id=transition, previous_state=previous,
                current_state=current, event_created_at=at,
            ))
        db.session.commit()
        return sid

    @staticmethod
    def _by_date(rows):
        return {r["date"]: r for r in rows}

    # -- C-01 / C-04 / C-19: the flow helper ------------------------------

    def test_a_case_entering_and_leaving_pending_overnight_is_pending_only_that_night(self):
        today = datetime.now(IST).date()
        d0 = today - timedelta(days=3)
        d1 = d0 + timedelta(days=1)
        # Enters the pending set at 22:00 on d0, leaves (coded) at 02:00 on d1.
        self._case("coder_finalized", created_at=_ist(d0, 21), events=[
            ("sync_new_payload_routed", None, "smartva_pending", _ist(d0, 22)),
            ("coding_started", "ready_for_coding", "coding_in_progress", _ist(d1, 1)),
            ("coder_finalized", "coding_in_progress", "coder_finalized", _ist(d1, 2)),
        ])
        # Still pending: enters on d1.
        self._case("ready_for_coding", created_at=_ist(d1, 9), events=[
            ("smartva_completed", None, "ready_for_coding", _ist(d1, 9)),
        ])

        grid = compute_c01(self._scope(), 8)["data"]
        rows = self._by_date(grid)
        # Every day of the window has a row, newest first.
        self.assertEqual(len(grid), 8)
        self.assertEqual(grid[0]["date"], today.isoformat())
        before = rows[(d0 - timedelta(days=1)).isoformat()]
        self.assertEqual((before["pending"], before["total"]), (0, 0))
        self.assertEqual((rows[d0.isoformat()]["pending"], rows[d0.isoformat()]["total"]), (1, 1))
        self.assertEqual((rows[d1.isoformat()]["pending"], rows[d1.isoformat()]["total"]), (1, 2))
        self.assertEqual(rows[d1.isoformat()]["coded"], 1)
        self.assertEqual(rows[d1.isoformat()]["new_from_odk"], 1)
        self.assertEqual((rows[today.isoformat()]["pending"], rows[today.isoformat()]["total"]), (1, 2))

        flow = self._by_date(compute_c19(self._scope(), 7)["data"])
        self.assertEqual(flow[d0.isoformat()]["inflow"], 1)
        self.assertEqual(flow[d1.isoformat()]["inflow"], 1)
        self.assertEqual(
            (flow[d1.isoformat()]["outflow"], flow[d1.isoformat()]["outflow_coded"]), (1, 1)
        )

        c04 = compute_c04(self._scope(), 7)
        self.assertEqual(c04["pending"], 1)
        self.assertEqual(c04["outflow_28d"], 1)
        self.assertEqual(c04["days_to_clear"], 28.0)  # 1 pending / (1 out / 28 days)
        trend = self._by_date(c04["series"])
        self.assertEqual(trend[d0.isoformat()]["pending"], 1)
        self.assertEqual(trend[today.isoformat()]["pending"], 1)

    def test_an_event_at_2345_utc_is_the_next_day_in_ist(self):
        today = datetime.now(IST).date()
        utc_day = today - timedelta(days=3)
        late = datetime.combine(utc_day, time(23, 45), UTC)  # 05:15 IST the next day
        self._case("coder_finalized", created_at=late - timedelta(hours=1), events=[
            ("coding_started", "ready_for_coding", "coding_in_progress", late - timedelta(minutes=5)),
            ("coder_finalized", "coding_in_progress", "coder_finalized", late),
        ])
        next_day = (utc_day + timedelta(days=1)).isoformat()

        ist = self._by_date(compute_c01(self._scope(), 8)["data"])
        self.assertEqual(ist[next_day]["coded"], 1)
        self.assertEqual(ist[utc_day.isoformat()]["coded"], 0)
        self.assertEqual(self._by_date(compute_c19(self._scope(), 7)["data"])[next_day]["outflow"], 1)


    def test_net_inflow_over_28_days_flags_a_backlog_that_does_not_clear(self):
        today = datetime.now(IST).date()
        for hour in (9, 10):
            self._case("ready_for_coding", created_at=_ist(today, hour), events=[
                ("smartva_failed_recorded", None, "ready_for_coding", _ist(today, hour)),
            ])

        c19 = compute_c19(self._scope(), 7)
        self.assertEqual(c19["data"][0]["inflow"], 2)
        self.assertEqual(c19["net_28d"], 2)
        self.assertTrue(c19["does_not_clear"])
        self.assertIsNone(compute_c04(self._scope())["days_to_clear"])

    def test_demo_events_leave_coded_and_flow_but_not_the_pending_count(self):
        today = datetime.now(IST).date()
        demo = [
            ("demo_started", "ready_for_coding", "coding_in_progress", _ist(today, 8)),
            ("coder_finalized", "coding_in_progress", "coder_finalized", _ist(today, 9)),
        ]
        self._case("coder_finalized", created_at=_ist(today, 7), events=[
            ("smartva_completed", None, "ready_for_coding", _ist(today, 7)), *demo,
        ])
        real = [
            ("smartva_completed", None, "ready_for_coding", _ist(today, 7)),
            ("coding_started", "ready_for_coding", "coding_in_progress", _ist(today, 8)),
            ("coder_finalized", "coding_in_progress", "coder_finalized", _ist(today, 9)),
        ]
        self._case("coder_finalized", created_at=_ist(today, 7), events=real)

        row = compute_c01(self._scope(), 1)["data"][0]
        self.assertEqual(row["coded"], 1)
        self.assertEqual(row["pending"], 0)
        flow = compute_c19(self._scope(), 1)["data"][0]
        self.assertEqual((flow["inflow"], flow["outflow"]), (1, 1))

        # The project half of the demo rule: a demo_training_enabled project.
        db.session.get(VaProjectMaster, self.SHORT).demo_training_enabled = True
        db.session.commit()
        self.assertEqual(compute_c01(self._scope(), 1)["data"][0]["coded"], 0)

    # -- C-08 time to code -------------------------------------------------

    def test_time_to_code_pairs_each_finalize_with_its_latest_start(self):
        t0 = datetime.now(UTC) - timedelta(hours=5)
        self._case("coder_finalized", created_at=t0 - timedelta(hours=1), events=[
            ("coding_started", "ready_for_coding", "coding_in_progress", t0),
            ("incomplete_first_pass_reset", "coding_in_progress", "ready_for_coding", t0 + timedelta(minutes=30)),
            ("coding_started", "ready_for_coding", "coding_in_progress", t0 + timedelta(hours=1)),
            ("coder_finalized", "coding_in_progress", "coder_finalized", t0 + timedelta(hours=1, minutes=10)),
            ("recode_started", "coder_finalized", "coding_in_progress", t0 + timedelta(hours=2)),
            ("recode_finalized", "coding_in_progress", "coder_finalized", t0 + timedelta(hours=2, minutes=5)),
        ])
        # A demo session's finalize is not output.
        self._case("coder_finalized", created_at=t0, events=[
            ("demo_started", "ready_for_coding", "coding_in_progress", t0),
            ("coder_finalized", "coding_in_progress", "coder_finalized", t0 + timedelta(minutes=1)),
        ])

        result = compute_c08(self._scope(), 7)

        # One duration per finalize: 10 min (after the second start), 5 min (after the recode start).
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["min_seconds"], 300.0)
        self.assertEqual(result["max_seconds"], 600.0)
        self.assertEqual(result["p50_seconds"], 450.0)
        self.assertGreaterEqual(result["min_seconds"], 0)

    def test_time_to_code_with_no_finalize_is_empty(self):
        self._case("coding_in_progress", created_at=datetime.now(UTC), events=[
            ("coding_started", "ready_for_coding", "coding_in_progress", datetime.now(UTC)),
        ])
        result = compute_c08(self._scope(), 7)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["p50_seconds"])

    # -- C-07 aging by state -----------------------------------------------

    def test_aging_by_state_uses_each_projects_recode_window(self):
        now = datetime.now(UTC)
        two_hours_ago = now - timedelta(hours=2)
        self._case("coder_finalized", created_at=now - timedelta(days=1), updated_at=two_hours_ago)
        self._case("coder_finalized", created_at=now - timedelta(days=1), updated_at=two_hours_ago,
                   project=self.LONG)
        self._case("ready_for_coding", created_at=now - timedelta(days=4),
                   updated_at=now - timedelta(days=3))

        states = {r["state"]: r for r in compute_c07(self._scope(self.SHORT, self.LONG), by="state")["states"]}

        finalized = states["coder_finalized"]
        self.assertEqual(finalized["total"], 2)
        # 2 h is beyond the 60-minute window and inside the 24-hour one.
        self.assertEqual((finalized["within_window"], finalized["beyond_window"]), (1, 1))
        self.assertEqual(finalized["alert_count"], 1)
        self.assertEqual(finalized["alert_level"], "warning")
        # The one-release overlap keys.
        self.assertEqual((finalized["within_24h"], finalized["gt_24h"]), (2, 0))

        ready = states["ready_for_coding"]
        self.assertEqual((ready["total"], ready["gt_48h"], ready["gt_7d"]), (1, 1, 0))
        self.assertEqual((ready["alert_count"], ready["critical_count"]), (1, 0))
        self.assertEqual(ready["alert_level"], "warning")

        # The ready-pool tiles (by=None) agree.
        self.assertEqual(compute_c07(self._scope(self.SHORT, self.LONG))["gt_48h"], 1)

    def test_stagnation_endpoint_wraps_c07_with_the_recode_window_and_its_keys(self):
        now = datetime.now(UTC)
        two_hours_ago = now - timedelta(hours=2)
        for project in (self.SHORT, self.LONG):
            self._case("coder_finalized", created_at=now - timedelta(days=1),
                       updated_at=two_hours_ago, project=project)
        scope = self._scope(self.SHORT, self.LONG)

        with self.app.test_request_context(), \
                mock.patch.object(dm_kpi_workflow, "dm_scope", return_value=scope), \
                mock.patch.object(dm_kpi_workflow, "cached_kpi", side_effect=lambda _k, fn: fn()):
            body = dm_kpi_workflow.stagnation.__wrapped__().get_json()

        self.assertEqual(set(body), {"alerts", "total_stagnant_gt_48h", "total_stagnant_gt_7d"})
        alert = next(a for a in body["alerts"] if a["state"] == "coder_finalized")
        # 2 h is beyond the SHORT project's window only: one warning, not 24 h.
        self.assertEqual((alert["total"], alert["alert_count"], alert["alert_level"]), (2, 1, "warning"))
        self.assertEqual(alert["beyond_window"], 1)
        self.assertTrue({"state", "label", "total", "gt_48h", "gt_7d", "gt_30d",
                         "p50_age_hours", "alert_level", "dm_action"} <= set(alert))
        self.assertIn("recode window", alert["dm_action"])
        self.assertNotIn("24h", alert["dm_action"])

    def test_burndown_projected_start_is_the_first_case_day_on_the_project_clock(self):
        # 20:00 UTC on 1 Jan is 01:30 IST on 2 Jan: the projected line starts on the project's day.
        self._case("ready_for_coding", created_at=datetime(2000, 1, 1, 20, 0, tzinfo=UTC))
        project = db.session.get(VaProjectMaster, self.SHORT)
        project.project_target_completion_date = datetime(2000, 1, 5).date()
        db.session.commit()
        scope = self._scope(self.SHORT)
        try:
            with self.app.test_request_context(), \
                    mock.patch.object(dm_kpi_burndown, "dm_scope", return_value=scope), \
                    mock.patch.object(dm_kpi_burndown, "cached_kpi", side_effect=lambda _k, fn: fn()):
                body = dm_kpi_burndown.burndown.__wrapped__().get_json()
        finally:
            project.project_target_completion_date = None
            db.session.commit()

        self.assertTrue(body["c18_burndown_available"])
        self.assertEqual(body["c18_projected"][0]["date"], "2000-01-02")

    def test_review_rate_denominator_follows_the_projects_recode_window(self):
        finalized_at = datetime.now(UTC) - timedelta(hours=2)
        for project in (self.SHORT, self.LONG):
            self._case("coder_finalized", created_at=finalized_at - timedelta(hours=1),
                       updated_at=finalized_at, project=project, events=[
                           ("coder_finalized", "coding_in_progress", "coder_finalized", finalized_at),
                       ])
        dm = self._get_or_make_user(f"kfl.dm.{uuid.uuid4().hex[:8]}@test.local", "LiveFlow123")
        for project in (self.SHORT, self.LONG):
            db.session.add(VaUserAccessGrants(
                user_id=dm.user_id, role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project, project_id=project,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()
        self._login(str(dm.user_id))

        response = self.client.get("/api/v1/analytics/dm-kpi/pipeline/reviewed")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        # Only the 60-minute project's case has left its window.
        self.assertEqual(response.get_json()["eligible"], 1)

    def test_unsupported_breakdowns_are_refused(self):
        for compute, kwargs in (
            (compute_c01, {"period": 8}), (compute_c04, {}), (compute_c19, {}), (compute_c08, {}),
        ):
            with self.subTest(compute=compute.__name__), self.assertRaises(ValueError):
                compute(self._scope(), by="unit", **kwargs)
        with self.assertRaises(ValueError):
            compute_c07(self._scope(), by="unit")
        self._login(str(self.base_admin_user.user_id))
        response = self.client.get("/api/v1/analytics/dm-kpi/pipeline/aging?by=unit")
        self.assertEqual(response.status_code, 400)

    # -- Days follow the project clock (digitva-apee) ------------------------

    def _finalized_at(self, project, at, *, actor=None):
        """A coded case of *project* whose coding started 10 minutes before *at*."""
        return self._case("coder_finalized", project=project, created_at=at - timedelta(hours=1), events=[
            ("coding_started", "ready_for_coding", "coding_in_progress", at - timedelta(minutes=10)),
            ("coder_finalized", "coding_in_progress", "coder_finalized", at),
        ])

    def test_an_event_at_2330_utc_lands_on_each_projects_own_day(self):
        # Wednesday 12 March 2031, 15:00 UTC: 20:30 in Kolkata, 11:00 in New York.
        now = datetime(2031, 3, 12, 15, 0, tzinfo=UTC)
        late = datetime(2031, 3, 10, 23, 30, tzinfo=UTC)  # 05:00 on the 11th in Kolkata
        for project in (self.SHORT, self.UTC_P, self.NY_P):
            self._finalized_at(project, late)
        all_three = self._scope(self.SHORT, self.UTC_P, self.NY_P)

        statements = []

        def record(_conn, _cursor, statement, *_args):
            if not statement.startswith(("SAVEPOINT", "RELEASE SAVEPOINT")):  # the test harness's
                statements.append(statement)

        from sqlalchemy import event
        with mock.patch("app.services.project_clock._now", return_value=now):
            event.listen(db.engine, "before_cursor_execute", record)
            try:
                grid = compute_c01(all_three, 8)["data"]
            finally:
                event.remove(db.engine, "before_cursor_execute", record)
            singles = {
                p: self._by_date(compute_c01(self._scope(p), 8)["data"])
                for p in (self.SHORT, self.UTC_P, self.NY_P)
            }
            flow = self._by_date(compute_c19(all_three, 7)["data"])

        # Three queries as before, plus the scope's project zones once.
        self.assertEqual(len(statements), 4, [" ".join(s.split())[:90] for s in statements])
        rows = self._by_date(grid)
        self.assertEqual(grid[0]["date"], "2031-03-12")
        # The sum of each project's local day.
        self.assertEqual(rows["2031-03-11"]["coded"], 1)
        self.assertEqual(rows["2031-03-10"]["coded"], 2)
        self.assertEqual(rows["2031-03-11"]["new_from_odk"], 1)  # created 22:30 UTC
        self.assertEqual(rows["2031-03-10"]["new_from_odk"], 2)
        self.assertEqual(flow["2031-03-11"]["outflow"], 1)
        self.assertEqual(flow["2031-03-10"]["outflow"], 2)
        self.assertEqual(singles[self.SHORT]["2031-03-11"]["coded"], 1)
        self.assertEqual(singles[self.SHORT]["2031-03-10"]["coded"], 0)
        for project in (self.UTC_P, self.NY_P):
            self.assertEqual(singles[project]["2031-03-10"]["coded"], 1, project)
            self.assertEqual(singles[project]["2031-03-11"]["coded"], 0, project)

    def test_today_and_last_7_days_are_each_projects_own(self):
        # Thursday 12 June 2031, 15:00 UTC: today is the 12th in all three zones.
        now = datetime(2031, 6, 12, 15, 0, tzinfo=UTC)
        # 03:00 UTC on the 12th: today in Kolkata and UTC, 23:00 on the 11th in New York.
        early = datetime(2031, 6, 12, 3, 0, tzinfo=UTC)
        # 02:00 UTC on the 6th: the first of the last 7 days in Kolkata (07:30)
        # and UTC, 22:00 on the 5th in New York, a day outside its window.
        edge = datetime(2031, 6, 6, 2, 0, tzinfo=UTC)
        for project in (self.SHORT, self.UTC_P, self.NY_P):
            self._finalized_at(project, early)
            self._finalized_at(project, edge)
        all_three = self._scope(self.SHORT, self.UTC_P, self.NY_P)

        with mock.patch("app.services.project_clock._now", return_value=now):
            today_all = compute_c08(all_three, 1)["count"]
            week_all = compute_c08(all_three, 7)["count"]
            today_ny = compute_c08(self._scope(self.NY_P), 1)["count"]
            week_ny = compute_c08(self._scope(self.NY_P), 7)["count"]
            today_utc = compute_c08(self._scope(self.UTC_P), 1)["count"]

        self.assertEqual(today_utc, 1)
        self.assertEqual(today_ny, 0)
        self.assertEqual(today_all, 2)
        self.assertEqual(week_ny, 1)
        self.assertEqual(week_all, 5)

    def test_the_viewers_timezone_does_not_move_a_coders_day(self):
        from app.services.data_management_service import dm_coder_daily_statistics

        now = datetime(2031, 9, 10, 15, 0, tzinfo=UTC)
        late = datetime(2031, 9, 8, 23, 30, tzinfo=UTC)  # the 9th in Kolkata, the 8th in UTC
        admin = self.base_admin_user
        for project in (self.SHORT, self.UTC_P):
            sid = self._finalized_at(project, late)
            db.session.execute(
                VaSubmissionWorkflowEvent.__table__.update()
                .where(VaSubmissionWorkflowEvent.va_sid == sid)
                .values(actor_user_id=admin.user_id)
            )
        db.session.commit()

        def daily(project, viewer_tz):
            admin.timezone = viewer_tz
            db.session.commit()
            with mock.patch("app.services.project_clock._now", return_value=now):
                result = dm_coder_daily_statistics(admin, project=project, days=7)
            row = next(r for r in result["rows"] if r["coder_id"] == str(admin.user_id))
            return row["daily"], result["timezone"]

        try:
            for viewer_tz in ("Asia/Kolkata", "America/Los_Angeles"):
                kolkata, label = daily(self.SHORT, viewer_tz)
                # The admin holds every project, in more than one zone.
                self.assertEqual(label, "project time zones")
                self.assertEqual((kolkata["2031-09-09"], kolkata["2031-09-08"]), (1, 0), viewer_tz)
                utc, _ = daily(self.UTC_P, viewer_tz)
                self.assertEqual((utc["2031-09-08"], utc["2031-09-09"]), (1, 0), viewer_tz)
        finally:
            admin.timezone = "Asia/Kolkata"
            db.session.commit()

    def test_project_clock_windows_parse_and_bind_on_every_route(self):
        """Each text-SQL window moved onto the project clock, through its route.
        The critical path reads the analytics MV, which this class does not
        build; tests/routes/test_dm_kpi_outcomes.py runs it."""
        today = datetime.now(IST).date()
        sid = self._finalized_at(self.UTC_P, _ist(today, 8))
        db.session.execute(
            VaSubmissionWorkflowEvent.__table__.update()
            .where(VaSubmissionWorkflowEvent.va_sid == sid)
            .values(actor_user_id=self.base_admin_user.user_id)
        )
        project = db.session.get(VaProjectMaster, self.UTC_P)
        project.project_target_completion_date = today + timedelta(days=30)
        db.session.commit()
        self._login(str(self.base_admin_user.user_id))
        base = "/api/v1/analytics/dm-kpi"
        try:
            for path, key in (
                ("/pipeline/reviewer-throughput", "last_7d"),
                ("/pipeline/upstream-changes", "d_wt_04_reopened_7d"),
                ("/pipeline/time-to-code?range=today", "count"),
                ("/pipeline/time-to-code", "count"),
                ("/sync/latency?range=today", "count"),
                ("/sync/latency", "count"),
                ("/workflow/state-velocity?days=7", "states"),
                ("/workflow/daily-transitions?days=7", "days"),
                ("/coders/output?range=7d", "heatmap"),
                ("/language/pendency", None),
                ("/burndown/", "c16_total_coded_7d"),
                ("/grid/?days=8", "data"),
            ):
                with self.subTest(path=path):
                    response = self.client.get(base + path)
                    self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                    if key:
                        self.assertIn(key, response.get_json())
        finally:
            project.project_target_completion_date = None
            db.session.commit()
