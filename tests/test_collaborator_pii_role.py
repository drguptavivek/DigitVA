"""The collaborator_pii role: grant creation, scope rules, and parity with
plain collaborator wherever a grant is read.

This is the foundation half of the viewer-PII split
(.tasks/viewer-pii-roles.md, docs/policy/access-control-model.md,
"collaborator" / "collaborator_pii" / Role To Scope Rules). Redaction itself
is a separate piece of work and is NOT exercised here — these tests only
cover that the role can be granted, at the right scopes and not at others,
and that it resolves through the shared org-unit helpers identically to
collaborator.
"""
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import org_grant_service as og
from app.services import organization_service as org
from tests.base import BaseTestCase


class CollaboratorPiiRoleTests(BaseTestCase):
    PROJECT = "CPR001"
    SITE = "CP01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=cls.PROJECT,
                    project_code=cls.PROJECT,
                    project_name="Collaborator PII Test Project",
                    project_nickname="CollabPiiTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(
                VaSiteMaster(
                    site_id=cls.SITE,
                    site_name="Collaborator PII Test Site",
                    site_abbr=cls.SITE,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
        db.session.commit()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.commit()
        cls.project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.PROJECT,
                VaProjectSites.site_id == cls.SITE,
            )
        )

    def setUp(self):
        super().setUp()
        self.target_user = self._get_or_make_user(
            "collab.pii.target@test.local", "CollabPiiTarget123"
        )

    def _grant(self, role, scope_type, **kwargs):
        grant = VaUserAccessGrants(
            user_id=self.target_user.user_id,
            role=role,
            scope_type=scope_type,
            grant_status=VaStatuses.active,
            **kwargs,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    # -- grant creation at permitted scopes --------------------------------

    def test_collaborator_pii_grant_can_be_created_at_project_scope(self):
        grant = self._grant(
            VaAccessRoles.collaborator_pii,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )
        self.assertEqual(grant.role, VaAccessRoles.collaborator_pii)

    def test_collaborator_pii_grant_can_be_created_at_project_site_scope(self):
        grant = self._grant(
            VaAccessRoles.collaborator_pii,
            VaAccessScopeTypes.project_site,
            project_site_id=self.project_site_id,
        )
        self.assertEqual(grant.role, VaAccessRoles.collaborator_pii)

    def test_collaborator_pii_grant_can_be_created_at_org_unit_scope(self):
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        unit = org.create_unit(
            self.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="CPRD01",
            unit_name="Collaborator PII District",
        )
        db.session.commit()

        resolved_unit, cadre = og.validate_org_unit_grant(
            role=VaAccessRoles.collaborator_pii, org_unit_id=unit.org_unit_id
        )
        self.assertEqual(resolved_unit.org_unit_id, unit.org_unit_id)
        self.assertIsNone(cadre)

        grant = self._grant(
            VaAccessRoles.collaborator_pii,
            VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id,
        )
        self.assertEqual(grant.role, VaAccessRoles.collaborator_pii)

    # -- rejection at global scope -------------------------------------------

    def test_collaborator_pii_grant_is_rejected_at_global_scope(self):
        grant = VaUserAccessGrants(
            user_id=self.target_user.user_id,
            role=VaAccessRoles.collaborator_pii,
            scope_type=VaAccessScopeTypes.global_scope,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_admin_api_refuses_collaborator_pii_at_global_scope(self):
        # Belt-and-suspenders on the HTTP path: _resolve_scope_from_payload's
        # global branch only ever accepts role == admin, so this never reaches
        # the database constraint above.
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        response = self.client.post(
            "/admin/api/access-grants",
            json={
                "user_id": str(self.target_user.user_id),
                "role": "collaborator_pii",
                "scope_type": "global",
            },
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["error"], "Only admin may use global scope."
        )

    # -- parity with plain collaborator --------------------------------------

    def test_collaborator_pii_is_allowed_wherever_collaborator_is(self):
        # ROLES_ALLOWING_ORG_UNIT is the shared allow-list org_grant_service
        # and admin.py's org_unit branch both consult. If collaborator_pii is
        # missing here, it silently loses org-unit scope even though the
        # check constraint permits it.
        self.assertIn(VaAccessRoles.collaborator, og.ROLES_ALLOWING_ORG_UNIT)
        self.assertIn(VaAccessRoles.collaborator_pii, og.ROLES_ALLOWING_ORG_UNIT)

        # And it must not have picked up coding ability by accident.
        self.assertNotIn(VaAccessRoles.collaborator, og.ROLES_REQUIRING_CODING_CADRE)
        self.assertNotIn(
            VaAccessRoles.collaborator_pii, og.ROLES_REQUIRING_CODING_CADRE
        )

    def test_collaborator_pii_reaches_the_same_units_as_collaborator(self):
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="CPRD02",
            unit_name="Collaborator PII District 2",
        )
        chc = org.create_unit(
            self.PROJECT,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id,
            unit_code="CPRC02",
            unit_name="Collaborator PII CHC 2",
        )
        db.session.commit()

        plain_viewer = self._get_or_make_user(
            "collab.plain@test.local", "CollabPlain123"
        )
        pii_viewer = self._get_or_make_user("collab.pii2@test.local", "CollabPii123")

        db.session.add_all(
            [
                VaUserAccessGrants(
                    user_id=plain_viewer.user_id,
                    role=VaAccessRoles.collaborator,
                    scope_type=VaAccessScopeTypes.org_unit,
                    org_unit_id=district.org_unit_id,
                    grant_status=VaStatuses.active,
                ),
                VaUserAccessGrants(
                    user_id=pii_viewer.user_id,
                    role=VaAccessRoles.collaborator_pii,
                    scope_type=VaAccessScopeTypes.org_unit,
                    org_unit_id=district.org_unit_id,
                    grant_status=VaStatuses.active,
                ),
            ]
        )
        db.session.commit()

        plain_units = og.scope_unit_ids(plain_viewer.user_id, VaAccessRoles.collaborator)
        pii_units = og.scope_unit_ids(
            pii_viewer.user_id, VaAccessRoles.collaborator_pii
        )

        expected = {district.org_unit_id, chc.org_unit_id}
        self.assertEqual(plain_units, expected)
        self.assertEqual(pii_units, expected)

    # -- no auto-upgrade ------------------------------------------------------

    def test_existing_collaborator_grant_is_not_upgraded(self):
        grant = self._grant(
            VaAccessRoles.collaborator,
            VaAccessScopeTypes.project,
            project_id=self.PROJECT,
        )
        grant_id = grant.grant_id

        db.session.expire_all()
        reloaded = db.session.get(VaUserAccessGrants, grant_id)
        self.assertEqual(reloaded.role, VaAccessRoles.collaborator)
