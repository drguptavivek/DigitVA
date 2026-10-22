"""The Users page admin tools (digitva-cgmc): account upload
(/api/v1/users/import/preview|apply) and the grant grid (GET /users/grid,
POST /users/<id>/grants).

Policy: docs/policy/account-onboarding-and-passwords.md ("Admin account
upload and invite on first grant"), docs/policy/access-control-model.md
("Users page admin tools"). Users, projects and units come from the authz
fixture (AZTA01 tree, AZSP01 site project).
"""
import base64
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthSecurityEvent,
    MapOrgLevelCadre,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import user_admin_tools_service as tools
from app.services.email_service import mail
from tests.authz.fixture import SP, TA, AuthzFixtureMixin
from tests.base import BaseTestCase

URL = "/api/v1/users"
R = VaAccessRoles


def _file(text: str, name="accounts.csv") -> dict:
    return {"filename": name, "content": base64.b64encode(text.encode()).decode()}


class UsersAdminToolsTests(AuthzFixtureMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.verify_sends = []
        patcher = patch("app.services.email_service._dispatch_email.delay",
                        side_effect=lambda **kw: self.verify_sends.append(kw["to"]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _as(self, key):
        self._login(str(self.users[key].user_id))

    def _post(self, path, body, csrf=True):
        return self.client.post(f"{URL}{path}", json=body, headers=self._csrf_headers() if csrf else {})

    # -- upload ------------------------------------------------------------

    def test_preview_classifies_new_existing_invalid_and_phone_clash(self):
        self._as("admin")
        self.users["interviewer_p1"].phone = "9876500001"
        self.users["interviewer_p1"].mobile_login = "9876500001"
        self.users["coder_p1"].phone = "98765 00003"
        db.session.commit()
        csv = (
            "name,email,phone\n"
            "New Person,new.person@example.org,+919876511111\n"
            "Coder,AUTHZ.CODER_TA@test.local,9876500001\n"
            "Bad,not-an-email,\n"
            "Short,short@example.org,12345\n"
            "Clash,clash@example.org,09876500003\n"
            "Again,new.person@example.org,\n"
        )
        res = self._post("/import/preview", _file(csv))
        self.assertEqual(res.status_code, 200, res.get_json())
        body = res.get_json()
        statuses = [(r["email"], r["status"]) for r in body["rows"]]
        self.assertEqual(statuses, [
            ("new.person@example.org", "new"), ("authz.coder_ta@test.local", "exists"),
            ("not-an-email", "invalid"), ("short@example.org", "invalid"),
            ("clash@example.org", "invalid"), ("new.person@example.org", "invalid"),
        ])
        self.assertTrue(body["rows"][1]["phone_clash"])
        self.assertEqual(body["rows"][0]["phone"], "******1111")
        self.assertIn("already used", body["rows"][4]["reason"])
        self.assertEqual(body["counts"], {"new": 1, "exists": 1, "invalid": 4})
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "new.person@example.org")))

    def test_apply_creates_only_new_rows_and_sends_nothing(self):
        self._as("admin")
        before = self.users["coder_ta"].name
        csv = "name,email,phone\nNew Person,new.person@example.org,9876511111\nRenamed,authz.coder_ta@test.local,\n"
        with mail.record_messages() as outbox:
            res = self._post("/import/apply", _file(csv))
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual(res.get_json()["created"], 1)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "new.person@example.org"))
        self.assertIsNotNone(user)
        self.assertEqual(user.user_status, VaStatuses.active)
        self.assertEqual(user.mobile_login, "9876511111")
        self.assertEqual(user.vacode_language, [])
        self.assertEqual(user.other["created_via"], "import")
        self.assertEqual(user.other["created_by_user_id"], str(self.users["admin"].user_id))
        self.assertFalse(user.check_password(""))
        self.assertEqual(db.session.get(VaUsers, self.users["coder_ta"].user_id).name, before)
        self.assertEqual(outbox, [])
        self.assertEqual(self.verify_sends, [])
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "account_upload_applied"))
        self.assertEqual(event.detail, {"created": 1, "rows": 2})
        self.assertEqual(event.actor_user_id, self.users["admin"].user_id)

    def test_upload_bounds_and_shape(self):
        self._as("admin")
        self.assertEqual(self._post("/import/preview", _file("email,name\nx@y.z,X\n")).status_code, 400)
        self.assertEqual(self._post("/import/preview", _file("name,email,phone\n")).status_code, 400)
        self.assertEqual(self._post("/import/preview", {"filename": "a.csv", "content": "%%%"}).status_code, 400)
        self.assertEqual(self._post("/import/preview", _file("name,email,phone\n", "a.txt")).status_code, 400)
        too_many = "name,email,phone\n" + "".join(f"P{i},p{i}@example.org,\n" for i in range(1001))
        res = self._post("/import/preview", _file(too_many))
        self.assertEqual(res.status_code, 400)
        self.assertIn("1000-row", res.get_json()["error"])
        big = {"filename": "a.csv", "content": "A" * (tools._MAX_ENCODED + 4)}
        self.assertEqual(self._post("/import/preview", big).status_code, 413)

    def test_upload_needs_admin_and_csrf(self):
        csv = _file("name,email,phone\nN,n@example.org,\n")
        for key in ("pi_ta", "dm_ta", "coder_ta"):
            self._as(key)
            self.assertEqual(self._post("/import/preview", csv).status_code, 403, key)
            self.assertEqual(self._post("/import/apply", csv).status_code, 403, key)
        self._as("admin")
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            self.assertEqual(self._post("/import/apply", csv, csrf=False).status_code, 400)
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "n@example.org")))

    # -- grid list ---------------------------------------------------------

    def _grid(self, **query):
        return self.client.get(f"{URL}/grid", query_string={"project": TA, **query})

    def _new_user(self, email, *, created=None, **kw):
        user = VaUsers(email=email, name=kw.pop("name", email), vacode_language=kw.pop("languages", ["English"]),
                       permission={}, landing_page="coder", pw_reset_t_and_c=False, email_verified=False,
                       user_status=VaStatuses.active, **kw)
        user.set_password(uuid.uuid4().hex)
        if created:
            user.user_created_at = created
        db.session.add(user)
        db.session.commit()
        return user

    def test_grid_lists_every_account_newest_first_with_project_grants(self):
        self._as("admin")
        fresh = self._new_user("fresh@example.org")
        body = self._grid(limit=100).get_json()
        self.assertEqual(body["users"][0]["email"], "fresh@example.org")
        self.assertEqual(body["users"][0]["grants"], [])
        self.assertEqual(body["options"]["mode"], "organization")
        self.assertTrue(any(u["key"] == f"unit:{self.units['P1'].org_unit_id}" for u in body["options"]["units"]))
        row = next(u for u in body["users"] if u["email"] == "authz.interviewer_p1@test.local")
        self.assertEqual([(g["role"], g["unit"]) for g in row["grants"]],
                         [("interviewer", f"unit:{self.units['P1'].org_unit_id}")])
        mixed = next(u for u in body["users"] if u["email"] == "authz.mixed@test.local")
        self.assertEqual([g["project_id"] for g in mixed["grants"]], [TA])
        self.assertTrue(body["users"][0]["created_at"].endswith("+00:00"))
        self.assertEqual(str(fresh.user_id), body["users"][0]["user_id"])

    def test_grid_filters_created_range_role_search_and_paging(self):
        self._as("admin")
        admin = self.users["admin"]
        admin.timezone = "Asia/Kolkata"
        # 2026-01-10 20:00 UTC is 2026-01-11 01:30 in India.
        late = self._new_user("late@example.org", created=datetime(2026, 1, 10, 20, 0))
        self._new_user("early@example.org", created=datetime(2026, 1, 10, 10, 0))
        emails = lambda **q: [u["email"] for u in self._grid(**q).get_json()["users"]]  # noqa: E731
        self.assertEqual(emails(**{"from": "2026-01-11", "to": "2026-01-11"}), ["late@example.org"])
        self.assertEqual(emails(**{"from": "2026-01-10", "to": "2026-01-10"}), ["early@example.org"])
        self.assertIn("late@example.org", emails(q="LATE@"))
        self.assertNotIn("early@example.org", emails(q="late"))
        self.assertEqual(emails(role="interviewer"), ["authz.interviewer_p1@test.local"])
        self.assertEqual(emails(role="coder", project=SP), sorted(emails(role="coder", project=SP)))
        page1 = self._grid(limit=2).get_json()
        page2 = self._grid(limit=2, offset=2).get_json()
        self.assertEqual(len(page1["users"]), 2)
        self.assertNotIn("options", page2)
        self.assertFalse({u["user_id"] for u in page1["users"]} & {u["user_id"] for u in page2["users"]})
        self.assertGreater(page1["total"], 2)
        self.assertEqual(self._grid(limit=101).status_code, 400)
        self.assertEqual(self._grid(**{"from": "11/01/2026"}).status_code, 400)
        self.assertEqual(self.client.get(f"{URL}/grid").status_code, 400)
        self.assertEqual(self._grid(project="NOPE01").status_code, 404)
        self.assertIsNotNone(late)

    def test_grid_site_project_offers_project_sites(self):
        self._as("admin")
        body = self._grid(project=SP).get_json()
        self.assertEqual(body["options"]["mode"], "sites")
        keys = {u["key"] for u in body["options"]["units"]}
        self.assertIn("site:AZS1", keys)
        self.assertNotIn("site:AZS4", keys)  # inactive pair

    def test_grid_is_admin_only(self):
        for key in ("pi_ta", "dm_ta", "dm_c1", "coder_ta"):
            self._as(key)
            self.assertEqual(self._grid().status_code, 403, key)
            res = self._post(f"/{self.users['coder_ta'].user_id}/grants",
                             {"project_id": TA, "unit": "project", "roles": []})
            self.assertEqual(res.status_code, 403, key)

    # -- grid save ---------------------------------------------------------

    def _save(self, user, **body):
        return self._post(f"/{user.user_id}/grants", {"project_id": TA, **body})

    def _active(self, user, project_unit=None):
        rows = db.session.scalars(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id)).all()
        return {(g.role.value, g.scope_type.value, str(g.org_unit_id or g.project_site_id or g.project_id))
                for g in rows if g.grant_status == VaStatuses.active}

    def test_save_adds_and_soft_revokes_at_one_unit(self):
        self._as("admin")
        user = self.users["interviewer_p1"]
        p1 = str(self.units["P1"].org_unit_id)
        res = self._save(user, unit=f"unit:{p1}", roles=["reviewer"])
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self._active(user), {("reviewer", "org_unit", p1)})
        revoked = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.role == R.interviewer))
        self.assertEqual(revoked.grant_status, VaStatuses.deactive)  # kept, not deleted
        self.assertEqual(res.get_json()["changes"], 2)
        # Re-adding reactivates the same row.
        self._save(user, unit=f"unit:{p1}", roles=["reviewer", "interviewer"])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.role == R.interviewer)), 1)

    def test_another_unit_is_edited_without_touching_the_first(self):
        self._as("admin")
        user = self.users["interviewer_p1"]
        p1, p2 = str(self.units["P1"].org_unit_id), str(self.units["P2"].org_unit_id)
        res = self._save(user, unit=f"unit:{p2}", roles=["interviewer"])
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self._active(user), {("interviewer", "org_unit", p1), ("interviewer", "org_unit", p2)})
        self.assertEqual({g["unit"] for g in res.get_json()["user"]["grants"]}, {f"unit:{p1}", f"unit:{p2}"})

    def test_save_profile_and_status(self):
        self._as("admin")
        user = self._new_user("profile@example.org")
        res = self._save(user, unit="project", roles=[], name=" New Name ", phone="+91 98765 22222", active=False)
        self.assertEqual(res.status_code, 200, res.get_json())
        db.session.refresh(user)
        self.assertEqual((user.name, user.mobile_login, user.user_status), ("New Name", "9876522222",
                                                                            VaStatuses.deactive))
        self.assertEqual(self._save(user, unit="project", roles=[], phone="12345").status_code, 400)
        other = self._new_user("taken@example.org")
        res = self._save(other, unit="project", roles=[], phone="9876522222")
        self.assertEqual(res.status_code, 400)
        admin = self.users["admin"]
        self.assertEqual(self._save(admin, unit="project", roles=[], active=False).status_code, 400)

    def test_another_admins_account_is_not_edited_here(self):
        other = self._new_user("second.admin@example.org", name="Second Admin")
        db.session.add(VaUserAccessGrants(user_id=other.user_id, role=VaAccessRoles.admin,
                                          scope_type=VaAccessScopeTypes.global_scope, grant_status=VaStatuses.active))
        db.session.commit()
        self._as("admin")
        # Present first: an unchanged profile save goes through.
        self.assertEqual(self._save(other, unit="project", roles=[], name="Second Admin", active=True).status_code, 200)
        for body in ({"active": False}, {"name": "Renamed"}, {"phone": "9876533333"}):
            res = self._save(other, unit="project", roles=[], **body)
            self.assertEqual((res.status_code, res.get_json()["code"]), (403, "admin_account"), body)
        db.session.refresh(other)
        self.assertEqual((other.name, other.user_status), ("Second Admin", VaStatuses.active))

    def test_grid_name_refuses_formula_characters(self):
        self._as("admin")
        user = self._new_user("formula@example.org")
        self.assertEqual(self._save(user, unit="project", roles=[], name="Fine Name").status_code, 200)
        self.assertEqual(self._save(user, unit="project", roles=[], name="=HYPERLINK(1)").status_code, 400)

    def test_refused_combinations_use_the_shared_validator_and_write_nothing(self):
        self._as("admin")
        user = self._new_user("refused@example.org")
        p1 = str(self.units["P1"].org_unit_id)
        # death_reporter cannot use project scope; coder at a unit needs a cadre.
        res = self._save(user, unit="project", roles=["death_reporter", "reviewer"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("death_reporter: This role cannot use project scope.", res.get_json()["error"])
        res = self._save(user, unit=f"unit:{p1}", roles=["coder"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("requires a cadre", res.get_json()["error"])
        self.assertEqual(self._active(user), set())
        nolang = self._new_user("nolang@example.org", languages=[])
        res = self._save(nolang, unit="project", roles=["coder", "reviewer", "interviewer"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("coder: set the account's coding languages", res.get_json()["error"])
        self.assertIn("reviewer: set the account's coding languages", res.get_json()["error"])
        self.assertNotIn("interviewer:", res.get_json()["error"])
        self.assertEqual(self._save(nolang, unit="project", roles=["interviewer"]).status_code, 200)
        self.assertEqual(self._save(user, unit="project", roles=["admin"]).status_code, 400)
        self.assertEqual(self._save(user, unit=f"unit:{self.units['G1'].org_unit_id}", roles=[]).status_code, 400)
        self.assertEqual(self._post(f"/{user.user_id}/grants",
                                    {"project_id": SP, "unit": "site:AZS4", "roles": []}).status_code, 400)

    def test_coder_at_unit_with_a_permitted_cadre(self):
        self._as("admin")
        user = self._new_user("cadre@example.org")
        p1 = self.units["P1"]
        cadre_id = db.session.scalar(sa.select(MapOrgLevelCadre.cadre_id).where(
            MapOrgLevelCadre.org_level_id == p1.org_level_id, MapOrgLevelCadre.can_code_va_form.is_(True),
            MapOrgLevelCadre.is_active.is_(True)))
        self.assertIsNotNone(cadre_id)
        res = self._save(user, unit=f"unit:{p1.org_unit_id}", roles=["coder"], cadre_id=str(cadre_id))
        self.assertEqual(res.status_code, 200, res.get_json())
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id))
        self.assertEqual(grant.cadre_id, cadre_id)

    def test_site_project_grant_at_a_project_site(self):
        self._as("admin")
        user = self._new_user("site@example.org")
        res = self._post(f"/{user.user_id}/grants", {"project_id": SP, "unit": "site:AZS1", "roles": ["coder"]})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()["user"]["grants"][0]["unit"], "site:AZS1")

    def test_first_grant_invites_once_and_enrols_collectors_only(self):
        self._as("admin")
        p1 = str(self.units["P1"].org_unit_id)
        collector = self._new_user("collector@example.org")
        with patch.dict(self.app.config, {"MAIL_SERVER": "smtp.test.invalid", "MAIL_SUPPRESS_SEND": True}), \
                mail.record_messages() as outbox:
            res = self._save(collector, unit=f"unit:{p1}", roles=["interviewer"])
            self.assertEqual(res.status_code, 200, res.get_json())
            self.assertTrue(res.get_json()["invited"])
            self.assertEqual(res.get_json()["enrolment_email"], "sent")
            self.assertEqual(self.verify_sends, ["collector@example.org"])
            self.assertEqual([m.recipients for m in outbox], [["collector@example.org"]])
            db.session.refresh(collector)
            self.assertIn(tools.INVITE_MARKER, collector.other)
            # Revoke everything, grant again: never a second invitation.
            self._save(collector, unit=f"unit:{p1}", roles=[])
            res = self._save(collector, unit=f"unit:{p1}", roles=["interviewer"])
            self.assertFalse(res.get_json()["invited"])
            self.assertEqual(self.verify_sends, ["collector@example.org"])
            self.assertEqual(len(outbox), 1)

            coder = self._new_user("reviewer.only@example.org")
            res = self._save(coder, unit="project", roles=["reviewer"])
            self.assertTrue(res.get_json()["invited"])
            self.assertIsNone(res.get_json()["enrolment_email"])
            self.assertEqual(len(outbox), 1)
            # An account that already signed in, or already had a grant, is not invited.
            seen = self._new_user("seen@example.org", last_signed_in_at=datetime.now(UTC) - timedelta(days=1))
            self.assertFalse(self._save(seen, unit="project", roles=["reviewer"]).get_json()["invited"])
            self.assertFalse(self._save(self.users["coder_ta"], unit="project",
                                        roles=["reviewer"]).get_json()["invited"])
        self.assertEqual(self.verify_sends, ["collector@example.org", "reviewer.only@example.org"])

    def test_mail_failure_is_a_warning(self):
        self._as("admin")
        user = self._new_user("nomail@example.org")
        with patch.dict(self.app.config, {"MAIL_SERVER": ""}):
            res = self._save(user, unit=f"unit:{self.units['P1'].org_unit_id}", roles=["interviewer"])
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertTrue(res.get_json()["warnings"])
        self.assertFalse(res.get_json()["invited"])
        self.assertEqual(self._active(user), {("interviewer", "org_unit", str(self.units["P1"].org_unit_id))})

    def test_save_needs_csrf(self):
        self._as("admin")
        user = self._new_user("csrf@example.org")
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            res = self._post(f"/{user.user_id}/grants", {"project_id": TA, "unit": "project", "roles": ["reviewer"]},
                             csrf=False)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._active(user), set())
