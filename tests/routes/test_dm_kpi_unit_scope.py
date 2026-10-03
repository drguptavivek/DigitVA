"""DM KPI panels for unit-scoped data managers (digitva-m5r).

A data_manager grant at an organization unit counts the submissions whose
``va_submissions.org_unit_id`` lies in its subtree on every
``/api/v1/analytics/dm-kpi/*`` panel, and nothing from a sibling unit of the
same site. A project/site DM keeps its results; a DM holding both kinds sees
the union with no submission counted twice, including where the site-keyed
``va_daily_kpi_aggregates`` are combined with live unit figures. Policy:
docs/policy/access-control-model.md, "Role To Scope Rules"; design notes in
app/routes/api/dm_kpi/dm_kpi_scope.py.

The fixture is the coding-scope tree project (District > CHC > PHC A / PHC B,
one site CS01): both PHCs share one site and one form, so only the unit
predicate can tell their submissions apart.
"""
import uuid
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa

from app import cache, db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDailyKpiAggregates,
    VaFinalAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
)
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture


class DmKpiUnitScopeTests(UnitScopeFixture, BaseTestCase):

    def setUp(self):
        super().setUp()
        _, _, _, self.phc_a, self.phc_b = self._tree()

    # -- fixtures ----------------------------------------------------------

    def _seed_coded(self, sid, unit, finalized_at=None, form_id=None):
        """One coded submission in *unit* with the rows every KPI group reads."""
        finalized_at = finalized_at or datetime.now(UTC) - timedelta(minutes=30)
        self._sub(sid, unit=unit, form_id=form_id)
        submission = db.session.get(VaSubmissions, sid)
        submission.va_odk_reviewstate = "hasIssues"
        submission.va_submission_date = finalized_at - timedelta(hours=4)
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid == sid
        ).values(workflow_state=WORKFLOW_CODER_FINALIZED))
        coder_id = self.base_coder_user.user_id
        db.session.add_all([
            VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id="smartva_completed",
                previous_state="smartva_pending", current_state="ready_for_coding",
                actor_kind="system", actor_role="vasystem", transition_reason="test_seed",
                event_created_at=finalized_at - timedelta(minutes=20),
            ),
            VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id="coding_started",
                previous_state="ready_for_coding", current_state="coding_in_progress",
                actor_kind="user", actor_role="vacoder", actor_user_id=coder_id,
                transition_reason="test_seed",
                event_created_at=finalized_at - timedelta(minutes=10),
            ),
            VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id="coder_finalized",
                previous_state="coding_in_progress", current_state=WORKFLOW_CODER_FINALIZED,
                actor_kind="user", actor_role="vacoder", actor_user_id=coder_id,
                transition_reason="test_seed", event_created_at=finalized_at,
            ),
            VaFinalAssessments(
                va_sid=sid, va_finassess_by=coder_id,
                va_conclusive_cod="I21-Acute myocardial infarction",
                va_finassess_status=VaStatuses.active,
            ),
            VaAllocations(
                va_sid=sid, va_allocated_to=coder_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            ),
        ])
        db.session.commit()

    def _unique(self, label):
        return f"{label}.{uuid.uuid4().hex[:8]}@test.local"

    def _unit_dm(self, unit):
        return self._user_with(self._unique("kpi.unit.dm"), VaAccessRoles.data_manager, unit)

    def _add_site_grant(self, user, project_id, site_id):
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == project_id, VaProjectSites.site_id == site_id,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def _site_dm(self, project_id=None, site_id=None):
        user = self._get_or_make_user(self._unique("kpi.site.dm"), "UnitScope123")
        self._add_site_grant(user, project_id or self.PROJECT, site_id or self.SITE)
        return user

    def _kpi(self, user, path):
        self._login(str(user.user_id))
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _counts(self, user):
        """One submission-count figure per KPI module."""
        get = lambda path: self._kpi(user, path)  # noqa: E731
        english = [
            d["count"] for d in get("language/distribution")["distribution"]
            if d["language"] == "English"
        ]
        return {
            "pipeline.coding_pool": get("pipeline/pending")["coding_pool"],
            "pipeline.outflow": sum(d["outflow"] for d in get("pipeline/inflow-outflow")["data"]),
            "pipeline.time_to_code": get("pipeline/time-to-code")["count"],
            "workflow.total_synced": get("workflow/flowchart")["total_synced"],
            "coders.output": get("coders/output")["total"],
            "exclusions.all_synced": get("exclusions/rates")["all_synced"],
            "exclusions.odk_issues": get("exclusions/odk-issues")["total"],
            "language.english": sum(english),
            "sync.latency": get("sync/latency")["count"],
            "grid.coded": sum(d["coded"] for d in get("grid/")["data"]),
            "burndown.coded_7d": get("burndown/")["c16_total_coded_7d"],
        }

    def _expect_all(self, counts, value):
        for name, count in counts.items():
            with self.subTest(kpi=name):
                self.assertEqual(count, value)

    # -- scope -------------------------------------------------------------

    def test_unit_dm_counts_its_subtree_and_not_a_sibling_unit_of_the_same_site(self):
        self._seed_coded("csc-kpi-in", self.phc_a)
        self._seed_coded("csc-kpi-sibling", self.phc_b)

        # Guard: a site DM sees both, so a 1 below is the unit predicate at work.
        self._expect_all(self._counts(self._site_dm()), 2)
        self._expect_all(self._counts(self._unit_dm(self.phc_a)), 1)

    def test_unit_dm_with_nothing_in_its_subtree_sees_zero_not_the_site(self):
        self._seed_coded("csc-kpi-sibling-only", self.phc_b)
        self._expect_all(self._counts(self._unit_dm(self.phc_a)), 0)

    def test_unit_dm_skips_a_subtree_submission_on_a_deactivated_pair(self):
        # digitva-26pg: the grid stops at a deactivated (project, site) pair
        # for unit grants too, so the KPI cards must.
        pair = self._inactive_pair_form()
        self._seed_coded("csc-kpi-pair-active", self.phc_a)
        self._seed_coded(
            "csc-kpi-pair-inactive", self.phc_a, form_id=self.INACTIVE_PAIR_FORM_ID
        )

        # Guard: with the pair active both count, so the 1 below is the pair rule.
        pair.project_site_status = VaStatuses.active
        db.session.commit()
        self._expect_all(self._counts(self._unit_dm(self.phc_a)), 2)

        pair.project_site_status = VaStatuses.deactive
        db.session.commit()
        self._expect_all(self._counts(self._unit_dm(self.phc_a)), 1)
        in_charge = self._user_with(
            self._unique("kpi.incharge"), VaAccessRoles.site_pi, self.phc_a
        )
        self._expect_all(self._counts(in_charge), 1)

    def test_mixed_dm_counts_a_submission_in_both_scopes_once(self):
        self._seed_coded("csc-kpi-both", self.phc_a)
        self._seed_coded("csc-kpi-site-only", self.phc_b)
        mixed = self._unit_dm(self.phc_a)
        self._add_site_grant(mixed, self.PROJECT, self.SITE)

        self._expect_all(self._counts(mixed), 2)

    def test_mixed_dm_gets_the_union_of_a_direct_site_and_a_unit_elsewhere(self):
        self._ensure_base_research_project_and_site()
        self._seed_coded("csc-kpi-unit-part", self.phc_a)
        self._seed_coded("csc-kpi-not-mine", self.phc_b)
        mixed = self._unit_dm(self.phc_a)
        self._add_site_grant(mixed, self.BASE_PROJECT_ID, self.BASE_SITE_ID)

        # The base site holds no submissions here, so the union is the unit part.
        self._expect_all(self._counts(mixed), 1)

    def test_unit_dm_coder_counts_include_its_projects_coders(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._sub("csc-kpi-gap-pending", unit=self.phc_a)
        dm = self._unit_dm(self.phc_a)

        gap = self._kpi(dm, "language/gap")
        english = [lang for lang in gap["languages"] if lang["language"] == "English"]
        self.assertEqual(len(english), 1)
        self.assertGreaterEqual(english[0]["coders_available"], 1)
        self.assertFalse(english[0]["gap"])
        self.assertGreaterEqual(self._kpi(dm, "coders/utilization")["total_coders"], 1)

    # -- aggregate panels --------------------------------------------------

    def _aggregate(self, site_id, project_id, day, coded, pending=0):
        db.session.add(VaDailyKpiAggregates(
            snapshot_date=day, site_id=site_id, project_id=project_id,
            total_submissions=10, new_from_odk=0, updated_from_odk=0,
            coded_count=coded, pending_count=pending,
            consent_refused_count=0, not_codeable_count=0,
        ))
        db.session.commit()

    def _grid_day(self, user, day):
        rows = {r["date"]: r for r in self._kpi(user, "grid/")["data"]}
        self.assertIn(str(day), rows)
        return rows[str(day)]

    def test_aggregates_for_a_direct_site_add_the_unit_part_live(self):
        self._ensure_base_research_project_and_site()
        yesterday = date.today() - timedelta(days=1)
        at_noon = datetime.combine(yesterday, time(12), UTC)
        self._aggregate(self.BASE_SITE_ID, self.BASE_PROJECT_ID, yesterday, coded=5, pending=7)
        self._seed_coded("csc-kpi-agg-unit", self.phc_a, finalized_at=at_noon)
        self._seed_coded("csc-kpi-agg-sibling", self.phc_b, finalized_at=at_noon)
        ready = self._sub("csc-kpi-agg-ready", unit=self.phc_a)
        self.assertIsNotNone(ready)

        mixed = self._unit_dm(self.phc_a)
        self._add_site_grant(mixed, self.BASE_PROJECT_ID, self.BASE_SITE_ID)
        site_only = self._site_dm(self.BASE_PROJECT_ID, self.BASE_SITE_ID)

        self.assertEqual(self._grid_day(site_only, yesterday)["coded"], 5)
        self.assertEqual(self._grid_day(mixed, yesterday)["coded"], 6)
        self.assertEqual(self._kpi(site_only, "burndown/")["c16_total_coded_7d"], 5)
        self.assertEqual(self._kpi(mixed, "burndown/")["c16_total_coded_7d"], 6)

        trend = self._kpi(mixed, "pipeline/backlog-trend")
        self.assertEqual(trend["source"], "aggregates")
        by_day = {r["date"]: r["pending"] for r in trend["data"]}
        self.assertEqual(by_day[str(yesterday)], 7)
        self.assertEqual(by_day[str(date.today())], 1)

    def test_aggregates_do_not_double_count_a_unit_inside_a_direct_site(self):
        yesterday = date.today() - timedelta(days=1)
        at_noon = datetime.combine(yesterday, time(12), UTC)
        # The aggregate row already includes the PHC A submission's coding.
        self._aggregate(self.SITE, self.PROJECT, yesterday, coded=5)
        self._seed_coded("csc-kpi-agg-inside", self.phc_a, finalized_at=at_noon)
        mixed = self._unit_dm(self.phc_a)
        self._add_site_grant(mixed, self.PROJECT, self.SITE)

        self.assertEqual(self._grid_day(mixed, yesterday)["coded"], 5)
        self.assertEqual(self._kpi(mixed, "burndown/")["c16_total_coded_7d"], 5)

    def test_unit_dm_burndown_achieved_line_is_computed_live(self):
        project = db.session.get(VaProjectMaster, self.PROJECT)
        project.project_target_completion_date = date.today() + timedelta(days=30)
        db.session.commit()
        self._seed_coded("csc-kpi-burn-in", self.phc_a)
        self._seed_coded("csc-kpi-burn-sibling", self.phc_b)

        burndown = self._kpi(self._unit_dm(self.phc_a), "burndown/")

        self.assertTrue(burndown["c18_burndown_available"])
        self.assertEqual(burndown["c18_achieved"][-1]["cumulative_coded"], 1)
        self.assertEqual(burndown["c18_achieved"][-1]["remaining_achieved"], 0)

    # -- cache -------------------------------------------------------------

    def test_cache_is_keyed_on_the_unit_scope(self):
        self._seed_coded("csc-kpi-cache-a", self.phc_a)
        self._seed_coded("csc-kpi-cache-b", self.phc_b)
        dm_a = self._unit_dm(self.phc_a)
        dm_b = self._unit_dm(self.phc_b)

        def pool(user):
            return self._kpi(user, "pipeline/pending")["coding_pool"]

        self.assertEqual(pool(dm_a), 1)
        self.assertTrue(
            cache.cache._write_client.keys(f"*dm_kpi:{dm_a.user_id}:*"),
            "KPI cache is not storing entries; the scope-key check below would be vacuous",
        )
        self.assertEqual(pool(dm_b), 1)

        # Widening dm_a's grants changes its scope, so the cached 1 is not served.
        db.session.add(VaUserAccessGrants(
            user_id=dm_a.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.phc_b.org_unit_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertEqual(pool(dm_a), 2)
