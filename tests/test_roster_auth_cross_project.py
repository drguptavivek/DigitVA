"""Regression tests for security-audit run-7 (digitva-l9dp.1, .2, .3, .5):
sign-in QR refusals for a non-admin issuer, mentoring-institute staff kept off
project rosters, cross-project imports that keep the placing project's
control, and the audit of a data manager's coding-language change.
Policy: docs/policy/mobile-sign-in.md sections 3 and 8,
docs/policy/dm-user-grant-management.md. Each test first asserts its subject
exists before asserting the refusal.
"""
import io
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthDeviceSession,
    AuthSecurityEvent,
    MapMentorInstituteUser,
    MapProjectMember,
    MasMentorInstitute,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.mas_languages import MasLanguages
from app.services import device_auth_service as devices
from app.services import mobile_sign_in_service as mobile
from app.services import sign_in_qr_service
from app.services.authz import resolve_grants
from app.services.sign_in_qr_service import COLLECTOR_ROLES
from tests.authz.fixture import AuthzFixtureMixin
from tests.base import BaseTestCase

R = VaAccessRoles
P = VaAccessScopeTypes.project
USERS = "/api/v1/users"
REDEEM = "/api/v1/auth/sign-in-qr/redeem"
DEVICE = {"device_name": "Pixel 7", "platform": "android", "app_version": "1.2.3"}


def _number():
    return f"9{uuid.uuid4().int % 10**9:09d}"


# ---------------------------------------------------------------------------
# Lead 1: non-admin sign-in QR for verified-email / live-phone / outside members
# ---------------------------------------------------------------------------


def _fake_context(user, roles=None, *, _grants=None):
    grants = _grants or resolve_grants(user)
    return [
        {"project_id": g.project_id, "web_intake_mode": "on"}
        for g in grants.of(COLLECTOR_ROLES, virtual=False)
    ]


