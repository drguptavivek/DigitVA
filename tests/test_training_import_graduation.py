"""Training session types, phase 3 and the review fixes
(docs/policy/training-session-types.md): the admin session import that
creates missing accounts and enrols them in one step, graduation into an
organizational project, the close checklist's trainee state, the corpus
language check (L1), the coder's own coding languages, and the corpus
eligibility count (L2, in ``test_training_session_types``)."""

import io
import uuid
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    AuthSecurityEvent,
    MapTrainingParticipant,
    MasCadre,
    VaAccessRoles,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import organization_service as org
from app.services import training_demo_service as svc
from tests.test_training_session_types import SessionTypeTestBase, fixture_corpus

API = "/admin/api/training/sessions"
GRAD_PROJECT = "GRD01"


def _csv(*lines, header="email,name,phone"):
    return io.BytesIO(("\n".join([header, *lines]) + "\n").encode())


class ImportTests(SessionTypeTestBase):
    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)

    def _post(self, code, body, kind, dry_run, name="t.csv"):
        with self._corpus():
            return self.client.post(
                f"{API}/{code}/import", headers=self._csrf_headers(), content_type="multipart/form-data",
                data={"file": (body, name), "kind": kind, "dry_run": "1" if dry_run else "0"},
            )

    def _language_events(self, user):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "coding_languages_changed")).all()

    def _participant_users(self, code):
        row = svc._find_session(code)
        return set(db.session.scalars(sa.select(MapTrainingParticipant.user_id).where(
            MapTrainingParticipant.training_session_id == row.training_session_id)))

    def test_self_coding_import_previews_then_creates_and_enrols_in_one_step(self):
        code = self._typed("self_coding", slots=3)["session_code"]
        existing = self._user("imp.existing")
        existing.vacode_language = ["hindi"]
        db.session.commit()
        email = f"imp.new.{uuid.uuid4().hex[:8]}@test.local"
        mobile = f"9{uuid.uuid4().int % 10**9:09d}"
        lines = (f"{email},New Trainee,", f",Phone Trainee,{mobile}", f"{existing.email},Ignored Name,")

        preview = self._post(code, _csv(*lines), "both", True)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        body = preview.get_json()
        self.assertEqual([r["action"] for r in body["rows"]], ["add", "add", "add"])
        self.assertEqual(body["created_users"], 2)
        self.assertEqual(sorted(r["account"] for r in body["rows"]),
                         ["English added to coding languages", "new account", "new account"])
        self.assertNotIn("sign_in_codes", body)
        db.session.expire_all()
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email)))
        self.assertEqual(self._participant_users(code), set())
        self.assertEqual(db.session.get(VaUsers, existing.user_id).vacode_language, ["hindi"])
        self.assertEqual(self._language_events(existing), [])  # a dry run audits nothing

        applied = self._post(code, _csv(*lines), "both", False)
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(applied.headers["Cache-Control"], "no-store")
        result = applied.get_json()
        self.assertEqual((result["created_users"], result["added"]), (2, 3))
        self.assertEqual(len(result["sign_in_codes"]), 1)
        self.assertNotIn(mobile, applied.get_data(as_text=True))  # the number is masked
        db.session.expire_all()
        new = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
        phone = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == mobile))
        self.assertEqual((new.vacode_language, phone.vacode_language), (["english"], ["english"]))
        self.assertEqual(db.session.get(VaUsers, existing.user_id).vacode_language, ["hindi", "english"])
        self.assertEqual(self._participant_users(code), {new.user_id, phone.user_id, existing.user_id})
        events = self._language_events(existing)
        self.assertEqual([e.detail["old"] for e in events], [["hindi"]])
        self.assertEqual(events[0].detail["new"], ["hindi", "english"])
        self.assertEqual(events[0].actor_user_id, self.admin.user_id)
        self.assertEqual(self._language_events(new), [])  # a new account is not a change
        # one coder participation each, carrying both grants
        self.assertEqual({g.role for g in self._grants(new, VaStatuses.active)},
                         {VaAccessRoles.coder, VaAccessRoles.interviewer})

    def test_a_refused_row_writes_nothing_not_even_the_new_accounts(self):
        code = self._typed("interviewer")["session_code"]
        inactive = self._user("imp.inactive")
        db.session.commit()
        already = self._user("imp.already")
        db.session.commit()
        svc.add_participant(code, already.email, "interviewer", self.admin)
        email = f"imp.rolled.{uuid.uuid4().hex[:8]}@test.local"
        inactive.user_status = VaStatuses.deactive
        db.session.commit()
        refused = self._post(code, _csv(f"{email},Rolled Back,", f"{inactive.email},X,"), "interviewer", False)
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertIn("existing user is inactive", refused.get_json()["error"])
        db.session.expire_all()
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email)))
        # an already-active trainee is "already", not refused
        again = self._post(code, _csv(f"{already.email},A,"), "interviewer", False)
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertEqual(again.get_json()["already"], 1)

    def test_an_enrolment_refusal_rolls_back_the_accounts_created_for_it(self):
        code = self._typed("coder", slots=1)["session_code"]
        emails = [f"imp.slot{i}.{uuid.uuid4().hex[:8]}@test.local" for i in range(2)]
        response = self._post(code, _csv(*(f"{e},Slot {i}," for i, e in enumerate(emails))), "coder", False)
        self.assertEqual(response.status_code, 409, response.get_json())
        body = response.get_json()
        self.assertEqual(body["applied"], False)
        self.assertEqual([r["action"] for r in body["rows"]], ["add", "refuse"])
        db.session.expire_all()
        self.assertEqual(db.session.scalars(sa.select(VaUsers).where(VaUsers.email.in_(emails))).all(), [])
        self.assertEqual(self._cases(code), [])

    def test_kind_must_match_the_session_type_and_legacy_sessions_take_no_import(self):
        coder = self._typed("coder", slots=1)["session_code"]
        line = f"k.{uuid.uuid4().hex[:8]}@test.local,K,"
        for code, kind in ((coder, "both"), (coder, "interviewer"), ("S001", "coder")):
            response = self._post(code, _csv(line), kind, True)
            self.assertEqual(response.status_code, 409, (code, kind))
            self.assertIn("not allowed", response.get_json()["error"])

    def test_username_and_unit_columns_are_refused(self):
        code = self._typed("interviewer")["session_code"]
        for header in ("email,name,phone,username", "email,name,org_unit_code"):
            response = self._post(code, _csv("a@test.local,A,x", header=header), "interviewer", True)
            self.assertEqual(response.status_code, 400, header)

    def test_import_is_admin_only_and_needs_csrf(self):
        code = self._typed("interviewer")["session_code"]
        no_csrf = self.client.post(f"{API}/{code}/import", content_type="multipart/form-data",
                                   data={"file": (_csv("a@test.local,A,"), "t.csv"), "kind": "interviewer"})
        self.assertIn(no_csrf.status_code, (400, 403))
        self._login(str(self.base_coder_user.user_id))
        response = self._post(code, _csv("a@test.local,A,"), "interviewer", True)
        self.assertIn(response.status_code, (302, 403))


