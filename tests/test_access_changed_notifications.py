"""An ``access_changed`` notification for a person whose grants change
(digitva-0rpi, docs/policy/app-notifications.md "Access changed").

The funnel is the session hook in app/services/authz/grant_cache.py: every
grant or mentor-membership row that really changes queues its user, and one
row per user is inserted at commit. These tests prove the funnel (dedupe,
no-op writes, new users, savepoints, the Core UPDATE) and that each grant
write family reaches it. The bulk-apply and worker-default families are in
tests/test_admin_project_setup.py beside their fixtures.
"""
import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MapUserNotification,
    MasLanguages,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import mentor_institute_service as mentors
from app.services import notification_service as ns
from app.services import project_user_import_service as user_import
from app.services import training_demo_service as svc
from tests.authz.fixture import TA, AuthzFixtureMixin, P, R, U
from tests.base import BaseTestCase
from tests.test_mentor_institute_stage1b import Stage1bBase
from tests.test_training_import_graduation import GRAD_PROJECT, GraduationTestBase

DM_GRANTS = "/data-management/api/access-grants"
ADMIN_GRANTS = "/admin/api/access-grants"


def access_rows(user_id) -> list[MapUserNotification]:
    return db.session.scalars(
        sa.select(MapUserNotification).where(
            MapUserNotification.user_id == user_id, MapUserNotification.kind == ns.ACCESS_CHANGED
        ).order_by(MapUserNotification.id)
    ).all()


class AccessChangedFunnelTests(BaseTestCase):
    """The hook itself, on the base fixtures (BASE01, the base coder)."""

    def setUp(self):
        super().setUp()
        self.user = self._get_or_make_user("access.changed.funnel@test.local", "AccessPass123")
        db.session.commit()  # the user exists before the writes under test

    def _grant(self, role=VaAccessRoles.reviewer, **extra):
        grant = VaUserAccessGrants(
            user_id=self.user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID, grant_status=VaStatuses.active, **extra,
        )
        db.session.add(grant)
        return grant

    def test_a_new_grant_leaves_one_account_wide_row_and_no_pii(self):
        self.assertEqual(access_rows(self.user.user_id), [])
        self._grant()
        db.session.commit()  # no explicit flush: the commit's own flush is collected
        rows = access_rows(self.user.user_id)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.project_id, row.death_id, row.draft_id, row.va_sid), (ns.NO_PROJECT, None, None, None))

    def test_one_row_per_user_per_transaction_across_grants_and_flushes(self):
        self._grant(VaAccessRoles.reviewer)
        db.session.flush()
        self._grant(VaAccessRoles.coder)
        db.session.flush()
        self._grant(VaAccessRoles.interviewer)
        db.session.commit()
        self.assertEqual(len(access_rows(self.user.user_id)), 1)
        # A later transaction is a new change: one more row.
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.user.user_id, VaUserAccessGrants.role == VaAccessRoles.coder))
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        self.assertEqual(len(access_rows(self.user.user_id)), 2)

    def test_a_write_that_changes_no_access_column_leaves_no_row(self):
        grant = self._grant()
        db.session.commit()
        before = len(access_rows(self.user.user_id))
        self.assertEqual(before, 1)
        # Writers read before they write (an expired attribute has no history to compare).
        self.assertEqual(grant.grant_status, VaStatuses.active)
        grant.notes = "a note is not access"
        grant.grant_status = VaStatuses.active  # same value
        db.session.commit()
        self.assertEqual(len(access_rows(self.user.user_id)), before)

    def test_a_revoke_and_a_rolled_back_write(self):
        grant = self._grant()
        db.session.commit()
        grant.grant_status = VaStatuses.deactive
        db.session.rollback()
        self.assertEqual(len(access_rows(self.user.user_id)), 1)
        grant = db.session.get(VaUserAccessGrants, grant.grant_id)
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        self.assertEqual(len(access_rows(self.user.user_id)), 2)

    def test_savepoints_send_nothing_and_lose_nothing(self):
        inner = db.session.begin_nested()
        self._grant(VaAccessRoles.reviewer)
        inner.commit()  # a savepoint release sends nothing ...
        self.assertEqual(access_rows(self.user.user_id), [])
        failed = db.session.begin_nested()
        failed.rollback()  # ... and a rolled-back one drops nothing queued before it
        db.session.commit()  # the outer commit sends one row
        self.assertEqual(len(access_rows(self.user.user_id)), 1)

    def test_a_user_created_in_the_same_transaction_gets_no_row(self):
        user = self._make_user("access.changed.new@test.local", "AccessPass123")  # flushed, not committed
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.reviewer, scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertTrue(db.session.get(VaUsers, user.user_id))
        self.assertEqual(access_rows(user.user_id), [])

    def test_the_poll_delivers_it_and_counts_one_insert_per_commit(self):
        from tests.authz.test_grants import count_queries

        self._grant(VaAccessRoles.reviewer)
        self._grant(VaAccessRoles.coder)
        with count_queries() as statements:
            db.session.commit()
        inserts = [s for s in statements if "INSERT INTO map_user_notifications" in s]
        self.assertEqual(len(inserts), 1)
        self._login(str(self.user.user_id))
        body = self.client.get("/api/v1/me/notifications?after=0").get_json()
        self.assertEqual([(n["kind"], n["project_id"]) for n in body["notifications"]],
                         [(ns.ACCESS_CHANGED, ns.NO_PROJECT)])


