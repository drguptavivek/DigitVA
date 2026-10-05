"""Mentoring institutes, stage 1b: district data-manager reach, institute admin, review fixes.

Rules under test: docs/policy/organization-model.md, "Mentoring institutes"
(who gives mentor staff their grants; institute admin), the data-manager grant
routes in app/routes/data_management.py, the staff API in
app/routes/admin_mentor_institute.py, mentor_institute_service and its CLI.
"""
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.commands.mentor_institute import mentor_group
from app.models import (
    MasLanguages,
    MasMentorInstitute,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import mentor_institute_service as mentors
from app.services import project_user_import_service as user_import
from app.services.authz import resolve_grants
from tests.test_mentor_institute import REFUSED, MentorBase

DM_GRANTS = "/data-management/api/access-grants"
ADMIN_GRANTS = "/admin/api/access-grants"
STAFF = "/admin/api/mentor-institutes/{code}/staff"


class Stage1bBase(MentorBase):
    def setUp(self):
        super().setUp()
        limiter.reset()  # in-memory buckets outlive a test

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(
                MasLanguages(language_code="english", language_name="English", is_active=True)
            )
        db.session.commit()

    def _grant(self, user, role, scope, *, unit=None, project=None):
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=scope,
            org_unit_id=unit.org_unit_id if unit else None,
            project_id=project,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    def _dm_at(self, email, unit):
        user = self._get_or_make_user(email, "x")
        self._grant(user, VaAccessRoles.data_manager, VaAccessScopeTypes.org_unit, unit=unit)
        return user

    def _unit_body(self, user, role, unit, **extra):
        return {
            "user_id": str(user.user_id),
            "role": role,
            "scope_type": "org_unit",
            "org_unit_id": str(unit.org_unit_id),
            **extra,
        }

    def _dm_post(self, body):
        return self.client.post(DM_GRANTS, json=body, headers=self._csrf_headers())

    def _dm_toggle(self, grant_id):
        return self.client.post(f"{DM_GRANTS}/{grant_id}/toggle", headers=self._csrf_headers())

    def _two_institutes(self):
        """MC1 on D01 with member one; MC2 on D01 and D02 with member two."""
        d1, d2, chc, one = self._setup_one()
        mentors.create_institute("MC2", "Medical College Two")
        mentors.attach_district("MC2", self.P1, "D01")
        mentors.attach_district("MC2", self.P1, "D02")
        db.session.commit()
        two = self._member("MC2", "mentor.two@test.local")
        return d1, d2, chc, one, two


class DataManagerMentorGrantTests(Stage1bBase):
    def test_district_dm_grants_a_member_in_the_district_and_below(self):
        d1, _, chc, member = self._setup_one()
        dm = self._dm_at("dm.d01@test.local", d1)
        self._login(str(dm.user_id))

        at_district = self._dm_post(self._unit_body(member, "reviewer", d1))
        self.assertEqual(at_district.status_code, 201, at_district.get_json())
        cadre = self._cadre(self.P1, "SMO")
        at_chc = self._dm_post(
            self._unit_body(member, "coder", chc, cadre_id=str(cadre.cadre_id))
        )
        self.assertEqual(at_chc.status_code, 201, at_chc.get_json())
        self.assertEqual(at_chc.get_json()["grant"]["unit_code"], "C01")
        self.assertEqual(at_chc.get_json()["grant"]["cadre_code"], "SMO")
        # Posting the same grant again reactivates it (200), as the admin route does.
        self.assertEqual(
            self._dm_post(self._unit_body(member, "reviewer", d1)).status_code, 200
        )

    def test_district_dm_rule_for_members_and_non_members(self):
        """digitva-0wc stage 6, district rule (owner 2026-10-02): a district DM
        writes the six roles anywhere in its subtree for anyone, and DMs
        strictly below; the mentor guard then narrows a member's grants.
        Before stage 6 the non-member and interviewer cases were refused 403
        because the DM page wrote only mentor-role unit grants for members."""
        d1, d2, chc, one, two = self._two_institutes()
        dm = self._dm_at("dm.d01@test.local", d1)
        outsider = self._get_or_make_user("outsider@test.local", "x")
        self._login(str(dm.user_id))

        non_member = self._dm_post(self._unit_body(outsider, "reviewer", chc))
        self.assertEqual(non_member.status_code, 201, non_member.get_json())
        # Allowed by the rule, refused by the guard (400, after authorization).
        for label, body in {
            "dm role": self._unit_body(one, "data_manager", chc),
            "interviewer": self._unit_body(one, "interviewer", chc),
        }.items():
            with self.subTest(label):
                response = self._dm_post(body)
                self.assertEqual(response.status_code, 400, response.get_json())
        refused = {
            # two is a member of an institute attached to D02 but this DM does not manage D02
            "other district": self._unit_body(two, "reviewer", d2),
            "non-member other district": self._unit_body(outsider, "reviewer", d2),
            "project scope": {
                "user_id": str(one.user_id), "role": "reviewer",
                "scope_type": "project", "project_id": self.P1,
            },
        }
        for label, body in refused.items():
            with self.subTest(label):
                response = self._dm_post(body)
                self.assertEqual(response.status_code, 403, response.get_json())
        # The refusal never says whether the target is a member.
        messages = {
            self._dm_post(refused[k]).get_json()["error"]
            for k in ("other district", "non-member other district")
        }
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
                    VaUserAccessGrants.user_id.in_([one.user_id, two.user_id])
                )
            ),
            0,
        )

    def test_dm_of_another_district_is_refused(self):
        d1, d2, chc, member = self._setup_one()
        dm_other = self._dm_at("dm.d02@test.local", d2)
        self._login(str(dm_other.user_id))
        response = self._dm_post(self._unit_body(member, "reviewer", chc))
        self.assertEqual(response.status_code, 403)

    def test_a_dm_below_the_district_writes_member_grants_in_its_own_subtree_only(self):
        """Stage 6: a CHC DM writes the six roles in its own subtree, so a
        member's reviewer grant at the CHC (inside the attached district) is
        written; before stage 6 it needed a DM covering the district."""
        d1, _, chc, member = self._setup_one()
        dm_chc = self._dm_at("dm.c01@test.local", chc)
        self._login(str(dm_chc.user_id))
        response = self._dm_post(self._unit_body(member, "reviewer", chc))
        self.assertEqual(response.status_code, 201, response.get_json())
        above = self._dm_post(self._unit_body(member, "reviewer", d1))
        self.assertEqual(above.status_code, 403)

    def test_project_scope_dm_covers_every_district_and_the_guard_still_applies(self):
        d1, d2, _, member = self._setup_one()
        dm = self._get_or_make_user("dm.project@test.local", "x")
        self._grant(dm, VaAccessRoles.data_manager, VaAccessScopeTypes.project, project=self.P1)
        self._login(str(dm.user_id))
        # D02 is not attached to the member's institute: the guard answers 400 after authz.
        unattached = self._dm_post(self._unit_body(member, "reviewer", d2))
        self.assertEqual(unattached.status_code, 400)
        self.assertIn("attached", unattached.get_json()["error"])
        project_scope = self._dm_post({
            "user_id": str(member.user_id), "role": "coder",
            "scope_type": "project", "project_id": self.P1,
        })
        self.assertEqual(project_scope.status_code, 400)
        self.assertIn("unit-scope", project_scope.get_json()["error"])
        self.assertEqual(
            self._dm_post(self._unit_body(member, "reviewer", d1)).status_code, 201
        )

    def test_toggle_by_a_covering_dm_only_and_reactivation_reruns_the_guard(self):
        d1, d2, chc, member = self._setup_one()
        grant = self._grant(
            member, VaAccessRoles.reviewer, VaAccessScopeTypes.org_unit, unit=chc
        )
        stranger = self._dm_at("dm.d02@test.local", d2)
        self._login(str(stranger.user_id))
        self.assertEqual(self._dm_toggle(grant.grant_id).status_code, 403)

        dm = self._dm_at("dm.d01@test.local", d1)
        self._login(str(dm.user_id))
        off = self._dm_toggle(grant.grant_id)
        self.assertEqual((off.status_code, off.get_json()["status"]), (200, "deactive"))
        mentors.detach_district("MC1", self.P1, "D01")
        db.session.commit()
        self.assertEqual(self._dm_toggle(grant.grant_id).status_code, 400)

    def test_a_non_members_unit_grant_is_toggled_by_a_dm_above_it_only(self):
        """Stage 6: the district rule covers everyone's grants in the DM's
        subtree, not only members' (before stage 6 this was 403)."""
        d1, d2, chc, _ = self._setup_one()
        outsider = self._get_or_make_user("outsider@test.local", "x")
        grant = self._grant(
            outsider, VaAccessRoles.reviewer, VaAccessScopeTypes.org_unit, unit=chc
        )
        stranger = self._dm_at("dm.d02@test.local", d2)
        self._login(str(stranger.user_id))
        self.assertEqual(self._dm_toggle(grant.grant_id).status_code, 403)
        dm = self._dm_at("dm.d01@test.local", d1)
        self._login(str(dm.user_id))
        self.assertEqual(self._dm_toggle(grant.grant_id).status_code, 200)

    def _search(self, query=""):
        response = self.client.get("/data-management/api/users", query_string={"query": query})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["users"]

    def test_unit_dm_user_search_is_scoped_to_covered_districts_and_slim(self):
        d1, d2, _, one, two = self._two_institutes()  # MC1: D01; MC2: D01+D02
        mentors.create_institute("MC3", "Medical College Three")
        mentors.attach_district("MC3", self.P1, "D02")
        db.session.commit()
        three = self._member("MC3", "mentor.three@test.local")
        self._get_or_make_user("outsider@test.local", "x")
        dm = self._dm_at("dm.d01@test.local", d1)
        self._login(str(dm.user_id))

        users = self._search()
        self.assertEqual(
            {u["email"]: u["institutes"] for u in users},
            {one.email: ["MC1"], two.email: ["MC2"]},  # not three (D02 only), not outsider
        )
        for user in users:
            self.assertEqual(
                set(user), {"user_id", "name", "email", "status", "institutes", "job_title"}
            )
        self.assertEqual([u["email"] for u in self._search("mentor.two")], [two.email])

        # inactive membership and inactive institute drop out
        mentors.remove_member("MC1", one.email)
        mentors.set_institute_active("MC2", False)
        db.session.commit()
        self.assertEqual(self._search(), [])
        mentors.set_institute_active("MC2", True)
        db.session.commit()
        self.assertEqual({u["email"] for u in self._search()}, {two.email})
        self.assertNotIn(three.email, {u["email"] for u in self._search()})

    def test_unit_dm_search_follows_the_districts_the_dm_covers(self):
        d1, d2, _, one, two = self._two_institutes()
        dm2 = self._dm_at("dm.d02@test.local", d2)
        self._login(str(dm2.user_id))
        self.assertEqual({u["email"] for u in self._search()}, {two.email})

    def _dm_search(self, dm, query="", include_inactive=True):
        return mentors.dm_visible_mentor_staff(dm.user_id, query, include_inactive)

    def test_project_scope_dm_search_reaches_every_attached_district(self):
        d1, d2, _, one, two = self._two_institutes()
        mentors.create_institute("MC3", "Medical College Three")
        mentors.attach_district("MC3", self.P1, "D02")
        db.session.commit()
        three = self._member("MC3", "mentor.three@test.local")
        outsider = self._get_or_make_user("dm.proj@test.local", "x")
        self._grant(
            outsider, VaAccessRoles.data_manager, VaAccessScopeTypes.project, project=self.P1
        )
        rows, truncated = self._dm_search(outsider)
        self.assertEqual({u.email for u, _ in rows}, {one.email, two.email, three.email})
        self.assertFalse(truncated)

    def test_dm_search_include_inactive_and_status(self):
        d1, _, _, one = self._setup_one()
        dm = self._dm_at("dm.d01@test.local", d1)
        one.user_status = VaStatuses.deactive
        db.session.commit()
        self.assertEqual([u.email for u, _ in self._dm_search(dm, include_inactive=True)[0]], [one.email])
        self.assertEqual(self._dm_search(dm, include_inactive=False)[0], [])
        self._login(str(dm.user_id))
        listed = self.client.get(
            "/data-management/api/users", query_string={"include_inactive": "0"}
        ).get_json()
        self.assertEqual(listed["users"], [])

    def test_dm_search_is_truncated_visibly_past_the_limit(self):
        d1, _, _, one = self._setup_one()
        for n in range(25):
            self._member("MC1", f"extra{n:02d}@test.local")  # 26 members in all
        dm = self._dm_at("dm.d01@test.local", d1)
        self._login(str(dm.user_id))
        body = self.client.get("/data-management/api/users").get_json()
        self.assertEqual(len(body["users"]), 25)
        self.assertTrue(body["truncated"])
        narrowed = self.client.get(
            "/data-management/api/users", query_string={"query": "extra07"}
        ).get_json()
        self.assertEqual(len(narrowed["users"]), 1)
        self.assertFalse(narrowed["truncated"])
        # exactly the limit is not truncated
        rows, truncated = mentors.dm_visible_mentor_staff(dm.user_id, "", True, limit=26)
        self.assertEqual((len(rows), truncated), (26, False))

    def test_dm_search_treats_percent_and_underscore_literally(self):
        d1, _, _, _ = self._setup_one()
        plain = self._member("MC1", "ab@test.local")
        pct = self._member("MC1", "a%b@test.local")
        under = self._member("MC1", "a_b@test.local")
        slash = self._member("MC1", "a\\b@test.local")
        dm = self._dm_at("dm.d01@test.local", d1)
        emails = lambda q: {u.email for u, _ in self._dm_search(dm, q)[0]}  # noqa: E731
        self.assertEqual(emails("a%b"), {pct.email})
        self.assertEqual(emails("a_b"), {under.email})
        self.assertEqual(emails("a\\b"), {slash.email})
        self.assertIn(plain.email, emails(""))
        self.assertEqual(emails("%"), {pct.email})

    def test_dm_search_returns_staff_of_districts_at_or_below_the_dm(self):
        d1, d2, chc, one, two = self._two_institutes()  # one: D01; two: D01+D02
        mentors.create_institute("MC3", "Medical College Three")
        mentors.attach_district("MC3", self.P1, "D02")
        db.session.commit()
        three = self._member("MC3", "mentor.three@test.local")
        self._tree(self.P2)
        dm_d1 = self._dm_at("dm.d01@test.local", d1)
        dm_chc = self._dm_at("dm.chc@test.local", chc)  # below the district
        dm_d2 = self._dm_at("dm.d02@test.local", d2)
        # A DM at a district (or above it) covers the staff of institutes
        # attached to that district; one below it, at a CHC, covers none.
        for dm, expected in (
            (dm_d1, {one.email, two.email}),
            (dm_d2, {two.email, three.email}),
            (dm_chc, set()),
        ):
            found = {u.email for u, _ in self._dm_search(dm)[0]}
            self.assertEqual(found, expected, dm.email)

    def test_unit_only_dm_is_refused_project_and_site_scope(self):
        d1, _, _, member = self._setup_one()
        dm = self._dm_at("dm.d01@test.local", d1)
        site = db.session.scalar(
            sa.select(VaProjectSites).where(VaProjectSites.project_id == self.BASE_PROJECT_ID)
        )
        project_grant = VaUserAccessGrants(
            user_id=member.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project, project_id=self.P1,
            grant_status=VaStatuses.active,
        )
        site_grant = VaUserAccessGrants(
            user_id=member.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=site.project_site_id, grant_status=VaStatuses.active,
        )
        db.session.add_all([project_grant, site_grant])
        db.session.commit()
        self._login(str(dm.user_id))
        creates = {
            "project": {
                "user_id": str(member.user_id), "role": "coder",
                "scope_type": "project", "project_id": self.P1,
            },
            "site": {
                "user_id": str(member.user_id), "role": "coding_tester",
                "scope_type": "project_site", "project_site_id": str(site.project_site_id),
            },
        }
        for label, body in creates.items():
            with self.subTest(f"create {label}"):
                self.assertEqual(self._dm_post(body).status_code, 403)
        for label, grant in (("project", project_grant), ("site", site_grant)):
            with self.subTest(f"toggle {label}"):
                self.assertEqual(self._dm_toggle(grant.grant_id).status_code, 403)
                db.session.refresh(grant)
                self.assertEqual(grant.grant_status, VaStatuses.active)

    def test_admin_on_the_data_manager_interface_writes_its_roles_only(self):
        """Stage 6: the page writes unit grants, so an admin's unit grant goes
        through (the guard still applies); roles outside the page's list stay
        refused. Before stage 6 the page refused every unit grant to admins."""
        d1, d2, _, member = self._setup_one()
        self._login(str(self.base_admin_id))
        self.assertEqual(
            self._dm_post(self._unit_body(member, "reviewer", d1)).status_code, 201
        )
        self.assertEqual(
            self._dm_post(self._unit_body(member, "reviewer", d2)).status_code, 400
        )
        self.assertEqual(
            self._dm_post(self._unit_body(member, "site_pi", d1)).status_code, 403
        )


