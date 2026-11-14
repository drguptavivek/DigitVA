"""A grant on the training project confers no authority over users or grants
(digitva-svx6): a reviewer_data_manager trainee, even with the data_manager
grant older sessions wrote, cannot list co-trainees, write or revoke their
grants, or issue their sign-in QR. Admins and real data managers are unaffected."""

from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import authz, sign_in_qr_service
from app.services import training_demo_service as svc
from tests.training_demo_fixtures import TrainingDemoTestBase


class TrainingGrantAuthorityTests(TrainingDemoTestBase):
    def setUp(self):
        super().setUp()
        self.manager = self._user("auth.rdm")
        svc.add_participant("S001", self.manager.email, "reviewer_data_manager", self.admin)
        self.legacy = self._legacy_dm_grant(self.manager)
        self.trainee = self._user("auth.trainee")
        svc.add_participant("S001", self.trainee.email, ["interviewer", "death_reporter"], self.admin)
        self.root = db.session.get(MasOrgUnit, svc._find_session("S001").org_unit_id)
        db.session.commit()

    def _trainee_grants(self):
        return self._grants(self.trainee, VaStatuses.active)

    def _target(self, role=VaAccessRoles.interviewer):
        return authz.GrantTarget(role=role, scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.root.org_unit_id)

    def _manageable(self, actor):
        return set(db.session.scalars(sa.select(VaUserAccessGrants.grant_id).where(
            VaUserAccessGrants.user_id == self.trainee.user_id, authz.grant_list_filter(actor))))

    def _listed(self, actor):
        return set(db.session.scalars(sa.select(VaUserAccessGrants.user_id).where(
            VaUserAccessGrants.user_id == self.trainee.user_id, authz.user_list_filter(actor))))

    def test_new_participation_writes_no_data_manager_grant(self):
        roles = {g.role for g in self._grants(self.manager, VaStatuses.active)}
        self.assertIn(VaAccessRoles.reviewer, roles)
        # The only data_manager grant is the legacy one this test wrote itself.
        dm = [g for g in self._grants(self.manager) if g.role == VaAccessRoles.data_manager]
        self.assertEqual([g.grant_id for g in dm], [self.legacy.grant_id])

    def test_training_data_manager_grant_confers_nothing(self):
        self.assertEqual(len(self._trainee_grants()), 2)  # the subject exists
        self.assertEqual(authz.writer_grants(authz.resolve_grants(self.manager)), [])
        self.assertEqual(self._listed(self.manager), set())
        self.assertEqual(self._manageable(self.manager), set())
        self.assertFalse(authz.can_grant(self.manager, self._target(), grantee_id=self.trainee.user_id))
        self.assertFalse(sign_in_qr_service.may_issue(self.manager, self.trainee.user_id))

    def test_the_same_grant_off_the_training_project_would_confer_it(self):
        # The presence half: were TRN01 not the training project, the legacy grant manages the co-trainee.
        with mock.patch("app.services.authz.grant_writes.training_project_id", return_value=None):
            self.assertTrue(authz.writer_grants(authz.resolve_grants(self.manager)))
            self.assertEqual(self._listed(self.manager), {self.trainee.user_id})
            self.assertEqual(self._manageable(self.manager), {g.grant_id for g in self._trainee_grants()})
            self.assertTrue(sign_in_qr_service.may_issue(self.manager, self.trainee.user_id))

    def test_users_api_lists_no_co_trainee(self):
        self._login(str(self.admin.user_id))
        as_admin = self.client.get(f"/api/v1/users?q={self.trainee.email}")
        self.assertEqual([u["email"] for u in as_admin.get_json()["users"]], [self.trainee.email])
        self._login(str(self.manager.user_id))
        response = self.client.get(f"/api/v1/users?q={self.trainee.email}")
        self.assertEqual(response.status_code, 200)  # the legacy grant passes the role gate...
        self.assertEqual(response.get_json()["users"], [])  # ...and reaches nobody

    def test_admin_keeps_its_authority(self):
        self.assertEqual(self._manageable(self.admin), {g.grant_id for g in self._trainee_grants()})
        self.assertTrue(authz.can_grant(self.admin, self._target()))
        self.assertTrue(sign_in_qr_service.may_issue(self.admin, self.trainee.user_id))

    def test_a_real_data_manager_is_unaffected(self):
        pair = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.BASE_PROJECT_ID, VaProjectSites.site_id == self.BASE_SITE_ID))
        real_dm, coder = self._user("auth.realdm"), self._user("auth.realcoder")
        for user, role in ((real_dm, VaAccessRoles.data_manager), (coder, VaAccessRoles.coder)):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project_site,
                project_site_id=pair.project_site_id, grant_status=VaStatuses.active))
        db.session.commit()
        authz.invalidate(real_dm.user_id)
        self.assertTrue(authz.writer_grants(authz.resolve_grants(real_dm)))
        managed = set(db.session.scalars(sa.select(VaUserAccessGrants.user_id).where(
            authz.grant_list_filter(real_dm))))
        self.assertIn(coder.user_id, managed)
        self.assertTrue(authz.can_grant(real_dm, authz.GrantTarget(
            role=VaAccessRoles.coder, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=pair.project_site_id), grantee_id=coder.user_id))
        # ... and still nothing on the training project.
        self.assertFalse(authz.can_grant(real_dm, self._target()))
