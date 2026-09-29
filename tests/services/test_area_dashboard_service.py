"""Area dashboard scope resolution and counts.

Rules under test live in app/services/area_dashboard_service.py, the unit
rollup in app/services/submission_analytics_mv.py and the bucket mapping in
app/services/workflow/definition.py. Policy: docs/policy/area-dashboard.md.
"""
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseContactAttempt,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
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
    VaWebIntakeDraft,
)
from app.services import area_dashboard_service as area
from app.services import organization_service as org
from app.services.submission_analytics_mv import (
    COD_MV_NAME,
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
)
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import (
    ALL_WORKFLOW_STATES,
    CODING_BUCKETS,
    WORKFLOW_CODING_BUCKETS,
    coding_bucket,
)
from tests.base import BaseTestCase

_ANALYTICS_MVS = (
    COD_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    CORE_MV_NAME,
    COD_SNAPSHOT_MV_NAME,
    "va_submission_analytics_mv",
)


class AreaDashboardFixture(BaseTestCase):
    """A tree project and a sites-mode project with routed submissions.

    Tree (ARDT01): District 1 > CHC A > PHC A1, District 1 > CHC B, and
    District 2. Sites-mode (ARDS01): sites AS01 and AS02. No test methods
    here, so importing it into another module collects nothing twice.
    """

    TREE = "ARDT01"
    TREE_SITE = "AR01"
    TREE_FORM = "ARDT01AR0101"
    SITES = "ARDS01"
    SITE_ONE = "AS01"
    SITE_TWO = "AS02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._make_project(cls.TREE, "organization", now)
        cls._make_project(cls.SITES, "sites", now)
        cls.tree_project_site = cls._make_site(cls.TREE, cls.TREE_SITE, cls.TREE_FORM, now)
        cls.site_one_ps = cls._make_site(cls.SITES, cls.SITE_ONE, "ARDS01AS0101", now)
        cls._make_site(cls.SITES, cls.SITE_TWO, "ARDS01AS0201", now)

        org.seed_default_organization(cls.TREE)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.TREE)}

        def unit(code, level, parent=None):
            return org.create_unit(
                cls.TREE,
                org_level_id=levels[level].org_level_id,
                parent_org_unit_id=parent.org_unit_id if parent else None,
                unit_code=code,
                unit_name=f"Unit {code}",
            )

        cls.district_1 = unit("AD1", "district")
        cls.chc_a = unit("ACA", "chc", cls.district_1)
        cls.phc_a1 = unit("APA", "phc", cls.chc_a)
        cls.chc_b = unit("ACB", "chc", cls.district_1)
        cls.chc_c = unit("ACC", "chc", cls.district_1)
        cls.district_2 = unit("AD2", "district")
        db.session.flush()

        # Tree submissions: 2 at PHC A1, 1 at CHC A itself, 1 at CHC B,
        # 1 in District 2, 2 unrouted.
        cls._submission("uuid:area-pa1", cls.TREE_FORM, cls.phc_a1, "ready_for_coding", 2)
        cls._submission("uuid:area-pa2", cls.TREE_FORM, cls.phc_a1, "smartva_pending", 20)
        cls._submission("uuid:area-ca1", cls.TREE_FORM, cls.chc_a, "coder_finalized", 60)
        cls._submission("uuid:area-cb1", cls.TREE_FORM, cls.chc_b, "coding_in_progress", 1)
        cls._submission("uuid:area-d21", cls.TREE_FORM, cls.district_2, "reviewer_coding_in_progress", 1)
        cls._submission("uuid:area-un1", cls.TREE_FORM, None, "not_codeable_by_coder", 1)
        cls._submission("uuid:area-un2", cls.TREE_FORM, None, None, 1)
        # Sites-mode submissions.
        cls._submission("uuid:area-s11", "ARDS01AS0101", None, "reviewer_finalized", 3)
        cls._submission("uuid:area-s21", "ARDS01AS0201", None, "consent_refused", 3)
        cls._submission("uuid:area-s22", "ARDS01AS0201", None, "ready_for_coding", 40)

        cls.interviewer = cls._get_or_make_user("area.interviewer@test.local", "AreaUser123")
        cls._draft(cls.TREE, cls.TREE_SITE, cls.TREE_FORM, cls.phc_a1, "draft")
        cls._draft(cls.TREE, cls.TREE_SITE, cls.TREE_FORM, cls.phc_a1, "submitted")
        cls._draft(cls.TREE, cls.TREE_SITE, cls.TREE_FORM, None, "draft")
        cls._draft(cls.SITES, cls.SITE_TWO, "ARDS01AS0201", None, "draft")

        for mv in _ANALYTICS_MVS:
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.execute(
            sa.text(f"CREATE UNIQUE INDEX ix_test_area_core_va_sid ON {CORE_MV_NAME} (va_sid)")
        )
        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(
            sa.text(f"CREATE UNIQUE INDEX ix_test_area_demo_va_sid ON {DEMOGRAPHICS_MV_NAME} (va_sid)")
        )
        db.session.commit()
        refresh_submission_analytics_mv_core_and_demographics()

        cls.unit_user = cls._get_or_make_user("area.unit@test.local", "AreaUser123")
        cls.overlap_user = cls._get_or_make_user("area.overlap@test.local", "AreaUser123")
        cls.project_user = cls._get_or_make_user("area.project@test.local", "AreaUser123")
        cls.site_user = cls._get_or_make_user("area.site@test.local", "AreaUser123")
        cls.sites_mode_site_user = cls._get_or_make_user("area.sitesmode@test.local", "AreaUser123")
        cls.no_grant_user = cls._get_or_make_user("area.nogrant@test.local", "AreaUser123")
        cls._grant(cls.unit_user, VaAccessRoles.coder, VaAccessScopeTypes.org_unit,
                   org_unit_id=cls.chc_a.org_unit_id)
        cls._grant(cls.overlap_user, VaAccessRoles.collaborator, VaAccessScopeTypes.org_unit,
                   org_unit_id=cls.district_1.org_unit_id)
        cls._grant(cls.overlap_user, VaAccessRoles.interviewer, VaAccessScopeTypes.org_unit,
                   org_unit_id=cls.phc_a1.org_unit_id)
        cls._grant(cls.project_user, VaAccessRoles.data_manager, VaAccessScopeTypes.project,
                   project_id=cls.TREE)
        cls._grant(cls.site_user, VaAccessRoles.reviewer, VaAccessScopeTypes.project_site,
                   project_site_id=cls.tree_project_site)
        cls._grant(cls.sites_mode_site_user, VaAccessRoles.site_pi, VaAccessScopeTypes.project_site,
                   project_site_id=cls.site_one_ps)
        cls._grant(cls.interviewer, VaAccessRoles.interviewer, VaAccessScopeTypes.org_unit,
                   org_unit_id=cls.chc_b.org_unit_id)
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            for mv in _ANALYTICS_MVS:
                db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
            db.session.commit()
        finally:
            super().tearDownClass()

    # -- fixture builders ----------------------------------------------------

    @classmethod
    def _make_project(cls, project_id, mode, now):
        for model in (VaResearchProjects, VaProjectMaster):
            kwargs = dict(
                project_id=project_id,
                project_code=project_id,
                project_name=f"Area {project_id}",
                project_nickname=project_id,
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
            if model is VaProjectMaster:
                kwargs["project_structure_mode"] = mode
            db.session.add(model(**kwargs))
            db.session.flush()

    @classmethod
    def _make_site(cls, project_id, site_id, form_id, now):
        common = dict(
            site_id=site_id,
            site_name=f"Area site {site_id}",
            site_abbr=site_id,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        )
        db.session.add(VaSites(project_id=project_id, **common))
        db.session.add(VaSiteMaster(**common))
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=form_id,
                project_id=project_id,
                site_id=site_id,
                odk_form_id=f"AREA_{form_id}",
                odk_project_id="31",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        project_site = VaProjectSites(
            project_id=project_id,
            site_id=site_id,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        )
        db.session.add(project_site)
        db.session.flush()
        return project_site.project_site_id

    @classmethod
    def _submission(cls, sid, form_id, unit, workflow_state, days_ago):
        submitted = datetime.now(UTC) - timedelta(days=days_ago)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=form_id,
                va_submission_date=submitted,
                va_odk_updatedat=submitted,
                va_data_collector="area",
                va_odk_reviewstate="reviewed",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=0,
                va_deceased_gender="female",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
                org_unit_id=unit.org_unit_id if unit else None,
                org_unit_resolution="manual" if unit else None,
            )
        )
        db.session.flush()
        if workflow_state is not None:
            db.session.add(
                VaSubmissionWorkflow(
                    va_sid=sid,
                    workflow_state=workflow_state,
                    workflow_reason="test",
                    workflow_updated_by_role="vasystem",
                )
            )
            db.session.flush()

    @classmethod
    def _draft(cls, project_id, site_id, form_id, unit, status):
        db.session.add(
            VaWebIntakeDraft(
                project_id=project_id,
                site_id=site_id,
                form_id=form_id,
                org_unit_id=unit.org_unit_id if unit else None,
                user_id=cls.interviewer.user_id,
                unique_id=f"area-{status}-{site_id}-{unit.unit_code if unit else 'none'}",
                status=status,
            )
        )
        db.session.flush()

    @classmethod
    def _grant(cls, user, role, scope_type, **kwargs):
        db.session.add(
            VaUserAccessGrants(
                user_id=user.user_id,
                role=role,
                scope_type=scope_type,
                grant_status=VaStatuses.active,
                **kwargs,
            )
        )
        db.session.flush()

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _by_key(summary):
        return {row["key"]: row for row in summary["rows"]}