class GraduationTestBase(SessionTypeTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=GRAD_PROJECT, project_code=GRAD_PROJECT, project_name="Graduation target",
            project_nickname="Grad", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
        ))
        db.session.flush()
        org.seed_default_organization(GRAD_PROJECT)
        top = min(org.list_levels(GRAD_PROJECT), key=lambda level: level.depth)
        org.create_unit(GRAD_PROJECT, org_level_id=top.org_level_id, unit_code="GRDU1", unit_name="Grad unit")
        cls.cadres = []
        for code in ("GRDA", "GRDB"):
            cadre = org.create_cadre(GRAD_PROJECT, cadre_code=code, cadre_name=f"Cadre {code}")
            db.session.flush()
            org.upsert_level_cadre(GRAD_PROJECT, org_level_id=top.org_level_id, cadre_id=cadre.cadre_id,
                                   allowed_roles=["site_pi", "collaborator", "collaborator_pii", "coder", "coding_tester", "reviewer", "data_manager", "interviewer"],
                               )
            cls.cadres.append(code)
        db.session.commit()

    def _real_grants(self, user, status=VaStatuses.active):
        unit = org.find_unit_by_code(GRAD_PROJECT, "GRDU1")
        return db.session.scalars(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.org_unit_id == unit.org_unit_id,
            VaUserAccessGrants.grant_status == status)).all()

    def _row(self, user, cadre="GRDA", **extra):
        return {"user_id": str(user.user_id), "org_unit_code": "GRDU1", "cadre_code": cadre, **extra}

    def _graduate(self, code, rows, **kwargs):
        return svc.graduate(code, GRAD_PROJECT, rows, self.admin, **kwargs)


