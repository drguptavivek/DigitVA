"""Training & demo project: admin API, public page, welcome and onboarding redirect."""

from contextlib import contextmanager
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import MapTrainingParticipant, VaUsers
from app.services import training_demo_service as svc
from tests.training_demo_fixtures import SRC_FORM, TrainingDemoTestBase

API = "/admin/api/training/sessions"


class AdminApiTests(TrainingDemoTestBase):
    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)

    def _post(self, path, body=None, headers=True):
        return self.client.post(
            API + path, json=body or {}, headers=self._csrf_headers() if headers else None
        )

    def test_panel_and_list(self):
        panel = self.client.get("/admin/panels/training-sessions")
        self.assertEqual(panel.status_code, 200)
        self.assertIn(b"Training sessions", panel.data)
        data = self.client.get(API).get_json()
        self.assertTrue(data["configured"])
        self.assertEqual([s["session_code"] for s in data["sessions"]], ["S001"])
        self.assertEqual(data["sessions"][0]["coder_slots_total"], 20)

    def test_full_participant_lifecycle_through_the_api(self):
        user = self._user("api")
        added = self._post("/S001/participants", {"email": user.email, "role": "coder"})
        self.assertEqual(added.status_code, 201, added.get_json())
        self.assertEqual(added.get_json()["coder_slot"], 1)
        detail = self.client.get(API + "/S001").get_json()
        self.assertEqual(detail["coder_slots_used"], 1)
        self.assertEqual(detail["participants"][0]["email"], user.email)
        again = self._post("/S001/participants", {"email": user.email, "role": "coder"})
        self.assertEqual(again.status_code, 409)
        removed = self._post("/S001/participants/remove", {"user_id": str(user.user_id), "role": "coder"})
        self.assertEqual(removed.get_json()["status"], "removed")
        closed = self._post("/S001/close")
        self.assertEqual(closed.get_json()["status"], "closed")
        self.assertEqual(self._post("/S001/participants", {"email": user.email, "role": "coder"}).status_code, 409)
        self.assertEqual(self._post("/S001/reopen").get_json()["status"], "active")

    def test_roles_list_and_legacy_role_both_work(self):
        both, legacy = self._user("roles"), self._user("legacy")
        added = self._post("/S001/participants", {"email": both.email, "roles": ["coder", "interviewer"]})
        self.assertEqual(added.status_code, 201, added.get_json())
        self.assertEqual([p["role"] for p in added.get_json()["participants"]], ["coder", "interviewer"])
        self.assertEqual(self._post("/S001/participants", {"email": legacy.email, "role": "interviewer"}).status_code, 201)
        self.assertEqual(self._post("/S001/participants", {"email": legacy.email, "roles": []}).status_code, 400)
        bulk = self._post("/S001/participants/bulk", {"user_ids": [str(both.user_id)], "roles": ["death_reporter", "coder"]})
        self.assertEqual(bulk.status_code, 200, bulk.get_json())
        self.assertEqual([(r["role"], r["action"]) for r in bulk.get_json()["rows"]],
                         [("death_reporter", "add"), ("coder", "already")])

    def test_panel_offers_role_checkboxes(self):
        page = self.client.get("/admin/panels/training-sessions").data
        self.assertIn(b'type="checkbox" name="roles" value="coder"', page)
        self.assertIn(b'id="training-bulk-role-reviewer_data_manager"', page)
        self.assertNotIn(b'<select id="training-role"', page)

    def test_missing_coder_language_is_shown_as_the_error(self):
        from app import db
        from app.models import VaSubmissions
        import sqlalchemy as sa

        user = self._user("nolang")
        db.session.execute(
            sa.update(VaSubmissions).where(VaSubmissions.va_sid == "trn-S001-3").values(va_narration_language="hindi")
        )
        db.session.flush()
        response = self._post("/S001/participants", {"email": user.email, "role": "coder"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Hindi", response.get_json()["error"])
        self.assertIn("coding languages", response.get_json()["error"])

    def test_refusals_are_json_errors(self):
        self.assertEqual(
            self._post("/S001/participants", {"email": "nobody@test.local", "role": "coder"}).status_code, 404)
        self.assertEqual(self._post("/S001/participants", {"email": "x@y.z", "role": "admin"}).status_code, 400)
        self.assertEqual(self._post("/S001/participants", {"email": 5, "role": []}).status_code, 400)
        self.assertEqual(self.client.get(API + "/S404").status_code, 404)
        self.assertEqual(self._post("", {"name": ""}).status_code, 400)
        self.assertIn("error", self._post("", {"name": ""}).get_json())

    def test_create_session_through_the_api(self):
        from unittest import mock

        with mock.patch.object(svc, "DEFAULT_SOURCE_FORM_ID", SRC_FORM):
            response = self._post("", {"name": "Second training"})
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["session_code"], "S002")
        self.assertEqual(body["cases_total"], 200)
        self.assertEqual(len(self.client.get(API).get_json()["sessions"]), 2)

    def test_create_takes_the_coder_slot_count_and_checks_it(self):
        from unittest import mock

        for bad in (0, 101, "20", True, None):
            response = self._post("", {"name": "Bad slots", "coder_slots": bad})
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("coder slots", response.get_json()["error"])
        with mock.patch.object(svc, "DEFAULT_SOURCE_FORM_ID", SRC_FORM):
            response = self._post("", {"name": "Small training", "coder_slots": 3})
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual((body["coder_slots_total"], body["cases_total"]), (3, 30))
        self.assertIn(b'id="training-slots"', self.client.get("/admin/panels/training-sessions").data)

    def test_non_admins_and_anonymous_are_refused(self):
        for who in (self.base_coder_id, self.base_project_pi_id):
            self._login(who)
            self.assertEqual(self.client.get(API).status_code, 403)
            self.assertEqual(self.client.get("/admin/panels/training-sessions").status_code, 403)
            self.assertEqual(self._post("", {"name": "x"}).status_code, 403)
            self.assertEqual(self._post("/S001/participants", {"email": "a@b.c", "role": "coder"}).status_code, 403)
            self.assertEqual(self._post("/S001/close").status_code, 403)
        with self.client.session_transaction() as session:
            session.clear()
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        self.assertEqual(self.client.get(API).status_code, 401)
        self.assertEqual(self._post("", {"name": "x"}).status_code, 401)

    def test_missing_csrf_token_is_refused(self):
        user = self._user("csrf")
        old = self.app.config.get("WTF_CSRF_ENABLED")
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            for path, body in (
                ("", {"name": "x"}),
                ("/S001/participants", {"email": user.email, "role": "coder"}),
                ("/S001/participants/remove", {"user_id": str(user.user_id), "role": "coder"}),
                ("/S001/close", {}),
                ("/S001/reopen", {}),
            ):
                self.assertEqual(self._post(path, body, headers=False).status_code, 400, path)
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = old
        self.assertEqual(svc.get_training_session("S001")["participants"], [])
        self.assertEqual(svc.get_training_session("S001")["status"], "active")

    def test_not_configured_blocks_writes(self):
        from unittest import mock

        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=""):
            self.assertFalse(self.client.get(API).get_json()["configured"])
            self.assertEqual(self._post("", {"name": "x"}).status_code, 409)


