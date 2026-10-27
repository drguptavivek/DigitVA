"""Live KPI flow, time to code and aging (digitva-0hul step 2, digitva-r5s0 2a/2b).

docs/policy/kpis.md: canonical definitions, C-01, C-04, C-19, C-07, C-08.
Every figure is computed live from workflow events; days are the viewer's
(Asia/Kolkata here unless a test says otherwise). The compute functions are
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
    SITES = {SHORT: "KF01", LONG: "KF02"}
    FORMS = {SHORT: "KFL001KF0101", LONG: "KFL002KF0201"}

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

    def _scope(self, *projects, tz="Asia/Kolkata"):
        projects = projects or (self.SHORT,)
        return DmScope(pairs=sorted((p, self.SITES[p]) for p in projects), unit_ids=[], tz=tz)

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

        utc = self._by_date(compute_c01(self._scope(tz="UTC"), 8)["data"])
        self.assertEqual(utc[utc_day.isoformat()]["coded"], 1)
        self.assertEqual(utc[next_day]["coded"], 0)

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

    def test_burndown_projected_start_is_the_first_case_day_in_the_viewers_timezone(self):
        # 20:00 UTC on 1 Jan is 01:30 IST on 2 Jan: the projected line starts on the viewer's day.
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