def refresh_submission_analytics_mv_core_and_demographics():
    """Refresh the two MVs the area counts read (the COD MVs are not built here)."""
    for mv in (CORE_MV_NAME, DEMOGRAPHICS_MV_NAME):
        db.session.execute(sa.text(f"REFRESH MATERIALIZED VIEW {mv}"))
    db.session.commit()


class CodingBucketMappingTests(BaseTestCase):
    def test_every_workflow_state_is_mapped_explicitly(self):
        self.assertTrue(ALL_WORKFLOW_STATES)
        self.assertEqual(set(WORKFLOW_CODING_BUCKETS), set(ALL_WORKFLOW_STATES))
        self.assertTrue(set(WORKFLOW_CODING_BUCKETS.values()) <= set(CODING_BUCKETS))

    def test_known_states_land_in_their_buckets(self):
        self.assertEqual(coding_bucket("smartva_pending"), "awaiting_coding")
        self.assertEqual(coding_bucket("ready_for_coding"), "awaiting_coding")
        self.assertEqual(coding_bucket("coder_step1_saved"), "in_coding")
        self.assertEqual(coding_bucket("reviewer_coding_in_progress"), "in_review")
        self.assertEqual(coding_bucket("reviewer_eligible"), "coded")
        self.assertEqual(coding_bucket("consent_refused"), "not_codeable")

    def test_unknown_and_missing_states_are_other(self):
        self.assertEqual(coding_bucket("no_such_state"), "other")
        self.assertEqual(coding_bucket(None), "other")


