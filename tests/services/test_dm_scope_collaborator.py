"""Tests for wiring collaborator/collaborator_pii into dm_scope_filter.

Access half of the viewer-PII split (.tasks/viewer-pii-roles.md,
docs/policy/access-control-model.md, "collaborator" / "collaborator_pii").
The redaction half (what a viewer may see once in scope) is covered by
tests/services/test_viewer_pii_redaction.py and is not re-tested here.

Covers all three grant scope types named in the task:
  - project        -> _dm_scope_pairs via VaUsers.get_viewer_projects()
  - project_site    -> _dm_scope_pairs via VaUsers.get_viewer_project_sites()
  - org_unit        -> bridged to its whole project in _dm_scope_pairs
                        (dm_scope_filter alone is coarse there), but every
                        caller that could disclose more than the unit grants
                        — dm_submissions_page, _dm_submission_query_parts,
                        dm_scoped_forms, dm_filter_options — additionally
                        ANDs in (or EXISTS-restricts by)
                        dm_submission_org_unit_condition, which narrows back
                        to VaSubmissions.org_unit_id. A plain data_manager
                        never triggers that extra restriction (it returns
                        None for them), so their results are unchanged.
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
from app.services.data_management_service import (
    _dm_scope_pairs,
    dm_filter_options,
    dm_scope_filter,
    dm_scoped_forms,
    dm_submission_org_unit_condition,
    dm_submissions_page,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_READY_FOR_CODING
from tests.base import BaseTestCase


class ViewerScopeHelperTests(BaseTestCase):
    """VaUsers.get_viewer_* — the building blocks _dm_scope_pairs relies on."""

    PROJECT = "VSC001"
    SITE_A = "VSCA"
    SITE_B = "VSCB"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer Scope Helper Project",
                project_nickname="ViewerScopeHelper",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        for site_id in (cls.SITE_A, cls.SITE_B):
            if db.session.get(VaSiteMaster, site_id) is None:
                db.session.add(VaSiteMaster(
                    site_id=site_id,
                    site_name=f"Viewer Scope Site {site_id}",
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
        db.session.commit()

    def test_get_viewer_projects_unions_both_viewer_roles(self):
        user = self._get_or_make_user("vsc.collab@test.local", "VscCollab123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.collaborator,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

        self.assertEqual(user.get_viewer_projects(), {self.PROJECT})
        self.assertTrue(user.is_viewer())
        # data_manager-only helpers are unaffected.
        self.assertEqual(user.get_data_manager_projects(), set())

    def test_get_viewer_project_sites_from_collaborator_pii(self):
        user = self._get_or_make_user("vsc.collab.pii@test.local", "VscCollabPii123")
        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.PROJECT,
                VaProjectSites.site_id == self.SITE_A,
            )
        )
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.collaborator_pii,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

        self.assertEqual(user.get_viewer_project_sites(), {(self.PROJECT, self.SITE_A)})
        self.assertTrue(user.is_viewer())

    def test_user_with_no_grants_is_not_a_viewer(self):
        user = self._get_or_make_user("vsc.none@test.local", "VscNone123")
        self.assertFalse(user.is_viewer())
        self.assertEqual(user.get_viewer_projects(), set())
        self.assertEqual(user.get_viewer_project_sites(), set())
        self.assertEqual(user.get_viewer_org_unit_ids(), set())

    def test_inactive_grant_does_not_count(self):
        user = self._get_or_make_user("vsc.inactive@test.local", "VscInactive123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.collaborator,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.deactive,
        ))
        db.session.commit()

        self.assertFalse(user.is_viewer())


class DmScopeFilterCollaboratorTests(BaseTestCase):
    """_dm_scope_pairs / dm_scope_filter resolve collaborator grants at all
    three scope types; data_manager behaviour is unchanged (regression)."""

    PROJECT = "VDS001"
    SITE_A = "VDSA"
    SITE_B = "VDSB"
    FORM_A = "VDS001VDSA01"
    FORM_B = "VDS001VDSB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="DM Scope Filter Collaborator Project",
                project_nickname="DmScopeCollab",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="DM Scope Filter Collaborator Project",
                project_nickname="DmScopeCollab",
                project_status=VaStatuses.active,
            ))
        db.session.flush()
        for site_id in (cls.SITE_A, cls.SITE_B):
            if db.session.get(VaSiteMaster, site_id) is None:
                db.session.add(VaSiteMaster(
                    site_id=site_id,
                    site_name=f"DM Scope Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ))
            if db.session.get(VaSites, site_id) is None:
                db.session.add(VaSites(
                    site_id=site_id,
                    project_id=cls.PROJECT,
                    site_name=f"DM Scope Site {site_id}",
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
            (cls.FORM_A, cls.SITE_A, "VDS_FORM_A"),
            (cls.FORM_B, cls.SITE_B, "VDS_FORM_B"),
        ):
            if db.session.get(VaForms, form_id) is None:
                db.session.add(VaForms(
                    form_id=form_id,
                    project_id=cls.PROJECT,
                    site_id=site_id,
                    odk_form_id=odk_form,
                    odk_project_id="399",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                ))
            db.session.add(MapProjectSiteOdk(
                project_id=cls.PROJECT,
                site_id=site_id,
                odk_project_id=399,
                odk_form_id=odk_form,
                last_synced_at=now,
            ))
        db.session.commit()

        # One submission per site, and an organization tree over site A so
        # the org_unit-scoped tests have something to restrict against.
        cls.sid_a = "uuid:dm-scope-collab-a"
        cls.sid_b = "uuid:dm-scope-collab-b"
        for sid, form_id in ((cls.sid_a, cls.FORM_A), (cls.sid_b, cls.FORM_B)):
            if db.session.get(VaSubmissions, sid) is None:
                submission = VaSubmissions(
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
                )
                db.session.add(submission)
                db.session.flush()
                ensure_active_payload_version(
                    submission,
                    payload_data={"sid": sid, "form_def": form_id, "unique_id": sid},
                    source_updated_at=now,
                    created_by_role="vasystem",
                )
                db.session.add(VaSubmissionWorkflow(
                    va_sid=sid,
                    workflow_state=WORKFLOW_READY_FOR_CODING,
                    workflow_created_at=now,
                    workflow_updated_at=now,
                ))
        db.session.commit()

        cls.level = MasOrgLevel(
            project_id=cls.PROJECT,
            level_code="vdsdistrict",
            level_name="District",
            depth=1,
        )
        db.session.add(cls.level)
        db.session.flush()
        cls.unit_a = MasOrgUnit(
            project_id=cls.PROJECT,
            org_level_id=cls.level.org_level_id,
            unit_code="VDSUNITA",
            unit_name="Unit A",
            path="VDSUNITA",
        )
        cls.unit_b = MasOrgUnit(
            project_id=cls.PROJECT,
            org_level_id=cls.level.org_level_id,
            unit_code="VDSUNITB",
            unit_name="Unit B",
            path="VDSUNITB",
        )
        db.session.add_all([cls.unit_a, cls.unit_b])
        db.session.flush()
        # ck_va_submissions_org_unit_resolution_pair requires org_unit_id and
        # org_unit_resolution to be both NULL or both set, so the resolution
        # has to be assigned alongside the unit, never on its own.
        submission_a = db.session.get(VaSubmissions, cls.sid_a)
        submission_a.org_unit_id = cls.unit_a.org_unit_id
        submission_a.org_unit_resolution = "manual"
        submission_b = db.session.get(VaSubmissions, cls.sid_b)
        submission_b.org_unit_id = cls.unit_b.org_unit_id
        submission_b.org_unit_resolution = "manual"
        db.session.commit()

    def _grant(self, user, role, **kwargs):
        kwargs.setdefault("grant_status", VaStatuses.active)
        db.session.add(VaUserAccessGrants(user_id=user.user_id, role=role, **kwargs))
        db.session.commit()

    def test_project_scope_collaborator_sees_both_sites(self):
        user = self._get_or_make_user("vds.collab.project@test.local", "VdsCollabProject123")
        self._grant(
            user,
            VaAccessRoles.collaborator,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        pairs = _dm_scope_pairs(user)
        self.assertEqual(pairs, {(self.PROJECT, self.SITE_A), (self.PROJECT, self.SITE_B)})

        result = dm_submissions_page(user, per_page=25)
        sids = {row["va_sid"] for row in result["data"]}
        self.assertIn(self.sid_a, sids)
        self.assertIn(self.sid_b, sids)

    def test_project_site_scope_collaborator_pii_sees_only_its_site(self):
        user = self._get_or_make_user("vds.collabpii.site@test.local", "VdsCollabPiiSite123")
        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.PROJECT,
                VaProjectSites.site_id == self.SITE_A,
            )
        )
        self._grant(
            user,
            VaAccessRoles.collaborator_pii,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id,
        )

        pairs = _dm_scope_pairs(user)
        self.assertEqual(pairs, {(self.PROJECT, self.SITE_A)})

        result = dm_submissions_page(user, per_page=25)
        sids = {row["va_sid"] for row in result["data"]}
        self.assertIn(self.sid_a, sids)
        self.assertNotIn(self.sid_b, sids)

    def test_org_unit_scope_collaborator_restricted_to_its_unit_not_whole_project(self):
        """The security-relevant case: dm_scope_filter alone bridges an
        org_unit grant to the whole project (coarse, by design), but
        dm_submissions_page also ANDs in dm_submission_org_unit_condition,
        which must narrow the result back to the granted unit's own
        submissions. Unit A's submission must be visible; unit B's
        (same project, different unit, no grant) must not.
        """
        user = self._get_or_make_user("vds.collab.org@test.local", "VdsCollabOrg123")
        self._grant(
            user,
            VaAccessRoles.collaborator,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.unit_a.org_unit_id,
        )

        # dm_scope_filter alone is coarse: it bridges the org_unit grant to
        # the whole project, so both site pairs come back from it.
        pairs = _dm_scope_pairs(user)
        self.assertEqual(pairs, {(self.PROJECT, self.SITE_A), (self.PROJECT, self.SITE_B)})

        # But the actual submission listing ANDs in the narrower per-unit
        # condition, so only the granted unit's submission is visible.
        result = dm_submissions_page(user, per_page=25)
        sids = {row["va_sid"] for row in result["data"]}
        self.assertIn(self.sid_a, sids)
        self.assertNotIn(self.sid_b, sids)

    def test_no_org_unit_grant_returns_no_extra_condition(self):
        """A user with no viewer org_unit grant (including a plain
        data_manager) gets None back — dm_submissions_page must not append
        anything, so its query is byte-for-byte what it was before this
        change for every role except a viewer holding an org_unit grant.
        """
        dm_user = self._get_or_make_user("vds.dm.plain@test.local", "VdsDmPlain123")
        self._grant(
            dm_user,
            VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )
        self.assertIsNone(dm_submission_org_unit_condition(dm_user))

    def test_data_manager_scope_unaffected_by_collaborator_wiring(self):
        """Regression: a data_manager-only user's scope is exactly what it
        was before collaborator roles were wired in."""
        user = self._get_or_make_user("vds.dm.regress@test.local", "VdsDmRegress123")
        self._grant(
            user,
            VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=db.session.scalar(
                sa.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == self.PROJECT,
                    VaProjectSites.site_id == self.SITE_A,
                )
            ),
        )

        pairs = _dm_scope_pairs(user)
        self.assertEqual(pairs, {(self.PROJECT, self.SITE_A)})

    def test_dm_scoped_forms_excludes_forms_with_only_sibling_unit_submissions(self):
        """dm_scope_filter alone bridges an org_unit grant to the whole
        project, which would hand a unit-scoped viewer every site name and
        ODK project/form id in that project (a leak: the site roster is more
        than the grant conveys). dm_scoped_forms closes this with an EXISTS
        on a submission the dm_submission_org_unit_condition actually allows
        — form B's only submission sits in unit B, which this viewer was
        never granted, so form B must not appear even though its project is
        the same as form A's.
        """
        user = self._get_or_make_user("vds.collab.forms@test.local", "VdsCollabForms123")
        self._grant(
            user,
            VaAccessRoles.collaborator_pii,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.unit_a.org_unit_id,
        )

        forms = dm_scoped_forms(user)
        form_ids = {f["form_id"] for f in forms}
        self.assertIn(self.FORM_A, form_ids)
        self.assertNotIn(self.FORM_B, form_ids)

    def test_dm_scoped_forms_unchanged_for_data_manager(self):
        """Regression: a data_manager grant (no org_unit involved) gets
        None back from dm_submission_org_unit_condition, so the EXISTS
        restriction never applies and both forms in scope are returned,
        exactly as before this fix."""
        user = self._get_or_make_user("vds.dm.forms@test.local", "VdsDmForms123")
        self._grant(
            user,
            VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        forms = dm_scoped_forms(user)
        form_ids = {f["form_id"] for f in forms}
        self.assertIn(self.FORM_A, form_ids)
        self.assertIn(self.FORM_B, form_ids)

    def test_dm_filter_options_excludes_sibling_unit_site_and_project_stays(self):
        """Same leak, same fix, in the filter-options dropdowns: a viewer
        granted only unit A must see site A (their own unit's submission)
        but not site B, even though both sites belong to the same project
        and dm_scope_filter alone would have allowed both.
        """
        user = self._get_or_make_user("vds.collab.filteropts@test.local", "VdsCollabFilterOpts123")
        self._grant(
            user,
            VaAccessRoles.collaborator,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.unit_a.org_unit_id,
        )

        options = dm_filter_options(user)
        self.assertIn(self.PROJECT, options["projects"])
        site_ids = {s["site_id"] for s in options["sites"] if s["project_id"] == self.PROJECT}
        self.assertIn(self.SITE_A, site_ids)
        self.assertNotIn(self.SITE_B, site_ids)

    def test_dm_filter_options_unchanged_for_data_manager(self):
        """Regression: a data_manager granted the whole project still sees
        every site in it — the org_unit restriction never applies to them."""
        user = self._get_or_make_user("vds.dm.filteropts@test.local", "VdsDmFilterOpts123")
        self._grant(
            user,
            VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        options = dm_filter_options(user)
        site_ids = {s["site_id"] for s in options["sites"] if s["project_id"] == self.PROJECT}
        self.assertEqual(site_ids, {self.SITE_A, self.SITE_B})

    def test_empty_scope_returns_false_clause(self):
        user = self._get_or_make_user("vds.none@test.local", "VdsNone123")
        clause = dm_scope_filter(user)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("false", compiled.lower())