class GraduationTests(GraduationTestBase):
    def test_self_coding_trainee_gets_coder_and_interviewer_once(self):
        code = self._typed("self_coding", slots=1)["session_code"]
        user = self._user("grad.both")
        self._add(code, user)
        trainees = svc.graduation_trainees(code, self.admin)["trainees"]
        self.assertEqual([(t["user_id"], t["role"]) for t in trainees], [(str(user.user_id), "both")])
        self.assertIn(["english", "English"], svc.graduation_trainees(code, self.admin)["languages"])

        preview = self._graduate(code, [self._row(user)])
        self.assertEqual(preview["rows"][0]["status"], "ready", preview)
        self.assertEqual(self._real_grants(user), [])

        saved = self._graduate(code, [self._row(user, language_codes=["english"])], dry_run=False)
        self.assertEqual((saved["rows"][0]["status"], saved["saved"]), ("saved", 1), saved)
        self.assertEqual({g.role for g in self._real_grants(user)}, {VaAccessRoles.coder, VaAccessRoles.interviewer})
        part = db.session.scalar(sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id))
        stamped = part.graduated_at
        self.assertIsNotNone(stamped)

        again = self._graduate(code, [self._row(user)], dry_run=False)
        self.assertEqual(again["rows"][0]["status"], "unchanged")
        self.assertEqual(len(self._real_grants(user)), 2)
        db.session.refresh(part)
        self.assertEqual(part.graduated_at, stamped)

    def test_only_coder_and_interviewer_never_reviewer_or_data_manager(self):
        manager, outsider = self._user("grad.rdm"), self._user("grad.out")
        svc.add_participant("S001", manager.email, "reviewer_data_manager", self.admin)
        result = self._graduate("S001", [self._row(manager), self._row(outsider)], dry_run=False)
        statuses = {r["user_id"]: (r["status"], r["reason"]) for r in result["rows"]}
        self.assertEqual(statuses[str(manager.user_id)], ("refused", svc.MESSAGES["nothing_to_graduate"]))
        self.assertEqual(statuses[str(outsider.user_id)], ("refused", svc.MESSAGES["not_a_trainee"]))
        self.assertEqual(self._real_grants(manager), [])

    def test_training_and_demo_targets_are_refused(self):
        project = db.session.get(VaProjectMaster, GRAD_PROJECT)
        for target in ("TRN01", ""):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.graduate("S001", target, [{}], self.admin)
            self.assertEqual(ctx.exception.code, "target_not_allowed")
        project.demo_training_enabled = True
        db.session.flush()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            self._graduate("S001", [{}])
        self.assertEqual(ctx.exception.code, "target_not_allowed")
        project.demo_training_enabled = False
        db.session.flush()

    def test_targets_list_only_real_active_organization_projects(self):
        now = datetime.now(UTC)
        extra = {}
        for pid, flags in (("GRDDT", {"demo_training_enabled": True}),
                           ("GRDSY", {"synthetic_demo_reset_enabled": True}),
                           ("GRDIN", {"project_status": VaStatuses.deactive})):
            extra[pid] = VaProjectMaster(
                project_id=pid, project_code=pid, project_name=pid, project_nickname=pid,
                project_status=flags.pop("project_status", VaStatuses.active),
                project_registered_at=now, project_updated_at=now,
                project_structure_mode="organization", **flags)
            db.session.add(extra[pid])
        db.session.flush()
        self._typed("coder", slots=1)
        ids = [pid for pid, _ in svc.graduation_trainees("S001", self.admin)["targets"]]
        self.assertIn(GRAD_PROJECT, ids)
        for excluded in ("TRN01", "GRDDT", "GRDSY", "GRDIN"):
            self.assertNotIn(excluded, ids)

    def test_cadre_change_and_reactivation_need_confirmation(self):
        code = self._typed("coder", slots=2)["session_code"]
        changed, revoked = self._user("grad.cadre"), self._user("grad.revoked")
        self._add(code, changed)
        self._add(code, revoked)
        self._graduate(code, [self._row(changed), self._row(revoked)], dry_run=False)
        self._real_grants(revoked)[0].grant_status = VaStatuses.deactive
        db.session.flush()

        rows = [self._row(changed, cadre="GRDB"), self._row(revoked)]
        preview = self._graduate(code, rows, dry_run=False)
        self.assertEqual([r["status"] for r in preview["rows"]], ["needs_confirmation", "needs_confirmation"])
        self.assertEqual([r["user_id"] for r in preview["cadre_changes"]], [str(changed.user_id)])
        self.assertEqual([r["user_id"] for r in preview["reactivations"]], [str(revoked.user_id)])
        self.assertEqual(self._real_grants(revoked), [])  # nothing applied without confirmation

        confirmed = self._graduate(code, rows, dry_run=False, confirm=[str(changed.user_id), str(revoked.user_id)])
        self.assertEqual([r["status"] for r in confirmed["rows"]], ["saved", "saved"])
        cadre_b = db.session.scalar(sa.select(MasCadre).where(
            MasCadre.project_id == GRAD_PROJECT, MasCadre.cadre_code == "GRDB"))
        self.assertEqual(self._real_grants(changed)[0].cadre_id, cadre_b.cadre_id)
        self.assertEqual(len(self._real_grants(revoked)), 1)

    def test_a_refused_row_does_not_block_the_others(self):
        code = self._typed("interviewer")["session_code"]
        good, bad, odd = self._user("grad.good"), self._user("grad.bad"), self._user("grad.odd")
        for user in (good, bad, odd):
            svc.add_participant(code, user.email, "interviewer", self.admin)
        rows = [self._row(good), {**self._row(bad), "org_unit_code": "NOPE"},
                self._row(odd, language_codes=["klingon"]), self._row(good)]
        result = self._graduate(code, rows, dry_run=False)
        self.assertEqual([r["status"] for r in result["rows"]], ["saved", "refused", "refused", "refused"])
        self.assertIn("unit", result["rows"][1]["reason"])
        self.assertEqual(result["rows"][2]["reason"], svc.MESSAGES["invalid_languages"])
        self.assertEqual(result["rows"][3]["reason"], svc.MESSAGES["not_a_trainee"])  # named twice
        self.assertEqual({g.role for g in self._real_grants(good)}, {VaAccessRoles.interviewer})

    def test_trainees_list_the_close_checklist_state_and_close_keeps_drafts(self):
        code = self._typed("interviewer")["session_code"]
        user = self._user("grad.sync")
        svc.add_participant(code, user.email, "interviewer", self.admin)
        row = svc._find_session(code)
        form = svc._web_form()
        draft = VaWebIntakeDraft(project_id="TRN01", site_id=form.site_id, form_id=form.form_id,
                                 user_id=user.user_id, unique_id=f"u-{uuid.uuid4().hex[:8]}",
                                 org_unit_id=row.org_unit_id)
        db.session.add(draft)
        db.session.flush()
        trainee = svc.graduation_trainees(code, self.admin)["trainees"][0]
        self.assertEqual((trainee["open_drafts"], trainee["role"]), (1, "interviewer"))
        self.assertIsNotNone(trainee["last_sync"])
        svc.close_training_session(code, self.admin)
        self.assertIsNotNone(db.session.get(VaWebIntakeDraft, draft.draft_id))  # never discarded


