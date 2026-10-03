"""Project- and project_site-scope coder/reviewer grants on a tree project.

Owner decision 2026-10-02 (digitva-7xq): such a grant is a grant at the top of
the organization tree. It views every submission of its project, or of its
(project, site) pair, routed or not. It codes or reviews them unless the
project sets a coding scope level with above_scope_coding_mode = 'view_only'.
Policy: docs/policy/organization-model.md, "Coding scope".
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.routes.api.workflow import _may_read_events
from app.services import org_unit_routing_service as routing
from app.services import organization_service as org
from app.services.attachment_service import can_access_submission_attachment
from app.services.authz import Action, Reason, can, scope_filter
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_pick_form,
    get_pick_available_forms,
)
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin

SCOPES = ("project", "project_site")
ROLES = (VaAccessRoles.coder, VaAccessRoles.reviewer)
# The action each role's coding scope answers.
WORK = {VaAccessRoles.coder: Action.CODE, VaAccessRoles.reviewer: Action.REVIEW}


class ProjectGrantOrgScopeTests(CodingScopeFixtureMixin, BaseTestCase):
    """CSC001 and QSC001 both hold site CS01; both have an organization tree."""

    OTHER_PROJECT = "QSC001"
    OTHER_FORM_ID = "QSC001CS0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for model in (VaProjectMaster, VaResearchProjects):
            if db.session.get(model, cls.OTHER_PROJECT) is None:
                db.session.add(model(
                    project_id=cls.OTHER_PROJECT, project_code=cls.OTHER_PROJECT,
                    project_name="Other Scope Project", project_nickname="OtherScope",
                    project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.OTHER_PROJECT, site_id=cls.SITE,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.add(VaForms(
            form_id=cls.OTHER_FORM_ID, project_id=cls.OTHER_PROJECT, site_id=cls.SITE,
            odk_form_id="OTHER_SCOPE_FORM", odk_project_id="92",
            form_type="WHO VA 2022", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.commit()
        org.seed_default_organization(cls.OTHER_PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.OTHER_PROJECT)}
        cls.other_district_id = org.create_unit(
            cls.OTHER_PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="QD01", unit_name="Other District",
        ).org_unit_id
        db.session.commit()

    def setUp(self):
        super().setUp()
        _, self.district, _, self.phc_a, _ = self._tree()
        self.levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        self._submission("csc-routed", unit=self.phc_a)
        self._submission("csc-unrouted")
        self.user = self._make_user("project.grantee@test.local", "Grantee123")

    # -- fixtures ----------------------------------------------------------

    def _wide_grant(self, scope, role):
        if scope == "project":
            fields = {"scope_type": VaAccessScopeTypes.project, "project_id": self.PROJECT}
        else:
            project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.PROJECT,
                VaProjectSites.site_id == self.SITE,
            ))
            fields = {
                "scope_type": VaAccessScopeTypes.project_site,
                "project_site_id": project_site_id,
            }
        db.session.add(VaUserAccessGrants(
            user_id=self.user.user_id, role=role,
            grant_status=VaStatuses.active, **fields,
        ))
        db.session.commit()

    def _configure(self, config):
        if config == "no_scope_level":
            return
        self._set_scope(self.levels["phc"], mode=config)

    def _listed(self, role):
        """Submissions of CSC001 the shared list filter offers for *role*."""
        stmt = sa.select(VaSubmissions.va_sid).where(
            VaSubmissions.va_form_id == self.FORM_ID,
            scope_filter(self.user, WORK[role]),
        )
        return set(db.session.scalars(stmt).all())

    def _check(self, role, *, codes):
        sids = ("csc-routed", "csc-unrouted")
        for sid in sids:
            # Viewing never depends on the coding scope level.
            self.assertTrue(can(self.user, Action.VIEW, sid))
            self.assertTrue(_may_read_events(self.user, db.session.get(VaSubmissions, sid)))
            self.assertEqual(bool(can(self.user, WORK[role], sid)), codes)
        self.assertEqual(self._listed(role), set(sids) if codes else set())

    # -- the three configurations ------------------------------------------

    def test_no_scope_level_views_and_codes_everything_in_scope(self):
        for scope in SCOPES:
            for role in ROLES:
                with self.subTest(scope=scope, role=role.value):
                    self._wide_grant(scope, role)
                    self._check(role, codes=True)
                    self._clear_wide_grants()

    def test_view_only_scope_level_views_but_codes_nothing(self):
        self._configure("view_only")
        for scope in SCOPES:
            for role in ROLES:
                with self.subTest(scope=scope, role=role.value):
                    self._wide_grant(scope, role)
                    self._check(role, codes=False)
                    self._clear_wide_grants()

    def test_code_any_scope_level_views_and_codes(self):
        self._configure("code_any")
        for scope in SCOPES:
            for role in ROLES:
                with self.subTest(scope=scope, role=role.value):
                    self._wide_grant(scope, role)
                    self._check(role, codes=True)
                    self._clear_wide_grants()

    def _clear_wide_grants(self):
        db.session.execute(sa.delete(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.user.user_id,
        ))
        db.session.commit()

    # -- coder surfaces: pick list and allocation --------------------------

    def _pick(self):
        forms = self.user.get_coder_va_forms()
        return {row["va_sid"] for row in get_pick_available_forms(self.user, list(forms))}

    def test_a_project_site_coder_picks_and_is_allocated_without_a_scope_level(self):
        self._wide_grant("project_site", VaAccessRoles.coder)
        self.assertEqual(self._pick(), {"csc-routed", "csc-unrouted"})
        result = allocate_pick_form(self.user, "csc-unrouted")
        self.assertEqual(result.va_sid, "csc-unrouted")

    def test_a_view_only_project_coder_is_offered_and_allocated_nothing(self):
        self._configure("view_only")
        self._wide_grant("project", VaAccessRoles.coder)
        # The grant reaches the form; the coding scope makes it view-only.
        self.assertIs(can(self.user, Action.CODE, "csc-routed").reason, Reason.VIEW_ONLY)
        self.assertEqual(self._pick(), set())
        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(self.user, "csc-routed")
        self.assertIn("outside your coding scope", str(ctx.exception))

    def test_a_view_only_project_reviewer_keeps_attachment_access(self):
        # Attachments follow VIEW, the wider right (digitva-0wc stage 2,
        # F7/F12): a reviewer who may not review above the scope level still
        # views the submission, attachments included.
        self._wide_grant("project", VaAccessRoles.reviewer)
        self.assertTrue(can_access_submission_attachment(
            self.user, va_form_id=self.FORM_ID, va_sid="csc-routed"))
        self._configure("view_only")
        self.assertTrue(can_access_submission_attachment(
            self.user, va_form_id=self.FORM_ID, va_sid="csc-routed"))

    # -- the pair key ------------------------------------------------------

    def test_a_project_site_grant_reaches_nothing_of_the_same_site_in_another_project(self):
        now = datetime.now(UTC)
        for sid, unit_id in (("qsc-routed", self.other_district_id), ("qsc-unrouted", None)):
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=self.OTHER_FORM_ID, va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="Collector",
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English",
                va_deceased_age=42, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
                org_unit_id=unit_id,
                org_unit_resolution=routing.RESOLUTION_FORM_FIELD if unit_id else None,
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state="ready_for_coding",
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))
        db.session.commit()
        for role in ROLES:
            with self.subTest(role=role.value):
                self._wide_grant("project_site", role)
                # The subject: the grant does reach (P, S).
                self.assertTrue(can(self.user, WORK[role], "csc-routed"))
                for sid in ("qsc-routed", "qsc-unrouted"):
                    self.assertFalse(can(self.user, Action.VIEW, sid))
                    self.assertFalse(can(self.user, WORK[role], sid))
                    self.assertFalse(_may_read_events(self.user, db.session.get(VaSubmissions, sid)))
                listed = set(db.session.scalars(sa.select(VaSubmissions.va_sid).where(
                    VaSubmissions.va_form_id == self.OTHER_FORM_ID,
                    scope_filter(self.user, WORK[role]),
                )).all())
                self.assertEqual(listed, set())
                self._clear_wide_grants()
