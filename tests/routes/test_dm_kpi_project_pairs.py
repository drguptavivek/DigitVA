"""DM KPI panels key direct scope on (project_id, site_id) pairs (digitva-lh1h).

A site_id is shared across projects. A data manager granted on (P1, S1) must
see P1's figures at S1 and nothing of P2's forms at the same S1, on the live
panels, on the site-keyed daily aggregates (one row per site mixes every
project there, so a shared site is never served from them), and through the
KPI cache (two such managers must never share a cache entry).
"""
import uuid
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDailyKpiAggregates,
    VaFinalAssessments,
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
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase


class DmKpiProjectPairTests(BaseTestCase):
    SITE = "LH01"
    P1, P2 = "LHA001", "LHB001"
    FORMS = {P1: "LHA001LH0101", P2: "LHB001LH0101"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(
            site_id=cls.SITE, site_abbr=cls.SITE, site_name="Shared Site",
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        for project_id in (cls.P1, cls.P2):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id,
                project_name=project_id, project_nickname=project_id,
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.add(VaResearchProjects(
                project_id=project_id, project_code=project_id,
                project_name=project_id, project_nickname=project_id,
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE, project_id=cls.P1, site_name="Shared Site",
            site_abbr=cls.SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        for project_id, form_id in cls.FORMS.items():
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=cls.SITE,
                odk_form_id=f"LH_{project_id}", odk_project_id="93",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _seed_coded(self, sid, form_id, finalized_at=None):
        finalized_at = finalized_at or datetime.now(UTC) - timedelta(minutes=30)
        coder_id = self.base_coder_user.user_id
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form_id,
            va_submission_date=finalized_at - timedelta(hours=4),
            va_odk_updatedat=finalized_at - timedelta(hours=4),
            va_data_collector="Collector", va_instance_name=sid,
            va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language="English", va_deceased_age=42,
            va_deceased_gender="male", va_summary=[], va_catcount={},
            va_category_list=[], va_odk_reviewstate="hasIssues",
        ))
        db.session.flush()
        db.session.add_all([
            VaSubmissionWorkflow(
                va_sid=sid, workflow_state=WORKFLOW_CODER_FINALIZED,
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ),
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

    def _pair_dm(self, project_id):
        user = self._get_or_make_user(
            f"lh1h.dm.{uuid.uuid4().hex[:8]}@test.local", "PairScope123"
        )
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == project_id, VaProjectSites.site_id == self.SITE,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _project_dm(self, project_id):
        user = self._get_or_make_user(
            f"lh1h.pdm.{uuid.uuid4().hex[:8]}@test.local", "PairScope123"
        )
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=project_id,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _kpi(self, user, path):
        self._login(str(user.user_id))
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _counts(self, user):
        get = lambda path: self._kpi(user, path)  # noqa: E731
        return {
            "pipeline.time_to_code": get("pipeline/time-to-code")["count"],
            "pipeline.outflow": sum(d["outflow"] for d in get("pipeline/inflow-outflow")["data"]),
            "workflow.total_synced": get("workflow/flowchart")["total_synced"],
            "coders.output": get("coders/output")["total"],
            "exclusions.all_synced": get("exclusions/rates")["all_synced"],
            "sync.latency": get("sync/latency")["count"],
            "grid.coded": sum(d["coded"] for d in get("grid/")["data"]),
            "burndown.coded_7d": get("burndown/")["c16_total_coded_7d"],
        }

    def _expect_all(self, counts, value):
        for name, count in counts.items():
            with self.subTest(kpi=name):
                self.assertEqual(count, value)

    def _aggregate(self, day, coded):
        db.session.add(VaDailyKpiAggregates(
            snapshot_date=day, site_id=self.SITE, project_id=self.P1,
            total_submissions=10, new_from_odk=0, updated_from_odk=0,
            coded_count=coded, pending_count=0,
            consent_refused_count=0, not_codeable_count=0,
        ))
        db.session.commit()

    # -- tests -------------------------------------------------------------

    def test_pair_dm_counts_its_project_and_not_the_other_project_at_the_same_site(self):
        self._seed_coded("lh1h-p1", self.FORMS[self.P1])
        self._seed_coded("lh1h-p2", self.FORMS[self.P2])

        self._expect_all(self._counts(self._pair_dm(self.P1)), 1)

    def test_project_dm_counts_its_project_only_at_a_shared_site(self):
        self._seed_coded("lh1h-proj-p1", self.FORMS[self.P1])
        self._seed_coded("lh1h-proj-p2", self.FORMS[self.P2])

        self._expect_all(self._counts(self._project_dm(self.P2)), 1)

    def test_a_shared_site_aggregate_row_is_not_served_to_one_projects_dm(self):
        yesterday = date.today() - timedelta(days=1)
        at_noon = datetime.combine(yesterday, time(12), UTC)
        # The stored row mixes both projects at the site (kpi_tasks counts by site).
        self._aggregate(yesterday, coded=2)
        self._seed_coded("lh1h-agg-p1", self.FORMS[self.P1], finalized_at=at_noon)
        self._seed_coded("lh1h-agg-p2", self.FORMS[self.P2], finalized_at=at_noon)
        dm = self._pair_dm(self.P1)

        rows = {r["date"]: r for r in self._kpi(dm, "grid/")["data"]}
        self.assertIn(str(yesterday), rows)
        self.assertEqual(rows[str(yesterday)]["coded"], 1)
        self.assertEqual(self._kpi(dm, "burndown/")["c16_total_coded_7d"], 1)

    def test_a_dm_on_every_project_at_the_site_reads_the_aggregate_row(self):
        yesterday = date.today() - timedelta(days=1)
        self._aggregate(yesterday, coded=5)
        dm = self._pair_dm(self.P1)
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == self.P2, VaProjectSites.site_id == self.SITE,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()

        rows = {r["date"]: r for r in self._kpi(dm, "grid/")["data"]}
        self.assertEqual(rows[str(yesterday)]["coded"], 5)

    def test_moving_a_grant_to_the_same_site_in_another_project_misses_the_cache(self):
        from app import cache

        self._seed_coded("lh1h-cache-p1", self.FORMS[self.P1])
        dm = self._pair_dm(self.P1)
        self.assertEqual(self._kpi(dm, "pipeline/time-to-code")["count"], 1)
        self.assertTrue(
            cache.cache._write_client.keys(f"*dm_kpi:{dm.user_id}:*"),
            "KPI cache is not storing entries; the check below would be vacuous",
        )

        db.session.execute(sa.update(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == dm.user_id,
        ).values(grant_status=VaStatuses.deactive))
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == self.P2, VaProjectSites.site_id == self.SITE,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()

        # Same site id, other project: the cached P1 figure must not be served.
        self.assertEqual(self._kpi(dm, "pipeline/time-to-code")["count"], 0)

    def test_scope_digest_differs_for_the_same_site_in_different_projects(self):
        from app.routes.api.dm_kpi.dm_kpi_scope import DmScope

        p1 = DmScope(pairs=[(self.P1, self.SITE)], unit_ids=[], aggregate_site_ids=[])
        p2 = DmScope(pairs=[(self.P2, self.SITE)], unit_ids=[], aggregate_site_ids=[])
        self.assertNotEqual(p1.digest(), p2.digest())
