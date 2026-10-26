"""Area dashboard scope resolution and counts.

Rules under test live in app/services/area_dashboard_service.py, the unit
rollup in app/services/submission_analytics_mv.py and the bucket mapping in
app/services/workflow/definition.py. Policy: docs/policy/area-dashboard.md.
"""
import uuid
from unittest import mock
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask_caching.backends.simplecache import SimpleCache

from app import db
from app.models import (
    MapCaseContactAttempt,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaFinalAssessments,
    VaFinalCodAuthority,
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
from app.services.odk_retirement_service import MISSING_IN_ODK
from app.services.submission_analytics_mv import (
    COD_MV_NAME,
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
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
        # The cause card reads it whenever the database holds an active scheme.
        db.session.execute(sa.text(build_submission_cod_detail_mv_sql(include_icd11=True)))
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

    def _give_authority(self, sid):
        """A coder final assessment holding authority on *sid* (rolled back per test)."""
        assessment = VaFinalAssessments(
            va_sid=sid,
            va_finassess_by=self.unit_user.user_id,
            va_conclusive_cod="I10 - Essential Hypertension",
        )
        db.session.add(assessment)
        db.session.flush()
        authority = VaFinalCodAuthority(
            va_sid=sid,
            authoritative_final_assessment_id=assessment.va_finassess_id,
            authority_source_role="vacoder",
            authority_reason="final_cod_submitted",
        )
        db.session.add(authority)
        db.session.commit()


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
        self.assertEqual(counts["submitted"], 3)
        self.assertEqual(counts["awaiting_coding"], 2)
        self.assertEqual(set(counts), set(area.COUNT_KEYS))
        self.assertTrue(rows[key]["has_children"])
        self.assertNotIn(area.UNROUTED_KEY, rows)

    def test_a_confirmed_duplicate_leaves_the_unit_counts_and_project_card(self):
        """digitva-vzk.7: exclusion is applied at query time over the MVs and
        the Site PI KPIs, so no refresh is needed either way."""
        key = str(self.chc_a.org_unit_id)

        def counts():
            summary = area.area_summary(self.unit_user, self.TREE)
            unit = self._by_key(summary)[key]["counts"]
            card = area.area_summary(self.project_user, self.TREE)["card"]
            return unit["submitted"], unit["awaiting_coding"], card["counts"]["submitted"]

        self.assertEqual(counts(), (3, 2, 7))
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
            self.assertEqual(counts(), (2, 2, 6))
            case.status = "submitted"
            db.session.commit()
            self.assertEqual(counts(), (3, 2, 7))
        finally:
            db.session.delete(case)
            db.session.commit()

    def test_project_wide_root_has_top_units_and_unrouted_row(self):
        rows = self._by_key(area.area_summary(self.project_user, self.TREE))
        self.assertIn(str(self.district_1.org_unit_id), rows)
        self.assertIn(str(self.district_2.org_unit_id), rows)
        self.assertNotIn(str(self.chc_a.org_unit_id), rows)
        district_1 = rows[str(self.district_1.org_unit_id)]["counts"]
        self.assertEqual(district_1["submitted"], 4)
        self.assertEqual(district_1["awaiting_coding"], 2)
        unrouted = rows[area.UNROUTED_KEY]["counts"]
        self.assertEqual(unrouted["submitted"], 2)
        self.assertEqual(unrouted["not_codeable"], 1)
        self.assertEqual(rows[str(self.district_2.org_unit_id)]["counts"]["submitted"], 1)

    def test_drill_down_lists_children_with_breadcrumb(self):
        summary = area.area_summary(self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id))
        rows = self._by_key(summary)
        self.assertEqual(
            set(rows),
            {str(self.chc_a.org_unit_id), str(self.chc_b.org_unit_id), str(self.chc_c.org_unit_id)},
        )
        self.assertEqual(rows[str(self.chc_c.org_unit_id)]["counts"]["submitted"], 0)
        self.assertEqual(rows[str(self.chc_b.org_unit_id)]["counts"]["submitted"], 1)
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
        self.assertEqual(site_two["submitted"], 2)
        self.assertEqual(site_two["not_codeable"], 1)
        self.assertEqual(site_two["awaiting_coding"], 1)
        self.assertEqual(rows[self.SITE_ONE]["counts"]["submitted"], 1)

    def test_sites_mode_site_grant_sees_only_its_site(self):
        rows = self._by_key(area.area_summary(self.sites_mode_site_user, self.SITES))
        self.assertIn(self.SITE_ONE, rows)
        self.assertNotIn(self.SITE_TWO, rows)
        with self.assertRaises(area.AreaNotFound):
            area.area_summary(self.sites_mode_site_user, self.SITES, site_id=self.SITE_TWO)


class AreaSummaryCacheTests(AreaDashboardFixture):
    """The summary is cached for a minute per user and arguments."""

    def test_second_call_runs_no_sql_and_refusals_are_not_cached(self):
        statements = []

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", count)
        self.addCleanup(sa.event.remove, db.engine, "before_cursor_execute", count)
        with mock.patch.object(area, "cache", SimpleCache()):
            first = area.area_summary(self.unit_user, self.TREE)
            self.assertTrue(first["rows"])
            self.assertTrue(statements)  # the listener sees this connection
            statements.clear()
            second = area.area_summary(self.unit_user, self.TREE)
            self.assertEqual(statements, [])
            self.assertEqual(second, first)

            for _ in range(2):
                with self.assertRaises(area.AreaNotFound):
                    area.area_summary(self.no_grant_user, self.TREE)
            with self.assertRaises(ValueError):
                area.area_summary(self.unit_user, self.TREE, period="bogus")


class AreaCardTests(AreaDashboardFixture):
    """The area card (every level), the project card (stations) and links."""

    def _screen_endpoints(self, links):
        return {key: link["endpoint"] for key, link in links.items()}

    def test_project_wide_root_card_sums_the_rows_including_unrouted(self):
        summary = area.area_summary(self.project_user, self.TREE)
        card = summary["card"]
        self.assertEqual(card["counts"]["submitted"], 7)
        for key in area.COUNT_KEYS:
            self.assertEqual(
                card["counts"][key], sum(row["counts"][key] for row in summary["rows"]), key
            )
        self.assertEqual(set(card["medians"]), {
            "death_to_interview_days", "death_to_interview_n",
            "interview_to_final_cod_days", "interview_to_final_cod_n",
        })
        self.assertIn("rows", card["causes"])

    def test_selected_unit_card_counts_its_own_subtree_not_the_child_rows(self):
        """CHC A has a submission of its own besides PHC A1's two."""
        summary = area.area_summary(self.project_user, self.TREE, unit_id=str(self.chc_a.org_unit_id))
        self.assertEqual([row["code"] for row in summary["rows"]], ["APA"])
        self.assertEqual(summary["rows"][0]["counts"]["submitted"], 2)
        self.assertEqual(summary["card"]["counts"]["submitted"], 3)

    def test_sites_mode_card_is_the_in_scope_sites(self):
        self.assertEqual(area.area_summary(self.base_admin_user, self.SITES)["card"]["counts"]["submitted"], 3)
        self.assertEqual(
            area.area_summary(self.sites_mode_site_user, self.SITES)["card"]["counts"]["submitted"], 1
        )

    def test_project_card_is_stations_at_a_project_wide_root_only(self):
        card = area.area_summary(self.project_user, self.TREE)["project_card"]
        self.assertEqual(
            card["stations"],
            {"active": 0, "never_synced": 0, "oldest_last_bundle_at": None, "latest_bundle_at": None},
        )
        unit_root = area.area_summary(self.unit_user, self.TREE)
        self.assertTrue(unit_root["rows"])
        self.assertIsNone(unit_root["project_card"])
        drilled = area.area_summary(
            self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id)
        )
        self.assertTrue(drilled["rows"])
        self.assertIsNone(drilled["project_card"])
        self.assertIsNotNone(area.area_summary(self.base_admin_user, self.SITES)["project_card"])
        one_site = area.area_summary(self.base_admin_user, self.SITES, site_id=self.SITE_ONE)
        self.assertIsNone(one_site["project_card"])

    def test_stations_count_active_station_devices_and_their_bundles(self):
        from app.models import AuthDevice, AuthStationConfig, VaBundleIngest

        now = datetime.now(UTC)

        def device(name, *, revoked=False, station=True):
            row = AuthDevice(
                project_id=self.TREE, name=name, platform="desktop", secret_hash="x" * 64,
                revoked_at=now if revoked else None,
            )
            db.session.add(row)
            db.session.flush()
            config = None
            if station:
                config = AuthStationConfig(
                    config_id=uuid.uuid4(), device_id=row.device_id, issued_at=now,
                    expires_at=now + timedelta(days=30), issued_by=self.project_user.user_id,
                    signed_text="t", text_sha256="0" * 64,
                )
                db.session.add(config)
                db.session.flush()
            return row, config

        def bundle(row, config, days_ago, seq):
            db.session.add(VaBundleIngest(
                bundle_id=uuid.uuid4(), device_id=row.device_id, project_id=self.TREE,
                bundle_seq=seq, manifest_sha256=f"{seq:064d}", station_config_id=config.config_id,
                kem_key_id="k", uploader_user_id=self.project_user.user_id, channel="browser",
                created_at=now, received_at=now - timedelta(days=days_ago), status="processed",
            ))

        old, old_config = device("old")
        bundle(old, old_config, 9, 1)
        bundle(old, old_config, 5, 2)
        fresh, fresh_config = device("fresh")
        bundle(fresh, fresh_config, 1, 3)
        device("never")
        revoked, revoked_config = device("revoked", revoked=True)
        bundle(revoked, revoked_config, 20, 4)
        device("handset", station=False)
        db.session.flush()

        stations = area.project_stations(self.TREE)
        self.assertEqual((stations["active"], stations["never_synced"]), (3, 1))
        self.assertEqual(stations["oldest_last_bundle_at"].date(), (now - timedelta(days=5)).date())
        self.assertEqual(stations["latest_bundle_at"].date(), (now - timedelta(days=1)).date())

    def test_data_manager_gets_data_manager_links_on_the_card(self):
        links = area.area_summary(self.project_user, self.TREE)["card"]["links"]
        self.assertEqual(
            self._screen_endpoints(links),
            {"submitted": area.SCREEN_DATA_MANAGEMENT, "visit_notes": area.SCREEN_DATA_MANAGEMENT},
        )
        self.assertEqual(links["submitted"]["params"]["project"], self.TREE)
        self.assertEqual(links["submitted"]["params"]["date_from"], "")
        self.assertEqual(set(links["submitted"]["params"]), set(area.DM_URL_FILTERS))
        period = area.area_summary(self.project_user, self.TREE, period="30d")["card"]["links"]
        self.assertEqual(
            period["submitted"]["params"]["date_from"],
            area.period_start("30d").date().isoformat(),
        )
        drilled = area.area_summary(
            self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id)
        )["card"]["links"]
        self.assertEqual(drilled["submitted"]["params"]["org_unit"], str(self.district_1.org_unit_id))

    def test_several_roots_have_no_single_data_manager_filter(self):
        user = self._get_or_make_user("area.card.unitdm@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.data_manager, VaAccessScopeTypes.org_unit,
                    org_unit_id=self.chc_a.org_unit_id)
        self._grant(user, VaAccessRoles.data_manager, VaAccessScopeTypes.org_unit,
                    org_unit_id=self.district_2.org_unit_id)
        summary = area.area_summary(user, self.TREE)
        self.assertEqual(len(summary["rows"]), 2)
        self.assertNotIn("submitted", summary["card"]["links"])
        self.assertEqual(summary["card"]["counts"]["submitted"], 4)

    def test_reviewer_site_grant_gets_card_without_links(self):
        card = area.area_summary(self.site_user, self.TREE)["card"]
        self.assertEqual(card["counts"]["submitted"], 7)
        self.assertEqual(card["links"], {})
        self.assertEqual(area.link_screens(self.site_user, self.TREE), set())

    def test_collaborators_get_the_data_manager_links(self):
        """digitva-1zdi: the data manager dashboard admits both viewer roles."""
        for role in (VaAccessRoles.collaborator, VaAccessRoles.collaborator_pii):
            user = self._get_or_make_user(f"area.card.{role.value}@test.local", "AreaUser123")
            self._grant(user, role, VaAccessScopeTypes.project, project_id=self.TREE)
            self.assertEqual(area.link_screens(user, self.TREE), {area.SCREEN_DATA_MANAGEMENT})
            links = area.area_summary(user, self.TREE)["card"]["links"]
            self.assertEqual(
                self._screen_endpoints(links),
                {"submitted": area.SCREEN_DATA_MANAGEMENT, "visit_notes": area.SCREEN_DATA_MANAGEMENT},
            )

    def test_collaborator_link_follows_the_role_on_that_project(self):
        """A collaborator on the sites project only gets no link on the tree project."""
        user = self._get_or_make_user("area.card.collab.cross@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.collaborator, VaAccessScopeTypes.project,
                    project_id=self.SITES)
        self._grant(user, VaAccessRoles.interviewer, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        self.assertEqual(area.link_screens(user, self.SITES), {area.SCREEN_DATA_MANAGEMENT})
        self.assertEqual(area.link_screens(user, self.TREE), {area.SCREEN_INTAKE})
        rows = self._by_key(area.area_summary(user, self.SITES))
        self.assertIn("submitted", rows[self.SITE_ONE]["links"])

    def test_project_coder_gets_coding_link(self):
        user = self._get_or_make_user("area.card.coder@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.coder, VaAccessScopeTypes.project, project_id=self.TREE)
        links = area.area_summary(user, self.TREE)["card"]["links"]
        self.assertEqual(self._screen_endpoints(links), {"awaiting_coding": area.SCREEN_CODING})

    def test_project_interviewer_gets_intake_link(self):
        user = self._get_or_make_user("area.card.intake@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.interviewer, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        links = area.area_summary(user, self.TREE)["card"]["links"]
        self.assertEqual(self._screen_endpoints(links), {"submitted": area.SCREEN_INTAKE})

    def test_role_on_another_project_gives_no_link(self):
        """Coder on the sites project, data manager on the tree: no coding link on the tree."""
        user = self._get_or_make_user("area.card.cross@test.local", "AreaUser123")
        self._grant(user, VaAccessRoles.data_manager, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        self._grant(user, VaAccessRoles.coder, VaAccessScopeTypes.project, project_id=self.SITES)
        self.assertIn(area.SCREEN_CODING, area.link_screens(user, self.SITES))
        links = area.area_summary(user, self.TREE)["card"]["links"]
        self.assertIn("submitted", links)
        self.assertNotIn("awaiting_coding", links)

    def test_sites_mode_rows_link_to_site_filter_for_data_managers_only(self):
        rows = self._by_key(area.area_summary(self.base_admin_user, self.SITES, period="90d"))
        link = rows[self.SITE_ONE]["links"]["submitted"]
        self.assertEqual(link["endpoint"], area.SCREEN_DATA_MANAGEMENT)
        self.assertEqual((link["params"]["project"], link["params"]["site"]), (self.SITES, self.SITE_ONE))
        self.assertEqual(link["params"]["date_from"], area.period_start("90d").date().isoformat())
        site_pi_rows = self._by_key(area.area_summary(self.sites_mode_site_user, self.SITES))
        self.assertIn(self.SITE_ONE, site_pi_rows)
        self.assertEqual(site_pi_rows[self.SITE_ONE]["links"], {})


class AreaFinalCodTests(AreaDashboardFixture):
    """Final COD: a final cause of death holds authority, live.

    Fixture: uuid:area-ca1 is coder_finalized at CHC A (District 1) and
    uuid:area-un2 has no workflow row and no unit; neither holds authority
    until a test gives it one.
    """

    def _chc_a_counts(self):
        rows = self._by_key(area.area_summary(self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id)))
        return rows[str(self.chc_a.org_unit_id)]["counts"]

    def test_coder_finalized_without_authority_is_not_final_cod(self):
        self.assertEqual(self._chc_a_counts()["final_cod"], 0)
        self.assertEqual(area.area_summary(self.project_user, self.TREE)["card"]["counts"]["final_cod"], 0)

    def test_authority_counts_in_the_column_the_subtree_and_the_card(self):
        self._give_authority("uuid:area-ca1")
        self._give_authority("uuid:area-un2")
        self._give_authority("uuid:area-pa1")  # still ready_for_coding
        summary = area.area_summary(self.project_user, self.TREE)
        rows = self._by_key(summary)
        # CHC A (1) + PHC A1 (1) are in District 1's subtree, counted once each.
        self.assertEqual(rows[str(self.district_1.org_unit_id)]["counts"]["final_cod"], 2)
        self.assertEqual(rows[area.UNROUTED_KEY]["counts"]["final_cod"], 1)
        self.assertEqual(rows[str(self.district_2.org_unit_id)]["counts"]["final_cod"], 0)
        # Drilled down, the same authority rows count at the child.
        self.assertEqual(self._chc_a_counts()["final_cod"], 2)
        self.assertEqual(summary["card"]["counts"]["final_cod"], 3)

    def test_consent_refused_is_not_codeable_but_not_final_cod(self):
        """Sites-mode site two holds a consent_refused submission."""
        self._give_authority("uuid:area-s11")
        rows = self._by_key(area.area_summary(self.base_admin_user, self.SITES))
        self.assertEqual(rows[self.SITE_TWO]["counts"]["not_codeable"], 1)
        self.assertEqual(rows[self.SITE_ONE]["counts"]["final_cod"], 1)
        self.assertEqual(rows[self.SITE_TWO]["counts"]["final_cod"], 0)

    def test_a_confirmed_duplicate_leaves_final_cod(self):
        self._give_authority("uuid:area-ca1")
        self.assertEqual(self._chc_a_counts()["final_cod"], 1)
        case = VaDeathRegister(
            project_id=self.TREE, site_id=self.TREE_SITE, death_number=990201,
            unique_id="AREA-DUP-2", deceased_name="Asha Devi", deceased_sex="female",
            date_of_death=datetime.now(UTC).date(), registered_by=self.interviewer.user_id,
            status="duplicate", va_sid="uuid:area-ca1",
        )
        db.session.add(case)
        db.session.commit()
        self.assertEqual(self._chc_a_counts()["final_cod"], 0)

    def test_a_retired_submission_leaves_final_cod(self):
        self._give_authority("uuid:area-ca1")
        self.assertEqual(self._chc_a_counts()["final_cod"], 1)
        db.session.get(VaSubmissions, "uuid:area-ca1").va_sync_issue_code = MISSING_IN_ODK
        db.session.commit()
        self.assertEqual(self._chc_a_counts()["final_cod"], 0)

    def test_an_inactive_project_site_leaves_final_cod(self):
        self._give_authority("uuid:area-ca1")
        self.assertEqual(self._chc_a_counts()["final_cod"], 1)
        project_site = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.TREE, VaProjectSites.site_id == self.TREE_SITE))
        project_site.project_site_status = VaStatuses.deactive
        db.session.commit()
        self.assertEqual(self._chc_a_counts()["final_cod"], 0)

    def test_a_unit_user_counts_final_cod_only_in_their_subtree(self):
        self._give_authority("uuid:area-pa1")  # PHC A1, under the user's CHC A
        self._give_authority("uuid:area-cb1")  # CHC B, outside it
        summary = area.area_summary(self.project_user, self.TREE)
        self.assertEqual(summary["card"]["counts"]["final_cod"], 2)
        rows = area.area_summary(self.unit_user, self.TREE)["rows"]
        self.assertTrue(rows)
        self.assertEqual(sum(row["counts"]["final_cod"] for row in rows), 1)


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
        cls._grant(cls.project_user, VaAccessRoles.collaborator_pii, VaAccessScopeTypes.project,
                   project_id=cls.TREE)

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
        # The per-coder table was cut (2026-10-22): no coder names at all.
        self.assertNotIn("coders", staff)

    def test_another_unit_counts_only_its_own_staff(self):
        staff = self._staff(self.project_user, self.chc_b)
        interviewers = self._by_name(staff["interviewers"])
        self.assertIn(self.interviewer_b.name, interviewers)
        self.assertEqual(interviewers[self.interviewer_b.name]["cases_registered"], 1)
        self.assertEqual(interviewers[self.interviewer_b.name]["contact_attempts_30_days"], 1)
        self.assertNotIn(self.interviewer.name, interviewers)

    def test_project_wide_root_counts_the_whole_project_once(self):
        staff = self._staff(self.project_user)
        interviewers = self._by_name(staff["interviewers"])
        self.assertEqual(set(interviewers), {self.interviewer.name, self.interviewer_b.name})
        # PHC A1 and the unrouted draft; the sites-mode project's draft is not here.
        self.assertEqual(interviewers[self.interviewer.name]["in_progress"], 2)

    def test_plain_collaborator_gets_no_staff_identity(self):
        shown = self._staff(self.unit_user, self.chc_a)
        self.assertIn(self.interviewer.name, self._by_name(shown["interviewers"]))
        self.assertTrue(should_redact_pii(self.collaborator))
        hidden = self._staff(self.collaborator, self.chc_a)
        self.assertTrue(hidden["staff_identity_redacted"])
        self.assertEqual(hidden["interviewers"], [])

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


def _count_statements(fn):
    """How many SQL statements *fn* runs."""
    seen = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    sa.event.listen(db.engine, "before_cursor_execute", listener)
    try:
        fn()
    finally:
        sa.event.remove(db.engine, "before_cursor_execute", listener)
    return len(seen)


class AreaDeathsReportedTests(AreaDashboardFixture):
    """Deaths reported: death-register cases per unit subtree, site and unrouted.

    Baselines are read first because other fixtures may leave cases behind;
    every case a test adds is deleted on cleanup.
    """

    def _death(self, number, status, unit=None, site=None, project=None, source="register"):
        case = VaDeathRegister(
            project_id=project or self.TREE,
            site_id=site or self.TREE_SITE,
            org_unit_id=unit.org_unit_id if unit else None,
            death_number=number,
            unique_id=f"AREA-DEATH-{number}",
            deceased_name="Test Case",
            deceased_sex="female",
            date_of_death=datetime.now(UTC).date(),
            registered_by=self.interviewer.user_id,
            source=source,
            status=status,
        )
        db.session.add(case)
        db.session.commit()
        self.addCleanup(self._delete_death, case.death_id)
        return case

    @staticmethod
    def _delete_death(death_id):
        case = db.session.get(VaDeathRegister, death_id)
        if case is not None:
            db.session.delete(case)
            db.session.commit()

    def _rows(self, user, **kwargs):
        return self._by_key(area.area_summary(user, self.TREE, **kwargs))

    def test_unit_counts_its_subtree_and_leaves_out_duplicates_and_cancelled(self):
        key = str(self.chc_a.org_unit_id)

        def chc_a_deaths():
            return self._rows(self.unit_user)[key]["counts"]["deaths_reported"]

        base = chc_a_deaths()
        self._death(990401, "registered", unit=self.phc_a1)
        self._death(990402, "submitted", unit=self.chc_a, source="direct")
        # Both counted cases (one in a child unit, one on CHC A itself) show first.
        self.assertEqual(chc_a_deaths(), base + 2)
        self._death(990403, "duplicate", unit=self.phc_a1)
        self._death(990404, "cancelled", unit=self.phc_a1)
        self.assertEqual(chc_a_deaths(), base + 2)

    def test_a_district_rolls_up_its_units_and_an_unrouted_case_counts_once(self):
        district_1 = str(self.district_1.org_unit_id)
        district_2 = str(self.district_2.org_unit_id)
        base = self._rows(self.project_user)
        base_counts = {k: base[k]["counts"]["deaths_reported"] for k in (district_1, district_2, area.UNROUTED_KEY)}
        self._death(990411, "registered", unit=self.chc_b)
        self._death(990412, "registered", unit=self.district_2)
        self._death(990413, "registered", unit=None)
        rows = self._rows(self.project_user)
        self.assertEqual(rows[district_1]["counts"]["deaths_reported"], base_counts[district_1] + 1)
        self.assertEqual(rows[district_2]["counts"]["deaths_reported"], base_counts[district_2] + 1)
        self.assertEqual(rows[area.UNROUTED_KEY]["counts"]["deaths_reported"], base_counts[area.UNROUTED_KEY] + 1)

    def test_a_unit_outside_the_viewers_reach_is_not_counted(self):
        key = str(self.chc_a.org_unit_id)
        chc_b = str(self.chc_b.org_unit_id)
        district_1 = str(self.district_1.org_unit_id)
        base = self._rows(self.unit_user)[key]["counts"]["deaths_reported"]
        base_district = self._rows(self.project_user)[district_1]["counts"]["deaths_reported"]
        self._death(990421, "registered", unit=self.chc_b)
        # Counted for a viewer who reaches CHC B, so its absence below is meaningful.
        self.assertEqual(
            self._rows(self.project_user)[district_1]["counts"]["deaths_reported"], base_district + 1
        )
        self.assertEqual(self._rows(self.unit_user)[key]["counts"]["deaths_reported"], base)
        self.assertNotIn(chc_b, self._rows(self.unit_user))
        with self.assertRaises(area.AreaNotFound):
            area.area_summary(self.unit_user, self.TREE, unit_id=chc_b)

    def test_sites_mode_counts_per_site(self):
        def rows():
            return self._by_key(area.area_summary(self.base_admin_user, self.SITES))

        base_one = rows()[self.SITE_ONE]["counts"]["deaths_reported"]
        base_two = rows()[self.SITE_TWO]["counts"]["deaths_reported"]
        self._death(990431, "submitted", site=self.SITE_TWO, project=self.SITES)
        self.assertEqual(rows()[self.SITE_TWO]["counts"]["deaths_reported"], base_two + 1)
        self._death(990432, "duplicate", site=self.SITE_TWO, project=self.SITES)
        self._death(990433, "cancelled", site=self.SITE_TWO, project=self.SITES)
        self.assertEqual(rows()[self.SITE_TWO]["counts"]["deaths_reported"], base_two + 1)
        self.assertEqual(rows()[self.SITE_ONE]["counts"]["deaths_reported"], base_one)

    def test_query_count_does_not_grow_with_units(self):
        # Ids read before measuring: an expired instance refreshes on access.
        one_id = self.chc_a.org_unit_id
        all_ids = [
            u.org_unit_id for u in (self.district_1, self.chc_a, self.chc_b, self.chc_c, self.phc_a1)
        ]
        one = _count_statements(lambda: area._case_counts_by_unit(self.TREE, [one_id]))
        many = _count_statements(lambda: area._case_counts_by_unit(self.TREE, all_ids))
        self.assertEqual(one, 1)
        self.assertEqual(many, one)


class AreaDistrictWidgetTests(AreaDeathsReportedTests):
    """digitva-qfh8: period, backlog, SmartVA failed, medians, causes, CSV.

    Inherits the case builder; every case a test adds is deleted on cleanup.
    """

    def _aged_case(self, number, status, unit, days_ago, va_sid=None, date_of_death=None):
        case = self._death(number, status, unit=unit)
        case.created_at = datetime.now(UTC) - timedelta(days=days_ago)
        case.va_sid = va_sid
        if date_of_death is not None:
            case.date_of_death = date_of_death
        db.session.commit()
        return case

    def _counts(self, user, key, **kwargs):
        return self._by_key(area.area_summary(user, self.TREE, **kwargs))[key]["counts"]

    # -- deaths and the period --------------------------------------------------

    def test_deaths_by_registration_date_at_two_levels_and_by_period(self):
        district_1, chc_a = str(self.district_1.org_unit_id), str(self.chc_a.org_unit_id)
        periods = ("30d", "90d", "12m", "all")
        base = {p: self._counts(self.project_user, district_1, period=p) for p in periods}
        base_unit = self._counts(self.project_user, chc_a, unit_id=district_1)
        self._aged_case(990501, "submitted", self.phc_a1, 2)
        self._aged_case(990502, "submitted", self.chc_b, 20)
        self._aged_case(990503, "submitted", self.phc_a1, 100)

        root = self._counts(self.project_user, district_1)
        self.assertEqual(root["deaths_7_days"] - base["all"]["deaths_7_days"], 1)
        self.assertEqual(root["deaths_30_days"] - base["all"]["deaths_30_days"], 2)
        for period, added in (("30d", 2), ("90d", 2), ("12m", 3), ("all", 3)):
            with self.subTest(period=period):
                counts = self._counts(self.project_user, district_1, period=period)
                self.assertEqual(
                    counts["deaths_reported"] - base[period]["deaths_reported"], added
                )
        # One level down: CHC A's subtree holds the two PHC A1 cases.
        unit = self._counts(self.project_user, chc_a, unit_id=district_1)
        self.assertEqual(unit["deaths_reported"] - base_unit["deaths_reported"], 2)
        self.assertEqual(unit["deaths_7_days"] - base_unit["deaths_7_days"], 1)

    def test_period_filters_submitted_but_not_the_backlog(self):
        """CHC A: submissions 2, 20 and 60 days old; two awaiting coding."""
        key = str(self.chc_a.org_unit_id)
        all_time = self._counts(self.unit_user, key)
        thirty = self._counts(self.unit_user, key, period="30d")
        self.assertEqual((all_time["submitted"], thirty["submitted"]), (3, 2))
        self.assertEqual(thirty["awaiting_coding"], all_time["awaiting_coding"])
        self.assertEqual(all_time["awaiting_coding"], 2)

    def test_unknown_period_is_refused(self):
        with self.assertRaises(ValueError):
            area.area_summary(self.project_user, self.TREE, period="7d")

    # -- interviews pending ----------------------------------------------------

    def test_interviews_pending_with_backlog_age(self):
        key = str(self.chc_a.org_unit_id)
        base = self._counts(self.unit_user, key)
        self._aged_case(990511, "registered", self.phc_a1, 1)
        self._aged_case(990512, "scheduled", self.phc_a1, 10)
        self._aged_case(990513, "not_reachable", self.chc_a, 40)
        self._aged_case(990514, "paused", self.phc_a1, 31)
        self._aged_case(990515, "submitted", self.phc_a1, 50)  # done: not pending
        self._aged_case(990516, "refused", self.phc_a1, 50)  # closed: not pending
        counts = self._counts(self.unit_user, key)
        self.assertEqual(counts["interviews_pending"] - base["interviews_pending"], 4)
        self.assertEqual(counts["pending_over_7_days"] - base["pending_over_7_days"], 3)
        self.assertEqual(counts["pending_over_30_days"] - base["pending_over_30_days"], 2)
        # The period never filters the backlog.
        self.assertEqual(self._counts(self.unit_user, key, period="30d")["interviews_pending"],
                         counts["interviews_pending"])
        # One level down: PHC A1 holds three of the four.
        phc = self._counts(self.unit_user, str(self.phc_a1.org_unit_id), unit_id=key)
        self.assertEqual(phc["interviews_pending"] - base["interviews_pending"], 3)

    # -- SmartVA failed --------------------------------------------------------

    def _smartva(self, sid, outcome, status=VaStatuses.active):
        from app.models import VaSmartvaResults

        row = VaSmartvaResults(va_sid=sid, va_smartva_outcome=outcome, va_smartva_status=status)
        db.session.add(row)
        db.session.commit()

    def test_smartva_failed_counts_the_active_failed_result_only(self):
        district_1 = str(self.district_1.org_unit_id)
        self.assertEqual(self._counts(self.project_user, district_1)["smartva_failed"], 0)
        self._smartva("uuid:area-pa1", "failed")
        self._smartva("uuid:area-pa2", "failed", VaStatuses.deactive)
        self._smartva("uuid:area-cb1", "success")
        self._smartva("uuid:area-d21", "failed")
        self.assertEqual(self._counts(self.project_user, district_1)["smartva_failed"], 1)
        self.assertEqual(
            self._counts(self.project_user, str(self.district_2.org_unit_id))["smartva_failed"], 1
        )
        self.assertEqual(
            self._counts(self.project_user, str(self.chc_a.org_unit_id), unit_id=district_1)["smartva_failed"], 1
        )
        self.assertEqual(area.area_summary(self.project_user, self.TREE)["card"]["counts"]["smartva_failed"], 2)
        # A unit user outside District 2 does not see its failure.
        self.assertEqual(area.area_summary(self.unit_user, self.TREE)["card"]["counts"]["smartva_failed"], 1)

    # -- medians ---------------------------------------------------------------

    def test_medians_over_the_area_and_only_the_users_subtree(self):
        submitted = {
            sid: db.session.get(VaSubmissions, sid).va_submission_date.date()
            for sid in ("uuid:area-pa1", "uuid:area-ca1", "uuid:area-cb1")
        }
        self._aged_case(990521, "submitted", self.phc_a1, 3, va_sid="uuid:area-pa1",
                        date_of_death=submitted["uuid:area-pa1"] - timedelta(days=4))
        self._aged_case(990522, "submitted", self.chc_a, 3, va_sid="uuid:area-ca1",
                        date_of_death=submitted["uuid:area-ca1"] - timedelta(days=10))
        self._aged_case(990523, "submitted", self.chc_b, 3, va_sid="uuid:area-cb1",
                        date_of_death=submitted["uuid:area-cb1"] - timedelta(days=30))
        self._give_authority("uuid:area-ca1")

        project = area.area_summary(self.project_user, self.TREE)["card"]["medians"]
        self.assertEqual((project["death_to_interview_days"], project["death_to_interview_n"]), (10.0, 3))
        self.assertEqual(project["interview_to_final_cod_n"], 1)
        # ca1 was submitted 60 days ago and took authority now.
        self.assertAlmostEqual(project["interview_to_final_cod_days"], 60.0, delta=1.0)

        mine = area.area_summary(self.unit_user, self.TREE)["card"]["medians"]
        self.assertEqual((mine["death_to_interview_days"], mine["death_to_interview_n"]), (7.0, 2))
        chc_b = area.area_summary(
            self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id)
        )["card"]["medians"]
        self.assertEqual(chc_b["death_to_interview_n"], 3)

    def test_medians_are_none_without_data(self):
        medians = area.area_summary(self.base_admin_user, self.SITES)["card"]["medians"]
        self.assertIsNone(medians["death_to_interview_days"])
        self.assertEqual(medians["death_to_interview_n"], 0)

    # -- causes ----------------------------------------------------------------

    def _causes_called_with(self, user, **kwargs):
        from unittest import mock

        with mock.patch.object(area, "default_reporting_scheme_code", return_value="WHO_2022_VA_2026"), \
                mock.patch.object(area, "count_coded_submissions_by_cause",
                                  return_value=(25, [{"label": "A", "coded_count": 21},
                                                     {"label": "B", "coded_count": 4}])) as fake:
            summary = area.area_summary(user, kwargs.pop("project", self.TREE), **kwargs)
        self.assertEqual(fake.call_count, 1)
        return fake.call_args.kwargs, summary["card"]["causes"]

    def test_causes_are_scoped_to_the_selected_area_and_suppressed(self):
        call, causes = self._causes_called_with(self.project_user)
        self.assertEqual(call["project_id"], self.TREE)
        # Project-wide: every active pair of the project, unrouted deaths included.
        self.assertEqual(call["allowed_project_site_pairs"], {(self.TREE, self.TREE_SITE)})
        self.assertNotIn("allowed_org_unit_ids", call)
        self.assertEqual(causes["rows"], [
            {"label": "A", "coded_count": 21, "suppressed": False, "percent": 84.0},
            {"label": area.OTHER_CAUSES_LABEL, "coded_count": 4, "suppressed": True, "percent": 16.0},
        ])

        call, _ = self._causes_called_with(self.project_user, unit_id=str(self.chc_a.org_unit_id))
        self.assertEqual(call["allowed_project_site_pairs"], set())
        self.assertEqual(call["allowed_org_unit_ids"], {self.chc_a.org_unit_id, self.phc_a1.org_unit_id})

        call, _ = self._causes_called_with(self.unit_user)
        self.assertEqual(call["allowed_project_site_pairs"], set())
        self.assertIn(self.phc_a1.org_unit_id, call["allowed_org_unit_ids"])
        self.assertNotIn(self.chc_b.org_unit_id, call["allowed_org_unit_ids"])

        call, _ = self._causes_called_with(self.sites_mode_site_user, project=self.SITES)
        self.assertEqual(call["allowed_project_site_pairs"], {(self.SITES, self.SITE_ONE)})

        call, _ = self._causes_called_with(self.project_user, period="90d")
        self.assertEqual(call["death_date_from"], area.period_start("90d").date())
        call, _ = self._causes_called_with(self.project_user)
        self.assertIsNone(call["death_date_from"])

    def test_suppression_hides_under_twenty_and_folds_small_causes(self):
        causes = [{"label": "Big", "coded_count": 12}, {"label": "Mid", "coded_count": 5},
                  {"label": "Small", "coded_count": 2}]
        self.assertEqual(area.suppress_causes(19, causes), {"coded": 19, "hidden": True, "rows": []})
        shown = area.suppress_causes(20, causes)
        self.assertFalse(shown["hidden"])
        self.assertEqual([(r["label"], r["coded_count"]) for r in shown["rows"]],
                         [("Big", 12), ("Mid", 5), (area.OTHER_CAUSES_LABEL, 3)])
        self.assertNotIn("Small", [r["label"] for r in shown["rows"]])
        # Unmapped codes (total above the causes' sum) are folded too.
        self.assertEqual(area.suppress_causes(25, causes)["rows"][-1]["coded_count"], 8)
        # Only the top ten causes are named.
        many = [{"label": f"C{i}", "coded_count": 10} for i in range(12)]
        rows = area.suppress_causes(120, many)["rows"]
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[-1], {"label": area.OTHER_CAUSES_LABEL, "coded_count": 20, "suppressed": True, "percent": 16.7})
        # Only the folded row is flagged; named rows say so explicitly.
        self.assertEqual([r["suppressed"] for r in rows], [False] * 10 + [True])
        # Nothing to fold: no Other row.
        self.assertEqual(len(area.suppress_causes(20, [{"label": "All", "coded_count": 20}])["rows"]), 1)

    # -- CSV -------------------------------------------------------------------

    def test_csv_carries_aggregates_only(self):
        import csv as csv_module
        import io as io_module

        self._aged_case(990531, "registered", self.phc_a1, 1)
        summary = area.area_summary(self.project_user, self.TREE, unit_id=str(self.district_1.org_unit_id))
        text = area.summary_csv(summary)
        lines = list(csv_module.reader(io_module.StringIO(text)))
        self.assertEqual(tuple(lines[0]), area.CSV_HEADER)
        self.assertEqual(lines[1], ["period", "AD1", "Unit AD1", "period", "all"])
        measures = {(row[0], row[1], row[3]): row[4] for row in lines[1:]}
        self.assertEqual(measures[("area", "AD1", "submitted")], "4")
        self.assertEqual(measures[("row", "ACA", "submitted")], "3")
        self.assertIn(("area", "AD1", "interviews_pending"), measures)
        for forbidden in ("uuid:", self.interviewer.name, "Test Case", "AREA-DEATH"):
            self.assertNotIn(forbidden, text)

    def test_csv_cells_cannot_run_as_formulas(self):
        self.assertEqual(area._csv_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(area._csv_cell("+1"), "'+1")
        self.assertEqual(area._csv_cell("@x"), "'@x")
        self.assertEqual(area._csv_cell(-3.5), -3.5)
        self.assertEqual(area._csv_cell("District 1"), "District 1")

    # -- no N+1 ----------------------------------------------------------------

    def test_summary_query_count_does_not_grow_with_child_units(self):
        district_1, chc_a = str(self.district_1.org_unit_id), str(self.chc_a.org_unit_id)
        area.area_summary(self.project_user, self.TREE, unit_id=district_1)  # warm-up
        many = _count_statements(
            lambda: area.area_summary(self.project_user, self.TREE, unit_id=district_1)
        )
        one = _count_statements(lambda: area.area_summary(self.project_user, self.TREE, unit_id=chc_a))
        self.assertEqual(len(area.area_summary(self.project_user, self.TREE, unit_id=district_1)["rows"]), 3)
        self.assertEqual(many, one)