class Lead1SignInQrNonAdminTests(AuthzFixtureMixin, BaseTestCase):
    """Scaffolding copied from tests/routes/test_sign_in_qr.py. ``dm_c1`` is a
    unit data manager (C1) who manages ``interviewer_p1`` / ``nobody`` (P1)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users["nobody"].email_verified = False
        cls.users["interviewer_p1"].email_verified = True
        db.session.add(cls._grant_row(cls.users["nobody"], R.death_reporter, VaAccessScopeTypes.org_unit, "P1"))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        for p in (
            patch.object(devices, "has_device_access", return_value=True),
            patch.object(sign_in_qr_service, "web_intake_service",
                         SimpleNamespace(interviewer_context=_fake_context,
                                         register_death_context=lambda *a, **k: [])),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _issue(self, actor, target):
        self._login(str(self.users[actor].user_id))
        return self.client.post(f"{USERS}/{self.users[target].user_id}/sign-in-qr",
                                json={"delivery": "show"}, headers=self._csrf_headers())

    def _redeem(self, token, **extra):
        return self.client.post(REDEEM, json={"token": token, **DEVICE, **extra})

    def _phones(self, user, n):
        sessions = []
        for i in range(n):
            device, _ = devices._add_device("AZTA01", f"Phone {i}", "android", "1.2.3", None)
            sessions.append(devices._open_authorized_session(device, user)[0].session)
        db.session.commit()
        return sessions

    def test_non_admin_cannot_show_qr_for_a_verified_email_account(self):
        target = self.users["interviewer_p1"]
        self.assertTrue(target.email_verified)
        self.assertEqual(self._issue("admin", "interviewer_p1").status_code, 201)  # subject eligible
        res = self._issue("dm_c1", "interviewer_p1")
        self.assertNotEqual(res.status_code, 201, "dm_c1 got a plaintext on-screen token for a verified-email account")
        self.assertNotIn("qr_payload", res.get_json())

    def test_non_admin_cannot_issue_qr_for_an_account_with_a_live_phone(self):
        user = self.users["nobody"]
        self.assertEqual(self._issue("dm_c1", "nobody").status_code, 201)  # baseline: dm may issue
        self._phones(user, 1)
        self.assertEqual(len(devices.list_account_devices(user.user_id)), 1)  # live phone exists
        res = self._issue("dm_c1", "nobody")
        self.assertNotEqual(res.status_code, 201, "dm_c1 issued a QR for a person already signed in on a phone")

    def test_non_admin_cannot_issue_qr_for_a_member_of_an_outside_project(self):
        user = self.users["nobody"]
        self.assertEqual(self._issue("dm_c1", "nobody").status_code, 201)  # baseline
        # A membership older than the person's grant here: the grant-then-take-over order.
        first_grant = db.session.scalar(sa.select(sa.func.min(VaUserAccessGrants.grant_created_at)).where(
            VaUserAccessGrants.user_id == user.user_id))
        db.session.add(MapProjectMember(project_id="AZSP01", user_id=user.user_id,
                                        added_at=first_grant.replace(tzinfo=UTC) - timedelta(days=1)))
        db.session.commit()
        res = self._issue("dm_c1", "nobody")  # dm_c1 manages nothing in AZSP01
        self.assertEqual(res.status_code, 404, "dm_c1 issued a QR for a member of a project it does not manage")
        self.assertEqual(self._issue("admin", "nobody").status_code, 201)

    def test_later_bare_outside_membership_does_not_block_the_managing_issuer(self):
        # Unit-scope grant first, then another project imports the person.
        db.session.add(MapProjectMember(project_id="AZSP01", user_id=self.users["nobody"].user_id))
        db.session.commit()
        self.assertEqual(self._issue("dm_c1", "nobody").status_code, 201)

    def test_non_admin_may_still_email_qr_to_a_verified_address(self):
        target = self.users["interviewer_p1"]
        self.assertTrue(target.email_verified)
        self._login(str(self.users["dm_c1"].user_id))
        with patch.object(sign_in_qr_service.email_service, "can_deliver_to", return_value=True), \
                patch.object(sign_in_qr_service.email_service, "send_sign_in_qr_email"):
            res = self.client.post(f"{USERS}/{target.user_id}/sign-in-qr", json={"delivery": "email"},
                                   headers=self._csrf_headers())
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertNotIn("code", res.get_json())

    def test_non_admin_qr_cannot_decommission_a_live_phone_via_replace_device_id(self):
        user = self.users["nobody"]
        existing = self._phones(user, 3)  # the device cap
        res = self._issue("dm_c1", "nobody")
        outcome = f"issue={res.status_code}"
        if res.status_code == 201:
            redeemed = self._redeem(res.get_json()["code"], replace_device_id=str(existing[0].device_id))
            db.session.expire_all()
            revoked = db.session.get(AuthDeviceSession, existing[0].session_id).revoked_reason
            outcome += f" redeem={redeemed.status_code} replaced_phone_revoked_reason={revoked}"
        self.assertNotEqual(res.status_code, 201, outcome)


# ---------------------------------------------------------------------------
# Shared two-project roster scaffolding for leads 2, 3 and 5
# ---------------------------------------------------------------------------


class _RosterBase(BaseTestCase):
    A = "R7RA01"
    B = "R7RB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.A, cls.B):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Run7 {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
            ))
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English", is_active=True))
        db.session.flush()
        cls.pi_a = cls._staff("pi.a", R.project_pi, cls.A)
        cls.dm_a = cls._staff("dm.a", R.data_manager, cls.A)
        cls.pi_b = cls._staff("pi.b", R.project_pi, cls.B)
        cls.pi_b.name = "Run7 PiB Distinct"
        db.session.commit()

    @classmethod
    def _staff(cls, name, role, project_id):
        user = cls._make_user(f"r7.{name}@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(user_id=user.user_id, role=role, scope_type=P, project_id=project_id,
                                          grant_status=VaStatuses.active))
        return user

    def setUp(self):
        super().setUp()
        limiter.reset()

    @staticmethod
    def _person(*, name="Run7 Person", email=None, verified=False, mobile_login=True, grants=(), members=()):
        number = _number() if mobile_login else None
        user = VaUsers(
            user_id=uuid.uuid4(), name=name, email=email, mobile_login=number, phone=number,
            vacode_language=["english"], permission={}, landing_page="coder", pw_reset_t_and_c=False,
            email_verified=verified, user_status=VaStatuses.active,
        )
        user.set_password("Unused123!x")
        db.session.add(user)
        db.session.flush()
        for role, project_id in grants:
            db.session.add(VaUserAccessGrants(user_id=user.user_id, role=role, scope_type=P,
                                              project_id=project_id, grant_status=VaStatuses.active))
        for project_id in members:
            db.session.add(MapProjectMember(project_id=project_id, user_id=user.user_id))
        db.session.commit()
        return user

    def _import(self, actor, project_id, text, dry_run="0"):
        self._login(str(actor.user_id))
        with patch("app.services.email_service.is_mail_configured", return_value=False):
            return self.client.post(
                f"/admin/api/projects/{project_id}/users-grid/members/import",
                data={"file": (io.BytesIO(text.encode()), "users.csv"), "dry_run": dry_run},
                content_type="multipart/form-data", headers=self._csrf_headers(),
            )

    def _grid(self, project_id, user_id, suffix=""):
        return f"/admin/api/projects/{project_id}/users-grid/{user_id}{suffix}"

    def _code(self, actor, project_id, user_id):
        self._login(str(actor.user_id))
        return self.client.post(self._grid(project_id, user_id, "/sign-in-code"), headers=self._csrf_headers())

    def _profile(self, actor, project_id, user_id, body):
        self._login(str(actor.user_id))
        return self.client.patch(self._grid(project_id, user_id, "/profile"), json=body,
                                 headers=self._csrf_headers())


# ---------------------------------------------------------------------------
# Lead 2: mentoring-institute admin imported into a project roster
# ---------------------------------------------------------------------------


class Lead2MentorInstituteAdminTests(_RosterBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        institute = MasMentorInstitute(institute_code=f"R7{uuid.uuid4().hex[:6].upper()}",
                                       institute_name="Run7 Institute", is_active=True)
        db.session.add(institute)
        db.session.flush()
        cls.mi_mobile = cls._person(name="MI Admin Mobile")  # mobile-only, no grants
        cls.mi_verified = cls._person(name="MI Admin Verified", email="r7.mi.verified@test.local", verified=True)
        for user in (cls.mi_mobile, cls.mi_verified):
            db.session.add(MapMentorInstituteUser(institute_id=institute.institute_id, user_id=user.user_id,
                                                  is_active=True, is_admin=True))
        db.session.commit()

    def _actors(self):
        return (("pi_a", self.pi_a), ("dm_a", self.dm_a))

    def test_import_refuses_a_mentor_institute_admin(self):
        self.assertTrue(self.mi_mobile.is_mentor_institute_admin())  # subject exists
        for label, actor in self._actors():
            with self.subTest(actor=label):
                res = self._import(actor, self.A, f"name,email,phone\nMI,,{self.mi_mobile.mobile_login}\n",
                                   dry_run="1")
                self.assertEqual(res.status_code, 200, res.get_json())
                self.assertEqual(res.get_json()["rows"][0]["action"], "refuse",
                                 f"{label}: mentor admin accepted as {res.get_json()['rows'][0]['action']}")

    def test_mentor_already_on_the_roster_gets_no_code_or_profile_edit(self):
        # An admin placed them (admins are not bound); non-admins still may not act.
        for user in (self.mi_mobile, self.mi_verified):
            db.session.add(MapProjectMember(project_id=self.A, user_id=user.user_id))
        db.session.commit()
        self.assertTrue(mobile.may_issue_code_in_project(self.base_admin_user, self.mi_mobile.user_id, self.A))
        for label, actor in self._actors():
            with self.subTest(actor=label):
                self.assertFalse(mobile.may_issue_code_in_project(actor, self.mi_mobile.user_id, self.A))
                self.assertEqual(self._code(actor, self.A, self.mi_mobile.user_id).status_code, 404)
                self.assertFalse(mobile.may_edit_account(actor, self.mi_verified.user_id, self.A))
                res = self._profile(actor, self.A, self.mi_verified.user_id, {"name": "Overwritten"})
                self.assertEqual(res.status_code, 403, res.get_json())

    def test_import_then_no_sign_in_code_for_a_mentor_institute_admin(self):
        # Import for real (the lead's path), then ask for a code.
        res = self._import(self.pi_a, self.A, f"name,email,phone\nMI,,{self.mi_mobile.mobile_login}\n")
        member = db.session.scalar(sa.select(MapProjectMember).where(
            MapProjectMember.project_id == self.A, MapProjectMember.user_id == self.mi_mobile.user_id))
        if member is None:  # import itself refused: the guard exists at the import layer
            self.assertEqual(res.status_code, 400, res.get_json())
            return
        for label, actor in self._actors():
            with self.subTest(actor=label):
                self.assertFalse(mobile.may_issue_code_in_project(actor, self.mi_mobile.user_id, self.A))
                self.assertEqual(self._code(actor, self.A, self.mi_mobile.user_id).status_code, 404)

    def test_import_then_no_profile_edit_for_a_mentor_institute_admin(self):
        res = self._import(self.pi_a, self.A, f"name,email,phone\nMI,{self.mi_verified.email},\n")
        member = db.session.scalar(sa.select(MapProjectMember).where(
            MapProjectMember.project_id == self.A, MapProjectMember.user_id == self.mi_verified.user_id))
        if member is None:
            self.assertEqual(res.status_code, 400, res.get_json())
            return
        for label, actor in self._actors():
            with self.subTest(actor=label):
                res = self._profile(actor, self.A, self.mi_verified.user_id, {"name": "Overwritten By Roster"})
                self.assertEqual(res.status_code, 403, f"{label}: {res.status_code} {res.get_json()}")
                db.session.refresh(self.mi_verified)
                self.assertEqual(self.mi_verified.name, "MI Admin Verified")


# ---------------------------------------------------------------------------
# Lead 3: PROJ_B's import locks PROJ_A's managers out of their own worker
# ---------------------------------------------------------------------------


class Lead3CrossProjectLockoutTests(_RosterBase):

    def _state(self, worker, name):
        return {
            "profile": self._profile(self.dm_a, self.A, worker.user_id, {"name": name}).status_code,
            "code": self._code(self.dm_a, self.A, worker.user_id).status_code,
            "dm_code": self._dm_code(worker.user_id).status_code,
        }

    def test_project_b_import_does_not_lock_project_a_manager_out(self):
        worker = self._person(name="Worker A", grants=[(R.coder, self.A)])
        pre = self._state(worker, "Worker A2")
        self.assertEqual(pre, {"profile": 200, "code": 200, "dm_code": 200})  # subject manageable

        res = self._import(self.pi_b, self.B, f"name,email,phone\nWorker,,{worker.mobile_login}\n")
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()["added"], 1)  # PROJ_B really holds the member row now
        self.assertEqual(self._state(worker, "Worker A3"), pre)

    def test_a_grant_in_project_b_still_locks_project_a_manager_out(self):
        worker = self._person(name="Worker A", grants=[(R.coder, self.A)])
        self.assertEqual(self._state(worker, "Worker A2"), {"profile": 200, "code": 200, "dm_code": 200})
        db.session.add(MapProjectMember(project_id=self.B, user_id=worker.user_id))
        db.session.add(VaUserAccessGrants(user_id=worker.user_id, role=R.coder, scope_type=P, project_id=self.B,
                                          grant_status=VaStatuses.active))
        db.session.commit()
        self.assertEqual(self._state(worker, "Worker A3"), {"profile": 403, "code": 404, "dm_code": 404})

    def test_reactivated_grant_is_dated_by_its_reactivation(self):
        # digitva-l9dp.3: grant at t0, revoke, PROJ_B adds a bare member at t1,
        # reactivate at t2 -> the membership predates the live grant: locked.
        worker = self._person(name="Worker A", grants=[(R.coder, self.A)])
        self.assertEqual(self._state(worker, "Worker A2"), {"profile": 200, "code": 200, "dm_code": 200})
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == worker.user_id))
        now = datetime.now(UTC).replace(tzinfo=None)
        grant.grant_created_at = grant.grant_updated_at = now - timedelta(days=3)
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        db.session.add(MapProjectMember(project_id=self.B, user_id=worker.user_id,
                                        added_at=datetime.now(UTC) - timedelta(days=2)))
        db.session.commit()
        grant.grant_status = VaStatuses.active  # onupdate bumps grant_updated_at
        db.session.commit()
        self.assertGreater(grant.grant_updated_at, now - timedelta(days=1))
        self.assertEqual(self._state(worker, "Worker A3"), {"profile": 403, "code": 404, "dm_code": 404})

    def _dm_code(self, user_id):
        self._login(str(self.dm_a.user_id))
        return self.client.post(f"/data-management/api/users/{user_id}/sign-in-code", headers=self._csrf_headers())



# ---------------------------------------------------------------------------
# Lead 5: Data Management PUT changes a shared user's languages, audited
# ---------------------------------------------------------------------------


class Lead5DmSharedUserOverwriteTests(_RosterBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "hindi") is None:
            db.session.add(MasLanguages(language_code="hindi", language_name="Hindi", is_active=True))
            db.session.commit()

    def _put(self, user_id, body):
        self._login(str(self.dm_a.user_id))
        return self.client.put(f"/data-management/api/users/{user_id}", json=body, headers=self._csrf_headers())

    def test_dm_language_change_of_a_shared_user_is_allowed_and_audited(self):
        # Owner accepts the overwrite (digitva-l9dp.5); the change is audited.
        user = self._person(grants=[(R.coder, self.A), (R.coder, self.B)])
        user.vacode_language = ["english", "hindi"]
        db.session.commit()
        res = self._put(user.user_id, {"languages": ["english"]})
        self.assertEqual(res.status_code, 200, res.get_json())
        db.session.refresh(user)
        self.assertEqual(user.vacode_language, ["english"])
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id, AuthSecurityEvent.event_type == "coding_languages_changed"))
        self.assertIsNotNone(event)
        self.assertEqual((event.actor_user_id, event.detail),
                         (self.dm_a.user_id, {"old": ["english", "hindi"], "new": ["english"]}))


# ---------------------------------------------------------------------------
# Owner rule: a project's managers set only their own project's access; only
# a global admin switches a whole account on or off (dm-user-grant-management.md)
# ---------------------------------------------------------------------------


class AccountStatusOwnerRuleTests(_RosterBase):

    def _bulk(self, actor, user, operation="deactivate_users"):
        from app.services import organization_service as org

        return org.bulk_apply_project_users_grid(
            self.A, {"user_ids": [str(user.user_id)], "operation": operation}, actor=actor)

    def test_non_admin_cannot_switch_off_a_shared_or_single_project_account(self):
        from app.services.organization_service import OrganizationError

        shared = self._person(grants=[(R.coder, self.A), (R.coder, self.B)])
        single = self._person(grants=[(R.coder, self.A)])
        for user in (shared, single):
            with self.subTest(user=user.name), self.assertRaises(OrganizationError):
                self._bulk(self.dm_a, user)
            db.session.rollback()
            self.assertEqual(db.session.get(VaUsers, user.user_id).user_status, VaStatuses.active)

    def test_admin_switches_off_a_shared_account(self):
        shared = self._person(grants=[(R.coder, self.A), (R.coder, self.B)])
        summary, _ = self._bulk(db.session.get(VaUsers, self.base_admin_id), shared)
        db.session.commit()
        self.assertEqual(summary["accounts_updated"], 1)
        self.assertEqual(db.session.get(VaUsers, shared.user_id).user_status, VaStatuses.deactive)

    def test_non_admin_revokes_own_project_grant_of_a_shared_account(self):
        shared = self._person(grants=[(R.coder, self.A), (R.coder, self.B)])
        own = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == shared.user_id, VaUserAccessGrants.project_id == self.A))
        self.assertIsNotNone(own)
        self._login(str(self.dm_a.user_id))
        res = self.client.post(f"/data-management/api/access-grants/{own.grant_id}/toggle",
                               headers=self._csrf_headers())
        self.assertEqual(res.status_code, 200, res.get_json())
        db.session.expire_all()
        self.assertEqual(db.session.get(VaUserAccessGrants, own.grant_id).grant_status, VaStatuses.deactive)
        self.assertEqual(db.session.get(VaUsers, shared.user_id).user_status, VaStatuses.active)