class ImportAndWarningTests(Stage1bBase):
    def test_import_refuses_a_member_row_outside_the_guard(self):
        d1, d2, chc, member = self._setup_one()
        db.session.get(VaProjectMaster, self.P1).project_structure_mode = "organization"
        db.session.commit()

        def row(role, unit_code):
            return {
                "_line_number": 2,
                "email": member.email, "name": "", "role": role, "org_unit_code": unit_code,
                "cadre_code": "", "language_codes": "", "phone": "",
            }

        for label, bad in (
            ("project scope", row("reviewer", "")),
            ("unattached district", row("reviewer", "D02")),
            ("non-mentor role", row("interviewer", "C01")),
        ):
            with self.subTest(label), self.assertRaises(user_import.ProjectUserImportError):
                user_import.prepare(self.P1, [bad], actor=self.base_admin_user)
        plan = user_import.prepare(self.P1, [row("reviewer", "C01")], actor=self.base_admin_user)
        self.assertEqual(len(plan), 1)

    def test_add_member_warning_counts_grants_outside_the_attached_subtrees(self):
        d1, d2, chc, _ = self._setup_one()
        user = self._get_or_make_user("holder@test.local", "x")
        org_unit = VaAccessScopeTypes.org_unit
        self._grant(user, VaAccessRoles.reviewer, org_unit, unit=chc)  # inside: fine
        self._grant(user, VaAccessRoles.reviewer, org_unit, unit=d2)  # mentor role, wrong district
        self._grant(user, VaAccessRoles.interviewer, org_unit, unit=chc)  # non-mentor role
        self._grant(user, VaAccessRoles.reviewer, VaAccessScopeTypes.project, project=self.P1)
        self.assertEqual(mentors.add_member("MC1", "holder@test.local"), 3)

    def test_project_pi_of_another_project_gets_403_not_a_guard_message(self):
        d1, _, chc, member = self._setup_one()
        self._login(str(self.base_project_pi_id))
        response = self.client.post(
            ADMIN_GRANTS,
            json=self._unit_body(member, "interviewer", chc),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403, response.get_json())
        self.assertNotIn("mentoring", response.get_json()["error"])

    def test_default_typical_roles_suggest_in_charge_for_the_in_charge_cadres(self):
        from app.services.organization_service import DEFAULT_TYPICAL_ROLES

        in_charge_cadres = {("district", "CS"), ("chc", "SMO"), ("phc", "MO")}
        for key in in_charge_cadres:
            self.assertEqual(DEFAULT_TYPICAL_ROLES[key][0], "site_pi")
        for key, roles in DEFAULT_TYPICAL_ROLES.items():
            self.assertNotIn("interview_supervisor", roles)
            if key not in in_charge_cadres:
                self.assertNotIn("site_pi", roles)


