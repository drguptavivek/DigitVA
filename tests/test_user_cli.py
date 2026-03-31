import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from tests.base import BaseTestCase


class UserCliTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()

    def test_users_list_includes_admin_state(self):
        result = self.runner.invoke(args=["users", "list"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("email | name | status | landing_page | onboarded | admin", result.output)
        self.assertIn("base.admin@test.local", result.output)
        self.assertIn("yes", result.output)

    def test_users_search_matches_name_or_email(self):
        result = self.runner.invoke(
            args=["users", "search", "--query", "base.admin"]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("email | name | status | landing_page", result.output)
        self.assertIn("base.admin@test.local", result.output)

    def test_users_list_grants_filters_by_email(self):
        result = self.runner.invoke(
            args=[
                "users",
                "list-grants",
                "--email",
                self.base_admin_user.email,
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("email | role | scope | project_id | site_id | status", result.output)
        self.assertIn(self.base_admin_user.email, result.output)
        self.assertIn("admin", result.output)
        self.assertIn("global", result.output)

    def test_users_list_grants_shows_project_and_site_for_project_site_scope(self):
        result = self.runner.invoke(
            args=[
                "users",
                "list-grants",
                "--email",
                self.base_coder_user.email,
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(self.BASE_PROJECT_ID, result.output)
        self.assertIn(self.BASE_SITE_ID, result.output)

    def test_users_create_creates_active_user(self):
        result = self.runner.invoke(
            args=[
                "users",
                "create",
                "--email",
                "cli.user@test.local",
                "--name",
                "CLI User",
                "--password",
                "CliUser123",
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == "cli.user@test.local")
        )
        self.assertIsNotNone(user)
        self.assertEqual(user.user_status, VaStatuses.active)
        self.assertFalse(user.pw_reset_t_and_c)
        self.assertTrue(user.check_password("CliUser123"))
        self.assertIn("password_reset_required: true", result.output)

    def test_users_reset_password_updates_hash_and_flag(self):
        result = self.runner.invoke(
            args=[
                "users",
                "reset-password",
                "--email",
                self.base_coder_user.email,
                "--password",
                "ResetPass123",
                "--require-password-change",
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        user = db.session.get(VaUsers, self.base_coder_user.user_id)
        self.assertTrue(user.check_password("ResetPass123"))
        self.assertFalse(user.pw_reset_t_and_c)

    def test_users_grant_admin_creates_global_admin_grant(self):
        result = self.runner.invoke(
            args=[
                "users",
                "grant-admin",
                "--email",
                self.base_coder_user.email,
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == self.base_coder_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.admin,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
            )
        )
        user = db.session.get(VaUsers, self.base_coder_user.user_id)
        self.assertIsNotNone(grant)
        self.assertEqual(grant.grant_status, VaStatuses.active)
        self.assertEqual(user.landing_page, "admin")

    def test_users_revoke_admin_deactivates_global_admin_grant(self):
        result = self.runner.invoke(
            args=[
                "users",
                "revoke-admin",
                "--email",
                self.base_admin_user.email,
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == self.base_admin_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.admin,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
            )
        )
        self.assertIsNotNone(grant)
        self.assertEqual(grant.grant_status, VaStatuses.deactive)

    def test_users_set_status_updates_user_status(self):
        result = self.runner.invoke(
            args=[
                "users",
                "set-status",
                "--email",
                self.base_coder_user.email,
                "--status",
                "deactive",
            ]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        user = db.session.get(VaUsers, self.base_coder_user.user_id)
        self.assertEqual(user.user_status, VaStatuses.deactive)
