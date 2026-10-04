"""Routes behind the prefill map (digitva-vzk.1) and interviewer profile (vzk.3).

- Profile: GET returns year of birth and sex; PATCH /interviewer validates,
  needs the CSRF header, and clears with blanks.
- Admin: PUT sets them; the admin-only master list shows them, the user
  search a project PI can call does not.
- Register API accepts parents' names; the form page embeds an age-only
  case's age in PREFILL and loads the summary module that shows it.
"""
from datetime import UTC, date, datetime, timedelta

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


class InterviewerProfileRouteTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls._get_or_make_user("profile.yob@test.local", "ProfileYob123")
        cls.user_id = str(cls.user.user_id)
        db.session.commit()

    def test_profile_get_and_patch_interviewer_details(self):
        self._login(self.user_id)
        body = self.client.get("/api/v1/profile/").get_json()
        self.assertIn("year_of_birth", body)
        self.assertIn("sex", body)

        ok = self.client.patch(
            "/api/v1/profile/interviewer", json={"year_of_birth": "1985", "sex": "female"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(ok.status_code, 200, ok.get_json())
        user = db.session.get(VaUsers, self.user.user_id)
        self.assertEqual((user.year_of_birth, user.sex), (1985, "female"))

        bad = self.client.patch(
            "/api/v1/profile/interviewer", json={"year_of_birth": 1800, "sex": "female"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(db.session.get(VaUsers, self.user.user_id).year_of_birth, 1985)

        cleared = self.client.patch(
            "/api/v1/profile/interviewer", json={"year_of_birth": None, "sex": None},
            headers=self._csrf_headers(),
        )
        self.assertEqual(cleared.status_code, 200)
        user = db.session.get(VaUsers, self.user.user_id)
        self.assertEqual((user.year_of_birth, user.sex), (None, None))

    def test_profile_patch_requires_csrf(self):
        self._login(self.user_id)
        response = self.client.patch("/api/v1/profile/interviewer", json={"year_of_birth": 1985})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(db.session.get(VaUsers, self.user.user_id).year_of_birth)

    def test_admin_sets_them_and_only_the_admin_list_shows_them(self):
        self._login(str(self.base_admin_id))
        response = self.client.put(
            f"/admin/api/users/{self.user_id}", json={"year_of_birth": 1990, "sex": "male"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["user"]["year_of_birth"], 1990)
        bad = self.client.put(
            f"/admin/api/users/{self.user_id}", json={"sex": "x"}, headers=self._csrf_headers(),
        )
        self.assertEqual(bad.status_code, 400)

        master = self.client.get("/admin/api/users?master=1&query=profile.yob").get_json()["users"]
        self.assertEqual([(u["year_of_birth"], u["sex"]) for u in master], [(1990, "male")])

        self._login(str(self.base_project_pi_id))
        search = self.client.get("/admin/api/users?query=profile.yob").get_json()["users"]
        self.assertEqual(len(search), 1)
        self.assertNotIn("year_of_birth", search[0])
        self.assertNotIn("sex", search[0])


class IntakePrefillRouteTests(BaseTestCase):
    PROJECT_ID = "WPR01"
    SITE_ID = "WPR1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Prefill Routes",
            project_nickname="PrefillR", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Prefill Routes Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id="WPR01WPR101", project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_WPR01", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        cls.interviewer = cls._get_or_make_user("prefill.routes@test.local", "PrefillR12345")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID,
            notes="prefill routes grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        cls.interviewer_id = str(cls.interviewer.user_id)

    def test_register_api_keeps_parents_names_and_form_page_embeds_the_age(self):
        self._login(self.interviewer_id)
        response = self.client.post(
            "/api/v1/intake/deaths",
            json={
                "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
                "deceased_name": "Gopal Das", "deceased_sex": "male",
                "date_of_death": (date.today() - timedelta(days=4)).isoformat(),
                "age_years": 64, "father_name": "Hari Das", "mother_name": "Radha Devi",
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        death = response.get_json()["case"]
        self.assertEqual((death["prefill"]["answers"]["Id10061"], death["prefill"]["answers"]["Id10062"]), ("Hari Das", "Radha Devi"))

        draft = self.client.post(
            "/api/v1/intake/drafts",
            json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_id": death["death_id"]},
            headers=self._csrf_headers(),
        ).get_json()["draft"]
        page = self.client.get(f"/intake/form/{draft['draft_id']}").get_data(as_text=True)
        self.assertIn('"ageInYears": 64', page)
        self.assertIn('"Id10061": "Hari Das"', page)
        self.assertIn("js/intake/summary.js", page)
        self.assertIn("updateSummary(summaryFromPrefill(PREFILL));", page)
