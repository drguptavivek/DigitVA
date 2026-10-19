"""Inactive DigitVA accounts cannot be newly linked to organization workers."""

from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from tests.base import BaseTestCase


class WorkerActiveLinkTests(BaseTestCase):
    PROJECT = "WALINK"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Worker active links",
                project_nickname="Worker links",
                project_status=VaStatuses.active,
                project_structure_mode="organization",
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.commit()

    def _fixture(self):
        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_project_pi_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        org.seed_default_organization(self.PROJECT)
        levels = {level.level_code: level for level in org.list_levels(self.PROJECT)}
        unit = org.create_unit(
            self.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="D01",
            unit_name="District One",
        )
        cadre = next(cadre for cadre in org.list_cadres(self.PROJECT) if cadre.cadre_code == "CS")
        # Remove the seeded default so these requests exercise roster-only
        # worker linking, without the project-user importer.
        org.upsert_level_cadre(
            self.PROJECT,
            org_level_id=levels["district"].org_level_id,
            cadre_id=cadre.cadre_id,
            can_fill_va_form=False,
            can_code_va_form=False,
            can_supervise_interviews=True,
            default_roles=[],
        )
        return unit, cadre

    def _user(self, email, *, status=VaStatuses.active, mobile=None):
        user = VaUsers(
            name="Worker Account",
            email=email,
            password="unused",
            vacode_language=["en"],
            permission={},
            landing_page="coder",
            user_status=status,
            phone=mobile,
            mobile_login=mobile,
        )
        db.session.add(user)
        db.session.flush()
        return user

    def _create_roster_worker(self, unit, cadre, *, user=None, code="W00001"):
        return org.create_worker(
            self.PROJECT,
            org_unit_id=unit.org_unit_id,
            cadre_id=cadre.cadre_id,
            worker_code=code,
            worker_name="Existing Worker",
            user=user,
        )

    def _post_worker(self, unit, cadre, **fields):
        self._login(str(self.base_project_pi_id))
        return self.client.post(
            f"/admin/api/organization/{self.PROJECT}/workers",
            json={
                "org_unit_id": str(unit.org_unit_id),
                "cadre_id": str(cadre.cadre_id),
                "worker_name": "Roster Worker",
                **fields,
            },
            headers=self._csrf_headers(),
        )

    def _assert_inactive_create_rejected(self, fields, *, code):
        unit, cadre = self._fixture()
        response = self._post_worker(unit, cadre, worker_code=code, **fields)
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("inactive", response.get_json()["error"])
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count()).select_from(MasOrgUnitWorker).where(
                    MasOrgUnitWorker.project_id == self.PROJECT
                )
            ),
            0,
        )

    def test_roster_only_create_rejects_inactive_email(self):
        self._user("inactive-email@example.org", status=VaStatuses.deactive)
        self._assert_inactive_create_rejected(
            {"email": "inactive-email@example.org"}, code="W00001"
        )

    def test_roster_only_create_rejects_inactive_uuid(self):
        inactive = self._user("inactive-uuid@example.org", status=VaStatuses.deactive)
        self._assert_inactive_create_rejected(
            {"user": str(inactive.user_id)}, code="W00001"
        )

    def test_roster_only_create_rejects_inactive_mobile(self):
        self._user(
            "inactive-mobile@example.org",
            status=VaStatuses.deactive,
            mobile="9876543210",
        )
        self._assert_inactive_create_rejected({"phone": "9876543210"}, code="W00001")

    def test_relink_to_inactive_account_is_rejected_without_changing_worker_or_grants(self):
        unit, cadre = self._fixture()
        active = self._user("active-link@example.org")
        inactive = self._user("inactive-link@example.org", status=VaStatuses.deactive)
        worker = self._create_roster_worker(unit, cadre, user=active.email)
        grant = VaUserAccessGrants(
            user_id=active.user_id,
            role=VaAccessRoles.interview_supervisor,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.flush()
        before_grants = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == active.user_id,
                VaUserAccessGrants.org_unit_id == unit.org_unit_id,
            )
        )
        with self.assertRaisesRegex(org.OrganizationError, "inactive"):
            org.update_worker(self.PROJECT, worker.worker_id, user=inactive.email)
        db.session.refresh(worker)
        self.assertEqual(worker.user_id, active.user_id)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
                    VaUserAccessGrants.user_id == active.user_id,
                    VaUserAccessGrants.org_unit_id == unit.org_unit_id,
                )
            ),
            before_grants,
        )

    def test_existing_link_to_now_inactive_account_remains_editable(self):
        unit, cadre = self._fixture()
        user = self._user("later-inactive@example.org")
        worker = self._create_roster_worker(unit, cadre, user=user.email)
        user.user_status = VaStatuses.deactive
        db.session.flush()
        org.update_worker(
            self.PROJECT,
            worker.worker_id,
            user=user.email,
            worker_name="Updated Worker",
        )
        db.session.refresh(worker)
        self.assertEqual(worker.user_id, user.user_id)
        self.assertEqual(worker.worker_name, "Updated Worker")

    def test_active_account_can_be_linked(self):
        unit, cadre = self._fixture()
        user = self._user("active-worker@example.org")
        worker = self._create_roster_worker(unit, cadre, user=user.email)
        self.assertEqual(worker.user_id, user.user_id)