class InstituteAdminTests(Stage1bBase):
    def _admin_of(self, institute_code, email):
        user = self._member(institute_code, email)
        mentors.set_member_admin(institute_code, email, True)
        db.session.commit()
        return user

    def _new_staff_body(self, email):
        return {
            "email": email, "email_confirm": email, "name": "New Staff",
            "phone": "", "languages": ["english"],
        }

    def _create(self, code, email):
        return self.client.post(
            STAFF.format(code=code), json=self._new_staff_body(email),
            headers=self._csrf_headers(),
        )

    def test_admin_creates_staff_of_their_own_institute_and_removes_them(self):
        self._two_institutes()
        boss = self._admin_of("MC1", "boss.one@test.local")
        self._login(str(boss.user_id))
        with mock.patch("app.services.user_account_service.send_invitation") as invite:
            created = self._create("MC1", "new.staff@test.local")
        self.assertEqual(created.status_code, 201, created.get_json())
        invite.assert_called_once()
        new_id = created.get_json()["staff"]["user_id"]
        staff = self.client.get(STAFF.format(code="MC1")).get_json()["staff"]
        self.assertIn("new.staff@test.local", {s["email"] for s in staff})
        self.assertEqual(
            self._create("MC1", "new.staff@test.local").status_code, 400
        )  # email in use

        removed = self.client.post(
            f"{STAFF.format(code='MC1')}/{new_id}/remove", headers=self._csrf_headers()
        )
        self.assertEqual(removed.status_code, 200, removed.get_json())
        self.assertTrue(removed.get_json()["account_deactivated"])
        user = db.session.get(VaUsers, new_id)
        self.assertEqual(user.user_status, VaStatuses.deactive)

    def test_remove_keeps_the_account_of_someone_the_institute_did_not_hire(self):
        _, _, _, one, two = self._two_institutes()
        boss = self._admin_of("MC1", "boss.one@test.local")
        self._login(str(boss.user_id))
        response = self.client.post(
            f"{STAFF.format(code='MC1')}/{one.user_id}/remove", headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["account_deactivated"])
        self.assertEqual(db.session.get(VaUsers, one.user_id).user_status, VaStatuses.active)
        self.assertNotIn(one.user_id, mentors.member_user_ids([one.user_id]))

    def test_admin_cannot_touch_another_institute_or_remove_themselves(self):
        _, _, _, one, two = self._two_institutes()
        boss = self._admin_of("MC1", "boss.one@test.local")
        self._login(str(boss.user_id))
        listing = self.client.get("/admin/api/mentor-institutes").get_json()["institutes"]
        self.assertEqual([i["institute_code"] for i in listing], ["MC1"])
        self.assertEqual(self.client.get(STAFF.format(code="MC2")).status_code, 403)
        self.assertEqual(self._create("MC2", "intruder@test.local").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"{STAFF.format(code='MC2')}/{two.user_id}/remove", headers=self._csrf_headers()
            ).status_code,
            403,
        )
        # same refusal for a code that does not exist: no probing
        self.assertEqual(self.client.get(STAFF.format(code="NOPE")).status_code, 403)
        # MC2's person cannot be removed through MC1 either
        cross = self.client.post(
            f"{STAFF.format(code='MC1')}/{two.user_id}/remove", headers=self._csrf_headers()
        )
        self.assertEqual(cross.status_code, 400)
        self.assertEqual(mentors.member_user_ids([two.user_id]), {two.user_id})
        selfremove = self.client.post(
            f"{STAFF.format(code='MC1')}/{boss.user_id}/remove", headers=self._csrf_headers()
        )
        self.assertEqual(selfremove.status_code, 400)

    def _grants_of(self, user):
        rows = db.session.execute(
            sa.select(VaUserAccessGrants.role, MasOrgUnit.unit_code, VaUserAccessGrants.grant_status)
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(VaUserAccessGrants.user_id == user.user_id)
        )
        return {(role.value, code): status for role, code, status in rows}

    def _remove(self, code, user):
        return self.client.post(
            f"{STAFF.format(code=code)}/{user.user_id}/remove", headers=self._csrf_headers()
        )

    def test_remove_deactivates_in_institute_mentor_grants_only(self):
        d1, d2, chc, one, two = self._two_institutes()  # MC1: D01; MC2: D01+D02
        mentors.add_member("MC1", two.email)  # two is dual: MC1 and MC2
        db.session.commit()
        boss = self._admin_of("MC1", "boss.one@test.local")
        A, D = VaAccessRoles, VaAccessScopeTypes.org_unit
        self._grant(one, A.reviewer, D, unit=chc)
        self._grant(one, A.coder, D, unit=d1)
        self._grant(one, A.data_manager, D, unit=d1)  # not a mentor role
        self._grant(one, A.reviewer, D, unit=d2)  # outside MC1's districts
        self._grant(two, A.reviewer, D, unit=chc)  # still covered by MC2
        self._grant(two, A.coder, D, unit=d2)

        self._login(str(boss.user_id))
        with self.assertLogs("GRANT_AUDIT", level="INFO") as logs:
            removed = self._remove("MC1", one)
        self.assertEqual(removed.status_code, 200, removed.get_json())
        self.assertEqual(removed.get_json()["grants_deactivated"], 2)
        active, off = VaStatuses.active, VaStatuses.deactive
        self.assertEqual(
            self._grants_of(one),
            {("reviewer", "C01"): off, ("coder", "D01"): off,
             ("data_manager", "D01"): active, ("reviewer", "D02"): active},
        )
        self.assertNotIn(one.email, "\n".join(logs.output))

        again = self._remove("MC1", two)
        self.assertEqual(again.get_json()["grants_deactivated"], 0)
        self.assertEqual(
            self._grants_of(two), {("reviewer", "C01"): active, ("coder", "D02"): active}
        )

    def test_remove_leaves_other_projects_and_other_users_grants_alone(self):
        d1, _, chc, one = self._setup_one()
        other_d1, _, other_chc = self._tree(self.P2)  # same codes; MC1 not attached to P2
        three = self._member("MC1", "mentor.three@test.local")
        boss = self._admin_of("MC1", "boss.one@test.local")
        A, D = VaAccessRoles, VaAccessScopeTypes.org_unit
        self._grant(one, A.reviewer, D, unit=chc)
        self._grant(one, A.reviewer, D, unit=other_chc)  # other project, same subtree codes
        self._grant(three, A.reviewer, D, unit=chc)  # another user, same district
        self._login(str(boss.user_id))
        self.assertEqual(self._remove("MC1", one).get_json()["grants_deactivated"], 1)
        active, off = VaStatuses.active, VaStatuses.deactive
        rows = db.session.execute(
            sa.select(MasOrgUnit.project_id, VaUserAccessGrants.grant_status)
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(VaUserAccessGrants.user_id == one.user_id)
        ).all()
        self.assertEqual(set(rows), {(self.P1, off), (self.P2, active)})
        self.assertEqual(self._grants_of(three), {("reviewer", "C01"): active})

    def test_remove_deactivates_grants_under_an_inactive_attachment_of_this_institute(self):
        d1, _, chc, one = self._setup_one()
        boss = self._admin_of("MC1", "boss.one@test.local")
        self._grant(one, VaAccessRoles.coder, VaAccessScopeTypes.org_unit, unit=chc)
        mentors.detach_district("MC1", self.P1, "D01")
        db.session.commit()
        self._login(str(boss.user_id))
        self.assertEqual(self._remove("MC1", one).get_json()["grants_deactivated"], 1)
        self.assertEqual(self._grants_of(one), {("coder", "C01"): VaStatuses.deactive})

    def test_an_inactive_attachment_of_another_institute_does_not_protect_a_grant(self):
        d1, d2, chc, one, two = self._two_institutes()  # MC2 on D01 and D02
        mentors.add_member("MC1", two.email)
        mentors.detach_district("MC2", self.P1, "D01")  # MC2 no longer covers D01
        db.session.commit()
        boss = self._admin_of("MC1", "boss.one@test.local")
        self._grant(two, VaAccessRoles.reviewer, VaAccessScopeTypes.org_unit, unit=chc)
        self._login(str(boss.user_id))
        self.assertEqual(self._remove("MC1", two).get_json()["grants_deactivated"], 1)
        self.assertEqual(self._grants_of(two), {("reviewer", "C01"): VaStatuses.deactive})

    def test_institute_admin_gets_a_generic_duplicate_email_refusal(self):
        _, _, _, one, _ = self._two_institutes()
        boss = self._admin_of("MC1", "boss.one@test.local")
        self._login(str(boss.user_id))
        duplicate = self._create("MC1", one.email)
        fresh_fail = self.client.post(
            STAFF.format(code="MC1"), json={"email": "a@test.local"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(
            duplicate.get_json()["error"],
            "Could not create this account. Contact a platform administrator.",
        )
        self.assertNotIn("in use", duplicate.get_json()["error"].lower())
        self.assertIn("required", fresh_fail.get_json()["error"])  # other errors stay specific

        self._login(str(self.base_admin_id))
        for_admin = self._create("MC1", one.email)
        self.assertEqual(for_admin.status_code, 400)
        self.assertEqual(for_admin.get_json()["error"], "Email already in use.")

    def test_staff_creation_is_capped_per_institute_per_day(self):
        self._two_institutes()
        boss1 = self._admin_of("MC1", "boss.one@test.local")
        boss2 = self._admin_of("MC2", "boss.two@test.local")
        self._login(str(boss1.user_id))
        with mock.patch("app.services.user_account_service.send_invitation"):
            for n in range(20):
                self.assertEqual(
                    self._create("MC1", f"cap{n}@test.local").status_code, 201, n
                )
            self.assertEqual(self._create("MC1", "cap20@test.local").status_code, 429)
            self._login(str(boss2.user_id))  # another institute has its own bucket
            self.assertEqual(self._create("MC2", "other@test.local").status_code, 201)
            self._login(str(self.base_admin_id))  # platform admin is exempt
            self.assertEqual(self._create("MC1", "by.admin@test.local").status_code, 201)

    def test_platform_admin_cannot_create_staff_in_an_inactive_institute(self):
        self._setup_one()
        mentors.set_institute_active("MC1", False)
        db.session.commit()
        self._login(str(self.base_admin_id))
        refused = self._create("MC1", "late@test.local")
        self.assertEqual(refused.status_code, 400)
        self.assertIsNone(
            db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "late@test.local"))
        )

    def test_only_a_platform_admin_removes_an_institute_admin(self):
        self._setup_one()
        institute = db.session.scalar(sa.select(MasMentorInstitute))
        boss = self._admin_of("MC1", "boss.one@test.local")
        second = self._admin_of("MC1", "boss.two@test.local")
        with self.assertRaises(REFUSED):  # even with another admin remaining
            mentors.remove_staff(institute, boss.user_id, actor_user_id=second.user_id)
        self.assertEqual(mentors.administered_institutes(boss.user_id), [institute])
        # an institute admin removes non-admin staff
        plain = self._member("MC1", "plain@test.local")
        mentors.remove_staff(institute, plain.user_id, actor_user_id=boss.user_id)
        # a platform admin may remove an admin, even the last one
        mentors.remove_staff(
            institute, boss.user_id, actor_user_id=self.base_admin_id, actor_is_platform_admin=True
        )
        mentors.remove_staff(
            institute, second.user_id, actor_user_id=self.base_admin_id, actor_is_platform_admin=True
        )
        self.assertEqual(mentors.administered_institutes(boss.user_id), [])
        self.assertEqual(mentors.administered_institutes(second.user_id), [])

    def test_institute_admin_cannot_remove_an_admin_but_platform_admin_can(self):
        self._setup_one()
        boss = self._admin_of("MC1", "boss.one@test.local")
        second = self._admin_of("MC1", "boss.two@test.local")
        self._login(str(boss.user_id))
        refused = self._remove("MC1", second)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("platform administrator", refused.get_json()["error"])
        self.assertEqual(self._remove("MC1", boss).status_code, 400)  # self
        self.assertEqual(len(mentors.administered_institutes(second.user_id)), 1)
        self._login(str(self.base_admin_id))
        self.assertEqual(self._remove("MC1", second).status_code, 200)
        self.assertEqual(mentors.administered_institutes(second.user_id), [])

    def test_plain_staff_and_strangers_cannot_manage_staff(self):
        self._setup_one()
        plain = self._get_or_make_user("mentor.one@test.local", "x")
        stranger = self._get_or_make_user("stranger@test.local", "x")
        for user in (plain, stranger):
            self._login(str(user.user_id))
            self.assertEqual(self.client.get(STAFF.format(code="MC1")).status_code, 403)
            self.assertEqual(self._create("MC1", "x@test.local").status_code, 403)

    def test_institute_admin_gets_403_on_every_grant_route_and_no_other_role(self):
        d1, _, chc, one = self._setup_one()
        boss = self._admin_of("MC1", "boss.one@test.local")
        grant = self._grant(one, VaAccessRoles.reviewer, VaAccessScopeTypes.org_unit, unit=chc)
        self._login(str(boss.user_id))
        body = self._unit_body(one, "reviewer", d1)
        headers = self._csrf_headers()
        responses = {
            "admin create": self.client.post(ADMIN_GRANTS, json=body, headers=headers),
            "admin toggle": self.client.post(f"{ADMIN_GRANTS}/{grant.grant_id}/toggle", headers=headers),
            "admin list": self.client.get(ADMIN_GRANTS),
            "dm create": self.client.post(DM_GRANTS, json=body, headers=headers),
            "dm toggle": self.client.post(f"{DM_GRANTS}/{grant.grant_id}/toggle", headers=headers),
            "dm list": self.client.get(DM_GRANTS),
            "dm users": self.client.get("/data-management/api/users"),
            "users import": self.client.post(
                f"/admin/api/organization/{self.P1}/project-users/import", headers=headers
            ),
        }
        for label, response in responses.items():
            with self.subTest(label):
                self.assertEqual(response.status_code, 403)
        self.assertTrue(boss.is_mentor_institute_admin())
        self.assertFalse(boss.is_admin())
        self.assertFalse(boss.is_data_manager())
        self.assertFalse(any(resolve_grants(boss).of(
            (VaAccessRoles.data_manager,), scope_types=(VaAccessScopeTypes.org_unit,))))
        self.assertTrue(db.session.get(VaUserAccessGrants, grant.grant_id).grant_status
                        == VaStatuses.active)

    def test_platform_admin_manages_any_institutes_staff(self):
        self._two_institutes()
        self._login(str(self.base_admin_id))
        with mock.patch("app.services.user_account_service.send_invitation"):
            created = self._create("MC2", "by.admin@test.local")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client.get(STAFF.format(code="NOPE")).status_code, 404)
        listing = self.client.get("/admin/api/mentor-institutes").get_json()["institutes"]
        self.assertEqual({i["institute_code"] for i in listing}, {"MC1", "MC2"})

    def test_admin_flag_needs_active_staff_and_lapses_with_the_institute(self):
        self._setup_one()
        with self.assertRaises(REFUSED):
            mentors.set_member_admin("MC1", self._get_or_make_user("x@test.local", "x").email, True)
        boss = self._admin_of("MC1", "boss.one@test.local")
        self.assertTrue(boss.is_mentor_institute_admin())
        mentors.set_institute_active("MC1", False)
        db.session.commit()
        self.assertFalse(boss.is_mentor_institute_admin())


