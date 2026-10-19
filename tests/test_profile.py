import uuid

from app import db
from app.models.va_users import VaUsers
from tests.base import BaseTestCase


class ProfileTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        sfx = uuid.uuid4().hex[:8]
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=f"test.profile.{sfx}@example.com",
            email=f"test.profile.{sfx}@example.com",
            vacode_language=["English"],
            vacode_formcount=0,
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status="active",
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        self.user_id = str(user.user_id)
        self._login(self.user_id)

    def test_timezone_update(self):
        headers = self._csrf_headers()
        resp = self.client.patch(
            "/api/v1/profile/timezone",
            json={"timezone": "America/New_York"},
            headers=headers,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["timezone"], "America/New_York")

    def test_profile_nudge_reports_the_currently_missing_optional_fields(self):
        user = db.session.get(VaUsers, uuid.UUID(self.user_id))
        user.job_title = "  "
        user.year_of_birth = None
        user.sex = None
        db.session.flush()
        with self.client.session_transaction() as sess:
            sess["profile_nudge"] = True

        response = self.client.get("/api/v1/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["profile_nudge"], True)
        self.assertEqual(
            response.get_json()["missing_profile_fields"],
            ["job_title", "year_of_birth", "sex"],
        )

    def test_profile_nudge_is_suppressed_when_all_optional_fields_are_complete(self):
        user = db.session.get(VaUsers, uuid.UUID(self.user_id))
        user.job_title = "Community health worker"
        user.year_of_birth = 1985
        user.sex = "undetermined"
        db.session.flush()
        with self.client.session_transaction() as sess:
            sess["profile_nudge"] = True

        response = self.client.get("/api/v1/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["profile_nudge"], False)
        self.assertEqual(response.get_json()["missing_profile_fields"], [])

    def test_profile_nudge_can_be_dismissed_for_the_session(self):
        with self.client.session_transaction() as sess:
            sess["profile_nudge"] = True

        response = self.client.post(
            "/api/v1/profile/nudge/dismiss", headers=self._csrf_headers()
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"profile_nudge": False})
        with self.client.session_transaction() as sess:
            self.assertNotIn("profile_nudge", sess)

    def test_profile_nudge_banner_names_missing_fields_and_links_to_profile(self):
        with self.client.session_transaction() as sess:
            sess["profile_nudge"] = True

        response = self.client.get("/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"profile-nudge-banner", response.data)
        self.assertIn(b"job title, year of birth, sex", response.data)
        self.assertIn(b'href="/profile/"', response.data)

    def test_force_password_change_is_terms_only(self):
        user = db.session.get(VaUsers, uuid.UUID(self.user_id))
        user.pw_reset_t_and_c = False
        db.session.commit()

        resp = self.client.get("/profile/force-password-change")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Terms & Conditions", resp.data)
        self.assertNotIn(b"New Password", resp.data)

        resp = self.client.post(
            "/profile/force-password-change",
            data={"accept_terms": "y"},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        user = db.session.get(VaUsers, uuid.UUID(self.user_id))
        db.session.refresh(user)
        self.assertTrue(user.pw_reset_t_and_c)
