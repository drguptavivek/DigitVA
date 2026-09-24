"""Route-access tests for wiring collaborator/collaborator_pii into the
read-only data-management surfaces (.tasks/viewer-pii-roles.md,
docs/policy/access-control-model.md, "collaborator" / "collaborator_pii").

Two things are asserted for every route below:
  - collaborator and collaborator_pii reach the read-only surfaces this
    change grants them (identical reach for both — see role_required.py)
  - collaborator and collaborator_pii are refused everywhere else: coding
    allocation, review actions, every POST/PUT/DELETE workflow route in
    this blueprint, admin panels, and grant management. None of those
    decorators were touched by this change; these tests are the regression
    proof that they still refuse a viewer.
"""
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    MasOrgLevel,
    MasOrgUnit,
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
    VaUserAccessGrants,
)
from app.services.submission_analytics_mv import (
    COD_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
)
from app.services.workflow.definition import WORKFLOW_READY_FOR_CODING
from tests.base import BaseTestCase


class CollaboratorViewerAccessTests(BaseTestCase):
    PROJECT = "VCA001"
    SITE = "VCA1"
    FORM_ID = "VCA001VCA101"
    SID = "uuid:collab-viewer-access"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Collaborator Viewer Access Project",
                project_nickname="CollabViewerAccess",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE,
                site_name="Collaborator Viewer Access Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        # va_forms.project_id / va_sites.project_id FK to va_research_projects
        # (the legacy table), NOT va_project_master — both must be seeded or
        # the VaForms insert below fails its FK and this class's setUpClass
        # errors (silently counting the whole class as passing).
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Collaborator Viewer Access Project",
                project_nickname="CollabViewerAccess",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE,
                project_id=cls.PROJECT,
                site_name="Collaborator Viewer Access Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        db.session.flush()
        if db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.PROJECT,
                VaProjectSites.site_id == cls.SITE,
            )
        ) is None:
            db.session.add(VaProjectSites(
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            ))
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                odk_form_id="VCA_FORM",
                odk_project_id="499",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.add(MapProjectSiteOdk(
            project_id=cls.PROJECT,
            site_id=cls.SITE,
            odk_project_id=499,
            odk_form_id="VCA_FORM",
            last_synced_at=now,
        ))
        db.session.flush()
        if db.session.get(VaSubmissions, cls.SID) is None:
            db.session.add(VaSubmissions(
                va_sid=cls.SID,
                va_form_id=cls.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="Collector",
                va_instance_name=cls.SID,
                va_uniqueid_real=cls.SID,
                va_uniqueid_masked=cls.SID,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=45,
                va_deceased_gender="female",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(
                va_sid=cls.SID,
                workflow_state=WORKFLOW_READY_FOR_CODING,
                workflow_created_at=now,
                workflow_updated_at=now,
            ))
        db.session.commit()

    def _make_viewer(self, role, email, password):
        user = self._get_or_make_user(email, password)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    # ------------------------------------------------------------------
    # Granted: read-only data-management surfaces
    # ------------------------------------------------------------------

    def _create_analytics_mvs(self, index_prefix):
        """Build the analytics MVs the dashboard and KPI routes query.

        conftest drops these and never recreates them, and per-test isolation
        rolls DDL back, so a test that reaches a route touching them must
        build them itself (docs/policy/test-harness.md). Without this the
        route is reached, authorization passes, and the request 500s on a
        missing relation -- which would look like an authorization failure.
        """
        for mv in (COD_MV_NAME, DEMOGRAPHICS_MV_NAME, CORE_MV_NAME):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.execute(
            sa.text(f"CREATE UNIQUE INDEX {index_prefix}_core_va_sid ON {CORE_MV_NAME} (va_sid)")
        )
        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(
            sa.text(f"CREATE UNIQUE INDEX {index_prefix}_demo_va_sid ON {DEMOGRAPHICS_MV_NAME} (va_sid)")
        )
        db.session.execute(sa.text(build_submission_cod_detail_mv_sql(include_icd11=True)))
        db.session.execute(
            sa.text(f"CREATE UNIQUE INDEX {index_prefix}_detail_va_sid ON {COD_MV_NAME} (va_sid)")
        )
        db.session.commit()

    def test_collaborator_reaches_dashboard_page(self):
        self._create_analytics_mvs("vca_dash")
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.dash@test.local", "VcaCollabDash123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/")

        self.assertEqual(response.status_code, 200)

    def test_collaborator_pii_reaches_dashboard_page(self):
        self._create_analytics_mvs("vca_dashpii")
        user = self._make_viewer(
            VaAccessRoles.collaborator_pii, "vca.collabpii.dash@test.local", "VcaCollabPiiDash123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/")

        self.assertEqual(response.status_code, 200)

    def test_collaborator_reaches_kpi_dashboard_shell(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.kpishell@test.local", "VcaCollabKpiShell123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/dashboard")

        self.assertEqual(response.status_code, 200)

    def test_collaborator_refused_on_cod_bucket_reporting_page(self):
        """Deliberately not widened: the page is a shell whose data all
        comes from app/routes/api/cod_buckets.py (/schemes, /aggregates,
        /export.csv), all three of which stay data_manager/admin only —
        granting the shell page alone would just 403 on every fetch, and
        opening the API is a separate widening (export.csv emits staff
        identity with no redaction path)."""
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.codbucket@test.local", "VcaCollabCodBucket123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/cod-buckets")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_pii_refused_on_cod_bucket_reporting_page(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator_pii,
            "vca.collabpii.codbucket@test.local",
            "VcaCollabPiiCodBucket123",
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/cod-buckets")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_reaches_submissions_api(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.submissions@test.local", "VcaCollabSubmissions123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/submissions")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        sids = {row["va_sid"] for row in payload["data"]}
        self.assertIn(self.SID, sids)

    def test_collaborator_pii_reaches_submissions_api(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator_pii,
            "vca.collabpii.submissions@test.local",
            "VcaCollabPiiSubmissions123",
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/submissions")

        self.assertEqual(response.status_code, 200)

    def test_collaborator_vs_collaborator_pii_staff_identity_redaction(self):
        """The route wiring must not bypass should_redact_pii: a plain
        collaborator gets a null data_collector; collaborator_pii does not.
        """
        collab = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.redact@test.local", "VcaCollabRedact123"
        )
        self._login(str(collab.user_id))
        collab_row = next(
            row for row in self.client.get(
                "/api/v1/data-management/submissions"
            ).get_json()["data"]
            if row["va_sid"] == self.SID
        )
        self.assertIsNone(collab_row["va_data_collector"])

        collab_pii = self._make_viewer(
            VaAccessRoles.collaborator_pii,
            "vca.collabpii.redact@test.local",
            "VcaCollabPiiRedact123",
        )
        self._login(str(collab_pii.user_id))
        collab_pii_row = next(
            row for row in self.client.get(
                "/api/v1/data-management/submissions"
            ).get_json()["data"]
            if row["va_sid"] == self.SID
        )
        self.assertEqual(collab_pii_row["va_data_collector"], "Collector")

    def test_collaborator_reaches_filter_options_api(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.filteropts@test.local", "VcaCollabFilterOpts123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/filter-options")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.PROJECT, response.get_json()["projects"])

    def test_collaborator_reaches_kpi_api(self):
        self._create_analytics_mvs("vca_kpi")
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.kpiapi@test.local", "VcaCollabKpiApi123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/kpi")

        self.assertEqual(response.status_code, 200)

    def test_viewer_with_no_grant_is_refused_even_on_granted_routes(self):
        """A collaborator role alone is not enough — the user must actually
        hold an active grant. Proves role_required("collaborator") checks
        real scope (is_viewer()), not just the string on some other grant.
        """
        user = self._get_or_make_user("vca.collab.nogrant@test.local", "VcaCollabNoGrant123")
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/submissions")

        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # Refused: writes, coding/review, admin, grant management
    # ------------------------------------------------------------------

    def test_collaborator_refused_on_screening_pass(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.screenpass@test.local", "VcaCollabScreenPass123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/submissions/{self.SID}/screening-pass",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_screening_reject(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.screenreject@test.local", "VcaCollabScreenReject123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/submissions/{self.SID}/screening-reject",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_accept_upstream_change(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.acceptupstream@test.local", "VcaCollabAcceptUpstream123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/submissions/{self.SID}/accept-upstream-change",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_pii_refused_on_reject_upstream_change(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator_pii,
            "vca.collabpii.rejectupstream@test.local",
            "VcaCollabPiiRejectUpstream123",
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/submissions/{self.SID}/reject-upstream-change",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_form_sync(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.formsync@test.local", "VcaCollabFormSync123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/forms/{self.FORM_ID}/sync",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_submission_sync(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.subsync@test.local", "VcaCollabSubSync123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/submissions/{self.SID}/sync",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_set_submission_org_unit(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.setorgunit@test.local", "VcaCollabSetOrgUnit123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            f"/api/v1/data-management/submissions/{self.SID}/org-unit",
            headers=headers,
            json={"org_unit_id": None},
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_coder_daily_stats(self):
        """Deliberately not widened: dm_coder_daily_statistics emits an
        unredacted coder_name today (see the docstring on
        dm_coder_daily_statistics and this task's final report)."""
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.dailystats@test.local", "VcaCollabDailyStats123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/coder-daily-stats")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_submissions_export_csv(self):
        """Deliberately not widened: dm_submissions_export_csv's base
        columns (dm_review_by, coder_review_by, reviewer_review_by, ...)
        carry staff-identity user ids with no should_redact_pii call."""
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.exportcsv@test.local", "VcaCollabExportCsv123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/submissions/export.csv")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_unrouted_submissions(self):
        """Deliberately not widened: this route resolves scope through its
        own private _dm_submission_scope_filter(), not dm_scope_filter."""
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.unrouted@test.local", "VcaCollabUnrouted123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/submissions/unrouted")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_project_site_submissions(self):
        """Deliberately not widened: resolves scope via
        get_data_manager_projects()/get_data_manager_project_sites()
        directly, not dm_scope_filter."""
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.pss@test.local", "VcaCollabPss123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/project-site-submissions")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_submission_detail_view(self):
        """Deliberately not widened: view_submission renders the ~1300-line
        renderpartial route, which is not yet redaction-safe for a viewer
        (.tasks/viewer-pii-roles.md, "Two surfaces still unredacted")."""
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.viewsub@test.local", "VcaCollabViewSub123"
        )
        self._login(str(user.user_id))

        response = self.client.get(f"/data-management/view/{self.SID}")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_odk_edit_link(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.odkedit@test.local", "VcaCollabOdkEdit123"
        )
        self._login(str(user.user_id))

        response = self.client.get(f"/data-management/submissions/{self.SID}/odk-edit")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_admin_user_management_page(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.usermgmt@test.local", "VcaCollabUserMgmt123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/users")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_grant_management_api(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.grants@test.local", "VcaCollabGrants123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/data-management/api/access-grants")

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_create_access_grant(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.creategrant@test.local", "VcaCollabCreateGrant123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post(
            "/data-management/api/access-grants",
            headers=headers,
            json={
                "user_id": str(user.user_id),
                "role": "coder",
                "scope_type": "project",
                "project_id": self.PROJECT,
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_admin_panel(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.adminpanel@test.local", "VcaCollabAdminPanel123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/admin/")

        self.assertIn(response.status_code, (403, 404))

    def test_collaborator_refused_on_coding_allocation(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.codingstart@test.local", "VcaCollabCodingStart123"
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post("/coding/start", headers=headers)

        self.assertEqual(response.status_code, 403)

    def test_collaborator_pii_refused_on_coding_allocation(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator_pii,
            "vca.collabpii.codingstart@test.local",
            "VcaCollabPiiCodingStart123",
        )
        self._login(str(user.user_id))
        headers = self._csrf_headers()

        response = self.client.post("/coding/start", headers=headers)

        self.assertEqual(response.status_code, 403)

    def test_collaborator_refused_on_reviewer_dashboard(self):
        user = self._make_viewer(
            VaAccessRoles.collaborator, "vca.collab.reviewdash@test.local", "VcaCollabReviewDash123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/reviewing/")

        self.assertEqual(response.status_code, 403)


class CollaboratorOrgUnitFilterOptionsRouteTests(BaseTestCase):
    """HTTP-level proof of the dm_filter_options / dm_scoped_forms fix.

    One project, one org tree with two sibling leaf units under two
    different sites, submissions in both units. A collaborator granted only
    unit A must not see site B (or form B) through the live routes — if
    both units' submissions landed on the same site, this could not fail
    for the right reason.
    """

    PROJECT = "VOU001"
    SITE_A = "VOUA"
    SITE_B = "VOUB"
    FORM_A = "VOU001VOUA01"
    FORM_B = "VOU001VOUB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Org Unit Filter Options Project",
                project_nickname="OrgUnitFilterOpts",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Org Unit Filter Options Project",
                project_nickname="OrgUnitFilterOpts",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()
        for site_id in (cls.SITE_A, cls.SITE_B):
            if db.session.get(VaSiteMaster, site_id) is None:
                db.session.add(VaSiteMaster(
                    site_id=site_id,
                    site_name=f"Org Unit Filter Options Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ))
            if db.session.get(VaSites, site_id) is None:
                db.session.add(VaSites(
                    site_id=site_id,
                    project_id=cls.PROJECT,
                    site_name=f"Org Unit Filter Options Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ))
        db.session.flush()
        for site_id in (cls.SITE_A, cls.SITE_B):
            if db.session.scalar(
                sa.select(VaProjectSites).where(
                    VaProjectSites.project_id == cls.PROJECT,
                    VaProjectSites.site_id == site_id,
                )
            ) is None:
                db.session.add(VaProjectSites(
                    project_id=cls.PROJECT,
                    site_id=site_id,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                ))
        db.session.flush()
        for form_id, site_id, odk_form in (
            (cls.FORM_A, cls.SITE_A, "VOU_FORM_A"),
            (cls.FORM_B, cls.SITE_B, "VOU_FORM_B"),
        ):
            if db.session.get(VaForms, form_id) is None:
                db.session.add(VaForms(
                    form_id=form_id,
                    project_id=cls.PROJECT,
                    site_id=site_id,
                    odk_form_id=odk_form,
                    odk_project_id="599",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                ))
            db.session.add(MapProjectSiteOdk(
                project_id=cls.PROJECT,
                site_id=site_id,
                odk_project_id=599,
                odk_form_id=odk_form,
                last_synced_at=now,
            ))
        db.session.flush()

        cls.sid_a = "uuid:org-unit-filter-opts-a"
        cls.sid_b = "uuid:org-unit-filter-opts-b"
        for sid, form_id in ((cls.sid_a, cls.FORM_A), (cls.sid_b, cls.FORM_B)):
            if db.session.get(VaSubmissions, sid) is None:
                db.session.add(VaSubmissions(
                    va_sid=sid,
                    va_form_id=form_id,
                    va_submission_date=now,
                    va_odk_updatedat=now,
                    va_data_collector="Collector",
                    va_instance_name=sid,
                    va_uniqueid_real=sid,
                    va_uniqueid_masked=sid,
                    va_consent="yes",
                    va_narration_language="English",
                    va_deceased_age=40,
                    va_deceased_gender="male",
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                ))
        db.session.flush()

        level = MasOrgLevel(
            project_id=cls.PROJECT,
            level_code="voudistrict",
            level_name="District",
            depth=1,
        )
        db.session.add(level)
        db.session.flush()
        cls.unit_a = MasOrgUnit(
            project_id=cls.PROJECT,
            org_level_id=level.org_level_id,
            unit_code="VOUUNITA",
            unit_name="Unit A",
            path="VOUUNITA",
        )
        cls.unit_b = MasOrgUnit(
            project_id=cls.PROJECT,
            org_level_id=level.org_level_id,
            unit_code="VOUUNITB",
            unit_name="Unit B",
            path="VOUUNITB",
        )
        db.session.add_all([cls.unit_a, cls.unit_b])
        db.session.flush()
        # ck_va_submissions_org_unit_resolution_pair requires both columns or
        # neither; setting org_unit_id alone violates it.
        sub_a = db.session.get(VaSubmissions, cls.sid_a)
        sub_a.org_unit_id = cls.unit_a.org_unit_id
        sub_a.org_unit_resolution = "manual"
        sub_b = db.session.get(VaSubmissions, cls.sid_b)
        sub_b.org_unit_id = cls.unit_b.org_unit_id
        sub_b.org_unit_resolution = "manual"
        db.session.commit()

    def _make_unit_a_viewer(self, role, email, password):
        user = self._get_or_make_user(email, password)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.unit_a.org_unit_id,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def test_unit_scoped_collaborator_filter_options_excludes_sibling_site(self):
        user = self._make_unit_a_viewer(
            VaAccessRoles.collaborator, "vou.collab.filteropts@test.local", "VouCollabFilterOpts123"
        )
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/filter-options")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        site_ids = {s["site_id"] for s in payload["sites"] if s["project_id"] == self.PROJECT}
        self.assertIn(self.SITE_A, site_ids)
        self.assertNotIn(self.SITE_B, site_ids)

    def test_data_manager_project_scope_filter_options_sees_both_sites(self):
        """Regression: a data_manager granted the whole project (not
        org_unit-scoped) is unaffected by the org_unit narrowing and still
        sees every site in it."""
        user = self._get_or_make_user("vou.dm.filteropts@test.local", "VouDmFilterOpts123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(user.user_id))

        response = self.client.get("/api/v1/data-management/filter-options")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        site_ids = {s["site_id"] for s in payload["sites"] if s["project_id"] == self.PROJECT}
        self.assertEqual(site_ids, {self.SITE_A, self.SITE_B})
