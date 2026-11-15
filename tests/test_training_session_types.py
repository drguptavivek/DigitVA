"""Training session types (docs/policy/training-session-types.md), phase 1:
the type and its slot rule, per-coder copies at add time from the typed
corpus, grants and areas by type, and the admin-only report of typed
sessions. Phase 2 (self-coding per session and the two queues) is in
``test_training_queues.py``."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    MapTrainingCase,
    MapTrainingParticipant,
    MasOrgUnit,
    MasTrainingSession,
    VaAccessRoles,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import training_demo_service as svc
from tests.training_demo_fixtures import SRC_FORM, TrainingDemoTestBase


@contextmanager
def fixture_corpus(sids, form_id=SRC_FORM, size=None, lines=None):
    """``english_v1.txt`` in a temporary corpus dir holding *sids* of *form_id*
    (or the raw *lines*); *size* overrides ``CORPUS_SIZE``."""
    with tempfile.TemporaryDirectory() as folder:
        body = lines if lines is not None else [f"{form_id},{sid}" for sid in sids]
        Path(folder, f"{svc.CORPUS_NAME}.txt").write_text("# test corpus\n" + "\n".join(body) + "\n")
        patches = [mock.patch.object(svc, "CORPUS_DIR", Path(folder))]
        if size is not None:
            patches.append(mock.patch.object(svc, "CORPUS_SIZE", size))
        for patch in patches:
            patch.start()
        try:
            yield
        finally:
            for patch in reversed(patches):
                patch.stop()


class SessionTypeTestBase(TrainingDemoTestBase):
    def _corpus(self, **kwargs):
        return fixture_corpus(self.source_sids[1:201], **kwargs)

    def _typed(self, session_type, slots=None, name="Typed"):
        with self._corpus():
            return svc.create_training_session(name, self.admin, session_type=session_type, coder_slots=slots)

    def _cases(self, code):
        row = svc._find_session(code)
        return db.session.scalars(
            sa.select(MapTrainingCase).where(MapTrainingCase.training_session_id == row.training_session_id)
        ).all()

    def _add(self, code, user, roles="coder"):
        with self._corpus():
            return svc.add_participant(code, user.email, roles, self.admin)


class TypeAndSlotRuleTests(SessionTypeTestBase):
    def _insert(self, session_type, slots, code):
        root = db.session.get(MasOrgUnit, svc._find_session("S001").org_unit_id)
        with db.session.begin_nested():
            db.session.add(MasTrainingSession(
                project_id="TRN01", session_code=code, name="x", created_by=self.admin.user_id,
                org_unit_id=root.org_unit_id, coder_slots=slots, session_type=session_type,
            ))
            db.session.flush()

    def test_the_check_ties_zero_slots_to_the_interviewer_type(self):
        for session_type, slots in (("interviewer", 1), ("coder", 0), (None, 0), ("reviewer", 1), ("coder", 101)):
            with self.assertRaises(IntegrityError, msg=(session_type, slots)):
                self._insert(session_type, slots, "S900")

    def test_service_without_a_type_is_legacy_and_unknown_types_are_refused(self):
        self.assertIsNone(svc.get_training_session("S001")["session_type"])
        self.assertEqual(svc.get_training_session("S001")["cases_total"], 200)  # legacy copies at create
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("x", self.admin, session_type="reviewer")
        self.assertEqual(ctx.exception.code, "invalid_session_type")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("x", self.admin, session_type="interviewer", coder_slots=3)
        self.assertEqual(ctx.exception.code, "invalid_coder_slots")

    def test_interviewer_session_copies_nothing_and_has_no_slot_unit(self):
        summary = self._typed("interviewer")
        self.assertEqual(summary["session_type"], "interviewer")
        self.assertEqual((summary["coder_slots_total"], summary["cases_total"], summary["slots"]), (0, 0, []))
        self.assertEqual(self._cases(summary["session_code"]), [])
        root = svc._find_session(summary["session_code"]).org_unit_id
        self.assertIsNotNone(db.session.get(MasOrgUnit, root))
        self.assertEqual(db.session.scalar(
            sa.select(sa.func.count()).select_from(MasOrgUnit).where(MasOrgUnit.parent_org_unit_id == root)), 0)

    def test_coder_session_needs_the_corpus_and_copies_nothing_at_create(self):
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("No corpus", self.admin, session_type="coder", coder_slots=2)
        self.assertEqual(ctx.exception.code, "corpus_missing")
        with fixture_corpus(self.source_sids[1:150]):  # short
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.create_training_session("Short", self.admin, session_type="coder", coder_slots=2)
        self.assertEqual(ctx.exception.code, "corpus_missing")
        with fixture_corpus([], lines=["no-comma-here"] * 200):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.create_training_session("Bad", self.admin, session_type="coder", coder_slots=2)
        self.assertEqual(ctx.exception.code, "corpus_missing")
        self.assertEqual(len(svc.list_training_sessions()), 1)
        summary = self._typed("self_coding", slots=2)
        self.assertEqual((summary["coder_slots_total"], summary["cases_total"]), (2, 0))
        self.assertEqual(self._cases(summary["session_code"]), [])


class PerCoderCopyTests(SessionTypeTestBase):
    def test_coder_add_copies_their_own_ten_on_their_slot(self):
        summary = self._typed("coder", slots=3)
        code = summary["session_code"]
        coder = self._user("typedcoder")
        self.assertEqual(self._add(code, coder)["coder_slot"], 1)
        cases = self._cases(code)
        self.assertEqual(len(cases), 10)
        self.assertEqual({c.coder_slot for c in cases}, {1})
        self.assertEqual(sorted(c.case_number for c in cases), list(range(1, 11)))
        self.assertTrue({c.source_va_sid for c in cases} <= set(self.source_sids[1:201]))
        slot_unit = svc._unit_by_code(svc.slot_unit_code(code, 1))
        sids = [c.va_sid for c in cases]
        self.assertEqual(set(db.session.scalars(
            sa.select(VaSubmissions.org_unit_id).where(VaSubmissions.va_sid.in_(sids)))), {slot_unit.org_unit_id})
        self.assertEqual(set(db.session.scalars(
            sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid.in_(sids)))),
            {"ready_for_coding"})
        # counts come from the rows, not slots * 10 (N12)
        listed = next(s for s in svc.list_training_sessions() if s["session_code"] == code)
        self.assertEqual((listed["cases_total"], listed["coder_slots_total"]), (10, 3))
        self.assertEqual(svc.get_training_session(code)["cases_total"], 10)

    def test_overlapping_draws_are_separate_copies_and_readd_copies_nothing(self):
        overlap = self.source_sids[1:11]  # a corpus of ten: both coders draw all of it
        with fixture_corpus(overlap, size=10):
            code = svc.create_training_session("Overlap", self.admin, session_type="coder", coder_slots=2)[
                "session_code"]
            one, two = self._user("ov1"), self._user("ov2")
            svc.add_participant(code, one.email, "coder", self.admin)
            svc.add_participant(code, two.email, "coder", self.admin)
            cases = self._cases(code)
            self.assertEqual(len(cases), 20)
            by_slot = {}
            for case in cases:
                by_slot.setdefault(case.coder_slot, []).append(case)
            self.assertEqual({c.source_va_sid for c in by_slot[1]}, {c.source_va_sid for c in by_slot[2]})
            self.assertEqual(len({c.va_sid for c in cases}), 20)
            self.assertEqual(sorted(c.case_number for c in cases), list(range(1, 21)))
            # attachments are copied per copy (src-001..003 carry one each)
            sids = [c.va_sid for c in cases]
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionAttachments)
                                               .where(VaSubmissionAttachments.va_sid.in_(sids))), 6)
            svc.remove_participant(code, one.user_id, "coder", self.admin)
            again = svc.add_participant(code, one.email, "coder", self.admin)
            self.assertEqual(again["coder_slot"], 1)
            self.assertEqual(len(self._cases(code)), 20)

    def test_a_failed_add_rolls_back_copies_and_removes_objects(self):
        with fixture_corpus(self.source_sids[1:11], size=10):
            code = svc.create_training_session("Rollback", self.admin, session_type="coder", coder_slots=1)[
                "session_code"]
            coder = self._user("rollback")
            removed = []
            with mock.patch.object(svc, "_check_grant", side_effect=svc.TrainingDemoError("grant_not_allowed")), \
                    mock.patch.object(svc, "_remove_objects", side_effect=removed.extend):
                with self.assertRaises(svc.TrainingDemoError):
                    svc.add_participant(code, coder.email, "coder", self.admin)
        self.assertEqual(len(removed), 3)  # the three attachment objects copied
        for target in removed:
            self.assertTrue(os.path.exists(os.path.join(self._tmp.name, target.va_form_id, "media", target.storage_name)))
            svc._remove_objects([target])
        self.assertEqual(self._cases(code), [])
        self.assertIsNone(svc._find_participant(svc._find_session(code), coder.user_id, "coder"))

    def test_coder_without_the_corpus_language_is_refused_before_any_copy(self):
        code = self._typed("coder", slots=1)["session_code"]
        coder = self._user("hindionly")
        coder.vacode_language = ["hindi"]
        db.session.flush()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            self._add(code, coder)
        self.assertEqual(ctx.exception.code, "coder_language_missing")
        self.assertIn("English", ctx.exception.message)
        self.assertEqual(self._cases(code), [])
        with self._corpus():
            plan = svc.bulk_add_participants(code, [str(coder.user_id)], ["coder"], self.admin, dry_run=True)
        self.assertEqual(plan["rows"][0]["action"], "refuse")

    def test_bulk_add_copies_each_new_coder_in_one_pass_and_dry_run_writes_nothing(self):
        code = self._typed("coder", slots=3)["session_code"]
        users = [self._user(f"bulk{i}") for i in range(2)]
        ids = [str(u.user_id) for u in users]
        with self._corpus():
            plan = svc.bulk_add_participants(code, ids, ["coder"], self.admin, dry_run=True)
            self.assertEqual([r["action"] for r in plan["rows"]], ["add", "add"])
            self.assertEqual(self._cases(code), [])
            with mock.patch.object(svc, "_load_corpus_rows", wraps=svc._load_corpus_rows) as loads:
                result = svc.bulk_add_participants(code, ids, ["coder"], self.admin, dry_run=False)
        self.assertTrue(result["applied"])
        self.assertEqual(loads.call_count, 1)
        cases = self._cases(code)
        self.assertEqual(len(cases), 20)
        self.assertEqual({c.coder_slot for c in cases}, {1, 2})

    def test_bulk_typed_coders_are_capped_and_need_the_corpus(self):
        code = self._typed("coder", slots=3)["session_code"]
        user = self._user("cap")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.bulk_add_participants(code, [str(user.user_id)], ["coder"], self.admin, dry_run=True)
        self.assertEqual(ctx.exception.code, "corpus_missing")
        many = [str(user.user_id)] + [f"00000000-0000-0000-0000-{i:012d}" for i in range(50)]
        with self._corpus(), self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.bulk_add_participants(code, many, ["coder"], self.admin, dry_run=True)
        self.assertEqual(ctx.exception.code, "bulk_too_many_coders")

    def test_multi_form_corpus_copies_each_forms_attachments(self):
        second = self._second_source_form()
        lines = [f"{SRC_FORM},{sid}" for sid in self.source_sids[1:10]] + [f"{second},src2-001"]
        with fixture_corpus([], lines=lines, size=10):
            code = svc.create_training_session("Two forms", self.admin, session_type="coder", coder_slots=1)[
                "session_code"]
            svc.add_participant(code, self._user("twoforms").email, "coder", self.admin)
        cases = self._cases(code)
        self.assertIn("src2-001", {c.source_va_sid for c in cases})
        copy = next(c.va_sid for c in cases if c.source_va_sid == "src2-001")
        attachment = db.session.scalar(sa.select(VaSubmissionAttachments).where(VaSubmissionAttachments.va_sid == copy))
        self.assertIsNotNone(attachment)
        with open(attachment.local_path, "rb") as handle:
            self.assertEqual(handle.read(), b"second-form-bytes")

    def _second_source_form(self) -> str:
        from datetime import datetime

        from app.models import VaForms, VaSubmissionPayloadVersion
        from app.services.attachment_service import generate_storage_name
        from app.services.submission_payload_version_service import write_payload_version
        from tests.training_demo_fixtures import source_payload

        form_id = "TRNSRC000002"
        form_type = self._ensure_form_type("WHO_2022_VA")
        db.session.add(VaForms(
            form_id=form_id, project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID, odk_form_id="src2",
            odk_project_id="1", form_type="WHO VA 2022", form_type_id=form_type.form_type_id, form_source="odk",
            form_status=VaStatuses.active,
        ))
        db.session.flush()
        sub = VaSubmissions(
            va_sid="src2-001", va_form_id=form_id, va_data_collector="Real", va_uniqueid_masked="M2",
            va_consent="yes", va_narration_language="english", va_deceased_age=40, va_deceased_gender="male",
            va_catcount={}, va_category_list=[], va_submission_date=datetime(2024, 5, 1),
        )
        db.session.add(sub)
        db.session.flush()
        version = VaSubmissionPayloadVersion(va_sid="src2-001", version_status="active")
        write_payload_version(version, {**source_payload(7), "sid": "src2-001", "form_def": form_id}, new=True)
        db.session.add(version)
        db.session.flush()
        sub.active_payload_version_id = version.payload_version_id
        name = generate_storage_name("img_2.jpg")
        folder = os.path.join(self._tmp.name, form_id, "media")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(b"second-form-bytes")
        db.session.add(VaSubmissionAttachments(
            va_sid="src2-001", filename="img_2.jpg", storage_name=name, local_path=os.path.join(folder, name),
            mime_type="image/jpeg", exists_on_odk=True, source_state="available",
        ))
        db.session.flush()
        return form_id


class RolesAndGrantsByTypeTests(SessionTypeTestBase):
    def test_roles_outside_the_type_are_refused(self):
        coder_code = self._typed("coder", slots=1, name="C")["session_code"]
        interview_code = self._typed("interviewer", name="I")["session_code"]
        user = self._user("roles")
        db.session.commit()  # the refusals roll back; keep the setup
        for code, role in ((coder_code, "interviewer"), (coder_code, "reviewer_data_manager"),
                           (coder_code, "death_reporter"), (interview_code, "coder"),
                           (interview_code, "reviewer_data_manager"), (interview_code, "death_reporter")):
            with self.assertRaises(svc.TrainingDemoError, msg=(code, role)) as ctx:
                self._add(code, user, role)
            self.assertEqual(ctx.exception.code, "role_not_in_session_type")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.bulk_add_participants(interview_code, [str(user.user_id)], ["interview_supervisor"], self.admin)
        self.assertEqual(ctx.exception.code, "role_not_in_session_type")
        supervisor = self._add(interview_code, user, "interview_supervisor")  # single add only
        self.assertEqual(supervisor["role"], "interview_supervisor")
        interviewer = self._add(interview_code, self._user("intv"), "interviewer")
        self.assertIsNone(interviewer["coder_slot"])
        # legacy sessions take every role, as before
        self.assertEqual(svc.add_participant("S001", self._user("legacy").email, "death_reporter",
                                             self.admin)["role"], "death_reporter")

    def test_self_coding_coder_gets_coder_and_interviewer_on_the_slot_that_flip_on_close(self):
        code = self._typed("self_coding", slots=1)["session_code"]
        user = self._user("selfcoder")
        self._add(code, user)
        unit = svc._unit_by_code(svc.slot_unit_code(code, 1))
        grants = self._grants(user)
        self.assertEqual({(g.role, g.org_unit_id) for g in grants},
                         {(VaAccessRoles.coder, unit.org_unit_id), (VaAccessRoles.interviewer, unit.org_unit_id)})
        participant = svc._find_participant(svc._find_session(code), user.user_id, "coder")
        self.assertEqual(set(participant.grant_ids), {g.grant_id for g in grants})
        svc.close_training_session(code, self.admin)
        self.assertEqual({g.grant_status for g in self._grants(user)}, {VaStatuses.deactive})
        svc.reopen_training_session(code, self.admin)
        self.assertEqual({g.grant_status for g in self._grants(user)}, {VaStatuses.active})

    def test_coder_session_coder_gets_only_a_coder_grant(self):
        code = self._typed("coder", slots=1)["session_code"]
        user = self._user("plaincoder")
        self._add(code, user)
        self.assertEqual({g.role for g in self._grants(user)}, {VaAccessRoles.coder})


class AreasByTypeTests(SessionTypeTestBase):
    def test_areas_follow_the_session_type(self):
        interview_code = self._typed("interviewer", name="I")["session_code"]
        coder_code = self._typed("coder", slots=1, name="C")["session_code"]
        self_code = self._typed("self_coding", slots=1, name="SC")["session_code"]
        interviewer, coder, self_coder = self._user("ai"), self._user("ac"), self._user("asc")
        self._add(interview_code, interviewer, "interviewer")
        self._add(coder_code, coder)
        self._add(self_code, self_coder)
        expected = {
            interviewer: {"interview"},
            coder: {"coding"},
            self_coder: {"interview", "coding"},
        }
        for user, areas in expected.items():
            self.assertEqual({a for a in ("interview", "coding", "review") if svc.may_use_area(user.user_id, a)},
                             areas, user.email)
            summary = svc.me_summary(user.user_id)
            self.assertEqual(set(summary["areas"]), areas)
        self.assertEqual(svc.me_summary(self_coder.user_id)["session_types"], ["self_coding"])
        self.assertEqual(svc.me_summary(coder.user_id)["participations"][0]["session_type"], "coder")
        # legacy: reviewer_data_manager still opens review, a legacy coder coding
        rdm = self._user("legacyrdm")
        svc.add_participant("S001", rdm.email, "reviewer_data_manager", self.admin)
        self.assertTrue(svc.may_use_area(rdm.user_id, "review"))
        self.assertEqual(svc.me_summary(rdm.user_id)["session_types"], [None])

    def test_me_access_keeps_its_training_keys_and_adds_session_types(self):
        code = self._typed("coder", slots=1)["session_code"]
        user = self._user("access")
        self._add(code, user)
        self._login(str(user.user_id))
        training = self.client.get("/api/v1/me/access").get_json()["training"]
        for key in ("project_id", "areas", "pending", "project"):
            self.assertIn(key, training)
        self.assertEqual(training["session_types"], ["coder"])
        self.assertEqual(training["areas"], ["coding"])


class TypedReportTests(SessionTypeTestBase):
    def test_typed_session_report_is_admin_only_and_legacy_rdm_keeps_it(self):
        from app.services import training_report_service as report

        rdm = self._user("reportrdm")
        svc.add_participant("S001", rdm.email, "reviewer_data_manager", self.admin)
        self.assertEqual(report.authorized_session("S001", rdm).session_code, "S001")
        code = self._typed("coder", slots=1)["session_code"]
        row = svc._find_session(code)
        # a reviewer participation cannot be added to a typed session; write one directly
        db.session.add(MapTrainingParticipant(
            training_session_id=row.training_session_id, user_id=rdm.user_id, role="reviewer_data_manager",
            grant_ids=[], added_by=self.admin.user_id,
        ))
        db.session.flush()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            report.authorized_session(code, rdm)
        self.assertEqual(ctx.exception.code, "report_forbidden")
        self.assertEqual({s["session_code"] for s in report.sessions_for_viewer(rdm)}, {"S001"})
        self.assertEqual(report.authorized_session(code, self.admin).session_code, code)


class BulkPreviewDrawTests(SessionTypeTestBase):
    def test_preview_refuses_an_ineligible_drawn_case_like_the_apply(self):
        refused_sid = self.source_sids[0]  # consent "no"
        code = None
        with fixture_corpus([refused_sid, *self.source_sids[1:10]], size=10):
            code = svc.create_training_session("Ineligible", self.admin, session_type="coder", coder_slots=1)[
                "session_code"]
            user = self._user("preview")
            db.session.commit()  # the refusals roll back; keep the user
            for dry_run in (True, False):
                with self.assertRaises(svc.TrainingDemoError, msg=dry_run) as ctx:
                    svc.bulk_add_participants(code, [str(user.user_id)], ["coder"], self.admin, dry_run=dry_run)
                self.assertEqual(ctx.exception.code, "corpus_cases_ineligible")
                self.assertIn("1 case(s)", ctx.exception.message)
        self.assertEqual(self._cases(code), [])