class GrantRouteNotificationTests(AuthzFixtureMixin, BaseTestCase):
    """Admin panel and data-management grant create and toggle."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English", is_active=True))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.grantee = self._get_or_make_user("access.changed.grantee@test.local", "AuthzTest123")
        db.session.commit()

    def _body(self, role, scope, where):
        body = {"user_id": str(self.grantee.user_id), "role": role.value, "scope_type": scope.value}
        if scope == P:
            body["project_id"] = where
        else:
            body["org_unit_id"] = str(self.units[where].org_unit_id)
            body["cadre_id"] = self.any_cadre[TA]  # digitva-4650: unit grants name a cadre
        return body

    def _post(self, url, body):
        return self.client.post(url, json=body, headers=self._csrf_headers())

    def _toggle(self, url, grant_id):
        return self.client.post(f"{url}/{grant_id}/toggle", headers=self._csrf_headers())

    def test_data_manager_create_and_toggle(self):
        self._login(str(self.users["dm_ta"].user_id))
        made = self._post(DM_GRANTS, self._body(R.reviewer, P, TA))
        self.assertEqual(made.status_code, 201, made.get_json())
        self.assertEqual(len(access_rows(self.grantee.user_id)), 1)
        again = self._post(DM_GRANTS, self._body(R.reviewer, P, TA))  # already held: nothing changes
        self.assertNotEqual(again.status_code, 201)
        self.assertEqual(len(access_rows(self.grantee.user_id)), 1)
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.grantee.user_id, VaUserAccessGrants.role == R.reviewer))
        off = self._toggle(DM_GRANTS, grant.grant_id)
        self.assertEqual(off.status_code, 200, off.get_json())
        self.assertEqual(len(access_rows(self.grantee.user_id)), 2)

    def test_admin_panel_create_and_toggle(self):
        self._login(str(self.users["pi_ta"].user_id))
        made = self._post(ADMIN_GRANTS, self._body(R.site_pi, U, "C1"))
        self.assertEqual(made.status_code, 201, made.get_json())
        self.assertEqual(len(access_rows(self.grantee.user_id)), 1)
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.grantee.user_id, VaUserAccessGrants.role == R.site_pi))
        off = self._toggle(ADMIN_GRANTS, grant.grant_id)
        self.assertEqual(off.status_code, 200, off.get_json())
        self.assertEqual(len(access_rows(self.grantee.user_id)), 2)


class MentorAndImportNotificationTests(Stage1bBase):
    """Project users import, mentor membership, and the one Core UPDATE."""

    def test_project_users_import(self):
        _d1, _d2, _chc, member = self._setup_one()
        from app.models import VaProjectMaster

        db.session.get(VaProjectMaster, self.P1).project_structure_mode = "organization"
        db.session.commit()
        before = len(access_rows(member.user_id))
        row = {"_line_number": 2, "email": member.email, "name": "", "role": "reviewer", "org_unit_code": "C01",
               "cadre_code": "", "language_codes": "", "phone": ""}
        plan = user_import.prepare(self.P1, [row], actor=self.base_admin_user)
        user_import.apply(self.P1, plan, actor_user_id=self.base_admin_user.user_id)
        db.session.commit()
        self.assertEqual(len(access_rows(member.user_id)), before + 1)
        plan = user_import.prepare(self.P1, [row], actor=self.base_admin_user)
        user_import.apply(self.P1, plan, actor_user_id=self.base_admin_user.user_id)  # already held
        db.session.commit()
        self.assertEqual(len(access_rows(member.user_id)), before + 1)

    def test_membership_change_and_the_core_lapse(self):
        d1, _d2, chc, one = self._setup_one()
        A = VaAccessRoles
        self._grant(one, A.coder, VaAccessScopeTypes.org_unit, unit=chc)
        before = len(access_rows(one.user_id))
        self.assertGreaterEqual(before, 1)  # the grant above

        # The institute's deactivation lapses the grant by a Core UPDATE.
        mentors.set_institute_active("MC1", False)
        db.session.commit()
        self.assertEqual(len(access_rows(one.user_id)), before + 1)
        # Nothing left to lapse, and the institute row is not the user's: no row.
        mentors.set_institute_active("MC1", False)
        db.session.commit()
        self.assertEqual(len(access_rows(one.user_id)), before + 1)

        mentors.set_institute_active("MC1", True)
        db.session.commit()
        mentors.remove_member("MC1", one.email)  # the membership row changes
        db.session.commit()
        self.assertEqual(len(access_rows(one.user_id)), before + 2)


    def test_mentor_scientist_unit_grants_sync(self):
        from app.services import organization_service as org

        _d1, _d2, chc, one = self._setup_one()
        before = len(access_rows(one.user_id))

        def sync():
            org.sync_mentor_scientist_unit_grants(
                self.P1, user_id=one.user_id, role_name="reviewer", org_unit_ids=[chc.org_unit_id],
                actor=self.base_admin_user,
            )
            db.session.commit()

        sync()
        self.assertEqual(len(access_rows(one.user_id)), before + 1)
        sync()  # already held: nothing changes
        self.assertEqual(len(access_rows(one.user_id)), before + 1)


class GraduationNotificationTests(GraduationTestBase):
    def test_graduation_notifies_the_trainee_and_the_poll_delivers_it(self):
        code = self._typed("self_coding", slots=1)["session_code"]
        user = self._user("grad.notice")
        self._add(code, user)
        db.session.commit()
        before = len(access_rows(user.user_id))
        saved = svc.graduate(code, GRAD_PROJECT, [self._row(user, language_codes=["english"])], self.admin,
                             dry_run=False)
        self.assertEqual(saved["saved"], 1, saved)
        db.session.commit()
        self.assertEqual(len(access_rows(user.user_id)), before + 1)
        self._login(str(user.user_id))
        body = self.client.get(f"/api/v1/me/notifications?after={access_rows(user.user_id)[-1].id - 1}").get_json()
        self.assertEqual([n["kind"] for n in body["notifications"]], [ns.ACCESS_CHANGED])