class MentorCliTests(Stage1bBase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()

    def _invoke(self, *args):
        return self.runner.invoke(mentor_group, list(args))

    def test_commands_record_the_actor_and_set_the_admin_flag(self):
        admin_email = "base.admin@test.local"
        self._tree(self.P1)
        created = self._invoke("create", "MC7", "Seven", "--actor", admin_email)
        self.assertEqual(created.exit_code, 0, created.output)
        institute = db.session.scalar(
            sa.select(MasMentorInstitute).where(MasMentorInstitute.institute_code == "MC7")
        )
        self.assertEqual(str(institute.created_by_user_id), str(self.base_admin_id))
        self.assertEqual(
            self._invoke("attach", "MC7", self.P1, "D01", "--actor", admin_email).exit_code, 0
        )
        self._get_or_make_user("seven@test.local", "x")
        self.assertEqual(
            self._invoke("add-user", "MC7", "seven@test.local", "--actor", admin_email).exit_code, 0
        )
        done = self._invoke("set-admin", "MC7", "seven@test.local", "--actor", admin_email)
        self.assertEqual(done.exit_code, 0, done.output)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "seven@test.local"))
        self.assertTrue(user.is_mentor_institute_admin())
        revoked = self._invoke(
            "set-admin", "MC7", "seven@test.local", "--revoke", "--actor", admin_email
        )
        self.assertEqual(revoked.exit_code, 0, revoked.output)
        self.assertFalse(user.is_mentor_institute_admin())

    def test_actor_must_be_an_active_global_admin(self):
        for actor in ("nobody@test.local", "base.coder@test.local"):
            with self.subTest(actor):
                result = self._invoke("create", "MC8", "Eight", "--actor", actor)
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("--actor must be", result.output)
        self.assertNotEqual(self._invoke("create", "MC8", "Eight").exit_code, 0)
