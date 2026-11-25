"""Roster user panel (digitva-eyp3).

Contract: the page GET /admin/project-roster/<id>/people/<user_id> (same
gate, 404 off the roster) fetches the JSON API under /admin/api/projects/<id>/users-grid/<user_id>, GET is the
panel (profile, grants in the caller's managed projects, phones, activity,
``may_edit_account``); PATCH .../profile, POST .../password-reset and POST
.../remove change the person. All pass ``_guard(project_id, roster=True)``;
a person not on the roster is 404. Account edits follow
``mobile_sign_in_service.may_edit_account``; remove is all or nothing.
Policy: docs/policy/dm-user-grant-management.md, "Roster User Panel".
"""
import uuid
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MapProjectMember,
    MapUserNotification,
    MasLanguages,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.auth_factors import AuthSecurityEvent
from app.services import mobile_sign_in_service as mobile
from app.services import notification_service as ns
from app.services import organization_service as org
from tests.base import BaseTestCase

R = VaAccessRoles
P = VaAccessScopeTypes.project


class RosterUserPanelTests(BaseTestCase):
    A = "RUPA01"
    B = "RUPB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.A, cls.B):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Panel {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
            ))
        if db.session.get(MasLanguages, "English") is None:
            db.session.add(MasLanguages(language_code="English", language_name="English", is_active=True))
        db.session.flush()
        cls.pi_a = cls._staff("pi.a", R.project_pi, cls.A)
        cls.dm_a = cls._staff("dm.a", R.data_manager, cls.A)
        db.session.commit()

    @classmethod
    def _staff(cls, name, role, project_id):
        user = cls._make_user(f"rup.{name}@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=P, project_id=project_id,
            grant_status=VaStatuses.active,
        ))
        return user

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _person(self, *, members=(), grants=(), email=None, verified=False, mobile_login=True):
        number = f"9{uuid.uuid4().int % 10**9:09d}"
        user = VaUsers(
            user_id=uuid.uuid4(), name="Panel Person", email=email,
            mobile_login=number if mobile_login else None, phone=number if mobile_login else None,
            vacode_language=["English"], permission={}, landing_page="coder",
            pw_reset_t_and_c=False, email_verified=verified, user_status=VaStatuses.active,
        )
        user.set_password("Unused123!x")
        db.session.add(user)
        db.session.flush()
        for project_id in members:
            db.session.add(MapProjectMember(project_id=project_id, user_id=user.user_id,
                                            added_by_user_id=self.pi_a.user_id))
        for role, project_id in grants:
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=P, project_id=project_id,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()
        return user

    def _url(self, user_id, suffix="", project_id=None):
        return f"/admin/api/projects/{project_id or self.A}/users-grid/{user_id}{suffix}"

    def _patch(self, user_id, body, headers=None):
        return self.client.patch(self._url(user_id, "/profile"), json=body,
                                 headers=self._csrf_headers() if headers is None else headers)

    def _post(self, user_id, suffix, headers=None):
        return self.client.post(self._url(user_id, suffix),
                                headers=self._csrf_headers() if headers is None else headers)

    def _grants(self, user):
        return {(g.role, g.project_id, g.grant_status) for g in db.session.scalars(
            sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id))}

    def _members(self, user):
        return set(db.session.scalars(sa.select(MapProjectMember.project_id).where(
            MapProjectMember.user_id == user.user_id)))

    def _events(self, user, event_type):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id, AuthSecurityEvent.event_type == event_type)).all()

    def _worker(self, user, project_id):
        org.seed_default_organization(project_id)
        level = next(lv for lv in org.list_levels(project_id) if lv.level_code == "district")
        cadre = next(c for c in org.list_cadres(project_id) if c.cadre_code == "MO")
        org.upsert_level_cadre(project_id, org_level_id=level.org_level_id, cadre_id=cadre.cadre_id,
                               allowed_roles=["site_pi", "collaborator", "collaborator_pii", "coder", "coding_tester", "reviewer", "data_manager", "interviewer"], default_roles=["coder"])
        unit = org.create_unit(project_id, org_level_id=level.org_level_id,
                               unit_code=f"{project_id}W{uuid.uuid4().hex[:3].upper()}", unit_name="District")
        worker = org.create_worker(project_id, org_unit_id=unit.org_unit_id, cadre_id=cadre.cadre_id,
                                   worker_name="Panel Person", user=user)
        db.session.commit()
        return worker

    # -- who may open the panel -------------------------------------------

    def test_panel_opens_for_a_roster_person(self):
        person = self._person(members=[self.A], grants=[(R.coder, self.A), (R.coder, self.B)])
        self._login(str(self.dm_a.user_id))
        response = self.client.get(self._url(person.user_id))
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["user"]["user_id"], str(person.user_id))
        # Grants in other projects are neither listed nor counted.
        self.assertEqual({(g["role"], g["project_id"]) for g in body["grants"]}, {("coder", self.A)})
        self.assertEqual(body["phones"], [])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self._login(self.base_admin_id)
        admin_body = self.client.get(self._url(person.user_id)).get_json()
        self.assertEqual({g["project_id"] for g in admin_body["grants"]}, {self.A, self.B})

    def test_another_projects_person_is_404_and_another_projects_url_403(self):
        b_person = self._person(members=[self.B])
        a_person = self._person(members=[self.A])
        self._login(str(self.dm_a.user_id))
        self.assertEqual(self.client.get(self._url(a_person.user_id)).status_code, 200)
        self.assertEqual(self.client.get(self._url(b_person.user_id)).status_code, 404)
        self.assertEqual(self.client.get(self._url(b_person.user_id, project_id=self.B)).status_code, 403)

    def test_a_non_roster_person_is_404_for_admins_too(self):
        stranger = self._person()
        self._login(self.base_admin_id)
        self.assertIsNotNone(db.session.get(VaUsers, stranger.user_id))
        for call in (
            lambda: self.client.get(self._url(stranger.user_id)),
            lambda: self._patch(stranger.user_id, {"name": "New Name"}),
            lambda: self._post(stranger.user_id, "/password-reset"),
            lambda: self._post(stranger.user_id, "/remove"),
        ):
            self.assertEqual(call().status_code, 404)
        self.assertEqual(self.client.get(self._url(uuid.uuid4())).status_code, 404)

    def test_person_page_renders_for_admin_and_dm_and_gates_the_rest(self):
        person = self._person(members=[self.A])
        stranger = self._person()
        page = f"/admin/project-roster/{self.A}/people/{person.user_id}"
        for login in (self.base_admin_id, str(self.dm_a.user_id)):
            self._login(login)
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Back to roster", response.get_data(as_text=True))
            self.assertIn("Panel Person", response.get_data(as_text=True))
        self.assertEqual(
            self.client.get(f"/admin/project-roster/{self.A}/people/{stranger.user_id}").status_code, 404)
        self.assertEqual(
            self.client.get(f"/admin/project-roster/{self.B}/people/{person.user_id}").status_code, 403)

    # -- account edits --------------------------------------------------------

    def test_profile_edit_writes_one_event_naming_fields_without_values(self):
        person = self._person(members=[self.A], grants=[(R.coder, self.A)])
        self._login(str(self.dm_a.user_id))
        self.assertTrue(self.client.get(self._url(person.user_id)).get_json()["may_edit_account"])
        response = self._patch(person.user_id, {"name": "Renamed Person", "age": 40, "sex": "female",
                                                "languages": ["English"]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["changed"], ["name", "sex", "year_of_birth"])
        db.session.refresh(person)
        self.assertEqual(person.name, "Renamed Person")
        self.assertEqual(person.year_of_birth, datetime.now(UTC).year - 40)
        events = self._events(person, "account_profile_changed")
        self.assertEqual(len(events), 1)
        detail = events[0].detail
        self.assertEqual(detail["fields"], ["name", "sex", "year_of_birth"])
        self.assertNotIn("Renamed Person", str(detail))
        self.assertNotIn("female", str(detail))
        self.assertNotIn(str(person.year_of_birth), str(detail))

    def test_profile_validation(self):
        person = self._person(members=[self.A])
        self._login(str(self.pi_a.user_id))
        for body in ({"name": "=cmd"}, {"name": ""}, {"name": "x" * 129}, {"age": 200},
                     {"age": 30, "year_of_birth": 1990}, {"year_of_birth": 1800}, {"sex": "other"},
                     {"languages": []}, {"languages": ["nope"]}, {}):
            with self.subTest(body=body):
                self.assertEqual(self._patch(person.user_id, body).status_code, 400)
        db.session.refresh(person)
        self.assertEqual(person.name, "Panel Person")
        self.assertEqual(self._events(person, "account_profile_changed"), [])

    def test_shared_accounts_are_read_only_to_a_non_admin(self):
        cases = {
            "member of B": self._person(members=[self.A, self.B]),
            "grant in B": self._person(grants=[(R.coder, self.A), (R.coder, self.B)]),
            "privileged grant": self._person(grants=[(R.coder, self.A), (R.project_pi, self.A)]),
        }
        for actor in (self.dm_a, self.pi_a):
            self._login(str(actor.user_id))
            for name, person in cases.items():
                with self.subTest(actor=actor.email, case=name):
                    body = self.client.get(self._url(person.user_id)).get_json()
                    self.assertEqual(body["user"]["user_id"], str(person.user_id))
                    self.assertFalse(body["may_edit_account"])
                    self.assertNotIn("language_options", body)
                    self.assertEqual(self._patch(person.user_id, {"name": "Taken Over"}).status_code, 403)
                    self.assertEqual(self._post(person.user_id, "/password-reset").status_code, 403)
        self._login(self.base_admin_id)
        self.assertEqual(self._patch(cases["member of B"].user_id, {"name": "Admin Edit"}).status_code, 200)

    def test_a_non_admin_cannot_edit_or_remove_an_admin(self):
        admin_person = self._person(members=[self.A])
        db.session.add(VaUserAccessGrants(
            user_id=admin_person.user_id, role=R.admin, scope_type=VaAccessScopeTypes.global_scope,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(self.pi_a.user_id))
        body = self.client.get(self._url(admin_person.user_id)).get_json()
        self.assertTrue(body["user"]["is_admin"])
        self.assertFalse(body["may_edit_account"])
        self.assertFalse(body["may_remove"])
        self.assertEqual(self._patch(admin_person.user_id, {"name": "Taken Over"}).status_code, 403)
        self.assertEqual(self._post(admin_person.user_id, "/remove").status_code, 403)
        self.assertEqual(self._members(admin_person), {self.A})

    def test_reset_password_needs_a_verified_email(self):
        unverified = self._person(members=[self.A], email="rup.unverified@test.local", mobile_login=False)
        mobile_only = self._person(members=[self.A])
        verified = self._person(members=[self.A], email="rup.verified@test.local", verified=True)
        self._login(str(self.dm_a.user_id))
        with mock.patch("app.services.email_service.send_password_reset_email", return_value=True) as send:
            for person in (unverified, mobile_only):
                with self.subTest(email=person.email):
                    self.assertTrue(mobile.may_edit_account(self.dm_a, person.user_id, self.A))
                    self.assertEqual(self._post(person.user_id, "/password-reset").status_code, 400)
                    self.assertEqual(self._events(person, "password_reset_sent"), [])
            send.assert_not_called()
            response = self._post(verified.user_id, "/password-reset")
        self.assertEqual(response.status_code, 200, response.get_json())
        send.assert_called_once()
        self.assertEqual(len(self._events(verified, "password_reset_sent")), 1)

    def test_csrf_is_required(self):
        person = self._person(members=[self.A], grants=[(R.coder, self.A)])
        self._login(str(self.pi_a.user_id))
        self.assertEqual(self._patch(person.user_id, {"name": "No Token"}, headers={}).status_code, 400)
        self.assertEqual(self._post(person.user_id, "/password-reset", headers={}).status_code, 400)
        self.assertEqual(self._post(person.user_id, "/remove", headers={}).status_code, 400)
        db.session.refresh(person)
        self.assertEqual(person.name, "Panel Person")
        self.assertEqual(self._members(person), {self.A})

    # -- remove from project -----------------------------------------------

    def test_remove_with_an_unrevocable_grant_changes_nothing(self):
        person = self._person(members=[self.A], grants=[(R.coder, self.A), (R.project_pi, self.A)])
        worker = self._worker(person, self.A)
        before = self._grants(person)
        self.assertIn((R.project_pi, self.A, VaStatuses.active), before)
        self._login(str(self.dm_a.user_id))
        response = self._post(person.user_id, "/remove")
        self.assertEqual(response.status_code, 403)
        self.assertIn("project_pi", response.get_json()["error"])
        self.assertEqual(self._grants(person), before)
        self.assertEqual(self._members(person), {self.A})
        db.session.refresh(worker)
        self.assertTrue(worker.is_active)
        self.assertEqual(self._events(person, "removed_from_project"), [])

    def test_remove_keeps_other_projects_and_writes_the_event(self):
        person = self._person(members=[self.A, self.B], grants=[(R.coder, self.A), (R.coder, self.B)])
        worker = self._worker(person, self.A)
        db.session.add(VaUserAccessGrants(
            user_id=person.user_id, role=R.coder, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=worker.org_unit_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(self.pi_a.user_id))
        response = self._post(person.user_id, "/remove")
        self.assertEqual(response.status_code, 200, response.get_json())
        grants = self._grants(person)
        self.assertIn((R.coder, self.B, VaStatuses.active), grants)
        self.assertNotIn((R.coder, self.A, VaStatuses.active), grants)
        self.assertNotIn((R.coder, None, VaStatuses.active), grants)
        self.assertEqual(self._members(person), {self.B})
        db.session.refresh(worker)
        self.assertFalse(worker.is_active)
        self.assertIsNotNone(db.session.get(VaUsers, person.user_id))
        events = self._events(person, "removed_from_project")
        self.assertEqual(len(events), 1)
        detail = events[0].detail
        self.assertEqual(detail["project_id"], self.A)
        self.assertEqual(detail["workers_deactivated"], 1)
        self.assertTrue(detail["membership_removed"])
        self.assertEqual(detail["member_added_by_user_id"], str(self.pi_a.user_id))
        self.assertIsNotNone(detail["member_added_at"])
        # The project grant and the unit grant.
        self.assertEqual(detail["grants_revoked"], 2)
        self.assertTrue(db.session.scalars(sa.select(MapUserNotification).where(
            MapUserNotification.user_id == person.user_id,
            MapUserNotification.kind == ns.ACCESS_CHANGED)).all())

    def test_remove_refuses_oneself(self):
        self._login(str(self.pi_a.user_id))
        self.assertEqual(self._post(self.pi_a.user_id, "/remove").status_code, 400)
        self.assertIn((R.project_pi, self.A, VaStatuses.active), self._grants(self.pi_a))

    # -- activity -------------------------------------------------------------

    def _form_with_audit(self, project_id, site_id, user, action):
        now = datetime.now(UTC)
        if db.session.get(VaResearchProjects, project_id) is None:
            db.session.add(VaResearchProjects(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.add(VaSites(
                site_id=site_id, project_id=project_id, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.flush()
        form_id = f"{project_id}{site_id}"[:12]
        if db.session.get(VaForms, form_id) is None:
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=site_id, odk_form_id=form_id,
                odk_project_id="1", form_type="Panel", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
            db.session.flush()
        sid = f"uuid:{uuid.uuid4()}"
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form_id, va_submission_date=now, va_odk_updatedat=now,
            va_data_collector="Collector", va_instance_name=sid, va_uniqueid_real=sid,
            va_uniqueid_masked=f"masked-{sid}", va_consent="yes", va_narration_language="English",
            va_deceased_age=60, va_deceased_gender="Male", va_summary=[], va_catcount={},
            va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionsAuditlog(
            va_sid=sid, va_audit_byrole="vacoder", va_audit_by=user.user_id, va_audit_operation="c",
            va_audit_action=action, va_audit_createdat=now,
        ))
        db.session.commit()
        return form_id

    def test_activity_is_this_project_and_the_allowlist_only(self):
        person = self._person(members=[self.A])
        form_a = self._form_with_audit(self.A, "RPA1", person, "panel action a")
        form_b = self._form_with_audit(self.B, "RPB1", person, "panel action b")
        for event_type in ("web_sign_in", "factor_enrolled", "account_profile_changed"):
            db.session.add(AuthSecurityEvent(user_id=person.user_id, actor_user_id=self.pi_a.user_id,
                                             event_type=event_type, detail={"secret": "hidden"}))
        db.session.commit()
        # The excluded rows exist before the response is checked for them.
        self.assertTrue(db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionsAuditlog)
                                          .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionsAuditlog.va_sid)
                                          .where(VaSubmissions.va_form_id == form_b,
                                                 VaSubmissionsAuditlog.va_audit_by == person.user_id)))
        self.assertEqual(len(self._events(person, "factor_enrolled")), 1)
        self._login(str(self.dm_a.user_id))
        activity = self.client.get(self._url(person.user_id)).get_json()["activity"]
        self.assertEqual([s["form_id"] for s in activity["submissions"]], [form_a])
        self.assertNotIn(form_b, str(activity))
        self.assertEqual(set(activity["submissions"][0]), {"at", "action", "form_id"})
        types = {e["type"] for e in activity["events"]}
        self.assertEqual(types, {"web_sign_in", "account_profile_changed"})
        self.assertNotIn("factor_enrolled", types)
        self.assertNotIn("hidden", str(activity))
        self.assertEqual({e["actor_name"] for e in activity["events"]}, {self.pi_a.name})
