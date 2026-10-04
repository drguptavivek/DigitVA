"""GET /api/v1/me/access and POST /api/v1/me/terms (bead digitva-339w).

Users and the AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2, D2) come from the
authz fixture; the device-token helpers from tests/routes/test_device_api.py.
"""
from app import db, limiter
from app.models import VaProjectMaster, VaStatuses, VaUsers
from app.services import organization_service as org
from tests.authz.fixture import DM, SP, TA, TB, AuthzFixtureMixin, P, R, U
from tests.authz.test_grants import count_queries
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

ACCESS = "/api/v1/me/access"
PASSWORD = "AuthzTest123"
_DEV = device_tests.DeviceApiTests.__dict__


class MeAccessTests(AuthzFixtureMixin, BaseTestCase):
    PROJECT_ID = TA

    _code = _DEV["_code"]
    _enrol = _DEV["_enrol"]
    _sign_in = _DEV["_sign_in"]
    _session = _DEV["_session"]
    _bearer = _DEV["_bearer"]

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}

    def _body(self, key):
        self._login(str(self.users[key].user_id))
        response = self.client.get(ACCESS)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    @staticmethod
    def _project(body, project_id):
        return next(p for p in body["projects"] if p["project_id"] == project_id)

    @staticmethod
    def _units(project):
        return {u["unit_code"]: u for u in project["units"]}

    def _tokens(self):
        """Device tokens of the P1 interviewer (sign-in needs web intake on)."""
        db.session.get(VaProjectMaster, TA).web_intake_mode = "both"
        db.session.commit()
        return self._session(email=self.users["interviewer_p1"].email, password=PASSWORD)[1]

    # ── shapes ─────────────────────────────────────────────────────────────

    def test_unit_grant_gives_its_subtree_and_ancestors_as_context(self):
        body = self._body("coder_p1")
        self.assertEqual(body["user"], {"user_id": str(self.users["coder_p1"].user_id),
                                        "name": self.users["coder_p1"].name})
        self.assertFalse(body["is_admin"])
        project = self._project(body, TA)
        self.assertEqual(project["grants"], [{
            "role": "coder", "scope": "org_unit",
            "org_unit_id": str(self.units["P1"].org_unit_id), "unit_name": "P1", "codes": True}])
        units = self._units(project)
        # Present first: the reached subtree and its ancestors.
        self.assertEqual(
            {c: (u["roles"], u["selectable"]) for c, u in units.items()},
            {"D1": ([], False), "C1": ([], False),
             "P1": (["coder"], True), "SC1": (["coder"], True)})
        # Absent: the sibling branch and the other district.
        self.assertNotIn("P2", units)
        self.assertNotIn("D2", units)
        self.assertEqual([lv["depth"] for lv in project["levels"]][:2], [1, 2])
        self.assertEqual(project["levels"][0]["level_code"], "district")
        self.assertEqual(set(units["P1"]), {
            "org_unit_id", "unit_code", "unit_name", "level_code", "depth", "parent_code",
            "path", "is_active", "roles", "selectable", "can_code"})
        self.assertEqual(units["P1"]["parent_code"], "C1")
        # A unit grant reaches every active site of its project.
        self.assertEqual([s["site_id"] for s in project["sites"]], ["AZS1", "AZS2"])
        self.assertEqual(project["sites"][0]["roles"], ["coder"])

    def test_project_grant_gives_the_whole_tree(self):
        project = self._project(self._body("coder_ta"), TA)
        units = self._units(project)
        self.assertEqual(set(units), {"D1", "C1", "P1", "SC1", "P2", "D2"})
        self.assertTrue(all(u["roles"] == ["coder"] and u["selectable"] for u in units.values()))
        self.assertEqual(project["grants"], [{"role": "coder", "scope": "project", "codes": False}])
        self.assertTrue(project["has_tree"])

    def test_site_grant_in_a_tree_project_gives_the_whole_tree_but_one_site(self):
        project = self._project(self._body("coder_ta_s1"), TA)
        self.assertEqual(set(self._units(project)), {"D1", "C1", "P1", "SC1", "P2", "D2"})
        self.assertEqual(project["sites"], [{"site_id": "AZS1", "site_name": "AZS1", "roles": ["coder"]}])
        self.assertEqual(project["grants"], [{"role": "coder", "scope": "project_site", "site_id": "AZS1", "codes": False}])

    def test_site_project_has_no_tree_and_skips_inactive_pairs(self):
        project = self._project(self._body("coder_sp"), SP)
        self.assertFalse(project["has_tree"])
        self.assertNotIn("units", project)
        self.assertNotIn("levels", project)
        self.assertEqual([s["site_id"] for s in project["sites"]], ["AZS1", "AZS3"])  # AZS4 inactive
        only = self._project(self._body("coder_sp1"), SP)
        self.assertEqual([s["site_id"] for s in only["sites"]], ["AZS1"])

    def test_two_roles_on_overlapping_units_tag_the_unit_with_both(self):
        # mentor: coder at P1 and collaborator_pii at D1 (the whole district branch).
        units = self._units(self._project(self._body("mentor"), TA))
        self.assertEqual(units["P1"]["roles"], ["coder", "collaborator_pii"])
        self.assertEqual(units["D1"]["roles"], ["collaborator_pii"])
        self.assertEqual(units["P2"]["roles"], ["collaborator_pii"])
        self.assertNotIn("D2", units)

    def test_a_unit_grant_in_one_project_adds_no_units_to_another(self):
        user = self._get_or_make_user("me.two@test.local", PASSWORD)
        for where in ("P1", "G1"):
            db.session.add(self._grant_row(user, R.coder, U, where))
        db.session.commit()
        self._login(str(user.user_id))
        body = self.client.get(ACCESS).get_json()
        self.assertEqual([p["project_id"] for p in body["projects"]], [TA, TB])
        self.assertEqual(set(self._units(self._project(body, TA))), {"D1", "C1", "P1", "SC1"})
        self.assertEqual(set(self._units(self._project(body, TB))), {"E1", "F1", "G1"})

    def test_inactive_grants_and_closed_projects_never_appear(self):
        self.assertEqual(self._body("closed_coder")["projects"], [])
        user = self._get_or_make_user("me.inactive@test.local", PASSWORD)
        grant = self._grant_row(user, R.coder, P, TA)
        db.session.add(grant)
        db.session.commit()
        self._login(str(user.user_id))
        self.assertEqual(len(self.client.get(ACCESS).get_json()["projects"]), 1)
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        from app.services.authz import invalidate
        invalidate(user.user_id)
        self.assertEqual(self.client.get(ACCESS).get_json()["projects"], [])

    def test_admin_is_reflected_and_gets_no_implicit_project(self):
        db.session.add(self._grant_row(self.users["admin"], R.coder, P, SP))
        db.session.commit()
        body = self._body("admin")
        self.assertTrue(body["is_admin"])
        self.assertEqual([p["project_id"] for p in body["projects"]], [SP])
        self.assertNotIn(TB, [p["project_id"] for p in body["projects"]])

    def test_demo_coding_is_reported_but_virtual_grants_are_not_listed(self):
        body = self._body("coder_sp")
        self.assertEqual(body["demo_coding"], {"available": True, "project_ids": [DM]})
        self.assertEqual([p["project_id"] for p in body["projects"]], [SP])
        self.assertEqual(body["projects"][0]["grants"], [{"role": "coder", "scope": "project", "codes": True}])
        # An interviewer is not demo-eligible.
        self.assertEqual(self._body("interviewer_p1")["demo_coding"],
                         {"available": False, "project_ids": []})

    def test_a_user_with_no_grants_gets_an_empty_summary(self):
        body = self._body("nobody")
        self.assertEqual((body["projects"], body["is_admin"]), ([], False))

    # ── credentials, gates, cost ───────────────────────────────────────────

    def test_signed_out_is_a_json_401(self):
        response = self.client.get(ACCESS)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentication required.", "code": "unauthorized"})

    def test_bearer_and_cookie_get_the_same_body(self):
        tokens = self._tokens()
        bearer = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True).get(
            ACCESS, headers=self._bearer(tokens))
        self.assertEqual(bearer.status_code, 200, bearer.get_data(as_text=True))
        cookie = self._body("interviewer_p1")
        self.assertEqual(bearer.get_json(), cookie)
        self.assertTrue(self._project(cookie, TA)["units"])
        self.assertEqual(cookie["projects"][0]["grants"][0]["role"], "interviewer")
        self.assertNotIn("Set-Cookie", bearer.headers)

    def test_terms_are_accepted_under_the_gate_for_bearer_and_cookie(self):
        tokens = self._tokens()
        user = db.session.get(VaUsers, self.users["interviewer_p1"].user_id)
        user.pw_reset_t_and_c = False
        db.session.commit()
        held = self.client.get(ACCESS, headers=self._bearer(tokens))
        self.assertEqual((held.status_code, held.get_json()["code"]), (403, "terms_required"))
        refused = self.client.post("/api/v1/me/terms", json={"accept_terms": "yes"}, headers=self._bearer(tokens))
        self.assertEqual(refused.status_code, 400)
        ok = self.client.post("/api/v1/me/terms", json={"accept_terms": True}, headers=self._bearer(tokens))
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        self.assertEqual(ok.get_json(), {"message": "Terms accepted.", "terms_accepted": True})
        self.assertEqual(self.client.get(ACCESS, headers=self._bearer(tokens)).status_code, 200)
        # Cookie: the gate holds /me/access, /me/terms opens it (CSRF token required).
        user.pw_reset_t_and_c = False
        db.session.commit()
        self._login(str(user.user_id))
        self.assertEqual(self.client.get(ACCESS).status_code, 403)
        accepted = self.client.post("/api/v1/me/terms", json={"accept_terms": True}, headers=self._csrf_headers())
        self.assertEqual(accepted.status_code, 200, accepted.get_data(as_text=True))
        self.assertEqual(self.client.get(ACCESS).status_code, 200)

    def _count(self, key):
        self._login(str(self.users[key].user_id))
        self.client.get(ACCESS)  # warm
        with count_queries() as statements:
            self.assertEqual(self.client.get(ACCESS).status_code, 200)
        return len(statements)

    def test_queries_grow_with_projects_not_units(self):
        small = self._count("coder_ta")
        self.assertLess(small, 40)
        levels = {lv.level_code: lv for lv in org.list_levels(TA)}
        for n in range(5):
            org.create_unit(TA, org_level_id=levels["phc"].org_level_id,
                            parent_org_unit_id=self.units["C1"].org_unit_id,
                            unit_code=f"X{n}", unit_name=f"X{n}")
        db.session.commit()
        self.assertEqual(self._count("coder_ta"), small)
        # A second tree project adds a bounded number of queries.
        user = self._get_or_make_user("me.tree2@test.local", PASSWORD)
        for project in (TA, TB):
            db.session.add(self._grant_row(user, R.coder, P, project))
        db.session.commit()
        self._login(str(user.user_id))
        self.client.get(ACCESS)
        with count_queries() as statements:
            self.assertEqual(self.client.get(ACCESS).status_code, 200)
        self.assertLessEqual(len(statements), small + 10, statements)

    # ── roles are reach; codes / can_code mirror the coding scope rule ─────

    def test_project_pi_holds_every_role_on_every_unit(self):
        user = self._get_or_make_user("me.pi@test.local", PASSWORD)
        db.session.add(self._grant_row(user, R.project_pi, P, TA))
        db.session.add(self._grant_row(user, R.coder, U, "P1"))
        db.session.commit()
        self._login(str(user.user_id))
        units = self._units(self._project(self.client.get(ACCESS).get_json(), TA))
        self.assertEqual(set(units), {"D1", "C1", "P1", "SC1", "P2", "D2"})
        for unit in units.values():
            self.assertEqual(unit["roles"], ["coder", "project_pi"], unit)
            self.assertTrue(unit["selectable"])
        # Coding is still scoped by the coder grant, not by project_pi.
        self.assertEqual({c: u["can_code"] for c, u in units.items()},
                         {"D1": False, "C1": False, "P1": True, "SC1": True, "P2": False, "D2": False})

    def test_a_project_grant_and_a_unit_grant_of_one_role_give_the_whole_tree(self):
        user = self._get_or_make_user("me.whole@test.local", PASSWORD)
        db.session.add(self._grant_row(user, R.coder, P, TA))
        db.session.add(self._grant_row(user, R.coder, U, "P1"))
        db.session.commit()
        self._login(str(user.user_id))
        units = self._units(self._project(self.client.get(ACCESS).get_json(), TA))
        self.assertEqual(set(units), {"D1", "C1", "P1", "SC1", "P2", "D2"})
        self.assertTrue(all(u["roles"] == ["coder"] for u in units.values()))
        # The P1 grant codes (PHC), so P1's subtree can code; the wide one does not.
        self.assertTrue(units["P1"]["can_code"])
        self.assertFalse(units["P2"]["can_code"])

    def test_can_code_is_false_above_the_scope_level_and_true_at_or_below(self):
        project = self._project(self._body("coder_p1"), TA)
        self.assertEqual({c: u["can_code"] for c, u in self._units(project).items()},
                         {"D1": False, "C1": False, "P1": True, "SC1": True})
        self.assertEqual([g["codes"] for g in project["grants"]], [True])
        # A grant above the level (CHC) codes nowhere under view_only.
        above = self._project(self._body("coder_c1"), TA)
        self.assertEqual([g["codes"] for g in above["grants"]], [False])
        self.assertFalse(any(u["can_code"] for u in above["units"]))

    def test_a_wide_coder_grant_does_not_code_under_a_scope_level_unless_code_any(self):
        wide = self._project(self._body("coder_ta"), TA)
        self.assertEqual(wide["grants"], [{"role": "coder", "scope": "project", "codes": False}])
        self.assertFalse(any(u["can_code"] for u in wide["units"]))
        # TB is code_any: the same grant codes everywhere.
        tb = self._project(self._body("coder_tb"), TB)
        self.assertEqual(tb["grants"], [{"role": "coder", "scope": "project", "codes": True}])
        self.assertTrue(all(u["can_code"] for u in tb["units"]))

    def test_coding_tester_is_exempt_from_the_scope_level_and_reviewer_is_not(self):
        tester = self._project(self._body("tester_ta"), TA)
        self.assertEqual([g["codes"] for g in tester["grants"]], [True])
        self.assertTrue(all(u["can_code"] for u in tester["units"]))
        reviewer = self._project(self._body("reviewer_ta"), TA)
        self.assertEqual([g["codes"] for g in reviewer["grants"]], [False])
        self.assertFalse(any(u["can_code"] for u in reviewer["units"]))
        # Roles with no coding scope carry no flag.
        self.assertEqual(self._project(self._body("dm_ta"), TA)["grants"],
                         [{"role": "data_manager", "scope": "project"}])

    def test_terms_share_one_rate_limit_with_the_profile_url(self):
        tokens = self._tokens()
        headers = self._bearer(tokens)
        statuses = [
            self.client.post(url, json={"accept_terms": True}, headers=headers).status_code
            for url in ("/api/v1/me/terms", "/api/v1/profile/terms") * 3
        ]
        self.assertEqual(statuses, [200] * 5 + [429])

    def test_me_responses_are_not_cached(self):
        self._login(str(self.users["coder_p1"].user_id))
        self.assertEqual(self.client.get(ACCESS).headers["Cache-Control"], "no-store")