class AreaScopeTests(AreaDashboardFixture):
    def test_unit_grant_sees_only_its_subtree(self):
        scope = area.resolve_area_scope(self.unit_user, self.TREE)
        self.assertIn(self.chc_a.org_unit_id, scope.unit_ids)
        self.assertIn(self.phc_a1.org_unit_id, scope.unit_ids)
        self.assertNotIn(self.chc_b.org_unit_id, scope.unit_ids)
        self.assertNotIn(self.district_1.org_unit_id, scope.unit_ids)
        self.assertFalse(scope.project_wide)

    def test_project_grant_on_tree_project_is_whole_tree(self):
        scope = area.resolve_area_scope(self.project_user, self.TREE)
        self.assertTrue(scope.has_tree)
        self.assertTrue(scope.project_wide)

    def test_site_grant_on_tree_project_is_whole_tree(self):
        scope = area.resolve_area_scope(self.site_user, self.TREE)
        self.assertTrue(scope.project_wide)

    def test_admin_sees_every_project_whole(self):
        admin = self.base_admin_user
        tree = area.resolve_area_scope(admin, self.TREE)
        sites = area.resolve_area_scope(admin, self.SITES)
        self.assertTrue(tree.project_wide)
        self.assertTrue(sites.project_wide)
        project_ids = {p["project_id"] for p in area.area_projects(admin)}
        self.assertTrue({self.TREE, self.SITES} <= project_ids)

    def test_sites_mode_site_grant_sees_only_granted_site(self):
        scope = area.resolve_area_scope(self.sites_mode_site_user, self.SITES)
        self.assertFalse(scope.has_tree)
        self.assertEqual(scope.site_ids, frozenset({self.SITE_ONE}))

    def test_no_grant_has_no_area(self):
        self.assertIsNone(area.resolve_area_scope(self.no_grant_user, self.TREE))
        self.assertEqual(area.area_projects(self.no_grant_user), [])

    def test_projects_list_carries_grant_roots(self):
        projects = {p["project_id"]: p for p in area.area_projects(self.unit_user)}
        self.assertIn(self.TREE, projects)
        self.assertNotIn(self.SITES, projects)
        roots = [root["key"] for root in projects[self.TREE]["roots"]]
        self.assertEqual(roots, [str(self.chc_a.org_unit_id)])

    def test_overlapping_grants_yield_one_root(self):
        """District 1 (collaborator) and PHC A1 inside it (interviewer): one root."""
        roots = area.grant_root_units(area.resolve_area_scope(self.overlap_user, self.TREE))
        self.assertEqual([row.org_unit_id for row in roots], [self.district_1.org_unit_id])


    def test_deactivated_grant_gives_no_scope(self):
        user = self._get_or_make_user("area.revoked@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.data_manager, VaAccessScopeTypes.project, project_id=self.TREE)
        self.assertIsNotNone(area.resolve_area_scope(user, self.TREE))
        grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id)
        )
        grant.grant_status = VaStatuses.deactive
        db.session.flush()
        self.assertIsNone(area.resolve_area_scope(user, self.TREE))
        self.assertEqual(area.area_projects(user), [])

    def test_closed_project_gives_no_area(self):
        self.assertEqual([p["project_id"] for p in area.area_projects(self.project_user)], [self.TREE])
        db.session.get(VaProjectMaster, self.TREE).project_status = VaStatuses.deactive
        db.session.flush()
        self.assertEqual(area.area_projects(self.project_user), [])
        self.assertIsNone(area.resolve_area_scope(self.project_user, self.TREE))

    def test_unit_grant_does_not_reach_another_tree_project(self):
        other = "ARDT02"
        self._make_project(other, "organization", datetime.now(UTC))
        org.seed_default_organization(other)
        levels = {lv.level_code: lv for lv in org.list_levels(other)}
        other_unit = org.create_unit(
            other, org_level_id=levels["district"].org_level_id, unit_code="BD1", unit_name="B District"
        )
        db.session.flush()
        self.assertTrue(area.area_summary(self.unit_user, self.TREE)["rows"])
        for unit_id in (None, str(other_unit.org_unit_id), str(self.chc_a.org_unit_id)):
            with self.assertRaises(area.AreaNotFound):
                area.area_summary(self.unit_user, other, unit_id=unit_id)

    def test_scope_is_a_union_over_roles(self):
        """Coder on CHC A plus interviewer on CHC B: both subtrees, not CHC C or the district."""
        user = self._get_or_make_user("area.union@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.coder, VaAccessScopeTypes.org_unit,
                    org_unit_id=self.chc_a.org_unit_id)
        self._grant(user, VaAccessRoles.interviewer, VaAccessScopeTypes.org_unit,
                    org_unit_id=self.chc_b.org_unit_id)
        scope = area.resolve_area_scope(user, self.TREE)
        self.assertEqual(
            scope.unit_ids,
            frozenset({self.chc_a.org_unit_id, self.phc_a1.org_unit_id, self.chc_b.org_unit_id}),
        )
        self.assertNotIn(self.chc_c.org_unit_id, scope.unit_ids)
        self.assertNotIn(self.district_1.org_unit_id, scope.unit_ids)
        roots = {row.org_unit_id for row in area.grant_root_units(scope)}
        self.assertEqual(roots, {self.chc_a.org_unit_id, self.chc_b.org_unit_id})

    def test_sites_mode_reviewer_site_grant_sees_only_its_site(self):
        user = self._get_or_make_user("area.sites.reviewer@test.local", "AreaUser123")
        site_two_ps = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.SITES, VaProjectSites.site_id == self.SITE_TWO
            )
        )
        self._grant(user, VaAccessRoles.reviewer, VaAccessScopeTypes.project_site,
                    project_site_id=site_two_ps)
        rows = self._by_key(area.area_summary(user, self.SITES))
        self.assertEqual(set(rows), {self.SITE_TWO})
        with self.assertRaises(area.AreaNotFound):
            area.area_summary(user, self.SITES, site_id=self.SITE_ONE)


