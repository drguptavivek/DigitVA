"""Roster sign-in codes, enrolment status and roster access (digitva-dcdb).

Contract: POST /admin/api/projects/<id>/users-grid/<user_id>/sign-in-code
issues a code when ``may_issue_code_in_project`` holds, else 404; the grid
row carries ``activated``, ``phone_count``, ``last_sign_in_at`` and
``can_issue_code``; /admin/project-roster serves only the All Users tab to
an admin, the project's PI or a project-scope data manager.
Policy: docs/policy/mobile-sign-in.md section 3 (roster rule) and
docs/policy/access-control-model.md ("Project membership").
"""
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    MapProjectMember,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.auth_factors import AuthSecurityEvent
from app.services import mobile_sign_in_service as mobile
from app.services import organization_service as org
from tests.base import BaseTestCase

R = VaAccessRoles
P = VaAccessScopeTypes.project
PS = VaAccessScopeTypes.project_site
CODE_RE = r"^[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$"


class RosterSignInCodeTests(BaseTestCase):
    A = "RSCA01"
    B = "RSCB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.A, cls.B):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Roster {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
            ))
        db.session.flush()
        cls.pi_a = cls._staff("pi.a", R.project_pi, P, cls.A)
        cls.dm_a = cls._staff("dm.a", R.data_manager, P, cls.A)
        cls.pi_b = cls._staff("pi.b", R.project_pi, P, cls.B)
        cls.coder_a = cls._staff("coder.a", R.coder, P, cls.A)
        db.session.commit()

    @classmethod
    def _staff(cls, name, role, scope, project_id):
        user = cls._make_user(f"rsc.{name}@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=scope, project_id=project_id,
            grant_status=VaStatuses.active,
        ))
        return user

    def setUp(self):
        super().setUp()
        limiter.reset()

    # -- fixtures ---------------------------------------------------------

    def _person(self, *, members=(), grants=(), email=None, verified=False, active=True, mobile_login=True):
        number = f"9{uuid.uuid4().int % 10**9:09d}"
        user = VaUsers(
            user_id=uuid.uuid4(), name="Roster Person", email=email,
            mobile_login=number if mobile_login else None, phone=number if mobile_login else None,
            vacode_language=["English"], permission={}, landing_page="coder",
            pw_reset_t_and_c=False, email_verified=verified,
            user_status=VaStatuses.active if active else VaStatuses.deactive,
        )
        user.set_password("Unused123!x")
        db.session.add(user)
        db.session.flush()
        for project_id in members:
            db.session.add(MapProjectMember(project_id=project_id, user_id=user.user_id))
        for role, scope, project_id in grants:
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=scope, project_id=project_id,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()
        return user

    def _issue(self, user_id, project_id=None, headers=None):
        return self.client.post(
            f"/admin/api/projects/{project_id or self.A}/users-grid/{user_id}/sign-in-code",
            headers=self._csrf_headers() if headers is None else headers,
        )

    # -- who may issue ----------------------------------------------------

    def test_pi_and_project_dm_issue_for_unplaced_and_fully_managed_people_admin_always(self):
        unplaced = self._person(members=[self.A])
        placed = self._person(grants=[(R.coder, P, self.A)])
        for actor in (self.pi_a, self.dm_a, self.base_admin_user):
            for target in (unplaced, placed):
                with self.subTest(actor=actor.email, target=str(target.user_id)):
                    self._login(str(actor.user_id))
                    response = self._issue(target.user_id)
                    self.assertEqual(response.status_code, 200, response.get_json())
                    body = response.get_json()
                    self.assertRegex(body["sign_in_code"], CODE_RE)
                    self.assertEqual(body["expires_in_minutes"], 90)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
        self._login(self.base_admin_id)
        verified = self._person(email="rsc.verified@test.local", verified=True)
        self.assertEqual(self._issue(verified.user_id).status_code, 200)

    def test_refusals_are_404(self):
        admin_target = self._person(members=[self.A])
        db.session.add(VaUserAccessGrants(
            user_id=admin_target.user_id, role=R.admin, scope_type=VaAccessScopeTypes.global_scope,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        refused = {
            "member of B too": self._person(members=[self.A, self.B]),
            "grant in B": self._person(grants=[(R.coder, P, self.A), (R.coder, P, self.B)]),
            "unmanaged grant, member": self._person(members=[self.A], grants=[(R.coder, P, self.B)]),
            "privileged grant": self._person(grants=[(R.data_manager, P, self.A)]),
            "verified email": self._person(members=[self.A], email="rsc.v2@test.local", verified=True),
            "admin": admin_target,
            "inactive": self._person(members=[self.A], active=False),
            "not a member, no grants": self._person(),
        }
        for actor in (self.pi_a, self.dm_a):
            self._login(str(actor.user_id))
            for name, user in refused.items():
                with self.subTest(actor=actor.email, case=name):
                    self.assertFalse(mobile.may_issue_code_in_project(actor, user.user_id, self.A))
                    self.assertEqual(self._issue(user.user_id).status_code, 404)
        self.assertEqual(self._issue(uuid.uuid4()).status_code, 404)

    def test_wrong_project_and_wrong_role_actors_are_refused(self):
        from app.models import VaProjectSites

        unplaced = self._person(members=[self.A])
        now = datetime.now(UTC)
        pair = VaProjectSites(project_id=self.A, site_id=self.BASE_SITE_ID, project_site_status=VaStatuses.active,
                              project_site_registered_at=now, project_site_updated_at=now)
        db.session.add(pair)
        db.session.flush()
        site_dm = self._make_user("rsc.sitedm@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(
            user_id=site_dm.user_id, role=R.data_manager, scope_type=PS,
            project_site_id=pair.project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        for actor in (self.pi_b, self.coder_a, site_dm):
            with self.subTest(actor=actor.email):
                self.assertFalse(mobile.may_issue_code_in_project(actor, unplaced.user_id, self.A))
                self._login(str(actor.user_id))
                self.assertIn(self._issue(unplaced.user_id).status_code, (403, 404))
        # A PI of A asking through project B's URL is refused too.
        self._login(str(self.pi_a.user_id))
        self.assertEqual(self._issue(unplaced.user_id, project_id=self.B).status_code, 404)

    def test_rule_a_matches_may_issue_code_row_by_row(self):
        people = [
            self._person(grants=[(R.coder, P, self.A)]),
            self._person(grants=[(R.coder, P, self.A), (R.coder, P, self.B)]),
            self._person(grants=[(R.data_manager, P, self.A)]),
            self._person(grants=[(R.coder, P, self.A)], email="rsc.v3@test.local", verified=True),
        ]
        for actor in (self.pi_a, self.dm_a):
            batch = mobile.issuable_user_ids(actor, self.A, [p.user_id for p in people])
            for person in people:
                with self.subTest(actor=actor.email, person=str(person.user_id)):
                    self.assertEqual(person.user_id in batch, mobile.may_issue_code(actor, person.user_id))

    # -- the issue itself -------------------------------------------------

    def test_issue_audits_and_never_logs_the_code(self):
        target = self._person(members=[self.A])
        self._login(str(self.pi_a.user_id))
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("rsc.marker").info("marker")
            response = self._issue(target.user_id)
        code = response.get_json()["sign_in_code"]
        self.assertNotIn(code, "\n".join(logs.output))
        self.assertNotIn(code.replace("-", ""), "\n".join(logs.output))
        events = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == target.user_id,
            AuthSecurityEvent.event_type == "mobile_code_issued",
            AuthSecurityEvent.actor_user_id == self.pi_a.user_id,
        )).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].detail, {"project_id": self.A, "via": "project_roster"})

    def test_missing_csrf_is_refused(self):
        target = self._person(members=[self.A])
        self._login(str(self.pi_a.user_id))
        self.assertEqual(self._issue(target.user_id, headers={}).status_code, 400)

    def test_rate_limited_per_caller(self):
        target = self._person(members=[self.A])
        self._login(str(self.dm_a.user_id))
        statuses = [self._issue(target.user_id).status_code for _ in range(21)]
        self.assertEqual(statuses[:20], [200] * 20)
        self.assertEqual(statuses[20], 429)

    # -- the grid ---------------------------------------------------------

    def _row(self, viewer, user):
        grid = org.get_project_users_grid(self.A, viewer=viewer)
        return next(u for u in grid["users"] if u["user_id"] == str(user.user_id))

    def test_grid_rows_carry_status_and_per_viewer_flag(self):
        fresh = self._person(members=[self.A])
        signed_in = self._person(members=[self.A])
        signed_in.mobile_verified_at = datetime.now(UTC)
        signed_in.last_signed_in_at = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
        now = datetime.now(UTC)
        for name, revoked in (("one", None), ("two", None), ("gone", now)):
            device = AuthDevice(project_id=self.A, name=name, platform="android", secret_hash=uuid.uuid4().hex,
                                revoked_at=revoked)
            db.session.add(device)
            db.session.flush()
            db.session.add(AuthDeviceSession(
                device_id=device.device_id, user_id=signed_in.user_id,
                access_hash=uuid.uuid4().hex, access_expires_at=now + timedelta(hours=1),
                refresh_hash=uuid.uuid4().hex, refresh_expires_at=now + timedelta(days=30),
            ))
        db.session.commit()

        row = self._row(self.pi_a, fresh)
        self.assertEqual((row["activated"], row["phone_count"], row["last_sign_in_at"], row["can_issue_code"]),
                         (False, 0, None, True))
        row = self._row(self.pi_a, signed_in)
        self.assertTrue(row["activated"])
        self.assertEqual(row["phone_count"], 2)
        self.assertEqual(datetime.fromisoformat(row["last_sign_in_at"]), signed_in.last_signed_in_at)
        self.assertTrue(self._row(self.dm_a, fresh)["can_issue_code"])
        self.assertTrue(self._row(self.base_admin_user, fresh)["can_issue_code"])
        self.assertFalse(self._row(self.pi_b, fresh)["can_issue_code"])
        self.assertFalse(org.get_project_users_grid(self.A)["users"][0]["can_issue_code"])
        both = self._person(members=[self.A, self.B])
        self.assertFalse(self._row(self.pi_a, both)["can_issue_code"])

    def test_grid_query_count_does_not_grow_with_rows(self):
        def statements():
            seen = []

            def record(conn, cursor, statement, *args):
                seen.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                grid = org.get_project_users_grid(self.A, viewer=self.pi_a)
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            return len(seen), grid

        self._person(members=[self.A])
        few, small = statements()
        for _ in range(12):
            self._person(members=[self.A])
        many, large = statements()
        self.assertGreaterEqual(len(large["users"]), len(small["users"]) + 12)
        self.assertEqual(few, many)

    # -- roster access ----------------------------------------------------

    def test_project_dm_and_pi_use_their_roster_only(self):
        self._person(members=[self.A])
        for actor in (self.pi_a, self.dm_a):
            with self.subTest(actor=actor.email):
                self._login(str(actor.user_id))
                page = self.client.get(f"/admin/project-roster?project_id={self.A}")
                self.assertEqual(page.status_code, 200)
                html = page.get_data(as_text=True)
                self.assertIn('id="setup-ug-card"', html)
                for absent in ('data-section="overview"', 'data-section="basics"', 'setup-people-pane-grants',
                               'setup-people-pane-audit', 'setup-people-pane-devices', 'data-section="sync"'):
                    self.assertNotIn(absent, html)
                self.assertEqual(self.client.get(f"/admin/api/projects/{self.A}/users-grid").status_code, 200)
                self.assertEqual(self.client.get(f"/admin/project-roster?project_id={self.B}").status_code, 404)
                self.assertEqual(self.client.get(f"/admin/api/projects/{self.B}/users-grid").status_code, 403)
                bulk = self.client.post(f"/admin/api/projects/{self.B}/users-grid/bulk-apply",
                                        json={"user_ids": [], "operation": "coder"}, headers=self._csrf_headers())
                self.assertEqual(bulk.status_code, 403)

    def test_dm_gets_upload_and_place_and_other_admin_apis_stay_closed(self):
        self._login(str(self.dm_a.user_id))
        html = self.client.get(f"/admin/project-roster?project_id={self.A}").get_data(as_text=True)
        self.assertIn('id="setup-ug-card"', html)
        self.assertIn('id="setup-ug-members-toggle"', html)
        # A data manager removes grants through the data-management toggle.
        self.assertIn("var UG_GRANTS_VIA_ADMIN = false;", html)
        self.assertNotIn("by an admin or the project's data manager only", html)
        closed = [
            ("get", f"/admin/panels/project-setup/{self.A}"),
            ("get", f"/admin/api/organization/{self.A}/workers"),
            ("post", f"/admin/api/organization/{self.B}/workers"),
            ("post", f"/admin/api/projects/{self.B}/users-grid/members/import"),
            ("get", f"/admin/api/projects/{self.A}/web-intake-readiness"),
            ("get", f"/admin/api/projects/{self.A}/devices"),
            ("put", f"/admin/api/projects/{self.A}"),
            ("get", "/admin/"),
        ]
        for method, url in closed:
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, json={}, headers=self._csrf_headers())
                self.assertIn(response.status_code, (401, 403, 404, 405), url)
        self._login(str(self.pi_a.user_id))
        html = self.client.get(f"/admin/project-roster?project_id={self.A}").get_data(as_text=True)
        self.assertIn('id="setup-ug-members-toggle"', html)
        self.assertIn("var UG_GRANTS_VIA_ADMIN = true;", html)
        self.assertIn("by an admin or the project's data manager only", html)

    def test_dm_bulk_apply_cannot_widen_grant_writes(self):
        target = self._person(members=[self.A])
        self._login(str(self.dm_a.user_id))
        refused = self.client.post(
            f"/admin/api/projects/{self.A}/users-grid/bulk-apply",
            json={"user_ids": [str(target.user_id)], "operation": "activate_users", "scope_mode": "project"},
            headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 400)
        refused = self.client.post(
            f"/admin/api/projects/{self.A}/users-grid/bulk-apply",
            json={"user_ids": [str(target.user_id)], "operation": "project_pi", "scope_mode": "project"},
            headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == target.user_id)), 0)

    def test_roster_page_refuses_other_roles(self):
        self._login(str(self.coder_a.user_id))
        self.assertEqual(self.client.get(f"/admin/project-roster?project_id={self.A}").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/api/projects/{self.A}/users-grid").status_code, 403)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(f"/admin/project-roster?project_id={self.A}").status_code, 200)
        self.assertTrue(re.search(r'data-project-id="RSCA01"',
                                  self.client.get(f"/admin/project-roster?project_id={self.A}").get_data(as_text=True)))

    # -- roster targets only (security review of digitva-dcdb) ------------

    def _grant_count(self, user):
        return db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id))

    def _bulk(self, user, operation="coder", project_id=None):
        return self.client.post(
            f"/admin/api/projects/{project_id or self.A}/users-grid/bulk-apply",
            json={"user_ids": [str(user.user_id)], "operation": operation, "scope_mode": "project"},
            headers=self._csrf_headers())

    def test_bulk_apply_refuses_an_account_not_on_the_roster_so_no_code_follows(self):
        member = self._person(members=[self.A])
        for actor in (self.pi_a, self.dm_a):
            outsider = self._person()
            member_of_b = self._person(members=[self.B])
            self._login(str(actor.user_id))
            for target in (outsider, member_of_b):
                with self.subTest(actor=actor.email, target=str(target.user_id)):
                    response = self._bulk(target)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["error"], "One or more selected users were not found.")
                    self.assertEqual(self._grant_count(target), 0)
                    self.assertFalse(mobile.may_issue_code_in_project(actor, target.user_id, self.A))
                    self.assertEqual(self._issue(target.user_id).status_code, 404)
        # A roster member is accepted, and the admin is not bound by the rule.
        self._login(str(self.dm_a.user_id))
        self.assertEqual(self._bulk(member).status_code, 200)
        self.assertEqual(self._grant_count(member), 1)
        self._login(self.base_admin_id)
        outsider = self._person()
        self.assertEqual(self._bulk(outsider).status_code, 200)

    def test_a_member_of_another_project_gets_no_code_even_with_a_grant_here(self):
        # The admin gave a member of B a grant in A: rule (a) alone would hold.
        target = self._person(members=[self.B], grants=[(R.coder, P, self.A)])
        self.assertTrue(mobile.may_issue_code(self.pi_a, target.user_id))
        for actor in (self.pi_a, self.dm_a):
            with self.subTest(actor=actor.email):
                self.assertFalse(mobile.may_issue_code_in_project(actor, target.user_id, self.A))
                self._login(str(actor.user_id))
                self.assertEqual(self._issue(target.user_id).status_code, 404)
        self._login(self.base_admin_id)
        self.assertEqual(self._issue(target.user_id).status_code, 200)

    # -- Place and move by a data manager ---------------------------------

    def _tree(self, project_id, default_roles=("coder",), can_fill=False):
        org.seed_default_organization(project_id)
        level = next(lv for lv in org.list_levels(project_id) if lv.level_code == "district")
        cadre = next(c for c in org.list_cadres(project_id) if c.cadre_code == "MO")
        org.upsert_level_cadre(
            project_id, org_level_id=level.org_level_id, cadre_id=cadre.cadre_id,
            can_fill_va_form=can_fill, can_code_va_form=True, default_roles=list(default_roles),
        )
        units = [org.create_unit(project_id, org_level_id=level.org_level_id,
                                 unit_code=f"{project_id}D{n}", unit_name=f"District {n}") for n in (1, 2)]
        db.session.commit()
        return units, cadre

    def _place(self, unit, cadre, user=None, project_id=None, **extra):
        body = {"org_unit_id": str(unit.org_unit_id), "cadre_id": str(cadre.cadre_id),
                "worker_name": "Roster Person", **extra}
        if user is not None:
            body["user"] = str(user.user_id)
        return self.client.post(f"/admin/api/organization/{project_id or self.A}/workers",
                                json=body, headers=self._csrf_headers())

    def _worker_count(self, user):
        return db.session.scalar(sa.select(sa.func.count()).select_from(MasOrgUnitWorker).where(
            MasOrgUnitWorker.user_id == user.user_id))

    def test_dm_places_a_roster_member_and_the_default_grants_apply(self):
        (unit, _), cadre = self._tree(self.A, default_roles=("coder", "reviewer"))
        member = self._person(members=[self.A])
        self._login(str(self.dm_a.user_id))
        response = self._place(unit, cadre, member)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self._worker_count(member), 1)
        roles = set(db.session.scalars(sa.select(VaUserAccessGrants.role).where(
            VaUserAccessGrants.user_id == member.user_id, VaUserAccessGrants.org_unit_id == unit.org_unit_id,
            VaUserAccessGrants.grant_status == VaStatuses.active)))
        self.assertEqual(roles, {R.coder, R.reviewer})

    def test_dm_place_is_refused_whole_when_a_default_grant_fails_can_grant(self):
        # site_pi (the In-charge) is not a role a data manager grants.
        (unit, _), cadre = self._tree(self.A, default_roles=("coder", "site_pi"))
        member = self._person(members=[self.A])
        self._login(str(self.dm_a.user_id))
        response = self._place(unit, cadre, member)
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual((self._worker_count(member), self._grant_count(member)), (0, 0))
        # The PI may grant both, so the same placement succeeds for them.
        self._login(str(self.pi_a.user_id))
        self.assertEqual(self._place(unit, cadre, member).status_code, 201)

    def test_dm_place_refused_outside_scope_off_roster_or_creating_an_account(self):
        (unit, _), cadre = self._tree(self.A)
        (unit_b, _), cadre_b = self._tree(self.B)
        member = self._person(members=[self.A])
        outsider = self._person()
        self._login(str(self.dm_a.user_id))
        cases = {
            "unit of another project": (self._place(unit_b, cadre_b, member), 403),
            "not on the roster": (self._place(unit, cadre, outsider), 400),
            "unknown account": (self._place(unit, cadre, VaUsers(user_id=uuid.uuid4())), 400),
            "account fields": (self._place(unit, cadre, member, email="rsc.new@test.local"), 403),
            "no account": (self._place(unit, cadre), 400),
        }
        for name, (response, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(response.status_code, status, response.get_json())
        self.assertEqual(cases["not on the roster"][0].get_json()["error"],
                         cases["unknown account"][0].get_json()["error"])
        self.assertEqual((self._worker_count(member), self._worker_count(outsider)), (0, 0))
        self.assertEqual(self._grant_count(outsider), 0)
        # The PI is held to the roster too.
        self._login(str(self.pi_a.user_id))
        self.assertEqual(self._place(unit, cadre, outsider).status_code, 400)
        self.assertEqual((self._worker_count(outsider), self._grant_count(outsider)), (0, 0))

    def test_dm_move_needs_both_the_old_and_the_new_unit_in_scope(self):
        (unit, other), cadre = self._tree(self.A)
        (unit_b, _), cadre_b = self._tree(self.B)
        member = self._person(members=[self.A])
        self._login(str(self.dm_a.user_id))
        placed = self._place(unit, cadre, member)
        self.assertEqual(placed.status_code, 201, placed.get_json())
        worker_id = placed.get_json()["worker"]["worker_id"]

        def move(body):
            return self.client.patch(f"/admin/api/organization/{self.A}/workers/{worker_id}",
                                     json=body, headers=self._csrf_headers())

        self.assertEqual(move({"org_unit_id": str(unit_b.org_unit_id), "cadre_id": str(cadre_b.cadre_id)})
                         .status_code, 403)
        self.assertEqual(move({"user": str(self.coder_a.user_id)}).status_code, 403)
        moved = move({"org_unit_id": str(other.org_unit_id), "cadre_id": str(cadre.cadre_id), "is_active": True})
        self.assertEqual(moved.status_code, 200, moved.get_json())
        self.assertEqual(db.session.get(MasOrgUnitWorker, uuid.UUID(worker_id)).org_unit_id, other.org_unit_id)
        # The current unit leaves the DM's scope (deactivated): moving out is refused.
        db.session.get(MasOrgUnit, other.org_unit_id).is_active = False
        db.session.commit()
        self.assertEqual(move({"org_unit_id": str(unit.org_unit_id)}).status_code, 403)
        self.assertEqual(db.session.get(MasOrgUnitWorker, uuid.UUID(worker_id)).org_unit_id, other.org_unit_id)

    def test_dm_places_a_data_collector_and_the_enrolment_email_step_runs(self):
        (unit, _), cadre = self._tree(self.A, default_roles=("interviewer",), can_fill=True)
        member = self._person(members=[self.A], email="rsc.collector@test.local")
        self._login(str(self.dm_a.user_id))
        response = self._place(unit, cadre, member)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertIn(response.get_json()["onboarding"]["enrolment_email"], ("sent", "failed"))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == member.user_id, VaUserAccessGrants.role == R.interviewer,
            VaUserAccessGrants.org_unit_id == unit.org_unit_id)), 1)

    def test_a_pair_scope_dm_gets_none_of_the_opened_routes(self):
        from app.models import VaProjectSites

        (unit, _), cadre = self._tree(self.A)
        member = self._person(members=[self.A])
        now = datetime.now(UTC)
        pair = VaProjectSites(project_id=self.A, site_id=self.BASE_SITE_ID, project_site_status=VaStatuses.active,
                              project_site_registered_at=now, project_site_updated_at=now)
        db.session.add(pair)
        db.session.flush()
        site_dm = self._make_user("rsc.pairdm@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(
            user_id=site_dm.user_id, role=R.data_manager, scope_type=PS,
            project_site_id=pair.project_site_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(site_dm.user_id))
        base = f"/admin/api/organization/{self.A}/workers"
        responses = {
            "place": self._place(unit, cadre, member),
            "move": self.client.patch(f"{base}/{uuid.uuid4()}", json={}, headers=self._csrf_headers()),
            "template": self.client.get(f"/admin/api/projects/{self.A}/users-grid/members/template.csv"),
            "import": self.client.post(f"/admin/api/projects/{self.A}/users-grid/members/import",
                                       headers=self._csrf_headers()),
            "bulk": self._bulk(member),
        }
        for name, response in responses.items():
            with self.subTest(route=name):
                self.assertEqual(response.status_code, 403)
        self.assertEqual((self._worker_count(member), self._grant_count(member)), (0, 0))

    # -- someone signed in on a phone needs no code (owner 2026-11-16) -----

    def _phone(self, user, *, session_revoked=False, refresh_expired=False, device_revoked=False):
        now = datetime.now(UTC)
        device = AuthDevice(project_id=self.A, name="phone", platform="android", secret_hash=uuid.uuid4().hex,
                            revoked_at=now if device_revoked else None)
        db.session.add(device)
        db.session.flush()
        db.session.add(AuthDeviceSession(
            device_id=device.device_id, user_id=user.user_id,
            access_hash=uuid.uuid4().hex, access_expires_at=now + timedelta(hours=1),
            refresh_hash=uuid.uuid4().hex,
            refresh_expires_at=now - timedelta(minutes=1) if refresh_expired else now + timedelta(days=30),
            revoked_at=now if session_revoked else None,
        ))
        db.session.commit()

    def test_a_live_phone_refuses_pi_and_dm_codes_and_hides_the_button_admin_unaffected(self):
        unplaced = self._person(members=[self.A])
        placed = self._person(grants=[(R.coder, P, self.A)])
        for target in (unplaced, placed):
            self._phone(target)
        for actor in (self.pi_a, self.dm_a):
            self._login(str(actor.user_id))
            for target in (unplaced, placed):
                with self.subTest(actor=actor.email, target=str(target.user_id)):
                    row = self._row(actor, target)
                    self.assertEqual(row["phone_count"], 1)
                    self.assertFalse(row["can_issue_code"])
                    self.assertFalse(mobile.may_issue_code_in_project(actor, target.user_id, self.A))
                    self.assertEqual(self._issue(target.user_id).status_code, 404)
        self.assertTrue(mobile.may_issue_code(self.pi_a, placed.user_id))  # the phone is what refuses
        self._login(self.base_admin_id)
        self.assertTrue(self._row(self.base_admin_user, unplaced)["can_issue_code"])
        self.assertEqual(self._issue(unplaced.user_id).status_code, 200)

    def test_a_revoked_or_expired_sign_in_is_no_live_phone(self):
        for kind in ("session_revoked", "refresh_expired", "device_revoked"):
            target = self._person(members=[self.A])
            self._phone(target, **{kind: True})
            with self.subTest(kind=kind):
                row = self._row(self.pi_a, target)
                self.assertEqual((row["phone_count"], row["can_issue_code"]), (0, True))
                self._login(str(self.pi_a.user_id))
                self.assertEqual(self._issue(target.user_id).status_code, 200)

    def test_grid_flag_matches_the_endpoint_row_by_row(self):
        signed_in = self._person(members=[self.A])
        self._phone(signed_in)
        people = [
            self._person(members=[self.A]),
            self._person(grants=[(R.coder, P, self.A)]),
            self._person(members=[self.A, self.B]),
            self._person(members=[self.A], email="rsc.v4@test.local", verified=True),
            self._person(members=[self.A], email="rsc.nomobile@test.local", mobile_login=False),
            signed_in,
        ]
        for actor in (self.pi_a, self.dm_a, self.base_admin_user):
            for person in people:
                with self.subTest(actor=actor.email, person=str(person.user_id)):
                    flag = self._row(actor, person)["can_issue_code"]
                    self._login(str(actor.user_id))
                    self.assertEqual(self._issue(person.user_id).status_code == 200, flag)
                    limiter.reset()


    def test_pi_gets_one_refusal_for_unknown_inactive_and_off_roster_accounts(self):
        (unit, _), cadre = self._tree(self.A)
        member = self._person(members=[self.A])
        inactive = self._person(email="rsc.inactive@test.local", active=False)  # off the roster
        outsider = self._person(email="rsc.outsider@test.local")
        base = f"/admin/api/organization/{self.A}/workers"
        self._login(str(self.pi_a.user_id))
        placed = self._place(unit, cadre, member)
        self.assertEqual(placed.status_code, 201, placed.get_json())
        worker_id = placed.get_json()["worker"]["worker_id"]
        for name, value in (("unknown email", "rsc.nobody@test.local"), ("unknown id", str(uuid.uuid4())),
                            ("inactive", str(inactive.user_id)), ("off roster", outsider.email)):
            with self.subTest(case=name):
                body = {"org_unit_id": str(unit.org_unit_id), "cadre_id": str(cadre.cadre_id),
                        "worker_name": "Roster Person", "user": value}
                for response in (self.client.post(base, json=body, headers=self._csrf_headers()),
                                 self.client.patch(f"{base}/{worker_id}", json={"user": value},
                                                   headers=self._csrf_headers())):
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["error"], "One or more selected users were not found.")
        self.assertEqual(self._worker_count(outsider), 0)
        # The admin keeps the detailed message.
        self._login(self.base_admin_id)
        response = self.client.post(base, json={"org_unit_id": str(unit.org_unit_id), "cadre_id": str(cadre.cadre_id),
                                                "worker_name": "Roster Person", "user": "rsc.nobody@test.local"},
                                    headers=self._csrf_headers())
        self.assertEqual(response.status_code, 400)
        self.assertIn("DigitVA user not found", response.get_json()["error"])


