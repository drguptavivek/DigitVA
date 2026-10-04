"""The worklist and case-flag endpoints of app/routes/intake.py (digitva-vzk.4).

The route layer only parses and serializes; scope and state rules are tested
in tests/services/test_case_worklist.py. Here: the JSON shape, parameter
validation (400 on junk), and CSRF on the flag endpoint.
"""
from datetime import UTC, date, datetime, timedelta

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


class IntakeWorklistApiTests(BaseTestCase):
    PROJECT_ID = "WLA01"
    SITE_ID = "WA11"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Worklist Api",
            project_nickname="WorklistApi", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Worklist Api Site", site_abbr=cls.SITE_ID,
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
            form_id="WLA01WA1101", project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_WORKLIST_API", odk_project_id="7", form_type="WHO VA 2022",
            form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        cls.interviewer = cls._get_or_make_user("wl.api@test.local", "WorklistApi123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID,
            notes="worklist api test grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        cls.interviewer_id = str(cls.interviewer.user_id)

    def _register(self, name="Bina Sahu"):
        response = self.client.post(
            "/api/v1/intake/deaths",
            json={
                "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": name,
                "deceased_sex": "female",
                "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["case"]

    def test_worklist_lists_team_cases_with_counts_and_no_contact_details(self):
        self._login(self.interviewer_id)
        death = self._register()

        response = self.client.get("/api/v1/intake/cases?mine=true&state=registered")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        rows = {row["death_id"]: row for row in body["cases"]}
        self.assertIn(death["death_id"], rows)
        row = rows[death["death_id"]]
        self.assertEqual((row["state"], row["source"], row["details_pending"]),
                         ("registered", "register", False))
        self.assertTrue(row["registered_by_me"])
        self.assertIn("deceased_name", row)
        self.assertNotIn("informant_phone", row)
        self.assertGreaterEqual(body["counts"]["registered"], 1)
        self.assertIn("next_cursor", body)

    def test_worklist_refuses_junk_parameters(self):
        self._login(self.interviewer_id)
        for query in ("mine=maybe", "state=va_submitted", "limit=ten", "cursor=zzz"):
            response = self.client.get(f"/api/v1/intake/cases?{query}")
            self.assertEqual(response.status_code, 400, query)
            self.assertIn("error", response.get_json())

    def test_a_direct_start_is_a_case_with_details_pending(self):
        self._login(self.interviewer_id)
        registered = self._register()
        response = self.client.post(
            "/api/v1/intake/drafts", json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        draft = response.get_json()["draft"]
        self.assertIsNotNone(draft["death_id"])

        rows = {r["death_id"]: r for r in self.client.get("/api/v1/intake/cases").get_json()["cases"]}
        self.assertIn(draft["death_id"], rows)
        self.assertTrue(rows[draft["death_id"]]["details_pending"])
        self.assertEqual(rows[draft["death_id"]]["my_draft_id"], draft["draft_id"])
        # The death register list stays the register: direct starts are not in it.
        listed = self.client.get(
            f"/api/v1/intake/deaths?project_id={self.PROJECT_ID}&site_id={self.SITE_ID}"
        ).get_json()["deaths"]
        self.assertIn(registered["death_id"], [d["death_id"] for d in listed])
        self.assertNotIn(draft["death_id"], [d["death_id"] for d in listed])

    def test_flagging_needs_csrf_and_records_the_flag(self):
        self._login(self.interviewer_id)
        kept = self._register()
        other = self._register(name="Bina S")
        url = f"/api/v1/intake/cases/{other['death_id']}/flags"
        body = {"kind": "duplicate", "duplicate_of": kept["death_id"], "reason": "same death"}

        self.assertEqual(self.client.post(url, json=body).status_code, 400)
        self.assertIsNone(db.session.get(VaDeathRegister, other["death_id"]).pending_flag)

        response = self.client.post(url, json=body, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["pending_flag"], "duplicate")
        self.assertEqual(response.get_json()["case"]["state"], "registered")