class AreaSummaryTests(AreaDashboardFixture):
    def test_unit_scope_root_counts_subtree_once_without_unrouted_row(self):
        summary = area.area_summary(self.unit_user, self.TREE)
        rows = self._by_key(summary)
        key = str(self.chc_a.org_unit_id)
        self.assertIn(key, rows)
        counts = rows[key]["counts"]
        # CHC A itself + two at PHC A1, each once.
        self.assertEqual(counts["total_submissions"], 3)
        self.assertEqual(counts["awaiting_coding"], 2)
        self.assertEqual(counts["coded"], 1)
        self.assertEqual(counts["last_7_days"], 1)
        self.assertEqual(counts["last_30_days"], 2)
        self.assertEqual(counts["drafts_in_progress"], 1)
        self.assertTrue(rows[key]["has_children"])
        self.assertNotIn(area.UNROUTED_KEY, rows)

    def test_a_confirmed_duplicate_leaves_the_unit_counts_and_project_card(self):
        """digitva-vzk.7: exclusion is applied at query time over the MVs and
        the Site PI KPIs, so no refresh is needed either way."""
        key = str(self.chc_a.org_unit_id)

        def counts():
            summary = area.area_summary(self.unit_user, self.TREE)
            unit = self._by_key(summary)[key]["counts"]
            card = area.area_summary(self.project_user, self.TREE)["project_card"]
            return unit["total_submissions"], unit["coded"], card["total_submissions"]

        self.assertEqual(counts(), (3, 1, 7))
        case = VaDeathRegister(
            project_id=self.TREE, site_id=self.TREE_SITE, death_number=990001,
            unique_id="AREA-DUP-1", deceased_name="Asha Devi", deceased_sex="female",
            date_of_death=datetime.now(UTC).date(), registered_by=self.interviewer.user_id,
            status="duplicate", va_sid="uuid:area-ca1",
        )
        db.session.add(case)
        db.session.commit()
        try:
            # The coder_finalized submission at CHC A drops out.
            self.assertEqual(counts(), (2, 0, 6))
            case.status = "submitted"
            db.session.commit()
            self.assertEqual(counts(), (3, 1, 7))
        finally:
            db.session.delete(case)
            db.session.commit()

    def test_project_wide_root_has_top_units_and_unrouted_row(self):
        rows = self._by_key(area.area_summary(self.project_user, self.TREE))
        self.assertIn(str(self.district_1.org_unit_id), rows)
        self.assertIn(str(self.district_2.org_unit_id), rows)
        self.assertNotIn(str(self.chc_a.org_unit_id), rows)
        district_1 = rows[str(self.district_1.org_unit_id)]["counts"]
        self.assertEqual(district_1["total_submissions"], 4)
        self.assertEqual(district_1["in_coding"], 1)
        unrouted = rows[area.UNROUTED_KEY]["counts"]
        self.assertEqual(unrouted["total_submissions"], 2)
        self.assertEqual(unrouted["not_codeable"], 1)
        # No workflow row at all falls to "other".
        self.assertEqual(unrouted["other"], 1)
        self.assertEqual(unrouted["drafts_in_progress"], 1)
        in_review = rows[str(self.district_2.org_unit_id)]["counts"]["in_review"]
        self.assertEqual(in_review, 1)

    def test_drill_down_lists_children_with_breadcrumb(self):
        summary = area.area_summary(self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id))
        rows = self._by_key(summary)
        self.assertEqual(
            set(rows),
            {str(self.chc_a.org_unit_id), str(self.chc_b.org_unit_id), str(self.chc_c.org_unit_id)},
        )
        self.assertEqual(rows[str(self.chc_c.org_unit_id)]["counts"]["total_submissions"], 0)
        self.assertEqual(rows[str(self.chc_b.org_unit_id)]["counts"]["total_submissions"], 1)
        self.assertEqual([c["code"] for c in summary["breadcrumb"]], ["AD1"])

    def test_breadcrumb_stops_at_the_users_own_root(self):
        summary = area.area_summary(self.unit_user, self.TREE, unit_id=str(self.phc_a1.org_unit_id))
        self.assertEqual([c["code"] for c in summary["breadcrumb"]], ["ACA", "APA"])
        self.assertEqual(summary["rows"], [])

    def test_unit_outside_scope_is_not_found(self):
        self.assertIsNotNone(area.area_summary(self.unit_user, self.TREE, unit_id=str(self.chc_a.org_unit_id)))
        for outside in (self.chc_b.org_unit_id, self.district_1.org_unit_id, "not-a-uuid"):
            with self.assertRaises(area.AreaNotFound):
                area.area_summary(self.unit_user, self.TREE, unit_id=str(outside))

    def test_project_without_area_is_not_found(self):
        with self.assertRaises(area.AreaNotFound):
            area.area_summary(self.unit_user, self.SITES)
        with self.assertRaises(area.AreaNotFound):
            area.area_summary(self.no_grant_user, self.TREE)

    def test_sites_mode_rows_per_site(self):
        rows = self._by_key(area.area_summary(self.base_admin_user, self.SITES))
        self.assertEqual(set(rows), {self.SITE_ONE, self.SITE_TWO})
        site_two = rows[self.SITE_TWO]["counts"]
        self.assertEqual(site_two["total_submissions"], 2)
        self.assertEqual(site_two["not_codeable"], 1)
        self.assertEqual(site_two["awaiting_coding"], 1)
        self.assertEqual(site_two["drafts_in_progress"], 1)
        self.assertEqual(rows[self.SITE_ONE]["counts"]["coded"], 1)

    def test_sites_mode_site_grant_sees_only_its_site(self):
        rows = self._by_key(area.area_summary(self.sites_mode_site_user, self.SITES))
        self.assertIn(self.SITE_ONE, rows)
        self.assertNotIn(self.SITE_TWO, rows)
        with self.assertRaises(area.AreaNotFound):
            area.area_summary(self.sites_mode_site_user, self.SITES, site_id=self.SITE_TWO)


