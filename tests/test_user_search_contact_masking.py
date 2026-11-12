"""Platform-wide user search with contact details masked outside the caller's
reach (owner 2026-11-12, digitva-9xn9.22). Policy:
docs/policy/dm-user-grant-management.md, "User listing".
"""
from datetime import UTC, datetime

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase


class UserSearchContactMaskingTests(BaseTestCase):
    PROJECT = "USM01"
    OTHER = "USM02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.PROJECT, cls.OTHER):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        db.session.flush()

        def user(key, phone):
            u = cls._get_or_make_user(f"{key}.usm@test.local", "UsmPass123")
            u.phone = phone
            return u

        cls.pi = user("pi", "9000000001")
        cls.dm = user("dm", "9000000002")
        cls.inside = user("inside", "9811114321")
        cls.outside = user("outside", "9822224321")
        cls.loner = user("loner", "9833334321")
        cls.outside.job_title = "Medical officer"
        for holder, role, project_id in (
            (cls.pi, VaAccessRoles.project_pi, cls.PROJECT),
            (cls.dm, VaAccessRoles.data_manager, cls.PROJECT),
            (cls.inside, VaAccessRoles.interviewer, cls.PROJECT),
            (cls.outside, VaAccessRoles.interviewer, cls.OTHER),
        ):
            db.session.add(VaUserAccessGrants(
                user_id=holder.user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=project_id, notes="usm test", grant_status=VaStatuses.active,
            ))
        db.session.commit()

    def _search(self, caller, url, query="4321"):
        self._login(str(caller.user_id))
        response = self.client.get(url, query_string={"query": query})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {row["user_id"]: row for row in response.get_json()["users"]}

    def _assert_masked_outside(self, rows):
        inside = rows[str(self.inside.user_id)]
        self.assertEqual((inside["email"], inside["phone"]), (self.inside.email, "9811114321"))
        self.assertFalse(inside["contact_masked"])
        for other in (self.outside, self.loner):
            row = rows[str(other.user_id)]
            self.assertTrue(row["contact_masked"])
            self.assertEqual(row["name"], other.name)
            self.assertEqual(row["email"], other.email[:2] + "***@test.local")
            self.assertEqual(row["phone"], "******4321")
            for key in ("job_title", "landing_page", "is_admin", "mobile_only",
                        "mobile_verified", "email_verified", "languages"):
                self.assertIn(key, row)
                self.assertIsNone(row[key], key)

    def test_project_pi_search_matches_partial_phone_and_masks_outside(self):
        rows = self._search(self.pi, "/admin/api/users")
        self.assertEqual(set(rows), {str(u.user_id) for u in (self.inside, self.outside, self.loner)})
        self._assert_masked_outside(rows)

    def test_project_dm_search_masks_outside_its_project(self):
        rows = self._search(self.dm, "/data-management/api/users")
        self._assert_masked_outside(rows)

    def test_search_by_partial_email_still_works(self):
        rows = self._search(self.pi, "/admin/api/users", query="outside.usm")
        self.assertEqual(list(rows), [str(self.outside.user_id)])

    def test_dm_user_detail_masks_an_outside_account(self):
        self._login(str(self.dm.user_id))
        outside = self.client.get(f"/data-management/api/users/{self.outside.user_id}").get_json()["user"]
        self.assertEqual(outside["phone"], "******4321")
        self.assertTrue(outside["contact_masked"])
        inside = self.client.get(f"/data-management/api/users/{self.inside.user_id}").get_json()["user"]
        self.assertEqual(inside["phone"], "9811114321")

    def test_admin_sees_everyone_in_full(self):
        rows = self._search(self.base_admin_user, "/admin/api/users")
        self.assertEqual(rows[str(self.loner.user_id)]["phone"], "9833334321")
        self.assertFalse(rows[str(self.loner.user_id)]["contact_masked"])


class MaskHelperTests(BaseTestCase):
    def test_short_values_leak_less(self):
        from app.routes.admin import _mask_email, _mask_phone

        self.assertEqual(_mask_email("vivek@gmail.com"), "vi***@gmail.com")
        self.assertEqual(_mask_email("vik@gmail.com"), "v***@gmail.com")
        self.assertEqual(_mask_email("nodomain"), "n***")
        self.assertIsNone(_mask_email(None))
        self.assertEqual(_mask_phone("+91 98765 54321"), "********4321")
        self.assertEqual(_mask_phone("12345678"), "****5678")
        self.assertEqual(_mask_phone("1234567"), "*******")
        self.assertIsNone(_mask_phone(None))
