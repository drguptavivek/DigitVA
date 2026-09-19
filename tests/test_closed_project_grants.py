"""A closed project resolves no grant, in any scope or mechanism.

Rule under test: a project whose ``va_project_master.project_status`` is not
``active`` resolves **no** grant of any scope (project, project_site,
org_unit) for any non-admin role. The grant rows are not touched — reopening
the project restores access unchanged.

Implementation: ``org_grant_service.active_project_condition``, applied by
every resolver. Policy: docs/policy/access-control-model.md, "Closed
projects".

Each test asserts access is present first, then closes the project, then
asserts it is gone, then reopens and asserts it is back — so a test cannot
pass because the fixture never granted anything.
"""

import uuid
from datetime import UTC, datetime

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
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from app.services.org_grant_service import (
    granted_project_ids,
    project_wide_grant_exists,
    scope_unit_ids,
)
from tests.base import BaseTestCase


class ClosedProjectGrantResolutionTests(BaseTestCase):
    # Ids unique to this class (see tests/base.py: fixtures are shared per
    # session, so a collision with another class is a cross-test failure).
    PROJECT = "CLSD01"
    OTHER_PROJECT = "CLSD02"
    SITE = "CS01"
    OTHER_SITE = "CS02"
    FORM = "CLSD01CS0101"
    OTHER_FORM = "CLSD02CS0201"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, site_id, form_id, odk_form in (
            (cls.PROJECT, cls.SITE, cls.FORM, "CLOSED_PROJ_FORM_A"),
            (cls.OTHER_PROJECT, cls.OTHER_SITE, cls.OTHER_FORM, "CLOSED_PROJ_FORM_B"),
        ):
            db.session.add(
                VaResearchProjects(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Closed Project Test {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Closed Project Test {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.add(
                VaSiteMaster(
                    site_id=site_id,
                    site_name=f"Closed Project Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.add(
                VaSites(
                    site_id=site_id,
                    project_id=project_id,
                    site_name=f"Closed Project Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
            db.session.add(
                VaProjectSites(
                    project_id=project_id,
                    site_id=site_id,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                )
            )
            db.session.add(
                VaForms(
                    form_id=form_id,
                    project_id=project_id,
                    site_id=site_id,
                    odk_form_id=odk_form,
                    odk_project_id="11",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.flush()

        org.seed_default_organization(cls.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT)}
        cls.district = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="CD1",
            unit_name="Closed Project District",
        )
        cls.chc = org.create_unit(
            cls.PROJECT,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=cls.district.org_unit_id,
            unit_code="CC1",
            unit_name="Closed Project CHC",
        )
        db.session.commit()

    # -- helpers ------------------------------------------------------------

    def _create_user(self, label):
        email = f"closed.project.{label}.{uuid.uuid4().hex[:8]}@test.local"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password("ClosedProject123")
        db.session.add(user)
        db.session.flush()
        return user

    def _project_site_id(self, project_id, site_id):
        return db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == project_id,
                VaProjectSites.site_id == site_id,
            )
        )

    def _grant(self, user, role, scope_type, **scope):
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=scope_type,
            grant_status=VaStatuses.active,
            notes="closed-project grant resolution test",
            **scope,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    def _set_project_status(self, project_id, status):
        project = db.session.get(VaProjectMaster, project_id)
        project.project_status = status
        db.session.commit()

    def _assert_dormant_then_restored(self, project_id, has_access):
        """has_access() is True now, False while closed, True again after."""
        self.assertTrue(has_access(), "grant did not resolve while project was active")
        self._set_project_status(project_id, VaStatuses.deactive)
        self.assertFalse(has_access(), "grant still resolved on a closed project")
        self._set_project_status(project_id, VaStatuses.active)
        self.assertTrue(has_access(), "grant did not come back when project reopened")

    # -- project scope ------------------------------------------------------

    def test_project_scoped_interviewer_grant_goes_dormant(self):
        user = self._create_user("interviewer")
        self._grant(
            user,
            VaAccessRoles.interviewer,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        roles = frozenset({VaAccessRoles.interviewer})
        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: project_wide_grant_exists(user.user_id, self.PROJECT, roles),
        )
        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: self.FORM in user.get_interviewer_va_forms(),
        )

    def test_project_scoped_grant_row_survives_closure(self):
        """The rule is resolution-time only: nothing rewrites the grant."""
        user = self._create_user("dormant.row")
        grant = self._grant(
            user,
            VaAccessRoles.interviewer,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        self._set_project_status(self.PROJECT, VaStatuses.deactive)
        db.session.refresh(grant)
        self.assertEqual(grant.grant_status, VaStatuses.active)
        self.assertEqual(grant.project_id, self.PROJECT)
        self._set_project_status(self.PROJECT, VaStatuses.active)

    # -- project_site scope -------------------------------------------------

    def test_project_site_grant_goes_dormant(self):
        user = self._create_user("coder")
        self._grant(
            user,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project_site,
            project_site_id=self._project_site_id(self.PROJECT, self.SITE),
        )

        roles = frozenset({VaAccessRoles.coder})
        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: project_wide_grant_exists(user.user_id, self.PROJECT, roles),
        )
        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: user.get_coder_va_forms() == {self.FORM},
        )

    # -- org_unit scope -----------------------------------------------------

    def test_org_unit_grant_goes_dormant(self):
        user = self._create_user("unit.interviewer")
        self._grant(
            user,
            VaAccessRoles.interviewer,
            VaAccessScopeTypes.org_unit,
            org_unit_id=self.chc.org_unit_id,
        )

        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: scope_unit_ids(user.user_id, VaAccessRoles.interviewer)
            == {self.chc.org_unit_id},
        )
        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: granted_project_ids(user.user_id, VaAccessRoles.interviewer)
            == {self.PROJECT},
        )

    # -- data_manager -------------------------------------------------------

    def test_data_manager_project_grant_goes_dormant(self):
        user = self._create_user("dm")
        self._grant(
            user,
            VaAccessRoles.data_manager,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: user.get_data_manager_projects() == {self.PROJECT},
        )
        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: user.has_data_manager_submission_access(self.PROJECT, self.SITE),
        )

    def test_data_manager_route_refuses_while_project_closed(self):
        """End-to-end control through a route that does NOT pre-check the
        project's status, so the refusal can only come from the resolver."""
        user = self._create_user("dm.route")
        self._grant(
            user,
            VaAccessRoles.data_manager,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )
        self._login(str(user.user_id))

        def reaches_api():
            return (
                self.client.get("/api/v1/data-management/filter-options").status_code
                == 200
            )

        self._assert_dormant_then_restored(self.PROJECT, reaches_api)

    # -- project_pi ---------------------------------------------------------

    def test_project_pi_grant_goes_dormant(self):
        user = self._create_user("pi")
        self._grant(
            user,
            VaAccessRoles.project_pi,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )

        self._assert_dormant_then_restored(
            self.PROJECT,
            lambda: user.can_manage_project(self.PROJECT),
        )

    # -- positive control ---------------------------------------------------

    def test_grant_on_a_different_active_project_is_unaffected(self):
        user = self._create_user("two.projects")
        for project_id in (self.PROJECT, self.OTHER_PROJECT):
            self._grant(
                user,
                VaAccessRoles.data_manager,
                VaAccessScopeTypes.project,
                project_id=project_id,
            )

        self.assertEqual(
            user.get_data_manager_projects(), {self.PROJECT, self.OTHER_PROJECT}
        )

        self._set_project_status(self.PROJECT, VaStatuses.deactive)
        self.assertEqual(user.get_data_manager_projects(), {self.OTHER_PROJECT})
        self.assertEqual(user.get_data_manager_va_forms(), {self.OTHER_FORM})

        self._set_project_status(self.PROJECT, VaStatuses.active)
        self.assertEqual(
            user.get_data_manager_projects(), {self.PROJECT, self.OTHER_PROJECT}
        )