class AreaProjectCardTests(AreaDashboardFixture):
    """Project card at the root of a project-wide scope, and count links.

    Card numbers are the Site PI KPIs (sitepi_reporting_service): a
    submission with no workflow row counts as pending there, and coded means
    a final-COD authority row, of which this fixture has none.
    """

    def _screen_endpoints(self, links):
        return {key: link["endpoint"] for key, link in links.items()}

    def test_project_wide_root_card_matches_fixture_and_reconciles(self):
        summary = area.area_summary(self.project_user, self.TREE)
        card = summary["project_card"]
        self.assertIsNotNone(card)
        self.assertEqual(card["total_submissions"], 7)
        self.assertEqual(card["current_state_kpis"]["pending_or_active"], 4)
        self.assertEqual(card["total_not_codeable"], 1)
        self.assertEqual(card["total_coded"], 0)
        self.assertEqual(card["authority_kpis"], {"coder_authority": 0, "reviewer_authority": 0})
        self.assertEqual(
            sum(row["counts"]["total_submissions"] for row in summary["rows"]),
            card["total_submissions"],
        )
        self.assertNotIn("coder_kpis", card)
        self.assertNotIn("submission_rows", card)

    def test_sites_mode_project_card(self):
        card = area.area_summary(self.base_admin_user, self.SITES)["project_card"]
        self.assertIsNotNone(card)
        self.assertEqual(card["total_submissions"], 3)
        self.assertEqual(card["current_state_kpis"]["reviewer_finalized"], 1)
        self.assertEqual(card["current_state_kpis"]["pending_or_active"], 1)
        # consent_refused is not "not codeable" in the Site PI KPIs.
        self.assertEqual(card["total_not_codeable"], 0)

    def test_no_card_for_unit_scope_or_below_the_root(self):
        self.assertIsNotNone(area.area_summary(self.project_user, self.TREE)["project_card"])
        unit_root = area.area_summary(self.unit_user, self.TREE)
        self.assertTrue(unit_root["rows"])
        self.assertIsNone(unit_root["project_card"])
        drilled = area.area_summary(
            self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id)
        )
        self.assertTrue(drilled["rows"])
        self.assertIsNone(drilled["project_card"])
        one_site = area.area_summary(self.base_admin_user, self.SITES, site_id=self.SITE_ONE)
        self.assertTrue(one_site["rows"])
        self.assertIsNone(one_site["project_card"])
        site_scoped = area.area_summary(self.sites_mode_site_user, self.SITES)
        self.assertTrue(site_scoped["rows"])
        self.assertIsNone(site_scoped["project_card"])

    def test_data_manager_gets_data_manager_links_only(self):
        links = area.area_summary(self.project_user, self.TREE)["project_card"]["links"]
        self.assertEqual(
            self._screen_endpoints(links),
            {
                key: area.SCREEN_DATA_MANAGEMENT
                for key in ("total_submissions", "reviewer_eligible",
                            "reviewer_finalized", "upstream_changed")
            },
        )
        self.assertEqual(links["total_submissions"]["params"]["project"], self.TREE)
        self.assertEqual(links["total_submissions"]["params"]["workflow"], "")
        self.assertEqual(links["reviewer_eligible"]["params"]["workflow"], "reviewer_eligible")
        self.assertEqual(set(links["reviewer_eligible"]["params"]), set(area.DM_URL_FILTERS))

    def test_reviewer_site_grant_gets_card_without_links(self):
        card = area.area_summary(self.site_user, self.TREE)["project_card"]
        self.assertIsNotNone(card)
        self.assertEqual(card["links"], {})

    def test_project_coder_gets_coding_link(self):
        user = self._get_or_make_user("area.card.coder@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.coder, VaAccessScopeTypes.project, project_id=self.TREE)
        links = area.area_summary(user, self.TREE)["project_card"]["links"]
        self.assertEqual(self._screen_endpoints(links), {"pending_or_active": area.SCREEN_CODING})

    def test_project_interviewer_gets_intake_link(self):
        user = self._get_or_make_user("area.card.intake@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.interviewer, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        links = area.area_summary(user, self.TREE)["project_card"]["links"]
        self.assertEqual(self._screen_endpoints(links), {"total_submissions": area.SCREEN_INTAKE})

    def test_role_on_another_project_gives_no_link(self):
        """Coder on the sites project, data manager on the tree: no coding link on the tree."""
        user = self._get_or_make_user("area.card.cross@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.data_manager, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        self._grant(user, VaAccessRoles.coder, VaAccessScopeTypes.project, project_id=self.SITES)
        self.assertIn(area.SCREEN_CODING, area.link_screens(user, self.SITES))
        links = area.area_summary(user, self.TREE)["project_card"]["links"]
        self.assertIn("total_submissions", links)
        self.assertNotIn("pending_or_active", links)

    def test_sites_mode_rows_link_to_site_filter_for_data_managers_only(self):
        rows = self._by_key(area.area_summary(self.base_admin_user, self.SITES))
        link = rows[self.SITE_ONE]["links"]["total_submissions"]
        self.assertEqual(link["endpoint"], area.SCREEN_DATA_MANAGEMENT)
        self.assertEqual((link["params"]["project"], link["params"]["site"]), (self.SITES, self.SITE_ONE))
        site_pi_rows = self._by_key(area.area_summary(self.sites_mode_site_user, self.SITES))
        self.assertIn(self.SITE_ONE, site_pi_rows)
        self.assertEqual(site_pi_rows[self.SITE_ONE]["links"], {})


class AreaStaffFixture(AreaDashboardFixture):
    """Cases, contact attempts and coder events on top of the area fixture.

    Interviewer (the fixture's) works PHC A1: one live case, one confirmed
    duplicate, and the fixture's PHC A1 drafts. A second interviewer works
    CHC B. Coder A finalized CHC A's submission and marked one PHC A1
    submission not codeable; coder B finalized CHC B's. No test methods, so
    the route tests can import it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls.interviewer_b = cls._get_or_make_user("area.interviewer.b@test.local", "AreaUser123")
        cls.coder_a = cls._get_or_make_user("area.coder.a@test.local", "AreaUser123")
        cls.coder_b = cls._get_or_make_user("area.coder.b@test.local", "AreaUser123")
        cls.collaborator = cls._get_or_make_user("area.collab@test.local", "AreaUser123")
        cls._grant(cls.collaborator, VaAccessRoles.collaborator, VaAccessScopeTypes.org_unit,
                   org_unit_id=cls.district_1.org_unit_id)

        case_a = cls._case(990101, cls.phc_a1, cls.interviewer, "in_progress", started=True)
        duplicate = cls._case(990102, cls.phc_a1, cls.interviewer, "duplicate", started=True)
        case_b = cls._case(990103, cls.chc_b, cls.interviewer_b, "registered")
        # An open draft on the duplicate case: not "in progress" for anyone.
        db.session.add(VaWebIntakeDraft(
            project_id=cls.TREE, site_id=cls.TREE_SITE, form_id=cls.TREE_FORM,
            org_unit_id=cls.phc_a1.org_unit_id, death_id=duplicate.death_id,
            user_id=cls.interviewer.user_id, unique_id="area-staff-dup-draft", status="draft",
        ))
        for case, user, days_ago in (
            (case_a, cls.interviewer, 1),
            (case_a, cls.interviewer, 40),  # outside the 30-day window
            (duplicate, cls.interviewer, 1),
            (case_b, cls.interviewer_b, 2),
        ):
            db.session.add(MapCaseContactAttempt(
                death_id=case.death_id, attempted_at=now - timedelta(days=days_ago),
                outcome="no_answer", by_user_id=user.user_id,
            ))
        for sid, transition, user, days_ago in (
            ("uuid:area-ca1", "coder_finalized", cls.coder_a, 2),
            ("uuid:area-pa2", "coder_not_codeable", cls.coder_a, 10),
            ("uuid:area-cb1", "coder_finalized", cls.coder_b, 1),
        ):
            db.session.add(VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id=transition, current_state="test",
                actor_user_id=user.user_id, event_created_at=now - timedelta(days=days_ago),
            ))
        db.session.commit()

    @classmethod
    def _case(cls, number, unit, user, status, started=False):
        case = VaDeathRegister(
            project_id=cls.TREE, site_id=cls.TREE_SITE, org_unit_id=unit.org_unit_id,
            death_number=number, unique_id=f"AREA-STAFF-{number}", deceased_name="Test Case",
            deceased_sex="female", date_of_death=datetime.now(UTC).date(),
            registered_by=user.user_id, source="register", status=status,
            started_by_user_id=user.user_id if started else None,
        )
        db.session.add(case)
        db.session.flush()
        return case

    @staticmethod
    def _by_name(rows):
        return {row["name"]: row for row in rows}


class AreaStaffTests(AreaStaffFixture):
    def _staff(self, user, unit=None, **kwargs):
        return area.area_staff(
            user, kwargs.pop("project", self.TREE),
            unit_id=str(unit.org_unit_id) if unit else None, **kwargs,
        )

    def test_unit_counts_its_subtree_and_names_staff_for_a_coder(self):
        staff = self._staff(self.unit_user, self.chc_a)
        self.assertFalse(staff["staff_identity_redacted"])
        interviewers = self._by_name(staff["interviewers"])
        self.assertIn(self.interviewer.name, interviewers)
        self.assertEqual(interviewers[self.interviewer.name], {
            "name": self.interviewer.name,
            # The duplicate case (and its open draft) counts nowhere.
            "cases_registered": 1, "interviews_started": 1,
            "submitted": 1, "in_progress": 1, "contact_attempts_30_days": 1,
        })
        self.assertNotIn(self.interviewer_b.name, interviewers)
        coders = self._by_name(staff["coders"])
        self.assertIn(self.coder_a.name, coders)
        self.assertEqual(
            (coders[self.coder_a.name]["coded_7_days"], coders[self.coder_a.name]["coded_30_days"],
             coders[self.coder_a.name]["not_codeable_7_days"],
             coders[self.coder_a.name]["not_codeable_30_days"]),
            (1, 1, 0, 1),
        )
        self.assertNotIn(self.coder_b.name, coders)

    def test_another_unit_counts_only_its_own_staff(self):
        staff = self._staff(self.project_user, self.chc_b)
        interviewers = self._by_name(staff["interviewers"])
        self.assertIn(self.interviewer_b.name, interviewers)
        self.assertEqual(interviewers[self.interviewer_b.name]["cases_registered"], 1)
        self.assertEqual(interviewers[self.interviewer_b.name]["contact_attempts_30_days"], 1)
        self.assertNotIn(self.interviewer.name, interviewers)
        coders = self._by_name(staff["coders"])
        self.assertEqual(set(coders), {self.coder_b.name})

    def test_project_wide_root_counts_the_whole_project_once(self):
        staff = self._staff(self.project_user)
        interviewers = self._by_name(staff["interviewers"])
        self.assertEqual(set(interviewers), {self.interviewer.name, self.interviewer_b.name})
        # PHC A1 and the unrouted draft; the sites-mode project's draft is not here.
        self.assertEqual(interviewers[self.interviewer.name]["in_progress"], 2)
        self.assertEqual(set(self._by_name(staff["coders"])), {self.coder_a.name, self.coder_b.name})

    def test_plain_collaborator_gets_no_staff_identity(self):
        shown = self._staff(self.unit_user, self.chc_a)
        self.assertIn(self.interviewer.name, self._by_name(shown["interviewers"]))
        self.assertTrue(should_redact_pii(self.collaborator))
        hidden = self._staff(self.collaborator, self.chc_a)
        self.assertTrue(hidden["staff_identity_redacted"])
        self.assertEqual((hidden["interviewers"], hidden["coders"]), ([], []))

    def test_a_confirmed_duplicate_leaves_the_coder_counts(self):
        def coded():
            coders = self._by_name(self._staff(self.unit_user, self.chc_a)["coders"])
            return coders[self.coder_a.name]["coded_30_days"]

        self.assertEqual(coded(), 1)
        case = VaDeathRegister(
            project_id=self.TREE, site_id=self.TREE_SITE, death_number=990109,
            unique_id="AREA-STAFF-DUP", deceased_name="Test Case", deceased_sex="female",
            date_of_death=datetime.now(UTC).date(), registered_by=self.interviewer.user_id,
            status="duplicate", va_sid="uuid:area-ca1",
        )
        db.session.add(case)
        db.session.commit()
        try:
            self.assertEqual(coded(), 0)
        finally:
            db.session.delete(case)
            db.session.commit()

    def test_outside_scope_or_without_one_area_is_not_found(self):
        self.assertTrue(self._staff(self.unit_user, self.phc_a1)["interviewers"])
        for call in (
            lambda: self._staff(self.unit_user, self.chc_b),
            lambda: self._staff(self.unit_user),  # root of a unit scope: no single area
            lambda: self._staff(self.project_user, site_id=self.TREE_SITE),
            lambda: self._staff(self.no_grant_user, self.chc_a),
            lambda: self._staff(self.sites_mode_site_user, project=self.SITES, site_id=self.SITE_TWO),
            # A redacted viewer is refused out of scope too, not told "redacted".
            lambda: self._staff(self.collaborator, self.district_2),
        ):
            with self.assertRaises(area.AreaNotFound):
                call()
        self.assertFalse(self._staff(
            self.sites_mode_site_user, project=self.SITES, site_id=self.SITE_ONE
        )["staff_identity_redacted"])
