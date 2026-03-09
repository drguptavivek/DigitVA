import uuid
import unittest
from datetime import datetime, timezone

from app import create_app, db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)


class AuthGrantResolutionTests(unittest.TestCase):
    project_id = "TST001"
    site_a = "TA01"
    site_b = "TB01"
    form_a = "TST001TA0101"
    form_b = "TST001TB0101"

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        cls._delete_fixture_rows()
        cls._create_fixture_rows()

    @classmethod
    def tearDownClass(cls):
        cls._delete_fixture_rows()
        db.session.remove()
        cls.ctx.pop()

    @classmethod
    def _create_fixture_rows(cls):
        now = datetime.now(timezone.utc)
        db.session.add(
            VaResearchProjects(
                project_id=cls.project_id,
                project_code=cls.project_id,
                project_name="Auth Grant Test Project",
                project_nickname="AuthGrantTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaProjectMaster(
                project_id=cls.project_id,
                project_code=cls.project_id,
                project_name="Auth Grant Test Project",
                project_nickname="AuthGrantTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        for site_id, site_name in [
            (cls.site_a, "Auth Grant Site A"),
            (cls.site_b, "Auth Grant Site B"),
        ]:
            db.session.add(
                VaSites(
                    site_id=site_id,
                    project_id=cls.project_id,
                    site_name=site_name,
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.add(
                VaSiteMaster(
                    site_id=site_id,
                    site_name=site_name,
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )

        db.session.flush()

        for site_id in [cls.site_a, cls.site_b]:
            db.session.add(
                VaProjectSites(
                    project_id=cls.project_id,
                    site_id=site_id,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                )
            )

        db.session.add(
            VaForms(
                form_id=cls.form_a,
                project_id=cls.project_id,
                site_id=cls.site_a,
                odk_form_id="AUTH_GRANT_FORM_A",
                odk_project_id="11",
                form_type="WHO VA 2022",
                form_smartvahiv="False",
                form_smartvamalaria="False",
                form_smartvahce="True",
                form_smartvafreetext="True",
                form_smartvacountry="IND",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.form_b,
                project_id=cls.project_id,
                site_id=cls.site_b,
                odk_form_id="AUTH_GRANT_FORM_B",
                odk_project_id="11",
                form_type="WHO VA 2022",
                form_smartvahiv="False",
                form_smartvamalaria="False",
                form_smartvahce="True",
                form_smartvafreetext="True",
                form_smartvacountry="IND",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    @classmethod
    def _delete_fixture_rows(cls):
        db.session.query(VaUserAccessGrants).filter(
            VaUserAccessGrants.notes.in_(
                [
                    "test coder grant",
                    "test reviewer grant",
                    "test site pi grant",
                ]
            )
        ).delete(synchronize_session=False)
        db.session.query(VaUsers).filter(
            VaUsers.email.in_(
                [
                    "test.auth.coder@example.com",
                    "test.auth.reviewer@example.com",
                    "test.auth.sitepi@example.com",
                    "test.auth.legacy@example.com",
                ]
            )
        ).delete(synchronize_session=False)
        db.session.query(VaForms).filter(
            VaForms.form_id.in_([cls.form_a, cls.form_b])
        ).delete(synchronize_session=False)
        db.session.query(VaProjectSites).filter(
            VaProjectSites.project_id == cls.project_id
        ).delete(synchronize_session=False)
        db.session.query(VaSiteMaster).filter(
            VaSiteMaster.site_id.in_([cls.site_a, cls.site_b])
        ).delete(synchronize_session=False)
        db.session.query(VaSites).filter(
            VaSites.site_id.in_([cls.site_a, cls.site_b])
        ).delete(synchronize_session=False)
        db.session.query(VaProjectMaster).filter(
            VaProjectMaster.project_id == cls.project_id
        ).delete(synchronize_session=False)
        db.session.query(VaResearchProjects).filter(
            VaResearchProjects.project_id == cls.project_id
        ).delete(synchronize_session=False)
        db.session.commit()

    def tearDown(self):
        db.session.query(VaUserAccessGrants).filter(
            VaUserAccessGrants.notes.in_(
                [
                    "test coder grant",
                    "test reviewer grant",
                    "test site pi grant",
                ]
            )
        ).delete(synchronize_session=False)
        db.session.query(VaUsers).filter(
            VaUsers.email.in_(
                [
                    "test.auth.coder@example.com",
                    "test.auth.reviewer@example.com",
                    "test.auth.sitepi@example.com",
                    "test.auth.legacy@example.com",
                ]
            )
        ).delete(synchronize_session=False)
        db.session.commit()

    def _create_user(self, email, permission=None):
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission=permission or {},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password("AuthGrantTest123")
        db.session.add(user)
        db.session.commit()
        return user

    def _project_site_id(self, site_id):
        return db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.project_id,
                VaProjectSites.site_id == site_id,
            )
        )

    def _grant(self, user, role, scope_type, notes, project_id=None, project_site_id=None):
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=scope_type,
            project_id=project_id,
            project_site_id=project_site_id,
            notes=notes,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    def test_coder_project_site_grant_resolves_only_matching_form(self):
        user = self._create_user("test.auth.coder@example.com")
        self._grant(
            user,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project_site,
            "test coder grant",
            project_site_id=self._project_site_id(self.site_a),
        )
        db.session.refresh(user)

        self.assertEqual(user.get_coder_va_forms(), {self.form_a})
        self.assertTrue(user.is_coder())
        self.assertTrue(user.has_va_form_access(self.form_a, "coder"))
        self.assertFalse(user.has_va_form_access(self.form_b, "coder"))

    def test_reviewer_project_grant_resolves_all_project_forms(self):
        user = self._create_user("test.auth.reviewer@example.com")
        self._grant(
            user,
            VaAccessRoles.reviewer,
            VaAccessScopeTypes.project,
            "test reviewer grant",
            project_id=self.project_id,
        )
        db.session.refresh(user)

        self.assertEqual(user.get_reviewer_va_forms(), {self.form_a, self.form_b})
        self.assertTrue(user.is_reviewer())
        self.assertTrue(user.has_va_form_access(self.form_a, "reviewer"))
        self.assertTrue(user.has_va_form_access(self.form_b, "reviewer"))
        self.assertTrue(user.has_va_form_access(self.form_a))
        self.assertTrue(user.has_va_form_access(self.form_b))

    def test_reviewer_without_grant_fails_closed(self):
        user = self._create_user("test.auth.reviewer@example.com")
        db.session.refresh(user)

        self.assertEqual(user.get_reviewer_va_forms(), set())
        self.assertFalse(user.is_reviewer())
        self.assertFalse(user.has_va_form_access(self.form_a, "reviewer"))
        self.assertFalse(user.has_va_form_access(self.form_b, "reviewer"))

    def test_site_pi_project_site_grant_resolves_site_and_form_scope(self):
        user = self._create_user("test.auth.sitepi@example.com")
        self._grant(
            user,
            VaAccessRoles.site_pi,
            VaAccessScopeTypes.project_site,
            "test site pi grant",
            project_site_id=self._project_site_id(self.site_b),
        )
        db.session.refresh(user)

        self.assertEqual(user.get_site_pi_sites(), {self.site_b})
        self.assertEqual(user.get_site_pi_va_forms(), {self.form_b})
        self.assertTrue(user.is_site_pi())
        self.assertTrue(user.has_va_form_access(self.form_b, "sitepi"))
        self.assertFalse(user.has_va_form_access(self.form_a, "sitepi"))
        self.assertTrue(user.has_va_form_access(self.form_b))
        self.assertFalse(user.has_va_form_access(self.form_a))

    def test_site_pi_without_grant_fails_closed(self):
        user = self._create_user("test.auth.sitepi@example.com")
        db.session.refresh(user)

        self.assertEqual(user.get_site_pi_sites(), set())
        self.assertEqual(user.get_site_pi_va_forms(), set())
        self.assertFalse(user.is_site_pi())
        self.assertFalse(user.has_va_form_access(self.form_a, "sitepi"))
        self.assertFalse(user.has_va_form_access(self.form_b, "sitepi"))

    def test_legacy_coder_permission_without_grant_fails_closed(self):
        user = self._create_user(
            "test.auth.legacy@example.com",
            permission={"coder": [self.form_a]},
        )
        db.session.refresh(user)

        self.assertEqual(user.get_coder_va_forms(), set())
        self.assertFalse(user.is_coder())
        self.assertFalse(user.has_va_form_access(self.form_a, "coder"))
        self.assertFalse(user.has_va_form_access(self.form_a))

    def test_generic_access_does_not_cross_role_or_scope_boundaries(self):
        user = self._create_user("test.auth.coder@example.com")
        self._grant(
            user,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project_site,
            "test coder grant",
            project_site_id=self._project_site_id(self.site_a),
        )
        db.session.refresh(user)

        self.assertTrue(user.has_va_form_access(self.form_a))
        self.assertFalse(user.has_va_form_access(self.form_b))

    def test_project_site_grant_ignores_inactive_project_site_mapping(self):
        user = self._create_user("test.auth.coder@example.com")
        project_site = db.session.get(VaProjectSites, self._project_site_id(self.site_a))
        project_site.project_site_status = VaStatuses.deactive
        db.session.commit()
        self._grant(
            user,
            VaAccessRoles.coder,
            VaAccessScopeTypes.project_site,
            "test coder grant",
            project_site_id=project_site.project_site_id,
        )
        db.session.refresh(user)

        self.assertEqual(user.get_coder_va_forms(), set())
        self.assertFalse(user.is_coder())
        self.assertFalse(user.has_va_form_access(self.form_a, "coder"))

        project_site.project_site_status = VaStatuses.active
        db.session.commit()

    def test_inactive_grant_does_not_authorize_access(self):
        user = self._create_user("test.auth.reviewer@example.com")
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.project_id,
            notes="test reviewer grant",
            grant_status=VaStatuses.deactive,
        )
        db.session.add(grant)
        db.session.commit()
        db.session.refresh(user)

        self.assertEqual(user.get_reviewer_va_forms(), set())
        self.assertFalse(user.is_reviewer())
        self.assertFalse(user.has_va_form_access(self.form_a, "reviewer"))

    def test_mixed_project_and_project_site_grants_union_access(self):
        user = self._create_user("test.auth.reviewer@example.com")
        self._grant(
            user,
            VaAccessRoles.reviewer,
            VaAccessScopeTypes.project_site,
            "test reviewer grant",
            project_site_id=self._project_site_id(self.site_a),
        )
        self._grant(
            user,
            VaAccessRoles.reviewer,
            VaAccessScopeTypes.project,
            "test reviewer grant",
            project_id=self.project_id,
        )
        db.session.refresh(user)

        self.assertEqual(user.get_reviewer_va_forms(), {self.form_a, self.form_b})
        self.assertTrue(user.has_va_form_access(self.form_a, "reviewer"))
        self.assertTrue(user.has_va_form_access(self.form_b, "reviewer"))


if __name__ == "__main__":
    unittest.main()