class GraduationApiTests(GraduationTestBase):
    def test_trainees_and_graduate_routes(self):
        code = self._typed("coder", slots=1)["session_code"]
        user = self._user("grad.api")
        self._add(code, user)
        self._login(self.base_admin_id)
        listed = self.client.get(f"{API}/{code}/trainees")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["trainees"][0]["role"], "coder")
        body = {"project_id": GRAD_PROJECT, "rows": [self._row(user)], "dry_run": False}
        self.assertIn(self.client.post(f"{API}/{code}/graduate", json=body).status_code, (400, 403))
        saved = self.client.post(f"{API}/{code}/graduate", json=body, headers=self._csrf_headers())
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(saved.get_json()["rows"][0]["status"], "saved")
        refused = self.client.post(f"{API}/{code}/graduate", json={**body, "project_id": "TRN01"},
                                   headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 409)
        self._login(str(self.base_coder_user.user_id))
        self.assertIn(self.client.get(f"{API}/{code}/trainees").status_code, (302, 403))


class CorpusLanguageTests(SessionTypeTestBase):
    def test_a_listed_case_in_another_language_refuses_the_corpus(self):
        sid = self.source_sids[5]
        db.session.execute(sa.update(VaSubmissions).where(VaSubmissions.va_sid == sid)
                           .values(va_narration_language="hindi"))
        with fixture_corpus(self.source_sids[1:11], size=10), mock.patch.object(svc.log, "warning") as warn:
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.typed_corpus()
        self.assertEqual(ctx.exception.code, "corpus_missing")
        self.assertIn(sid, warn.call_args.args[-1])
        with fixture_corpus(self.source_sids[6:16], size=10):
            self.assertEqual(len(svc.typed_corpus()), 10)  # the English cases pass