class DataManagementSignInCodeTests(BaseTestCase):
    """The data-management code endpoint after a grant (security review of
    digitva-dcdb): a data manager may grant any account it looks up, so a
    member of another project or someone signed in on a phone gets no code
    from them; a fresh account with neither is the accepted residual."""

    A = "DMSC01"
    B = "DMSC02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.A, cls.B):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"DM code {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        db.session.flush()
        cls.dm_a = RosterSignInCodeTests._staff.__func__(cls, "dmsc.dm.a", R.data_manager, P, cls.A)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    _person = RosterSignInCodeTests._person
    _phone = RosterSignInCodeTests._phone

    def _grant_and_issue(self, target):
        """The attack: look the account up, grant it a role here, ask for a code."""
        found = self.client.get("/data-management/api/users/lookup", query_string={"value": target.mobile_login})
        self.assertEqual(found.status_code, 200, found.get_json())
        self.assertIn(str(target.user_id), {u["user_id"] for u in found.get_json()["users"]})
        granted = self.client.post("/data-management/api/access-grants", json={
            "user_id": str(target.user_id), "role": R.coder.value, "scope_type": P.value, "project_id": self.A,
        }, headers=self._csrf_headers())
        self.assertIn(granted.status_code, (200, 201), granted.get_json())
        return self._issue(target)

    def _issue(self, target):
        return self.client.post(f"/data-management/api/users/{target.user_id}/sign-in-code",
                                headers=self._csrf_headers())

    def test_grant_then_issue_is_refused_for_a_member_elsewhere_or_a_signed_in_phone(self):
        member_of_b = self._person(members=[self.B])
        signed_in = self._person()
        self._phone(signed_in)
        self._login(str(self.dm_a.user_id))
        for name, target in (("member of B", member_of_b), ("live phone", signed_in)):
            with self.subTest(case=name):
                response = self._grant_and_issue(target)
                # may_issue_code alone would allow it: the new clauses refuse.
                self.assertTrue(mobile.may_issue_code(self.dm_a, target.user_id))
                self.assertFalse(mobile.may_issue_code_from_data_management(self.dm_a, target.user_id))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.get_json()["error"], "User not found.")

    def test_a_fresh_account_the_dm_granted_still_gets_a_code_the_accepted_residual(self):
        fresh = self._person()
        self._login(str(self.dm_a.user_id))
        response = self._grant_and_issue(fresh)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertRegex(response.get_json()["sign_in_code"], CODE_RE)
        # A member of the DM's own project is not "outside".
        own = self._person(members=[self.A])
        self.assertEqual(self._grant_and_issue(own).status_code, 200)

    def test_admin_is_unaffected(self):
        target = self._person(members=[self.B], grants=[(R.coder, P, self.A)])
        self._phone(target)
        self._login(self.base_admin_id)
        self.assertTrue(mobile.may_issue_code_from_data_management(self.base_admin_user, target.user_id))
        self.assertEqual(self._issue(target).status_code, 200)

    def test_a_unit_dm_issues_for_a_member_of_its_own_project(self):
        # writer_grants, not roster_project_ids: a unit writer's project is not "outside".
        org.seed_default_organization(self.A)
        level = next(lv for lv in org.list_levels(self.A) if lv.level_code == "district")
        unit = org.create_unit(self.A, org_level_id=level.org_level_id, unit_code="DMSCD1", unit_name="D1")
        unit_dm = self._make_user("dmsc.unitdm@test.local", "Staff123!x")
        target = self._person(members=[self.A])
        for user, role in ((unit_dm, R.data_manager), (target, R.interviewer)):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=unit.org_unit_id, grant_status=VaStatuses.active,
            ))
        db.session.commit()
        self._login(str(unit_dm.user_id))
        self.assertEqual(self._issue(target).status_code, 200)
        other = self._person(members=[self.B])
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id, role=R.interviewer, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertEqual(self._issue(other).status_code, 404)
