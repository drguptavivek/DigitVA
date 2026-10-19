"""Platform mentor configuration stays admin-only and never creates grants."""
import sqlalchemy as sa

from app import db
from app.models import (
    MapMentorInstituteOrgUnit,
    MapMentorInstituteUser,
    MasMentorInstitute,
    VaProjectMaster,
    VaUserAccessGrants,
)
from app.services import mentor_institute_service as mentors
from tests.test_mentor_institute_stage1b import Stage1bBase

API = "/admin/api/mentor-institutes/platform"
PANEL = "/admin/panels/mentor-institutes"


class MentorInstitutePanelTests(Stage1bBase):
    def setUp(self):
        super().setUp()
        for project_id in (self.P1, self.P2):
            db.session.get(VaProjectMaster, project_id).project_structure_mode = "organization"
        db.session.commit()
        self._login(self.base_admin_id)

    def _post(self, action, **data):
        return self.client.post(API, json={"action": action, "code": "MC1", **data}, headers=self._csrf_headers())

    def test_panel_and_create_reversible_status(self):
        response = self.client.get(PANEL)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mentoring institutes", response.data)
        self.assertIn(b"one-time code", response.data)
        self.assertEqual(self._post("create", name="College One").status_code, 200)
        institute = db.session.scalar(sa.select(MasMentorInstitute).where(MasMentorInstitute.institute_code == "MC1"))
        self.assertTrue(institute.is_active)
        for active in (False, True):
            self.assertEqual(self._post("status", active=active).status_code, 200)
            self.assertEqual(institute.is_active, active)
        self.assertEqual(self._post("create", name="Duplicate").status_code, 400)

    def test_membership_admin_flag_and_district_attachment_never_grant_access(self):
        d1, _, chc = self._tree(self.P1)
        self.assertEqual(self._post("create", name="College One").status_code, 200)
        self.assertEqual(self._post("attach", project_id=self.P1, unit_code="C01").status_code, 400)
        self.assertEqual(self._post("attach", project_id=self.P1, unit_code="D01").status_code, 200)
        user = self._get_or_make_user("new.mentor@test.local", "x")
        self.assertEqual(self._post("link", user_id=str(user.user_id)).status_code, 200)
        institute = mentors._institute("MC1")
        member = db.session.get(MapMentorInstituteUser, (institute.institute_id, user.user_id))
        self.assertTrue(member.is_active)
        for flag in (True, False):
            self.assertEqual(self._post("set-admin", user_id=str(user.user_id), is_admin=flag).status_code, 200)
            self.assertEqual(member.is_admin, flag)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id)), 0)
        self.assertEqual(self._post("detach", project_id=self.P1, unit_code="D01").status_code, 200)
        link = db.session.get(MapMentorInstituteOrgUnit, (institute.institute_id, d1.org_unit_id))
        self.assertFalse(link.is_active)
        self.assertEqual(self._post("attach", project_id=self.P1, unit_code="D01").status_code, 200)
        self.assertTrue(link.is_active)
        chc.is_active = False
        d1.is_active = False
        db.session.commit()
        self.assertEqual(self._post("attach", project_id=self.P1, unit_code="D01").status_code, 400)

    def test_platform_routes_refuse_pi_and_institute_admin_but_keep_own_staff_api(self):
        self._setup_one()
        boss = self._member("MC1", "boss.panel@test.local")
        mentors.set_member_admin("MC1", boss.email, True)
        db.session.commit()
        for user_id in (str(boss.user_id), self.base_project_pi_id):
            self._login(user_id)
            self.assertEqual(self.client.get(PANEL).status_code, 403)
            self.assertEqual(self.client.get(API).status_code, 403)
            self.assertEqual(self._post("status", active=False).status_code, 403)
        self._login(str(boss.user_id))
        self.assertEqual(self.client.get("/admin/api/mentor-institutes/MC1/staff").status_code, 200)

    def test_schema_csrf_and_invalid_member_are_refused(self):
        self._post("create", name="College One")
        for body in ([], {"action": "status", "code": "MC1", "active": "false"}, {"action": "create", "code": []}):
            self.assertEqual(self.client.post(API, json=body, headers=self._csrf_headers()).status_code, 400)
        self.assertEqual(self._post("set-admin", email="absent@test.local", is_admin=True).status_code, 400)
        self.assertEqual(self._post("link", user_id="bad").status_code, 400)
        with self.app.app_context():
            old = self.app.config.get("WTF_CSRF_ENABLED")
            self.app.config["WTF_CSRF_ENABLED"] = True
            try:
                self.assertEqual(self.client.post(API, json={"action": "status", "code": "MC1", "active": False}).status_code, 400)
            finally:
                self.app.config["WTF_CSRF_ENABLED"] = old

    def test_bounded_institute_list_and_invalid_cursor(self):
        for n in range(51):
            mentors.create_institute(f"PAGE{n:02d}", f"Institute {n}")
        db.session.commit()
        data = self.client.get(API).get_json()
        self.assertEqual(len(data["institutes"]), 50)
        self.assertIsNotNone(data["next"])
        following = self.client.get(API, query_string={"after": data["next"]}).get_json()
        self.assertGreater(len(following["institutes"]), 0)
        self.assertFalse(set(i["institute_code"] for i in data["institutes"]) & set(i["institute_code"] for i in following["institutes"]))
        self.assertEqual(self._post("create", name="One").status_code, 200)
        self.assertEqual(self.client.get(API, query_string={"code": "MC1", "staff_after": "bad"}).status_code, 400)

    def test_new_mobile_staff_can_be_promoted_without_email_or_grants(self):
        self.assertEqual(self._post("create", name="College One").status_code, 200)
        response = self.client.post(
            "/admin/api/mentor-institutes/MC1/staff",
            json={"name": "Mobile Mentor", "phone": "9812345678", "languages": ["english"]},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(response.get_json()["sign_in_code"])
        staff = response.get_json()["staff"]
        self.assertIsNone(staff["email"])
        self.assertEqual(self._post("set-admin", user_id=staff["user_id"], is_admin=True).status_code, 200)
        details = self.client.get(API, query_string={"code": "MC1"})
        self.assertEqual(details.headers["Cache-Control"], "no-store")
        self.assertTrue(details.get_json()["staff"][0]["is_admin"])
        self.assertNotIn("sign_in_code", details.get_json())

    def test_inactive_institute_and_inactive_membership_reject_writes(self):
        self._setup_one()
        user = self._get_or_make_user("mentor.one@test.local", "x")
        institute = mentors._institute("MC1")
        link = db.session.get(MapMentorInstituteUser, (institute.institute_id, user.user_id))
        link.is_active = False
        db.session.commit()
        self.assertEqual(self._post("set-admin", user_id=str(user.user_id), is_admin=True).status_code, 400)
        self.assertEqual(self._post("status", active=False).status_code, 200)
        self.assertEqual(self._post("link", user_id=str(user.user_id)).status_code, 400)
        self.assertEqual(self._post("attach", project_id=self.P1, unit_code="D02").status_code, 400)

    def test_staff_validation_preserves_required_fields_and_rejects_bad_shapes(self):
        self.assertEqual(self._post("create", name="College One").status_code, 200)
        path = "/admin/api/mentor-institutes/MC1/staff"
        missing = self.client.post(path, json={"email": "fresh@test.local"}, headers=self._csrf_headers())
        self.assertEqual(missing.status_code, 400)
        self.assertIn("required", missing.get_json()["error"])
        for languages in (None, "english", [{}]):
            response = self.client.post(path, json={"languages": languages}, headers=self._csrf_headers())
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error"], "Select valid languages.")
