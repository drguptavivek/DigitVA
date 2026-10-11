"""Stored daily KPI "Not analysable" / "Not Codeable" are per-day event counts.

Policy: docs/policy/kpis.md, C-01. The stored columns used to count every
submission *currently* in the state (a running stock) while the live grid
counted that day's events (digitva-9uqn). ``flask kpi recount-day-events``
repairs rows written under the old definition.

Each assertion on a zero is preceded by the row it reads existing.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.commands.kpi import kpi
from app.models import (
    VaDeathRegister,
    VaForms,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
)
from app.routes.api.dm_kpi.dm_kpi_grid import _live_daily_counts
from app.services.odk_retirement_service import IN_ODK_BIND
from app.tasks.kpi_tasks import _compute_site_snapshot, recompute_kpi_days_for_submission
from tests.base import BaseTestCase

_COLUMNS = ("consent_refused_count", "not_codeable_count", "pending_count", "coded_count")


class DayEventCountTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}24"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
            odk_form_id="KPI_DAY_EVENTS", odk_project_id="75", form_type="WHO VA 2022",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        today = db.session.scalar(sa.text("SELECT CURRENT_DATE"))
        self.d1, self.d2, self.d3 = today - timedelta(days=10), today - timedelta(days=6), today - timedelta(days=3)
        self.runner = self.app.test_cli_runner()

    # ── helpers ────────────────────────────────────────────────────────────

    def _submission(self, state, *, events=(), out_of_odk=False, duplicate=False):
        """A submission now in *state*; *events* are (transition, resulting state, day)."""
        sid = f"uuid:kpide-{uuid.uuid4()}"
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now, va_odk_updatedat=now,
            va_data_collector="kpide", va_odk_reviewstate="approved", va_instance_name=sid,
            va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language="English", va_deceased_age=50, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
            va_sync_issue_code=IN_ODK_BIND["odk_missing_code"] if out_of_odk else None,
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=state))
        for transition, current, day in events:
            db.session.add(VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id=transition, previous_state="ready_for_coding",
                current_state=current,
                event_created_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12),
            ))
        if duplicate:
            number = db.session.scalar(
                sa.select(sa.func.coalesce(sa.func.max(VaDeathRegister.death_number), 0))
            ) + 1
            db.session.add(VaDeathRegister(
                project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID, death_number=number,
                unique_id=f"KPIDE-{uuid.uuid4().hex[:12]}", deceased_name="Asha Devi",
                deceased_sex="female", date_of_death=date.today() - timedelta(days=30),
                registered_by=self.base_coder_user.user_id, source="register",
                status="duplicate", va_sid=sid,
            ))
        db.session.commit()
        return sid

    def _refused(self, day, **kw):
        return self._submission("consent_refused", events=[("consent_refused", "consent_refused", day)], **kw)

    def _not_codeable(self, day, transition="coder_not_codeable", **kw):
        return self._submission("not_codeable_by_coder", events=[(transition, "not_codeable_by_coder", day)], **kw)

    def _snapshot(self, *days, keep=False):
        for day in days:
            _compute_site_snapshot(db, day, self.BASE_SITE_ID, keep_end_of_day=keep)

    def _stored(self, day, column):
        # column: hardcoded by the callers below
        return db.session.scalar(
            sa.text(f"SELECT {column} FROM va_daily_kpi_aggregates WHERE snapshot_date = :d AND site_id = :s"),
            {"d": day, "s": self.BASE_SITE_ID},
        )

    def _set(self, day, **columns):
        assignments = ", ".join(f"{c} = :{c}" for c in columns)  # column names: test literals
        db.session.execute(
            sa.text(f"UPDATE va_daily_kpi_aggregates SET {assignments} WHERE snapshot_date = :d AND site_id = :s"),
            {**columns, "d": day, "s": self.BASE_SITE_ID},
        )
        db.session.commit()

    def _row(self, day):
        return tuple(self._stored(day, c) for c in _COLUMNS)

    # ── stored counts ──────────────────────────────────────────────────────

    def test_a_later_day_does_not_count_an_earlier_days_refusal_or_not_codeable(self):
        self._refused(self.d1)
        self._not_codeable(self.d1)
        self._not_codeable(self.d1, transition="data_manager_not_codeable")
        self._snapshot(self.d1, self.d2)

        # Present first: D1 has its events ...
        self.assertEqual(self._stored(self.d1, "consent_refused_count"), 1)
        self.assertEqual(self._stored(self.d1, "not_codeable_count"), 2)
        # ... D2's row exists, and the still-refused submissions are not recounted on it.
        self.assertIsNotNone(self._stored(self.d2, "total_submissions"))
        self.assertEqual(self._stored(self.d2, "consent_refused_count"), 0)
        self.assertEqual(self._stored(self.d2, "not_codeable_count"), 0)

    def test_stored_day_matches_the_live_grid_count(self):
        self._refused(self.d1)
        self._not_codeable(self.d1)
        self._snapshot(self.d1)
        live = _live_daily_counts("f.site_id = :scope_site", {"scope_site": self.BASE_SITE_ID}, self.d1)

        self.assertEqual(live["consent_refused"][str(self.d1)], 1)
        self.assertEqual(live["not_codeable"][str(self.d1)], 1)
        self.assertEqual(self._stored(self.d1, "consent_refused_count"), live["consent_refused"][str(self.d1)])
        self.assertEqual(self._stored(self.d1, "not_codeable_count"), live["not_codeable"][str(self.d1)])

    def test_duplicates_and_retired_submissions_are_not_counted(self):
        self._refused(self.d1)
        self._not_codeable(self.d1)
        self._refused(self.d1, duplicate=True)
        self._not_codeable(self.d1, duplicate=True)
        self._refused(self.d1, out_of_odk=True)
        self._not_codeable(self.d1, out_of_odk=True)
        self._snapshot(self.d1)

        # Each kind has a counted row (1) and two excluded ones.
        self.assertEqual(self._stored(self.d1, "consent_refused_count"), 1)
        self.assertEqual(self._stored(self.d1, "not_codeable_count"), 1)

    def test_a_past_day_recomputed_keeping_end_of_day_refreshes_the_event_counts_only(self):
        self._refused(self.d1)
        self._snapshot(self.d1)
        self._set(self.d1, consent_refused_count=7, not_codeable_count=7, pending_count=999)

        self._snapshot(self.d1, keep=True)

        self.assertEqual(self._stored(self.d1, "pending_count"), 999)
        self.assertEqual(self._stored(self.d1, "consent_refused_count"), 1)
        self.assertEqual(self._stored(self.d1, "not_codeable_count"), 0)

    def test_confirming_a_duplicate_recounts_the_days_of_its_refusal_and_not_codeable_events(self):
        refused = self._refused(self.d1)
        self._not_codeable(self.d2)
        self._snapshot(self.d1, self.d2)
        self.assertEqual(self._stored(self.d1, "consent_refused_count"), 1)

        # Confirmed as a duplicate after the snapshot: only the recount task fixes the stored day.
        number = db.session.scalar(sa.select(sa.func.coalesce(sa.func.max(VaDeathRegister.death_number), 0))) + 1
        db.session.add(VaDeathRegister(
            project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID, death_number=number,
            unique_id=f"KPIDE-{uuid.uuid4().hex[:12]}", deceased_name="Asha Devi",
            deceased_sex="female", date_of_death=date.today() - timedelta(days=30),
            registered_by=self.base_coder_user.user_id, source="register",
            status="duplicate", va_sid=refused,
        ))
        db.session.commit()
        result = recompute_kpi_days_for_submission.run(refused)

        self.assertEqual(result["days_recomputed"], 1)
        self.assertEqual(self._stored(self.d1, "consent_refused_count"), 0)
        self.assertEqual(self._stored(self.d2, "not_codeable_count"), 1)

    # ── flask kpi recount-day-events ───────────────────────────────────────

    def _seed_stock_rows(self):
        self._refused(self.d1)
        self._not_codeable(self.d2)
        self._snapshot(self.d1, self.d2, self.d3)
        for day in (self.d1, self.d2, self.d3):
            self._set(day, consent_refused_count=5, not_codeable_count=5, pending_count=999, coded_count=42)

    def _run(self, *args):
        result = self.runner.invoke(kpi, ["recount-day-events", *args])
        self.assertEqual(result.exit_code, 0, result.output)
        return result.output

    def test_recount_fixes_rows_in_range_and_touches_nothing_else(self):
        self._seed_stock_rows()

        output = self._run("--from", str(self.d1), "--to", str(self.d2))

        self.assertIn("Updated 2 row(s)", output)
        # Fixed in range; every other column keeps the seeded value.
        self.assertEqual(self._row(self.d1), (1, 0, 999, 42))
        self.assertEqual(self._row(self.d2), (0, 1, 999, 42))
        # Out of range: untouched, and no row was inserted.
        self.assertEqual(self._row(self.d3), (5, 5, 999, 42))
        self.assertEqual(
            db.session.scalar(
                sa.text("SELECT COUNT(*) FROM va_daily_kpi_aggregates WHERE site_id = :s"),
                {"s": self.BASE_SITE_ID},
            ),
            3,
        )

    def test_recount_without_a_range_covers_every_stored_row_and_is_idempotent(self):
        self._seed_stock_rows()

        self.assertIn("Updated 3 row(s)", self._run())
        self.assertEqual(self._row(self.d3), (0, 0, 999, 42))
        self.assertIn("Updated 0 row(s)", self._run())

    def test_dry_run_reports_the_count_and_writes_nothing(self):
        self._seed_stock_rows()

        output = self._run("--dry-run", "--from", str(self.d1), "--to", str(self.d2))

        self.assertIn("2 row(s) would be updated", output)
        for day in (self.d1, self.d2, self.d3):
            self.assertEqual(self._row(day), (5, 5, 999, 42))

    def test_recount_rejects_a_reversed_range(self):
        output = self._run("--from", str(self.d2), "--to", str(self.d1))

        self.assertIn("--from date must be <= --to date", output)
