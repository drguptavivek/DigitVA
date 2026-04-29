from datetime import datetime, timedelta, timezone
import uuid

import sqlalchemy as sa

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes, VaSiteMaintenance, VaStatuses, VaUserAccessGrants, VaUsers
from tests.base import BaseTestCase


class SiteMaintenanceTests(BaseTestCase):
    def _create_user(self, email, password, *, is_admin=False):
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
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if is_admin:
            db.session.add(
                VaUserAccessGrants(
                    user_id=user.user_id,
                    role=VaAccessRoles.admin,
                    scope_type=VaAccessScopeTypes.global_scope,
                    notes="site maintenance admin",
                    grant_status=VaStatuses.active,
                )
            )
            db.session.flush()
        db.session.commit()
        return user

    def _activate_maintenance(self, *, starts_at, cutoff_at, message="Planned maintenance"):
        maintenance = VaSiteMaintenance(
            enabled=True,
            starts_at=starts_at,
            cutoff_at=cutoff_at,
            message=message,
            enabled_by_user_id=self.base_admin_user.user_id,
        )
        db.session.add(maintenance)
        db.session.commit()
        return maintenance

    def test_admin_can_start_and_end_site_maintenance(self):
        self._login(self.base_admin_id)

        start_response = self.client.post(
            "/admin/api/site-maintenance",
            json={"message": "Planned maintenance"},
            headers=self._csrf_headers(),
        )

        self.assertEqual(start_response.status_code, 200)
        payload = start_response.get_json()
        self.assertTrue(payload["maintenance"]["enabled"])
        self.assertEqual(payload["maintenance"]["message"], "Planned maintenance")
        self.assertTrue(payload["maintenance"]["starts_at"])
        self.assertTrue(payload["maintenance"]["cutoff_at"])

        end_response = self.client.delete(
            "/admin/api/site-maintenance",
            headers=self._csrf_headers(),
        )

        self.assertEqual(end_response.status_code, 200)
        refreshed = db.session.scalar(
            sa.select(VaSiteMaintenance).order_by(VaSiteMaintenance.created_at.desc())
        )
        self.assertFalse(refreshed.enabled)
        self.assertIsNotNone(refreshed.disabled_at)
        self.assertEqual(refreshed.disabled_by_user_id, self.base_admin_user.user_id)

    def test_non_admin_login_is_blocked_after_cutoff(self):
        password = "Maintenance123!"
        user = self._create_user(
            f"maintenance.blocked.{uuid.uuid4().hex[:8]}@example.com",
            password,
        )
        now = datetime.now(timezone.utc)
        self._activate_maintenance(
            starts_at=now - timedelta(minutes=20),
            cutoff_at=now - timedelta(minutes=5),
        )

        response = self.client.post(
            "/vaauth/valogin",
            data={
                "email": user.email,
                "password": password,
            },
            headers=self._csrf_headers(),
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Site is under maintenance", response.data)
        self.assertIn(b"Only admin login is allowed right now.", response.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_admin_login_remains_allowed_after_cutoff(self):
        password = "AdminMaintenance123!"
        admin_user = self._create_user(
            f"maintenance.admin.{uuid.uuid4().hex[:8]}@example.com",
            password,
            is_admin=True,
        )
        now = datetime.now(timezone.utc)
        self._activate_maintenance(
            starts_at=now - timedelta(minutes=20),
            cutoff_at=now - timedelta(minutes=5),
        )

        response = self.client.post(
            "/vaauth/valogin",
            data={
                "email": admin_user.email,
                "password": password,
            },
            headers=self._csrf_headers(),
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/vaauth/valogin", response.location)

    def test_non_admin_is_logged_out_after_cutoff(self):
        now = datetime.now(timezone.utc)
        self._activate_maintenance(
            starts_at=now - timedelta(minutes=20),
            cutoff_at=now - timedelta(minutes=5),
        )
        self._login(self.base_coder_id)

        response = self.client.get("/", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Site is under maintenance", response.data)
        self.assertIn(b"Only admin login is allowed right now.", response.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_non_admin_sees_countdown_banner_during_grace_period(self):
        now = datetime.now(timezone.utc)
        self._activate_maintenance(
            starts_at=now - timedelta(minutes=1),
            cutoff_at=now + timedelta(minutes=14),
            message="DigitVA will be temporarily unavailable.",
        )
        self._login(self.base_coder_id)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"site-maintenance-banner", response.data)
        self.assertIn(b"Site is under maintenance", response.data)
        self.assertIn(b"DigitVA will be temporarily unavailable.", response.data)

    def test_non_admin_page_includes_maintenance_watcher_without_refresh(self):
        self._login(self.base_coder_id)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"site-maintenance-root", response.data)
        self.assertIn(b"/vaauth/site-maintenance-status", response.data)

    def test_admin_sees_maintenance_message_banner_context(self):
        now = datetime.now(timezone.utc)
        self._activate_maintenance(
            starts_at=now - timedelta(minutes=1),
            cutoff_at=now + timedelta(minutes=14),
            message="Smoke maintenance",
        )
        self._login(self.base_admin_id)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"site-maintenance-root", response.data)
        self.assertIn(b"Smoke maintenance", response.data)
        self.assertIn(b'data-is-admin="true"', response.data)
        self.assertIn(b'data-initial-show-countdown="false"', response.data)