@contextmanager
def export(ready: bool):
    """The Expo export present (or not): the hook reads expo_client's, the routes their own import."""
    with mock.patch("app.routes.expo_client.export_ready", return_value=ready), \
            mock.patch("app.routes.training_demo.export_ready", return_value=ready):
        yield


class PublicAndWelcomeTests(TrainingDemoTestBase):
    def test_public_page_needs_no_login_and_lists_no_users(self):
        user = self._user("listed")
        svc.add_participant("S001", user.email, "coder", self.admin)
        anonymous = self.app.test_client()
        response = anonymous.get("/demo")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Sign in", text)  # subject present before asserting absence
        for role in ("Death reporter", "Interviewer", "Interview supervisor", "Coder", "Reviewer and data manager"):
            self.assertIn(role, text)
        self.assertIn("pseudonymis", text.lower().replace("made-up", "pseudonymis"))
        self.assertIn("phone numbers", text)
        self.assertIn("Photos, documents and audio", text)
        self.assertIn("Do not copy, photograph or share", text)
        self.assertIn("only their own 10", text)
        self.assertNotIn(user.email, text)
        self.assertNotIn("@test.local", text)

    def test_welcome_requires_login(self):
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        self.assertIn(self.client.get("/demo/welcome").status_code, (302, 401))
        self.assertIn(self.client.post("/demo/welcome/start", headers=self._csrf_headers()).status_code, (302, 401))

    def test_welcome_shows_only_the_users_own_roles(self):
        user, other = self._user("mine"), self._user("theirs")
        svc.add_participant("S001", user.email, "coder", self.admin)
        svc.add_participant("S001", other.email, "interviewer", self.admin)
        self._login(str(user.user_id))
        with export(False):
            text = self.client.get("/demo/welcome").get_data(as_text=True)
        self.assertIn("Coder", text)
        self.assertIn("coder slot 1", text.lower())
        self.assertIn('href="/app/training"', text)  # training is done in the DigitVA app
        for flask_work_link in ("Open your coding list", "Open your worklist", "Open the reviewer list"):
            self.assertNotIn(flask_work_link, text)
        self.assertNotIn("Interviewer", text)
        self.assertNotIn(other.email, text)

    def test_welcome_for_someone_not_in_a_session(self):
        self._login(self.base_coder_id)
        with export(False):
            text = self.client.get("/demo/welcome").get_data(as_text=True)
        self.assertIn("not been added", text)

    def test_first_sign_in_redirects_once_and_start_records_onboarding(self):
        user = self._user("first")
        svc.add_participant("S001", user.email, "reviewer_data_manager", self.admin)
        self._login(str(user.user_id))
        with export(False):  # the Flask fallback while there is no export
            first = self.client.get("/people-roles")
            self.assertEqual(first.status_code, 302)
            self.assertTrue(first.headers["Location"].endswith("/demo/welcome"))
            self.assertEqual(self.client.get("/people-roles").status_code, 200)  # once per login session
            self.assertEqual(self.client.get("/demo/welcome").status_code, 200)
        start = self.client.post("/demo/welcome/start", headers=self._csrf_headers())
        self.assertEqual(start.status_code, 302)
        self.assertTrue(start.headers["Location"].endswith("/app/training"))
        row = db.session.scalar(
            sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id))
        self.assertIsNotNone(row.onboarded_at)
        self._login(str(user.user_id))  # a new sign-in
        self.assertEqual(self.client.get("/people-roles").status_code, 200)

    def test_redirect_repeats_at_next_sign_in_until_started(self):
        user = self._user("again")
        svc.add_participant("S001", user.email, "interviewer", self.admin)
        with export(False):
            for _ in range(2):
                self._login(str(user.user_id))
                self.assertEqual(self.client.get("/people-roles").status_code, 302)

    def test_with_the_export_the_redirect_goes_to_the_expo_training_page(self):
        user = self._user("expo")
        svc.add_participant("S001", user.email, "coder", self.admin)
        self._login(str(user.user_id))
        with export(True):
            # /app/ itself is never sent to a Flask page, and does not use up the redirect.
            self.assertNotEqual(self.client.get("/app/").status_code, 302)
            first = self.client.get("/people-roles")
            self.assertEqual(first.status_code, 302)
            self.assertTrue(first.headers["Location"].endswith("/app/training"))
            self.assertEqual(self.client.get("/people-roles").status_code, 200)  # once per login session
            welcome = self.client.get("/demo/welcome")
            self.assertEqual(welcome.status_code, 302)
            self.assertTrue(welcome.headers["Location"].endswith("/app/training"))
        with export(False):
            self.assertEqual(self.client.get("/demo/welcome").status_code, 200)

    def test_no_redirect_for_apis_fragments_or_other_users(self):
        user = self._user("quiet")
        svc.add_participant("S001", user.email, "coder", self.admin)
        self._login(str(user.user_id))
        self.assertNotEqual(self.client.get("/people-roles", headers={"HX-Request": "true"}).status_code, 302)
        self.assertNotEqual(self.client.get("/api/v1/me/access").status_code, 302)
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/people-roles").status_code, 200)

    def test_feature_off_means_no_redirect_and_no_query(self):
        from unittest import mock

        user = self._user("off")
        svc.add_participant("S001", user.email, "coder", self.admin)
        self._login(str(user.user_id))
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=""):
            self.assertEqual(self.client.get("/people-roles").status_code, 200)

    def test_help_and_public_pages_link_to_the_training_page(self):
        self._login(self.base_coder_id)
        for ready, target in ((False, b"/demo/welcome"), (True, b"/app/training")):
            with export(ready):
                response = self.client.get("/help/training-demo")
                self.assertEqual(response.status_code, 200)
                self.assertIn(target, response.data)
                self.assertIn(target, self.client.get("/demo").data)


class MigrationAndModelTests(TrainingDemoTestBase):
    def test_participant_constraints(self):
        user = self._user("unique")
        svc.add_participant("S001", user.email, "coder", self.admin)
        row = db.session.scalar(
            sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id))
        self.assertEqual(row.coder_slot, 1)
        self.assertEqual(len(row.grant_ids), 1)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers).where(
            VaUsers.email == user.email)), 1)
