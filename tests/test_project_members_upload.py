"""Roster "Upload users CSV": project members that grant nothing (digitva-plgm).

Contract: POST /admin/api/projects/<id>/users-grid/members/import previews
(dry_run=1, the default) or applies (dry_run=0) ``name, email, phone`` rows;
existing accounts are added unchanged, new ones created without a sign-in
code, and a member row gives no access anywhere.
Policy: docs/policy/account-onboarding-and-passwords.md ("Roster upload") and
docs/policy/access-control-model.md ("Project membership").
"""
import io
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectMember,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.auth_factors import AuthMobileCode, AuthSecurityEvent
from app.models.mas_languages import MasLanguages
from app.services import organization_service as org
from tests.base import BaseTestCase


class ProjectMembersUploadTests(BaseTestCase):
    PROJECT = "MEMB01"
    OTHER = "MEMB02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.PROJECT, cls.OTHER):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Members {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
            ))
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English", is_active=True))
        db.session.flush()
        cls.email_user = cls._make_user("member.existing@test.local", "Existing123")
        cls.email_user.name = "Original Name"
        cls.email_user.phone = "0000"
        cls.mobile_user = VaUsers(
            user_id=uuid.uuid4(), name="Mobile Person", email=None, mobile_login="9123450001",
            vacode_language=["english"], permission={}, landing_page="coder", pw_reset_t_and_c=False,
            email_verified=False, user_status=VaStatuses.active,
        )
        cls.mobile_user.set_password("Mobile123!x")
        db.session.add(cls.mobile_user)
        cls.inactive_user = cls._make_user("member.inactive@test.local", "Inactive123")
        cls.inactive_user.user_status = VaStatuses.deactive
        cls.other_pi = cls._make_user("member.other.pi@test.local", "OtherPi123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.other_pi.user_id, role=VaAccessRoles.project_pi,
            scope_type=VaAccessScopeTypes.project, project_id=cls.OTHER, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        cls.email_user_id = cls.email_user.user_id
        cls.mobile_user_id = cls.mobile_user.user_id
        cls.other_pi_id = str(cls.other_pi.user_id)

    def _upload(self, text, dry_run="1", project_id=None, headers=None, reactivate=""):
        return self.client.post(
            f"/admin/api/projects/{project_id or self.PROJECT}/users-grid/members/import",
            data={"file": (io.BytesIO(text.encode("utf-8")), "users.csv"), "dry_run": dry_run,
                  "reactivate": reactivate},
            content_type="multipart/form-data",
            headers=self._csrf_headers() if headers is None else headers,
        )

    def _members(self):
        return set(db.session.scalars(
            sa.select(MapProjectMember.user_id).where(MapProjectMember.project_id == self.PROJECT)
        ))

    def _apply(self, text, reactivate=""):
        with patch("app.services.email_service.is_mail_configured", return_value=False):
            return self._upload(text, dry_run="0", reactivate=reactivate)

    def test_template_is_header_only(self):
        self._login(self.base_admin_id)
        response = self.client.get(f"/admin/api/projects/{self.PROJECT}/users-grid/members/template.csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True).strip(), "name,email,phone")

    def test_dry_run_writes_nothing_and_apply_writes_members(self):
        self._login(self.base_admin_id)
        text = "name,email,phone\nNew Person,new.member@test.local,\n"
        preview = self._upload(text)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(preview.get_json()["rows"][0]["action"], "create")
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "new.member@test.local")))
        self.assertEqual(self._members(), set())

        applied = self._apply(text)
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(applied.get_json()["added"], 1)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "new.member@test.local"))
        self.assertIsNotNone(user)
        self.assertEqual(user.vacode_language, ["english"])
        self.assertEqual(self._members(), {user.user_id})
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id, AuthSecurityEvent.event_type == "project_member_added",
        )), 1)

    def test_existing_accounts_by_email_and_by_mobile_are_added_unchanged(self):
        self._login(self.base_admin_id)
        text = ("name,email,phone\n"
                "Renamed,MEMBER.EXISTING@test.local,\n"
                "Someone Else,,091234 50001\n")
        preview = self._upload(text).get_json()
        self.assertEqual([r["action"] for r in preview["rows"]], ["add_existing", "add_existing"])
        self.assertEqual(preview["rows"][1]["identity"], "******0001")
        self.assertEqual(self._apply(text).status_code, 200)
        self.assertEqual(self._members(), {self.email_user_id, self.mobile_user_id})
        email_user = db.session.get(VaUsers, self.email_user_id)
        mobile_user = db.session.get(VaUsers, self.mobile_user_id)
        self.assertEqual((email_user.name, email_user.phone), ("Original Name", "0000"))
        self.assertEqual((mobile_user.name, mobile_user.email), ("Mobile Person", None))

    def test_conflicting_email_and_mobile_is_refused_and_blocks_apply(self):
        self._login(self.base_admin_id)
        text = ("name,email,phone\n"
                "Fine,new.ok@test.local,\n"
                "Clash,member.existing@test.local,9123450001\n")
        preview = self._upload(text).get_json()
        self.assertEqual(preview["rows"][1]["action"], "refuse")
        self.assertIn("different accounts", preview["rows"][1]["reason"])
        applied = self._apply(text)
        self.assertEqual(applied.status_code, 400)
        self.assertEqual(self._members(), set())
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "new.ok@test.local")))

    def test_inactive_account_and_bad_phone_are_refused(self):
        self._login(self.base_admin_id)
        rows = self._upload("name,email,phone\nX,member.inactive@test.local,\nY,y@test.local,12345\n"
                            "Z,,5123456789\n,n@test.local,\nW,,\n").get_json()["rows"]
        mobile_rule = "phone must be a 10-digit mobile number starting 6, 7, 8 or 9"
        self.assertEqual([(r["action"], r["reason"]) for r in rows], [
            ("refuse", "existing user is deactivated"),
            ("refuse", mobile_rule),
            ("refuse", mobile_rule),
            ("refuse", "name is required (at most 128 characters)"),
            ("refuse", "an email or a mobile number is required"),
        ])
        # Each row echoes its own uploaded data in full, with its line number.
        self.assertEqual({k: rows[2][k] for k in ("row", "name", "email", "phone")},
                         {"row": 4, "name": "Z", "email": "", "phone": "5123456789"})
        self.assertEqual([r["can_reactivate"] for r in rows], [True, False, False, False, False])

    def test_more_than_150_rows_is_refused_whole(self):
        self._login(self.base_admin_id)
        text = "name,email,phone\n" + "".join(f"P{i},p{i}@test.local,\n" for i in range(151))
        response = self._upload(text)
        self.assertEqual(response.status_code, 400)
        self.assertIn("150-row limit", response.get_json()["error"])
        self.assertEqual(self._upload(text.rsplit("P150", 1)[0]).status_code, 200)

    def test_admin_ticks_reactivate_and_add_and_it_is_audited(self):
        self._login(self.base_admin_id)
        text = "name,email,phone\nX,member.inactive@test.local,\n"
        inactive_id = self.inactive_user.user_id
        self.assertEqual(self._apply(text).status_code, 400)  # not ticked: refused
        preview = self._upload(text, reactivate="2").get_json()
        self.assertEqual(preview["rows"][0]["action"], "reactivate")
        self.assertEqual(db.session.get(VaUsers, inactive_id).user_status, VaStatuses.deactive)
        applied = self._apply(text, reactivate="2")
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(applied.get_json()["added"], 1)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaUsers, inactive_id).user_status, VaStatuses.active)
        self.assertEqual(self._members(), {inactive_id})
        self.assertTrue(db.session.scalar(sa.select(sa.exists().where(
            AuthSecurityEvent.user_id == inactive_id, AuthSecurityEvent.event_type == "account_reactivated"))))

    def test_an_existing_member_is_a_no_op(self):
        self._login(self.base_admin_id)
        text = "name,email,phone\nE,member.existing@test.local,\n"
        self.assertEqual(self._apply(text).status_code, 200)
        again = self._apply(text)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["rows"][0]["action"], "already_member")
        self.assertEqual(again.get_json()["added"], 0)
        self.assertEqual(self._members(), {self.email_user_id})

    def test_one_account_named_twice_is_refused(self):
        self._login(self.base_admin_id)
        rows = self._upload("name,email,phone\nA,,9123450001\nB,,09123450001\n").get_json()["rows"]
        self.assertEqual(rows[1]["action"], "refuse")

    def test_new_mobile_only_account_gets_no_sign_in_code(self):
        self._login(self.base_admin_id)
        applied = self._apply("name,email,phone\nField Worker,,9123450099\n")
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertNotIn("sign_in_codes", applied.get_json())
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == "9123450099"))
        self.assertIsNotNone(user)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthMobileCode).where(
            AuthMobileCode.user_id == user.user_id)), 0)

    def test_members_appear_in_the_grid_unplaced_with_no_grants(self):
        self._login(self.base_admin_id)
        self.assertEqual(self._apply("name,email,phone\nE,member.existing@test.local,\n").status_code, 200)
        grid = org.get_project_users_grid(self.PROJECT)
        row = next(u for u in grid["users"] if u["user_id"] == str(self.email_user_id))
        self.assertIsNone(row["primary_worker"])
        self.assertEqual(row["pii_status"]["tier"], "none")
        self.assertEqual(row["active_grant_count"], 0)

    def test_placing_a_member_applies_the_cadre_default_roles(self):
        self._login(self.base_admin_id)
        self.assertEqual(self._apply("name,email,phone\nM,,9123450001\n").status_code, 200)
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        org.upsert_level_cadre(
            self.PROJECT, org_level_id=levels["phc"].org_level_id, cadre_id=cadres["MO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, default_roles=["coder"],
        )
        dist = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id,
                               unit_code="MBD1", unit_name="Member District")
        chc = org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id,
                              parent_org_unit_id=dist.org_unit_id, unit_code="MBC1", unit_name="Member CHC")
        phc = org.create_unit(self.PROJECT, org_level_id=levels["phc"].org_level_id,
                              parent_org_unit_id=chc.org_unit_id, unit_code="MBP1", unit_name="Member PHC")
        db.session.commit()
        placed = self.client.post(
            f"/admin/api/organization/{self.PROJECT}/workers",
            json={"org_unit_id": str(phc.org_unit_id), "cadre_id": str(cadres["MO"].cadre_id),
                  "worker_name": "Mobile Person", "user": str(self.mobile_user_id)},
            headers=self._csrf_headers(),
        )
        self.assertEqual(placed.status_code, 201, placed.get_json())
        row = next(u for u in org.get_project_users_grid(self.PROJECT)["users"]
                   if u["user_id"] == str(self.mobile_user_id))
        self.assertEqual(row["primary_worker"]["unit_code"], "MBP1")
        self.assertEqual(row["unit_grants"][0]["role"], "coder")

    def test_a_member_without_a_grant_has_no_project_access(self):
        from app.services.authz import resolve_grants
        from app.services.device_auth_service import has_device_access
        from app.services.viewer_pii_service import pii_scope

        self._login(self.base_admin_id)
        self.assertEqual(self._apply("name,email,phone\nE,member.existing@test.local,\n").status_code, 200)
        self.assertIn(self.email_user_id, self._members())
        user = db.session.get(VaUsers, self.email_user_id)
        self.assertFalse(user.can_manage_project(self.PROJECT))
        self.assertFalse(has_device_access(user))
        self.assertFalse(pii_scope(user).sees(self.PROJECT))
        self.assertEqual(list(resolve_grants(user).grants), [])
        self._login(str(self.email_user_id))
        self.assertIn(self.client.get(f"/admin/api/projects/{self.PROJECT}/users-grid").status_code, (302, 403))

    def test_project_pi_of_another_project_is_refused(self):
        self._login(self.other_pi_id)
        self.assertEqual(self._upload("name,email,phone\nE,member.existing@test.local,\n").status_code, 403)
        self.assertEqual(self.client.get(
            f"/admin/api/projects/{self.PROJECT}/users-grid/members/template.csv").status_code, 403)
        self.assertEqual(self._members(), set())

    def test_project_pi_adds_existing_accounts_but_creates_none(self):
        self._login(self.other_pi_id)
        rows = self._upload("name,email,phone\nE,member.existing@test.local,\nN,brand.new@test.local,\n"
                            "I,member.inactive@test.local,\nC,unknown.pi@test.local,9123450077\n"
                            # Two active accounts: the mismatch is not revealed to a PI.
                            "M,member.existing@test.local,9123450001\n",
                            project_id=self.OTHER, reactivate="4").get_json()["rows"]
        unavailable = ("refuse", "account is unavailable for this project import")
        self.assertEqual([(r["action"], r["reason"]) for r in rows],
                         [("add_existing", None), unavailable, unavailable, unavailable, unavailable])
        # A ticked reactivation from a PI changes nothing: only admins reactivate.
        self.assertFalse(any(r["can_reactivate"] for r in rows))

    def test_apply_requires_the_csrf_header(self):
        self._login(self.base_admin_id)
        response = self._upload("name,email,phone\nE,member.existing@test.local,\n", dry_run="0", headers={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.get_json()["error"])
        self.assertEqual(self._members(), set())
