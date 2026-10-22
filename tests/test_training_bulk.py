"""Bulk add of trainees and the graduation CSV (digitva-vd0g.3): service and admin API."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import MapTrainingParticipant, VaStatuses, VaSubmissions, VaUsers
from app.models.mas_training import PARTICIPANT_ROLES
from app.services import training_demo_service as svc
from app.services.project_user_import_service import HEADERS
from tests.training_demo_fixtures import TrainingDemoTestBase

API = "/admin/api/training/sessions"


def _now():
    return datetime.now(UTC).replace(tzinfo=None)  # user_created_at is naive UTC


class BulkTestBase(TrainingDemoTestBase):
    def _made_by(self, tag, creator=None, created_at=None, **fields):
        user = self._user(tag)
        if creator is not False:
            user.other = {"created_by_user_id": str(creator or self.admin.user_id)}
        user.user_created_at = created_at or _now()
        for key, value in fields.items():
            setattr(user, key, value)
        db.session.flush()
        return user

    def _participants(self, role=None):
        stmt = sa.select(MapTrainingParticipant)
        if role:
            stmt = stmt.where(MapTrainingParticipant.role == role)
        return db.session.scalars(stmt).all()

    def _ids(self, *users):
        return [str(u.user_id) for u in users]


class CandidateTests(BulkTestBase):
    def _find(self, **kwargs):
        kwargs.setdefault("tz_name", "UTC")
        return svc.training_candidates("S001", self.admin, **kwargs)

    def test_filters_by_creator_and_date_and_excludes_active_participants(self):
        mine = self._made_by("c.mine")
        old = self._made_by("c.old", created_at=_now() - timedelta(days=3))
        theirs = self._made_by("c.theirs", creator=self.base_coder_user.user_id)
        unknown = self._made_by("c.unknown", creator=False)
        today = datetime.now(UTC).date().isoformat()

        found = {u["user_id"] for u in self._find(created_since=today)["users"]}
        self.assertEqual(found, {str(mine.user_id)})
        both = {u["user_id"] for u in self._find()["users"]}
        self.assertEqual(both, {str(mine.user_id), str(old.user_id)})
        anyone = {u["user_id"] for u in self._find(created_since=today, created_by="any")["users"]}
        self.assertTrue({str(mine.user_id), str(theirs.user_id), str(unknown.user_id)} <= anyone)
        self.assertNotIn(str(old.user_id), anyone)

        svc.add_participant("S001", mine.email, "interviewer", self.admin)
        self.assertNotIn(str(mine.user_id), {u["user_id"] for u in self._find()["users"]})
        svc.remove_participant("S001", mine.user_id, "interviewer", self.admin)
        self.assertIn(str(mine.user_id), {u["user_id"] for u in self._find()["users"]})

    def test_lean_fields_search_and_limit(self):
        self._made_by("c.lean.one", name="Zed Needle One")
        self._made_by("c.lean.two", name="Zed Needle Two")
        self._made_by("c.other", name="Someone Else")
        result = self._find(query="needle")
        self.assertEqual(len(result["users"]), 2)
        self.assertEqual(set(result["users"][0]), {"user_id", "name", "email", "status"})
        self.assertFalse(result["truncated"])
        limited = self._find(query="needle", limit=1)
        self.assertEqual((len(limited["users"]), limited["truncated"]), (1, True))
        self.assertLessEqual(len(self._find(limit=10_000)["users"]), svc.CANDIDATES_MAX)
        self.assertEqual(len(self._find(query="needle", limit=0)["users"]), 1)  # clamped up to 1
        self.assertEqual(self._find(query="needle one")["users"][0]["status"], "active")

    def test_inactive_users_and_wildcards(self):
        gone = self._made_by("c.inactive", name="Gone Person")
        gone.user_status = VaStatuses.deactive
        db.session.flush()
        self.assertEqual(self._find(query="Gone Person")["users"], [])
        self.assertEqual(self._find(query="%")["users"], [])

    def test_mobile_only_accounts_show_a_masked_number(self):
        user = self._made_by("c.mobile", email=None, mobile_login="9876543210", name="Mobile Only")
        result = self._find(query="Mobile Only")
        self.assertEqual(result["users"][0]["email"], "******3210")
        self.assertNotIn("9876543210", str(result))
        self.assertEqual(result["users"][0]["user_id"], str(user.user_id))

    def test_date_is_read_in_the_admins_zone(self):
        user = self._made_by("c.zone", created_at=datetime(2026, 3, 1, 19, 0))  # 00:30 on 2 March in Kolkata
        ids = lambda day, tz: {  # noqa: E731
            u["user_id"] for u in svc.training_candidates(
                "S001", self.admin, created_since=day, created_by="any", limit=200, tz_name=tz)["users"]}
        self.assertIn(str(user.user_id), ids("2026-03-02", "Asia/Kolkata"))
        self.assertNotIn(str(user.user_id), ids("2026-03-02", "UTC"))

    def test_bad_input_and_non_admin(self):
        for kwargs in ({"created_since": "yesterday"}, {"created_by": "everyone"}):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                self._find(**kwargs)
            self.assertEqual(ctx.exception.code, "invalid_filter")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.training_candidates("S001", self.base_coder_user)
        self.assertEqual(ctx.exception.code, "admin_required")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.training_candidates("S404", self.admin)
        self.assertEqual(ctx.exception.code, "session_not_found")


class BulkAddTests(BulkTestBase):
    def _bulk(self, users, role, dry_run):
        return svc.bulk_add_participants("S001", self._ids(*users), role, self.admin, dry_run=dry_run)

    def test_dry_run_reports_actions_and_writes_nothing(self):
        users = [self._made_by(f"b.dry{i}") for i in range(3)]
        svc.add_participant("S001", users[2].email, "coder", self.admin)
        result = self._bulk(users, "coder", dry_run=True)
        self.assertTrue(result["dry_run"])
        rows = {r["user_id"]: r for r in result["rows"]}
        self.assertEqual(
            [(rows[str(u.user_id)]["action"], rows[str(u.user_id)]["slot_or_scope"]) for u in users],
            [("add", "Coder slot 02"), ("add", "Coder slot 03"), ("already", "Coder slot 01")],
        )
        self.assertEqual(set(result["rows"][0]), {"user_id", "name", "email", "role", "slot_or_scope", "action", "reason"})
        self.assertEqual(len(self._participants()), 1)  # only the one added directly
        self.assertEqual([r["slot_or_scope"] for r in self._bulk(users[:1], "interviewer", True)["rows"]], ["Whole session"])

    def test_apply_adds_coders_to_slots_in_order_with_grants(self):
        users = [self._made_by(f"b.slot{i}") for i in range(3)]
        result = self._bulk(users, "coder", dry_run=False)
        self.assertEqual((result["applied"], result["added"], result["reactivated"], result["already"]), (True, 3, 0, 0))
        slots = {p.user_id: p.coder_slot for p in self._participants("coder")}
        self.assertEqual([slots[u.user_id] for u in users], [1, 2, 3])
        for user in users:
            self.assertEqual(len(self._grants(user, VaStatuses.active)), 1)
        pick = self._pick_list(users[1])
        self.assertTrue(pick and pick <= self._session_sids()[2])

    def test_reviewer_data_manager_gets_both_grants_and_reactivation_keeps_the_slot(self):
        manager = self._made_by("b.rdm")
        self.assertEqual(self._bulk([manager], "reviewer_data_manager", False)["added"], 1)
        self.assertEqual(len(self._grants(manager, VaStatuses.active)), 2)
        coder = self._made_by("b.react")
        self._bulk([coder], "coder", False)
        svc.remove_participant("S001", coder.user_id, "coder", self.admin)
        self.assertEqual(self._grants(coder, VaStatuses.active), [])
        again = self._bulk([coder], "coder", dry_run=True)["rows"][0]
        self.assertEqual((again["action"], again["slot_or_scope"]), ("reactivate", "Coder slot 01"))
        result = self._bulk([coder], "coder", dry_run=False)
        self.assertEqual((result["reactivated"], result["added"]), (1, 0))
        self.assertEqual(len(self._grants(coder, VaStatuses.active)), 1)

    def test_two_roles_for_two_users_give_four_rows_with_slots_in_order(self):
        users = [self._made_by(f"b.two{i}") for i in range(2)]
        roles = ["coder", "interviewer"]
        dry = self._bulk(users, roles, dry_run=True)
        self.assertEqual([(r["role"], r["action"]) for r in dry["rows"]],
                         [("coder", "add"), ("interviewer", "add")] * 2)
        self.assertEqual(self._participants(), [])
        result = self._bulk(users, roles, dry_run=False)
        self.assertEqual((result["applied"], result["added"]), (True, 4))
        self.assertEqual(len(self._participants()), 4)
        slots = {p.user_id: p.coder_slot for p in self._participants("coder")}
        self.assertEqual([slots[u.user_id] for u in users], [1, 2])
        self.assertEqual(len(self._grants(users[0], VaStatuses.active)), 2)

    def test_one_refused_row_of_several_roles_writes_nothing(self):
        user = self._made_by("b.mixroles")
        with mock.patch.object(svc, "_used_slots", return_value=set(range(1, 21))):  # every slot taken
            result = self._bulk([user], ["interviewer", "coder"], dry_run=False)
        self.assertFalse(result["applied"])
        self.assertEqual(self._participants(), [])

    def test_apply_is_all_or_nothing(self):
        good = [self._made_by("b.good1"), self._made_by("b.good2")]
        inactive = self._made_by("b.bad")
        inactive.user_status = VaStatuses.deactive
        db.session.flush()
        result = self._bulk([*good, inactive], "interviewer", dry_run=False)
        self.assertFalse(result["applied"])
        self.assertEqual((result["added"], len(result["refused"])), (0, 1))
        self.assertEqual(result["refused"][0]["user_id"], str(inactive.user_id))
        self.assertEqual(self._participants(), [])
        self.assertEqual(self._grants(good[0]), [])
        result = self._bulk(good, "interviewer", dry_run=False)
        self.assertEqual((result["applied"], result["added"]), (True, 2))

    def test_unknown_and_malformed_ids_are_refused_rows(self):
        user = self._made_by("b.mixed")
        result = svc.bulk_add_participants(
            "S001", [str(user.user_id), "not-a-uuid", "3b241101-e2bb-4255-8caf-4136c566a962", 7],
            "interviewer", self.admin, dry_run=True)
        self.assertEqual([r["action"] for r in result["rows"]], ["add", "refuse", "refuse"])
        self.assertEqual(result["rows"][1]["reason"], svc.MESSAGES["unknown_user"])

    def test_slot_exhaustion_is_refused(self):
        users = [self._made_by(f"b.full{i}") for i in range(3)]
        svc._find_session("S001").coder_slots = 2  # the session's own count bounds the slots
        db.session.flush()
        dry = self._bulk(users, "coder", dry_run=True)
        self.assertEqual([r["action"] for r in dry["rows"]], ["add", "add", "refuse"])
        self.assertEqual(dry["rows"][2]["reason"], svc.MESSAGES["no_free_coder_slot"])
        applied = self._bulk(users, "coder", dry_run=False)
        self.assertFalse(applied["applied"])
        self.assertEqual(self._participants("coder"), [])

    def test_hindi_requirement_surfaces_as_a_refuse_row(self):
        db.session.execute(
            sa.update(VaSubmissions).where(VaSubmissions.va_sid == "trn-S001-3").values(va_narration_language="hindi"))
        lacking = self._made_by("b.nohindi")
        able = self._made_by("b.hindi", vacode_language=["english", "hindi"])
        rows = self._bulk([lacking, able], "coder", dry_run=True)["rows"]
        self.assertEqual(rows[0]["action"], "refuse")
        self.assertIn("Hindi", rows[0]["reason"])
        self.assertEqual(rows[1]["action"], "add")
        self.assertEqual(rows[1]["slot_or_scope"], "Coder slot 01")  # a refused row takes no slot
        self.assertEqual(self._bulk([lacking, able], "interviewer", dry_run=True)["rows"][0]["action"], "add")

    def test_limits_roles_closed_session_and_non_admin(self):
        user = self._made_by("b.limits")

        def code(call):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                call()
            return ctx.exception.code

        self.assertEqual(code(lambda: svc.bulk_add_participants("S001", [], "coder", self.admin)), "bulk_empty")
        self.assertEqual(code(lambda: svc.bulk_add_participants(
            "S001", [f"u{i}" for i in range(svc.BULK_MAX + 1)], "coder", self.admin)), "bulk_too_many")
        self.assertEqual(code(lambda: svc.bulk_add_participants(
            "S001", self._ids(user), "admin", self.admin)), "invalid_role")
        self.assertEqual(code(lambda: svc.bulk_add_participants(
            "S001", self._ids(user), "coder", self.base_coder_user)), "admin_required")
        svc.close_training_session("S001", self.admin)
        self.assertEqual(code(lambda: svc.bulk_add_participants(
            "S001", self._ids(user), "coder", self.admin)), "session_closed")


class GraduationTests(BulkTestBase):
    def _rows(self, **kwargs):
        text = svc.graduation_csv("S001", self.admin, **kwargs)
        return list(csv.reader(io.StringIO(text)))

    def test_headers_rows_and_reviewer_data_manager_two_rows(self):
        coder, manager, reporter = (self._made_by(t) for t in ("g.coder", "g.rdm", "g.reporter"))
        svc.bulk_add_participants("S001", self._ids(coder), "coder", self.admin, dry_run=False)
        svc.bulk_add_participants("S001", self._ids(manager), "reviewer_data_manager", self.admin, dry_run=False)
        svc.bulk_add_participants("S001", self._ids(reporter), "death_reporter", self.admin, dry_run=False)
        rows = self._rows()
        self.assertEqual(tuple(rows[0]), HEADERS)
        body = [dict(zip(HEADERS, r)) for r in rows[1:]]
        self.assertEqual(
            sorted((r["email"], r["role"]) for r in body),
            sorted([(coder.email, "coder"), (manager.email, "reviewer"), (manager.email, "data_manager"),
                    (reporter.email, "death_reporter")]),
        )
        self.assertTrue(all(r["org_unit_code"] == "" and r["cadre_code"] == "" for r in body))
        filled = [dict(zip(HEADERS, r)) for r in self._rows(org_unit_code="phc01", cadre_code="staff")[1:]]
        self.assertTrue(all((r["org_unit_code"], r["cadre_code"]) == ("PHC01", "STAFF") for r in filled))
        only = [dict(zip(HEADERS, r)) for r in self._rows(role="reviewer_data_manager")[1:]]
        self.assertEqual({r["role"] for r in only}, {"reviewer", "data_manager"})

    def test_removed_participants_are_left_out_and_bad_filters_refused(self):
        user = self._made_by("g.removed")
        svc.bulk_add_participants("S001", self._ids(user), "interviewer", self.admin, dry_run=False)
        svc.remove_participant("S001", user.user_id, "interviewer", self.admin)
        self.assertEqual(len(self._rows()), 1)  # header only
        for kwargs in ({"role": "admin"}, {"org_unit_code": "a,b"}, {"cadre_code": "=cmd"}):
            with self.assertRaises(svc.TrainingDemoError):
                self._rows(**kwargs)

    def test_mobile_only_user_is_keyed_by_phone_and_names_are_formula_safe(self):
        user = self._made_by("g.mobile", email=None, mobile_login="9876543210", name="=Evil")
        svc.bulk_add_participants("S001", self._ids(user), "coder", self.admin, dry_run=False)
        row = dict(zip(HEADERS, self._rows()[1]))
        self.assertEqual((row["email"], row["phone"], row["name"]), ("", "9876543210", "'=Evil"))

    def test_every_participant_role_maps(self):
        self.assertEqual(set(svc._GRADUATION_ROLES), set(PARTICIPANT_ROLES))


class BulkApiTests(BulkTestBase):
    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)

    def _post(self, body, headers=True, path="/S001/participants/bulk"):
        return self.client.post(API + path, json=body, headers=self._csrf_headers() if headers else None)

    def test_candidates_endpoint(self):
        user = self._made_by("api.cand")
        today = datetime.now(UTC).date().isoformat()
        response = self.client.get(f"{API}/S001/candidates?created_since={today}&limit=5")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(set(body), {"users", "truncated"})
        self.assertIn(str(user.user_id), {u["user_id"] for u in body["users"]})
        self.assertEqual(self.client.get(f"{API}/S001/candidates?created_by=x").status_code, 400)
        self.assertEqual(self.client.get(f"{API}/S001/candidates?limit=abc").status_code, 400)
        self.assertEqual(self.client.get(f"{API}/S404/candidates").status_code, 404)

    def test_preview_then_apply(self):
        users = [self._made_by("api.bulk1"), self._made_by("api.bulk2")]
        preview = self._post({"user_ids": self._ids(*users), "role": "coder", "dry_run": True})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual([r["action"] for r in preview.get_json()["rows"]], ["add", "add"])
        self.assertEqual(self._participants(), [])
        applied = self._post({"user_ids": self._ids(*users), "role": "coder", "dry_run": False})
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.get_json()["added"], 2)
        self.assertEqual(len(self._participants("coder")), 2)
        # dry_run defaults to a preview
        again = self._post({"user_ids": self._ids(*users), "role": "coder"})
        self.assertTrue(again.get_json()["dry_run"])

    def test_refused_apply_is_a_409_with_the_rows(self):
        user, bad = self._made_by("api.ok"), self._made_by("api.bad")
        bad.user_status = VaStatuses.deactive
        db.session.flush()
        response = self._post({"user_ids": self._ids(user, bad), "role": "interviewer", "dry_run": False})
        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertEqual(len(body["refused"]), 1)
        self.assertIn("nothing was changed", body["error"])
        self.assertEqual(self._participants(), [])

    def test_bad_requests(self):
        self.assertEqual(self._post({"user_ids": "x", "role": "coder"}).status_code, 400)
        self.assertEqual(self._post({"user_ids": ["a"], "role": "nope"}).status_code, 400)
        self.assertEqual(self._post({"user_ids": ["a"] * 300 + [str(i) for i in range(300)], "role": "coder"}
                                    ).status_code, 400)

    def test_non_admins_anonymous_and_missing_csrf_are_refused(self):
        user = self._made_by("api.deny")
        body = {"user_ids": self._ids(user), "role": "interviewer", "dry_run": False}
        for who in (self.base_coder_id, self.base_project_pi_id):
            self._login(who)
            self.assertEqual(self._post(body).status_code, 403)
            self.assertEqual(self.client.get(f"{API}/S001/candidates").status_code, 403)
            self.assertEqual(self.client.get(f"{API}/S001/graduation.csv").status_code, 403)
        self._login(self.base_admin_id)
        old = self.app.config.get("WTF_CSRF_ENABLED")
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            self.assertEqual(self._post(body, headers=False).status_code, 400)
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = old
        self.assertEqual(self._participants(), [])
        with self.client.session_transaction() as session:
            session.clear()
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        self.assertEqual(self._post(body).status_code, 401)

    def test_graduation_download(self):
        user = self._made_by("api.grad")
        self._post({"user_ids": self._ids(user), "role": "reviewer_data_manager", "dry_run": False})
        response = self.client.get(f"{API}/S001/graduation.csv?org_unit_code=PHC01&cadre_code=STAFF")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(response.data.decode())))
        self.assertEqual(tuple(rows[0]), HEADERS)
        self.assertEqual(sorted(r[2] for r in rows[1:]), ["data_manager", "reviewer"])
        self.assertEqual(self.client.get(f"{API}/S001/graduation.csv?role=admin").status_code, 400)
        self.assertEqual(self.client.get(f"{API}/S404/graduation.csv").status_code, 404)

    def test_panel_carries_the_bulk_and_graduation_controls(self):
        page = self.client.get("/admin/panels/training-sessions").data
        for needle in (b'id="training-find"', b'id="training-preview"', b'id="training-grad-link"',
                       b"graduation.csv", b'id="training-report-link"'):
            self.assertIn(needle, page)

    def test_admin_created_accounts_record_their_creator(self):
        email = f"mba.{uuid.uuid4().hex[:8]}@test.local"
        with mock.patch("app.services.user_account_service.send_invitation"):
            response = self.client.post(
                "/admin/api/users",
                json={"name": "Made By Admin", "email": email, "email_confirm": email, "languages": ["english"]},
                headers=self._csrf_headers())
        self.assertEqual(response.status_code, 201, response.get_json())
        created = db.session.get(VaUsers, response.get_json()["user"]["user_id"])
        self.assertEqual(created.other["created_by_user_id"], str(self.admin.user_id))
        self.assertEqual(created.other["created_via"], "admin")
        # ...and the training picker's "accounts I created" filter finds it.
        mine = {u["user_id"] for u in svc.training_candidates(
            "S001", self.admin, created_by="me", tz_name="UTC")["users"]}
        self.assertIn(str(created.user_id), mine)