class OwnCodingLanguagesTests(SessionTypeTestBase):
    def test_only_a_coder_may_set_languages(self):
        user = self._user("lang.noncoder")
        db.session.commit()
        self._login(str(user.user_id))
        refused = self.client.patch("/api/v1/profile/languages", json={"languages": ["english"]},
                                    headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 403)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaUsers, user.user_id).vacode_language, ["english"])
        self.assertEqual(db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id)).all(), [])

    def test_coder_sets_own_languages_with_the_admin_rule(self):
        user = self.base_coder_user
        user.vacode_language = ["hindi"]
        db.session.commit()
        self._login(str(user.user_id))
        url = "/api/v1/profile/languages"
        self.assertEqual(self.client.patch(url, json={"languages": ["english"]}).status_code, 400)  # CSRF
        saved = self.client.patch(url, json={"languages": ["english", "english"]}, headers=self._csrf_headers())
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(saved.get_json()["languages"], ["english"])
        for body in ({"languages": []}, {"languages": ["klingon"]}, {"languages": "english"}, [1]):
            self.assertEqual(self.client.patch(url, json=body, headers=self._csrf_headers()).status_code, 400, body)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaUsers, user.user_id).vacode_language, ["english"])
        events = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "coding_languages_changed")).all()
        self.assertEqual([(e.detail["old"], e.detail["new"]) for e in events], [(["hindi"], ["english"])])
