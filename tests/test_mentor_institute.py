"""Mentoring institutes: the grant guard, the service, and site_pi at unit scope.

Rules under test: app/services/mentor_institute_service.py and
org_grant_service.validate_org_unit_grant. Policy:
docs/policy/organization-model.md, "Mentoring institutes".
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import mentor_institute_service as mentors
from app.services import org_grant_service as og
from app.services import organization_service as org
from tests.base import BaseTestCase

REFUSED = org.OrganizationError


class MentorBase(BaseTestCase):
    """Fixtures only; no tests here."""

    P1 = "MNT001"
    P2 = "MNT002"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.P1, cls.P2):
            if db.session.get(VaProjectMaster, project_id) is None:
                db.session.add(
                    VaProjectMaster(
                        project_id=project_id,
                        project_code=project_id,
                        project_name=f"Mentor {project_id}",
                        project_nickname=project_id,
                        project_status=VaStatuses.active,
                        project_registered_at=now,
                        project_updated_at=now,
                    )
                )
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _tree(self, project_id):
        """Districts D01 (> CHC C01) and D02 in *project_id*."""
        org.seed_default_organization(project_id)
        lv = {level.level_code: level for level in org.list_levels(project_id)}
        d1 = org.create_unit(
            project_id, org_level_id=lv["district"].org_level_id, unit_code="D01", unit_name="D1"
        )
        d2 = org.create_unit(
            project_id, org_level_id=lv["district"].org_level_id, unit_code="D02", unit_name="D2"
        )
        chc = org.create_unit(
            project_id,
            org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=d1.org_unit_id,
            unit_code="C01",
            unit_name="CHC",
        )
        db.session.commit()
        return d1, d2, chc

    def _cadre(self, project_id, code):
        return next(c for c in org.list_cadres(project_id) if c.cadre_code == code)

    def _member(self, institute_code, email):
        user = self._get_or_make_user(email, "MentorPass123")
        mentors.add_member(institute_code, email)
        db.session.commit()
        return user

    def _validate(self, user, role, unit, cadre_code=None):
        cadre = self._cadre(unit.project_id, cadre_code) if cadre_code else None
        return og.validate_org_unit_grant(
            role=role,
            org_unit_id=unit.org_unit_id,
            cadre_id=cadre.cadre_id if cadre else None,
            user_id=user.user_id,
        )

    def _setup_one(self):
        d1, d2, chc = self._tree(self.P1)
        mentors.create_institute("MC1", "Medical College One")
        mentors.attach_district("MC1", self.P1, "D01")
        db.session.commit()
        return d1, d2, chc, self._member("MC1", "mentor.one@test.local")


class MentorInstituteTests(MentorBase):
    # -- guard: refusals ---------------------------------------------------

    def test_member_refused_at_unattached_district(self):
        _, d2, _, user = self._setup_one()
        with self.assertRaises(REFUSED) as ctx:
            self._validate(user, VaAccessRoles.collaborator_pii, d2)
        self.assertIn("attached", str(ctx.exception))

    def test_member_refused_in_another_project_with_same_codes(self):
        self._setup_one()
        other_d1, _, _ = self._tree(self.P2)
        user = self._get_or_make_user("mentor.one@test.local", "x")
        with self.assertRaises(REFUSED):
            self._validate(user, VaAccessRoles.collaborator_pii, other_d1)

    def test_member_refused_interviewer_data_manager_and_site_pi(self):
        d1, _, chc, user = self._setup_one()
        for role in (
            VaAccessRoles.interviewer,
            VaAccessRoles.data_manager,
            VaAccessRoles.interview_supervisor,
            VaAccessRoles.collaborator,
        ):
            with self.subTest(role=role):
                with self.assertRaises(REFUSED) as ctx:
                    self._validate(user, role, chc)
                self.assertIn("may hold only", str(ctx.exception))
        with self.assertRaises(REFUSED):
            self._validate(user, VaAccessRoles.site_pi, d1)

    def test_member_refused_project_and_other_non_unit_scopes(self):
        _, _, _, user = self._setup_one()
        with self.assertRaises(REFUSED) as ctx:
            mentors.check_mentor_grant(user.user_id, VaAccessRoles.coder, None)
        self.assertIn("unit-scope", str(ctx.exception))

    # -- guard: accepted ---------------------------------------------------

    def test_member_accepted_for_mentor_roles_in_attached_subtree(self):
        d1, _, chc, user = self._setup_one()
        for unit, cadre in ((d1, "MO"), (chc, "SMO")):
            unit_row, _ = self._validate(user, VaAccessRoles.coder, unit, cadre)
            self.assertEqual(unit_row.org_unit_id, unit.org_unit_id)
        for role in (
            VaAccessRoles.reviewer,
            VaAccessRoles.coding_tester,
            VaAccessRoles.collaborator_pii,
        ):
            for unit in (d1, chc):
                with self.subTest(role=role, unit=unit.unit_code):
                    self._validate(user, role, unit)

    def test_non_member_is_unaffected(self):
        d1, d2, chc, _ = self._setup_one()
        other = self._get_or_make_user("not.a.mentor@test.local", "x")
        self._validate(other, VaAccessRoles.data_manager, d2)
        self._validate(other, VaAccessRoles.interviewer, chc)
        mentors.check_mentor_grant(other.user_id, VaAccessRoles.data_manager, None)

    def test_one_institute_on_districts_in_two_projects(self):
        d1, _, _, user = self._setup_one()
        other_d1, _, _ = self._tree(self.P2)
        with self.assertRaises(REFUSED):
            self._validate(user, VaAccessRoles.reviewer, other_d1)
        mentors.attach_district("MC1", self.P2, "D01")
        db.session.commit()
        self._validate(user, VaAccessRoles.reviewer, other_d1)
        self._validate(user, VaAccessRoles.reviewer, d1)

    def test_one_district_with_two_institutes(self):
        d1, d2, chc, user_one = self._setup_one()
        mentors.create_institute("MC2", "Medical College Two")
        mentors.attach_district("MC2", self.P1, "D01")
        mentors.attach_district("MC2", self.P1, "D02")
        db.session.commit()
        user_two = self._member("MC2", "mentor.two@test.local")

        self._validate(user_two, VaAccessRoles.reviewer, chc)
        self._validate(user_two, VaAccessRoles.reviewer, d2)
        with self.assertRaises(REFUSED):
            self._validate(user_one, VaAccessRoles.reviewer, d2)
        listed = {(i.institute_code, u.email) for i, u in mentors.mentors_for_unit(chc.org_unit_id)}
        self.assertEqual(
            listed, {("MC1", "mentor.one@test.local"), ("MC2", "mentor.two@test.local")}
        )

    # -- management --------------------------------------------------------

    def test_detach_remove_and_deactivate_lift_the_restriction(self):
        d1, d2, _, user = self._setup_one()
        mentors.detach_district("MC1", self.P1, "D01")
        db.session.commit()
        with self.assertRaises(REFUSED):
            self._validate(user, VaAccessRoles.reviewer, d1)
        self.assertEqual(mentors.mentors_for_unit(d1.org_unit_id), [])
        mentors.attach_district("MC1", self.P1, "D01")
        mentors.set_institute_active("MC1", False)
        db.session.commit()
        self._validate(user, VaAccessRoles.data_manager, d2)  # no longer a member
        mentors.set_institute_active("MC1", True)
        mentors.remove_member("MC1", "mentor.one@test.local")
        db.session.commit()
        self._validate(user, VaAccessRoles.data_manager, d2)

    def test_attach_refuses_non_district_units_and_unknown_codes(self):
        self._setup_one()
        with self.assertRaises(REFUSED) as ctx:
            mentors.attach_district("MC1", self.P1, "C01")
        self.assertIn("district-level", str(ctx.exception))
        with self.assertRaises(REFUSED):
            mentors.attach_district("NOPE", self.P1, "D01")
        with self.assertRaises(REFUSED):
            mentors.attach_district("MC1", self.P1, "ZZ99")
        with self.assertRaises(REFUSED):
            mentors.create_institute("MC1", "duplicate")

    def test_add_member_reports_existing_grants_the_guard_would_refuse(self):
        self._setup_one()
        user = self._get_or_make_user("holder@test.local", "x")
        db.session.add(
            VaUserAccessGrants(
                user_id=user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.P1,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self.assertEqual(mentors.add_member("MC1", "holder@test.local"), 1)

    # -- site_pi -----------------------------------------------------------

    def test_site_pi_refused_at_unit_scope_but_allowed_at_project_site(self):
        d1, _, _ = self._tree(self.P1)
        non_member = self._get_or_make_user("sitepi@test.local", "x")
        with self.assertRaises(REFUSED) as ctx:
            self._validate(non_member, VaAccessRoles.site_pi, d1)
        self.assertIn("project-site role", str(ctx.exception))

        now = datetime.now(UTC)
        if db.session.get(VaSiteMaster, "MN01") is None:
            db.session.add(
                VaSiteMaster(
                    site_id="MN01", site_name="Mentor Site", site_abbr="MN01",
                    site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
                )
            )
            db.session.commit()
        db.session.add(
            VaProjectSites(
                project_id=self.P2, site_id="MN01", project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            )
        )
        db.session.commit()
        ps_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.P2, VaProjectSites.site_id == "MN01"
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=non_member.user_id, role=VaAccessRoles.site_pi,
                scope_type=VaAccessScopeTypes.project_site, project_site_id=ps_id,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()  # the CHECK still allows site_pi at project_site

    def test_database_refuses_a_site_pi_unit_grant(self):
        d1, _, _ = self._tree(self.P1)
        user = self._get_or_make_user("sitepi.db@test.local", "x")
        db.session.add(
            VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.site_pi,
                scope_type=VaAccessScopeTypes.org_unit, org_unit_id=d1.org_unit_id,
                grant_status=VaStatuses.active,
            )
        )
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()


class MentorGrantApiTests(MentorBase):
    """The admin grant API applies the guard on every scope."""

    def _post(self, body):
        return self.client.post("/admin/api/access-grants", json=body, headers=self._csrf_headers())

    def test_api_refuses_project_scope_but_accepts_unit_scope_for_a_member(self):
        d1, _, chc, user = self._setup_one()
        self._login(str(self.base_admin_id))
        refused = self._post(
            {"user_id": str(user.user_id), "role": "reviewer", "scope_type": "project", "project_id": self.P1}
        )
        self.assertEqual(refused.status_code, 400, refused.get_json())
        accepted = self._post(
            {"user_id": str(user.user_id), "role": "reviewer", "scope_type": "org_unit",
             "org_unit_id": str(chc.org_unit_id)}
        )
        self.assertEqual(accepted.status_code, 201, accepted.get_json())
        grant_id = accepted.get_json()["grant"]["grant_id"]

        # Reactivation re-runs the guard: detach, deactivate, then re-toggle.
        self.client.post(f"/admin/api/access-grants/{grant_id}/toggle", headers=self._csrf_headers())
        mentors.detach_district("MC1", self.P1, "D01")
        db.session.commit()
        again = self.client.post(
            f"/admin/api/access-grants/{grant_id}/toggle", headers=self._csrf_headers()
        )
        self.assertEqual(again.status_code, 400, again.get_json())
