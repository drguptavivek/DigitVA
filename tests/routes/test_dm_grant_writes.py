"""Grant writes through the data-manager, admin and import interfaces
(digitva-0wc stage 6).

The rule itself (``authz.can_grant``) is tested against the policy table in
tests/authz/test_can_grant.py. These tests prove the interfaces route every
write, list and search through it, both project kinds, and that the
write-time checks (cadre, mentor guard) still refuse after it allows.

Policy: access-control-model.md "Who creates which grants";
dm-user-grant-management.md.
"""
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import MasOrgLevel, VaProjectMaster, VaStatuses, VaUserAccessGrants
from app.models.mas_languages import MasLanguages
from app.services import project_user_import_service as user_import
from app.services.authz import GrantTarget, can_grant
from app.services.authz.actions import DM_SITE_ASSIGNABLE, DM_TREE_ASSIGNABLE
from app.services.organization_service import list_cadres
from tests.authz.fixture import PS, SP, TA, AuthzFixtureMixin, P, R, U
from tests.base import BaseTestCase

DM_GRANTS = "/data-management/api/access-grants"
ADMIN_GRANTS = "/admin/api/access-grants"
LOOKUP = "/data-management/api/users/lookup"
# The roles the data-manager page writes and lists; the rest are the admin panel's.
DM_PAGE_ROLES = DM_SITE_ASSIGNABLE | DM_TREE_ASSIGNABLE


