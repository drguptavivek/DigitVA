"""Retired-from-ODK submissions must not be counted by any DM KPI endpoint.

Policy: docs/policy/odk-retired-submissions.md and docs/policy/kpis.md
("Retired from ODK is a scope-wide exclusion").  One test per module in
app/routes/api/dm_kpi/: the class seeds two submissions that are identical
in every respect except that one carries `va_sync_issue_code =
'missing_in_odk'`, so any endpoint that still counts the retired row reports
2 where it should report 1.

The one KPI that deliberately keeps counting them, D-SH-03 ("Missing in
ODK"), is served from the analytics MV rather than this package and is
covered by tests/services/test_submission_analytics_mv.py.
"""

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
    VaUsers,
)
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase


class DmKpiRetiredSubmissionTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}07"
    LIVE_SID = "uuid:dm-kpi-in-sync"
    RETIRED_SID = "uuid:dm-kpi-retired"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        cls._ensure_base_research_project_and_site()
        cls._create_daily_kpi_aggregates_table()

        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="DM_KPI_RETIRED_FORM",
                odk_project_id="71",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()

        cls._seed_submission(cls.LIVE_SID, now, sync_issue_code=None)
        cls._seed_submission(cls.RETIRED_SID, now, sync_issue_code="missing_in_odk")
        db.session.commit()

    @classmethod
    def _create_daily_kpi_aggregates_table(cls):
        """Create the columns the burndown KPIs read from the daily aggregates.

        ``va_daily_kpi_aggregates`` (migration d7e8f9a0b1c2) has no ORM model,
        so ``db.create_all()`` does not build it for the test schema and the
        burndown endpoint fails on a missing relation.  The table is created
        empty inside the class transaction — and rolled back with it — so the
        endpoint takes its live-SQL fallback, which is what this class tests.
        """
        db.session.execute(
            sa.text("""
                CREATE TABLE IF NOT EXISTS va_daily_kpi_aggregates (
                    snapshot_date DATE NOT NULL,
                    site_id VARCHAR(4) NOT NULL,
                    project_id VARCHAR(6) NOT NULL,
                    coded_count INTEGER,
                    pending_count INTEGER,
                    PRIMARY KEY (snapshot_date, site_id)
                )
            """)
        )
        db.session.flush()

    @classmethod
    def _seed_submission(cls, sid: str, now: datetime, sync_issue_code: str | None):
        """Seed one coded submission plus the rows every KPI group reads."""
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=cls.FORM_ID,
                va_submission_date=now - timedelta(minutes=30),
                va_odk_updatedat=now,
                va_odk_reviewstate="hasIssues",
                va_sync_issue_code=sync_issue_code,
                va_sync_issue_detail=(
                    "absent from the active ODK list" if sync_issue_code else None
                ),
                va_sync_issue_updated_at=now if sync_issue_code else None,
                va_data_collector="Collector",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=f"masked-{sid[-8:]}",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=55,
                va_deceased_gender="female",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state=WORKFLOW_CODER_FINALIZED,
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.add_all(
            [
                VaSubmissionWorkflowEvent(
                    va_sid=sid,
                    transition_id="smartva_completed",
                    previous_state="smartva_pending",
                    current_state="ready_for_coding",
                    actor_kind="system",
                    actor_role="vasystem",
                    transition_reason="test_seed",
                    event_created_at=now - timedelta(hours=3),
                ),
                VaSubmissionWorkflowEvent(
                    va_sid=sid,
                    transition_id="coding_started",
                    previous_state="ready_for_coding",
                    current_state="coding_in_progress",
                    actor_kind="user",
                    actor_role="vacoder",
                    actor_user_id=cls.base_coder_user.user_id,
                    transition_reason="test_seed",
                    event_created_at=now - timedelta(hours=2),
                ),
                VaSubmissionWorkflowEvent(
                    va_sid=sid,
                    transition_id="coder_finalized",
                    previous_state="coding_in_progress",
                    current_state=WORKFLOW_CODER_FINALIZED,
                    actor_kind="user",
                    actor_role="vacoder",
                    actor_user_id=cls.base_coder_user.user_id,
                    transition_reason="test_seed",
                    event_created_at=now - timedelta(hours=1),
                ),
            ]
        )
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                va_finassess_by=cls.base_coder_user.user_id,
                va_conclusive_cod="I21-Acute myocardial infarction",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=cls.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.flush()

    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex[:8]
        dm_user = VaUsers(
            user_id=uuid.uuid4(),
            name=f"dmkpi.{suffix}",
            email=f"dmkpi.{suffix}@example.com",
            vacode_language=["English"],
            permission={},
            landing_page="data_manager",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        dm_user.set_password("DataManager123")
        db.session.add(dm_user)
        db.session.flush()
        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=dm_user.user_id,
                role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="dm kpi retired grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(dm_user.user_id))

    def _kpi(self, path: str) -> dict:
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    # -- one test per module ------------------------------------------------

    def test_fixture_would_be_double_counted_without_the_predicate(self):
        """Guard: the per-module counts below are 1 only because of the filter.

        Without ``in_odk_sql()`` the same DM-scoped query over the same seed
        returns both submissions, so a count of 1 elsewhere in this class is
        evidence of the exclusion and not of a one-row fixture.
        """
        scoped = sa.text("""
            SELECT COUNT(*) FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
        """)
        in_odk = sa.text(f"""
            SELECT COUNT(*) FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND {in_odk_sql("s")}
        """)

        params = {"site_id": self.BASE_SITE_ID}
        self.assertEqual(db.session.scalar(scoped, params), 2)
        self.assertEqual(db.session.scalar(in_odk, {**IN_ODK_BIND, **params}), 1)

    def test_pipeline_counts_exclude_retired_submissions(self):
        pending = self._kpi("pipeline/pending")
        inflow = self._kpi("pipeline/inflow-outflow")
        time_to_code = self._kpi("pipeline/time-to-code")

        self.assertEqual(pending["coding_pool"], 1)
        self.assertEqual(sum(d["outflow"] for d in inflow["data"]), 1)
        self.assertEqual(sum(d["inflow"] for d in inflow["data"]), 1)
        self.assertEqual(time_to_code["count"], 1)

    def test_workflow_counts_exclude_retired_submissions(self):
        flowchart = self._kpi("workflow/flowchart")
        transitions = self._kpi("workflow/daily-transitions")

        self.assertEqual(flowchart["total_synced"], 1)
        self.assertEqual(flowchart["stages"]["coder_finalized"]["total"], 1)
        self.assertEqual(sum(d["total"] for d in transitions["days"]), 3)

    def test_coder_counts_exclude_retired_submissions(self):
        output = self._kpi("coders/output")
        # Roster selected a non-existent g.created_at column and 500ed until
        # fixed alongside the retirement predicate; assert it answers at all.
        roster = self._kpi("coders/roster")
        self.assertIsNotNone(roster)

        self.assertEqual(output["total"], 1)
        self.assertEqual([c["total"] for c in output["per_coder"]], [1])

    def test_exclusion_rates_exclude_retired_submissions(self):
        rates = self._kpi("exclusions/rates")
        odk_issues = self._kpi("exclusions/odk-issues")

        self.assertEqual(rates["all_synced"], 1)
        self.assertEqual(rates["coding_pool"], 1)
        self.assertEqual(odk_issues["total"], 1)
        self.assertEqual(odk_issues["count"], 1)

    def test_language_counts_exclude_retired_submissions(self):
        distribution = self._kpi("language/distribution")
        missing = self._kpi("language/missing")

        english = [d for d in distribution["distribution"] if d["language"] == "English"]
        self.assertEqual(english, [{"language": "English", "count": 1}])
        self.assertEqual(missing["total_coding_pool"], 1)

    def test_sync_latency_excludes_retired_submissions(self):
        latency = self._kpi("sync/latency")
        attachments = self._kpi("sync/attachment-health")

        self.assertEqual(latency["count"], 1)
        self.assertEqual(attachments["c14"]["total_past_smartva"], 1)

    def test_burndown_counts_exclude_retired_submissions(self):
        burndown = self._kpi("burndown/")

        self.assertEqual(burndown["c16_total_coded_7d"], 1)
        self.assertEqual(
            [r["coded_7d"] for r in burndown["c16_per_language"]], [1]
        )