class DmGrantWriteTests(AuthzFixtureMixin, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(
                MasLanguages(language_code="english", language_name="English", is_active=True)
            )
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()  # in-memory buckets outlive a test
        self.grantee = self._get_or_make_user("authz.dm.grantee@test.local", "AuthzTest123")

    # -- helpers -----------------------------------------------------------

    def _as(self, key):
        self._login(str(self.users[key].user_id))

    def _body(self, role, scope, where, user=None, **extra):
        body = {"user_id": str((user or self.grantee).user_id), "role": role.value,
                "scope_type": scope.value, **extra}
        if scope == P:
            body["project_id"] = where
        elif scope == PS:
            body["project_site_id"] = str(self.project_site_ids[where])
        else:
            body["org_unit_id"] = str(self.units[where].org_unit_id)
        return body

    def _post(self, url, body):
        return self.client.post(url, json=body, headers=self._csrf_headers())

    def _toggle(self, url, grant_id):
        return self.client.post(f"{url}/{grant_id}/toggle", headers=self._csrf_headers())

    def _cadre(self, code):
        return next(c for c in list_cadres(TA) if c.cadre_code == code)

    def _held(self, key, role, scope):
        return db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.users[key].user_id,
            VaUserAccessGrants.role == role, VaUserAccessGrants.scope_type == scope,
        ))

    def _assert_codes(self, actor, cases, url=DM_GRANTS):
        self._as(actor)
        for role, scope, where, expected in cases:
            with self.subTest(actor=actor, role=role.value, scope=scope.value, where=where):
                response = self._post(url, self._body(role, scope, where))
                self.assertEqual(response.status_code, expected, response.get_json())

    # -- the district rule -------------------------------------------------

    def test_unit_dm_creates_dms_strictly_below_and_the_six_roles_in_its_subtree(self):
        self._assert_codes("dm_c1", [
            (R.data_manager, U, "P1", 201),
            (R.data_manager, U, "SC1", 201),
            (R.data_manager, U, "C1", 403),        # not at own level
            (R.reviewer, U, "C1", 201),            # six roles, own level included
            (R.interviewer, U, "SC1", 201),
            (R.collaborator, U, "P2", 201),
            (R.collaborator_pii, U, "P1", 201),
            (R.coding_tester, U, "SC1", 201),
            (R.reviewer, U, "D1", 403),            # above
            (R.reviewer, U, "D2", 403),            # outside
            (R.reviewer, PS, (TA, "AZS1"), 403),
            (R.reviewer, P, TA, 403),
        ])
        coder = self._post(DM_GRANTS, self._body(
            R.coder, U, "P1", cadre_id=str(self._cadre("MO").cadre_id)))
        self.assertEqual(coder.status_code, 201, coder.get_json())

    def test_project_dm_in_a_district_project_creates_dms_below_project_level_only(self):
        self._assert_codes("dm_ta", [
            (R.data_manager, P, TA, 403),
            (R.data_manager, PS, (TA, "AZS1"), 201),
            (R.data_manager, U, "D1", 201),
            (R.reviewer, P, TA, 201),
            (R.interviewer, U, "P1", 201),
            (R.reviewer, P, SP, 403),              # another project
        ])

    def test_in_charge_creates_dms_at_its_own_level_and_below(self):
        self._assert_codes("incharge_c1", [
            (R.data_manager, U, "C1", 201),
            (R.data_manager, U, "P1", 201),
            (R.reviewer, U, "SC1", 201),
            (R.data_manager, U, "D1", 403),
            (R.reviewer, U, "D2", 403),
        ])

    def test_project_pi_creates_dms_at_any_level_of_a_district_project(self):
        self._assert_codes("pi_ta", [
            (R.data_manager, P, TA, 201),
            (R.data_manager, PS, (TA, "AZS2"), 201),
            (R.data_manager, U, "SC1", 201),
            (R.data_manager, U, "F1", 403),        # another project's unit
        ])

    def test_only_admin_or_project_pi_create_site_pi_or_interview_supervisor(self):
        for actor in ("dm_ta", "dm_c1", "incharge_c1", "pi_ta", "admin"):
            with self.subTest(actor=actor):
                self._as(actor)
                for role in (R.site_pi, R.interview_supervisor, R.project_pi, R.admin):
                    response = self._post(DM_GRANTS, self._body(role, U, "P1"))
                    self.assertIn(response.status_code, (400, 403), response.get_json())
                    self.assertIsNone(self._held_by_grantee(role))
        # The admin panel: the project PI writes the In-charge, a data manager
        # cannot reach the route at all.
        self._as("dm_ta")
        self.assertEqual(self._post(ADMIN_GRANTS, self._body(R.site_pi, U, "C1")).status_code, 403)
        self._as("pi_ta")
        made = self._post(ADMIN_GRANTS, self._body(R.site_pi, U, "C1"))
        self.assertEqual(made.status_code, 201, made.get_json())

    def _held_by_grantee(self, role):
        return db.session.scalar(sa.select(VaUserAccessGrants.grant_id).where(
            VaUserAccessGrants.user_id == self.grantee.user_id, VaUserAccessGrants.role == role,
        ))

    # -- the site rule, unchanged ---------------------------------------------

    def test_site_project_dms_keep_todays_rule(self):
        self._assert_codes("dm_sp", [
            (R.coder, P, SP, 201),
            (R.data_manager, P, SP, 201),
            (R.coding_tester, PS, (SP, "AZS3"), 201),
            (R.reviewer, P, SP, 403),
            (R.interviewer, PS, (SP, "AZS1"), 403),
            (R.coder, P, TA, 403),
        ])
        self._assert_codes("dm_sp1", [
            (R.data_manager, PS, (SP, "AZS1"), 201),
            (R.coder, P, SP, 403),
            (R.coder, PS, (SP, "AZS3"), 403),
        ])

    # -- write-time checks after can_grant --------------------------------

    def test_cadre_and_mentor_checks_still_refuse_after_can_grant_allows(self):
        mentor = self.users["mentor"]
        self.assertTrue(can_grant(self.users["dm_c1"], GrantTarget(
            role=R.coder, scope_type=U, org_unit_id=self.units["P1"].org_unit_id)))
        self._as("dm_c1")
        no_cadre = self._post(DM_GRANTS, self._body(R.coder, U, "P1"))
        self.assertEqual(no_cadre.status_code, 400, no_cadre.get_json())
        self.assertIn("requires a cadre", no_cadre.get_json()["error"])

        self.assertTrue(can_grant(self.users["dm_ta"], GrantTarget(
            role=R.data_manager, scope_type=U, org_unit_id=self.units["P1"].org_unit_id),
            grantee_id=mentor.user_id))
        self._as("dm_ta")
        guarded = self._post(DM_GRANTS, self._body(R.data_manager, U, "P1", user=mentor))
        self.assertEqual(guarded.status_code, 400, guarded.get_json())
        self.assertIn("mentoring institute", guarded.get_json()["error"])
        # The same grant for someone outside the institute is written.
        self.assertEqual(self._post(DM_GRANTS, self._body(R.data_manager, U, "P1")).status_code, 201)

    def test_a_death_reporter_grant_needs_a_cadre_with_the_flag_and_only_at_unit_scope(self):
        self.assertIn(R.death_reporter, DM_TREE_ASSIGNABLE)
        self._as("dm_c1")
        none = self._post(DM_GRANTS, self._body(R.death_reporter, U, "SC1"))
        self.assertEqual(none.status_code, 400, none.get_json())
        self.assertIn("requires a cadre", none.get_json()["error"])
        cho = self._post(DM_GRANTS, self._body(R.death_reporter, U, "SC1", cadre_id=str(self._cadre("CHO").cadre_id)))
        self.assertEqual(cho.status_code, 400, cho.get_json())
        self.assertIn("may not report deaths", cho.get_json()["error"])
        self.assertIsNone(self._held_by_grantee(R.death_reporter))
        anm = self._post(DM_GRANTS, self._body(R.death_reporter, U, "SC1", cadre_id=str(self._cadre("ANM").cadre_id)))
        self.assertEqual(anm.status_code, 201, anm.get_json())
        self.assertIsNotNone(self._held_by_grantee(R.death_reporter))
        # Never at project scope, even for a project data manager.
        self._as("dm_ta")
        project = self._post(DM_GRANTS, self._body(R.death_reporter, P, TA))
        self.assertEqual(project.status_code, 400, project.get_json())
        self.assertIn("cannot use project scope", project.get_json()["error"])

    def test_a_refusal_never_discloses_institute_membership(self):
        mentor = self.users["mentor"]
        self._as("dm_c1")
        member = self._post(DM_GRANTS, self._body(R.data_manager, U, "C1", user=mentor))
        stranger = self._post(DM_GRANTS, self._body(R.data_manager, U, "C1"))
        self.assertEqual((member.status_code, stranger.status_code), (403, 403))
        self.assertEqual(member.get_json()["error"], stranger.get_json()["error"])

    # -- toggle ----------------------------------------------------------

    def test_toggle_follows_the_same_rule_on_the_stored_grant(self):
        inside = self._held("reviewer_c1", R.reviewer, U)
        outside = self._held("reviewer_ta", R.reviewer, P)
        self._as("dm_c1")
        self.assertEqual(self._toggle(DM_GRANTS, outside.grant_id).status_code, 403)
        off = self._toggle(DM_GRANTS, inside.grant_id)
        self.assertEqual((off.status_code, off.get_json()["status"]), (200, "deactive"))
        on = self._toggle(DM_GRANTS, inside.grant_id)
        self.assertEqual((on.status_code, on.get_json()["status"]), (200, "active"))

    def test_nobody_revokes_their_own_data_manager_grant(self):
        for key, scope in (("dm_c1", U), ("dm_ta", P), ("dm_sp1", PS)):
            with self.subTest(key=key):
                own = self._held(key, R.data_manager, scope)
                self.assertIsNotNone(own)
                self._as(key)
                response = self._toggle(DM_GRANTS, own.grant_id)
                self.assertEqual(response.status_code, 400)
                self.assertIn("own data_manager grant", response.get_json()["error"])
                db.session.refresh(own)
                self.assertEqual(own.grant_status, VaStatuses.active)

    # -- listing and search --------------------------------------------

    def test_the_grant_list_shows_exactly_what_can_grant_allows(self):
        places = [
            (P, TA), (PS, (TA, "AZS1")), (U, "D1"), (U, "C1"), (U, "P1"), (U, "SC1"),
            (U, "D2"), (U, "F1"), (P, SP), (PS, (SP, "AZS1")), (PS, (SP, "AZS3")),
        ]
        roles = [R.coder, R.reviewer, R.coding_tester, R.data_manager,
                 R.collaborator, R.collaborator_pii, R.interviewer]
        rows = [self._grant_row(self.grantee, role, scope, where)
                for role in roles for scope, where in places]
        rows += [self._grant_row(self.grantee, R.interview_supervisor, U, "C1"),
                 self._grant_row(self.grantee, R.site_pi, U, "P1"),
                 self._grant_row(self.grantee, R.project_pi, P, TA)]
        db.session.add_all(rows)
        db.session.flush()
        for actor in ("dm_c1", "incharge_c1", "dm_ta", "dm_ta_s1", "pi_ta", "dm_sp", "dm_sp1"):
            with self.subTest(actor=actor):
                user = self.users[actor]
                allowed = {
                    str(row.grant_id) for row in rows
                    if row.role in DM_PAGE_ROLES and can_grant(user, GrantTarget(
                        role=row.role, scope_type=row.scope_type, project_id=row.project_id,
                        project_site_id=row.project_site_id, org_unit_id=row.org_unit_id,
                    ), grantee_id=self.grantee.user_id)
                }
                self.assertTrue(allowed)
                self._as(actor)
                listed = {g["grant_id"] for g in self.client.get(DM_GRANTS).get_json()["grants"]
                          if g["user_id"] == str(self.grantee.user_id)}
                self.assertEqual(listed, allowed)
                detail = self.client.get(f"/data-management/api/users/{self.grantee.user_id}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual({g["grant_id"] for g in detail.get_json()["grants"]}, allowed)

    def test_a_unit_writer_finds_the_people_it_manages_and_no_one_else(self):
        inside = self.users["reviewer_c1"]
        outside = self.users["reviewer_ta"]
        for actor in ("dm_c1", "incharge_c1"):
            with self.subTest(actor=actor):
                self._as(actor)
                found = self.client.get(
                    "/data-management/api/users", query_string={"query": "authz.reviewer_"}
                ).get_json()["users"]
                emails = {u["email"] for u in found}
                self.assertIn(inside.email, emails)
                self.assertNotIn(outside.email, emails)
                for user in found:
                    self.assertNotIn("phone", user)
                detail = self.client.get(f"/data-management/api/users/{inside.user_id}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.get_json()["user"]["email"], inside.email)
                self.assertNotIn("phone", detail.get_json()["user"])
                self.assertEqual(
                    self.client.get(f"/data-management/api/users/{outside.user_id}").status_code, 404)

    def test_a_project_writer_keeps_the_full_user_search(self):
        self._as("pi_ta")
        found = self.client.get(
            "/data-management/api/users", query_string={"query": "authz.reviewer_sp1"}
        ).get_json()["users"]
        self.assertEqual([u["email"] for u in found], [self.users["reviewer_sp1"].email])

    # -- pickers ---------------------------------------------------------

    def test_scope_pickers_follow_the_writer_grants(self):
        def units(actor, project_id=TA):
            self._as(actor)
            response = self.client.get(
                "/data-management/api/organization", query_string={"project_id": project_id})
            return response.status_code, {u["unit_code"] for u in (response.get_json().get("units") or [])}

        self.assertEqual(units("dm_c1"), (200, {"C1", "P1", "SC1", "P2"}))
        self.assertEqual(units("incharge_c1"), (200, {"C1", "P1", "SC1", "P2"}))
        self.assertEqual(units("dm_ta"), (200, {"D1", "C1", "P1", "SC1", "P2", "D2"}))
        self.assertEqual(units("dm_ta_s1"), (200, set()))
        self.assertEqual(units("dm_c1", project_id=SP)[0], 403)

        self._as("incharge_c1")
        boot = self.client.get("/data-management/api/bootstrap").get_json()
        self.assertIn("data_manager", boot["allowed_roles"])
        self.assertIn("reviewer", boot["allowed_roles"])
        projects = self.client.get("/data-management/api/projects").get_json()["projects"]
        self.assertEqual([(p["project_id"], p["has_tree"]) for p in projects], [(TA, True)])

        self._as("dm_sp")
        boot = self.client.get("/data-management/api/bootstrap").get_json()
        self.assertEqual(boot["allowed_roles"], ["coder", "coding_tester", "data_manager"])

    # -- user creation with a unit grant ---------------------------------

    def test_a_unit_writer_creates_a_user_with_an_initial_unit_grant(self):
        self._as("dm_c1")
        payload = {
            "email": "authz.new.unit.user@test.local",
            "email_confirm": "authz.new.unit.user@test.local",
            "name": "New Unit User", "languages": ["english"],
            "initial_project_id": TA, "initial_role": "reviewer",
            "initial_scope_type": "org_unit",
            "initial_org_unit_id": str(self.units["P1"].org_unit_id),
        }
        with patch("app.services.user_account_service.send_invitation"):
            made = self._post("/data-management/api/users", payload)
            self.assertEqual(made.status_code, 201, made.get_json())
            payload.update(email="authz.new.unit.user2@test.local",
                           email_confirm="authz.new.unit.user2@test.local",
                           initial_org_unit_id=str(self.units["D1"].org_unit_id))
            refused = self._post("/data-management/api/users", payload)
            self.assertEqual(refused.status_code, 403, refused.get_json())

    # -- exact lookup by email or mobile (digitva-i0zb) ---------------------

    def _lookup(self, value):
        return self.client.get(LOOKUP, query_string={"value": value})

    def _found(self, value):
        response = self._lookup(value)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["users"]

    def _phone_users(self):
        """Three accounts holding one mobile number in different formats."""
        stored = ("+91 98765 43210", "09876543210", "9876543210")
        made = []
        for i, phone in enumerate(stored):
            user = self._get_or_make_user(f"authz.phone{i}@test.local", "AuthzTest123")
            user.phone = phone
            made.append(user)
        db.session.flush()
        return made

    def test_lookup_finds_an_outside_person_by_exact_email_case_insensitively(self):
        outside = self.users["reviewer_ta"]
        self._as("dm_c1")
        found = self._found("  AUTHZ.Reviewer_TA@test.LOCAL ")
        self.assertEqual([u["email"] for u in found], [outside.email])
        self.assertEqual(found[0]["user_id"], str(outside.user_id))
        # No partial match, no wildcard.
        self.assertEqual(self._found("authz.reviewer_t"), [])
        self.assertEqual(self._found("reviewer_ta@test.local"), [])
        self.assertEqual(self._found("authz.reviewer_%@test.local"), [])

    def test_lookup_matches_a_mobile_in_any_format_and_returns_every_holder(self):
        made = self._phone_users()
        self._as("dm_c1")
        expected = sorted(u.email for u in made)
        for typed in ("9876543210", "98765-43210", "+91 98765 43210", "09876543210",
                      "919876543210"):
            with self.subTest(typed=typed):
                self.assertEqual(sorted(u["email"] for u in self._found(typed)), expected)
        # A partial or padded number is not the full number.
        for typed in ("9876543", "876543210", "59876543210", "1919876543210"):
            with self.subTest(typed=typed):
                self.assertEqual(self._found(typed), [])

    def test_lookup_caps_mobile_matches(self):
        for i in range(7):
            user = self._get_or_make_user(f"authz.cap{i}@test.local", "AuthzTest123")
            user.phone = "9123456789"
        db.session.flush()
        self._as("dm_c1")
        self.assertEqual(len(self._found("9123456789")), 5)

    def test_lookup_returns_active_accounts_only(self):
        made = self._phone_users()
        self._as("dm_c1")
        self.assertIn(made[0].email, [u["email"] for u in self._found("9876543210")])
        self.assertEqual([u["email"] for u in self._found(made[0].email)], [made[0].email])
        made[0].user_status = VaStatuses.deactive
        db.session.flush()
        self.assertNotIn(made[0].email, [u["email"] for u in self._found("9876543210")])
        self.assertEqual(self._found(made[0].email), [])

    def test_lookup_shows_posts_with_cadre_and_no_contact_roles_or_grants(self):
        person = self._get_or_make_user("authz.posted@test.local", "AuthzTest123")
        person.phone = "9000000001"
        mo = self._cadre("MO")
        db.session.add_all([
            VaUserAccessGrants(user_id=person.user_id, role=R.interviewer, scope_type=U,
                               org_unit_id=self.units["D2"].org_unit_id, cadre_id=mo.cadre_id,
                               grant_status=VaStatuses.active),
            # Same post under a second role: still one post.
            VaUserAccessGrants(user_id=person.user_id, role=R.reviewer, scope_type=U,
                               org_unit_id=self.units["D2"].org_unit_id, cadre_id=mo.cadre_id,
                               grant_status=VaStatuses.active),
            VaUserAccessGrants(user_id=person.user_id, role=R.coder, scope_type=U,
                               org_unit_id=self.units["E1"].org_unit_id,
                               grant_status=VaStatuses.deactive),
            VaUserAccessGrants(user_id=person.user_id, role=R.coder, scope_type=P,
                               project_id=SP, grant_status=VaStatuses.active),
        ])
        db.session.flush()
        self._as("dm_c1")
        [row] = self._found("9000000001")
        self.assertEqual(row["email"], person.email)
        self.assertEqual(row["name"], person.name)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["posts"], [{
            "unit_code": "D2", "unit_name": "D2",
            "level_name": db.session.get(MasOrgLevel, self.units["D2"].org_level_id).level_name,
            "cadre_code": "MO", "cadre_name": mo.cadre_name,
        }])
        for key in ("phone", "roles", "role", "grants", "grant_id", "languages", "is_admin"):
            self.assertNotIn(key, row)
        self.assertNotIn("9000000001", str(row))
        # A project-scope grant is not a post.
        [outside] = self._found(self.users["reviewer_ta"].email)
        self.assertEqual(outside["posts"], [])

    def test_finding_someone_does_not_open_their_details_until_granted(self):
        outside = self.users["reviewer_ta"]
        detail = f"/data-management/api/users/{outside.user_id}"
        self._as("dm_c1")
        self.assertEqual([u["email"] for u in self._found(outside.email)], [outside.email])
        self.assertEqual(self.client.get(detail).status_code, 404)
        made = self._post(DM_GRANTS, self._body(R.reviewer, U, "C1", user=outside))
        self.assertEqual(made.status_code, 201, made.get_json())
        opened = self.client.get(detail)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.get_json()["user"]["email"], outside.email)

    def test_in_charge_and_wide_writers_may_look_up_too(self):
        outside = self.users["reviewer_sp1"]
        for actor in ("incharge_c1", "dm_ta", "admin"):
            with self.subTest(actor=actor):
                self._as(actor)
                self.assertEqual([u["email"] for u in self._found(outside.email)], [outside.email])
        self._as("coder_c1")
        self.assertEqual(self._lookup(outside.email).status_code, 403)

    def test_lookup_rejects_an_empty_value(self):
        self._as("dm_c1")
        self.assertEqual(self._lookup("   ").status_code, 400)

    def test_lookup_is_rate_limited(self):
        self._as("dm_c1")
        for _ in range(10):
            self.assertEqual(self._lookup("nobody@test.local").status_code, 200)
        limited = self._lookup("nobody@test.local")
        self.assertEqual(limited.status_code, 429)
        self.assertIn("error", limited.get_json())

    # -- invalidate ---------------------------------------------------------

    def test_every_grant_write_invalidates_the_grantees_memoised_grants(self):
        with patch("app.services.authz.invalidate") as spy:
            self._as("dm_c1")
            made = self._post(DM_GRANTS, self._body(R.reviewer, U, "P1"))
            self.assertEqual(made.status_code, 201)
            spy.assert_called_with(self.grantee.user_id)
            spy.reset_mock()
            self.assertEqual(self._toggle(DM_GRANTS, made.get_json()["grant"]["grant_id"]).status_code, 200)
            spy.assert_called_with(self.grantee.user_id)

            spy.reset_mock()
            self._as("pi_ta")
            made = self._post(ADMIN_GRANTS, self._body(R.reviewer, U, "SC1"))
            self.assertEqual(made.status_code, 201)
            spy.assert_called_with(self.grantee.user_id)
            spy.reset_mock()
            self.assertEqual(self._toggle(ADMIN_GRANTS, made.get_json()["grant"]["grant_id"]).status_code, 200)
            spy.assert_called_with(self.grantee.user_id)

    # -- admin panel project_pi branch -----------------------------------

    def test_admin_panel_project_pi_writes_inside_its_own_project_only(self):
        self._as("pi_ta")
        self.assertEqual(self._post(ADMIN_GRANTS, self._body(R.reviewer, U, "D2")).status_code, 201)
        outside = self._post(ADMIN_GRANTS, self._body(R.reviewer, P, SP))
        self.assertEqual(outside.status_code, 403)
        self.assertEqual(outside.get_json()["error"], "You do not have access to that project.")
        never = self._post(ADMIN_GRANTS, self._body(R.project_pi, P, TA))
        self.assertEqual(never.status_code, 403)
        other = self._held("reviewer_sp1", R.reviewer, PS)
        self.assertEqual(self._toggle(ADMIN_GRANTS, other.grant_id).status_code, 403)

    # -- import --------------------------------------------------------------

    def test_import_checks_every_row_with_can_grant(self):
        db.session.get(VaProjectMaster, TA).project_structure_mode = "organization"
        db.session.flush()
        rows = [{"_line_number": 2, "email": self.grantee.email, "name": "", "role": "data_manager",
                 "org_unit_code": "C1", "cadre_code": "", "language_codes": "", "phone": ""}]
        plan = user_import.prepare(TA, rows, actor=self.users["pi_ta"])
        self.assertEqual([item["action"] for item in plan], ["grant"])
        # A project PI of another project is refused row by row, even if a
        # caller forgot the route's project guard.
        with self.assertRaisesRegex(user_import.ProjectUserImportError, "Row 2: .*not permitted"):
            user_import.prepare(TA, rows, actor=self.users["pi_sp"])
        # The admin may still create accounts; a project PI may not.
        new = [{**rows[0], "email": "authz.import.new@test.local", "name": "New",
                "language_codes": "english"}]
        self.assertEqual(
            [i["action"] for i in user_import.prepare(TA, new, actor=self.users["admin"])],
            ["create_user"])
        with self.assertRaisesRegex(user_import.ProjectUserImportError, "account is unavailable"):
            user_import.prepare(TA, new, actor=self.users["pi_ta"])

    def test_import_refuses_a_death_reporter_row_without_the_cadre_flag_or_a_unit(self):
        db.session.get(VaProjectMaster, TA).project_structure_mode = "organization"
        db.session.flush()
        row = {"_line_number": 2, "email": self.grantee.email, "name": "", "role": "death_reporter",
               "org_unit_code": "SC1", "cadre_code": "ANM", "language_codes": "", "phone": ""}
        # Present first: the ANM, who may report deaths at a sub-centre, is accepted.
        plan = user_import.prepare(TA, [row], actor=self.users["pi_ta"])
        self.assertEqual([item["action"] for item in plan], ["grant"])
        with self.assertRaisesRegex(user_import.ProjectUserImportError, "needs a cadre permitted to report deaths"):
            user_import.prepare(TA, [{**row, "cadre_code": "CHO"}], actor=self.users["pi_ta"])
        with self.assertRaisesRegex(user_import.ProjectUserImportError, "needs a cadre permitted to report deaths"):
            user_import.prepare(TA, [{**row, "cadre_code": ""}], actor=self.users["pi_ta"])
        with self.assertRaisesRegex(user_import.ProjectUserImportError, "requires an organization unit"):
            user_import.prepare(TA, [{**row, "org_unit_code": "", "cadre_code": ""}], actor=self.users["pi_ta"])
