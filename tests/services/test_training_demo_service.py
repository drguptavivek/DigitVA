"""Training & demo project: setup, sessions, participants, grants, onboarding.

A fake source form (see tests/training_demo_fixtures.py) stands in for the real
ODK form.
"""

import hashlib
import os
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MapTrainingCase,
    MapTrainingParticipant,
    MasOrgUnit,
    MasTrainingSession,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaFinalAssessments,
    VaProjectMaster,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUsers,
)
from app.services import training_demo_service as svc
from app.services.attachment_service import resolve_attachment_record
from app.services.authz import Action, scope_filter
from app.services.coder_workflow_service import get_pick_available_forms
from tests.training_demo_fixtures import (
    SOURCE_COUNT,
    SRC_FORM,
    TrainingDemoTestBase,
    source_payload,
)


class SetupAndSessionTests(TrainingDemoTestBase):
    def test_project_is_configured_as_decided(self):
        from app.routes.api.organization import project_instrument_and_extensions

        project = db.session.get(VaProjectMaster, "TRN01")
        self.assertEqual(project.project_structure_mode, "organization")
        self.assertEqual(project.icd_classification, "icd11")
        self.assertEqual(project.cod_entry_mode, "doris")
        self.assertFalse(project.masked_cod_required)
        self.assertFalse(project.narrative_qa_enabled)
        self.assertFalse(project.social_autopsy_enabled)
        self.assertFalse(project.reviewer_social_autopsy_enabled)
        self.assertFalse(project.demo_training_enabled)
        self.assertEqual(project.coding_intake_mode, "pick_and_choose")
        self.assertEqual(project.web_intake_available_locales, ["en"])
        self.assertEqual(project.web_intake_narration_languages, ["english", "hindi"])
        self.assertEqual(project.recode_window_minutes, 60)
        _code, extensions = project_instrument_and_extensions(project)
        self.assertEqual(
            set(extensions),
            {"digitva_core", "doris_support_whova_2022", "narration_language", "death_summary",
             "medical_records", "geography"},
        )

    def test_setup_updates_the_narration_languages_of_an_existing_project(self):
        project = db.session.get(VaProjectMaster, "TRN01")
        project.web_intake_narration_languages = ["english"]
        db.session.flush()
        self.assertEqual(svc.setup_training_project(), {"project": False, "cadre": False, "units": 0})
        self.assertEqual(project.web_intake_narration_languages, ["english", "hindi"])
        self.assertEqual(project.web_intake_available_locales, ["en"])

    def test_setup_resets_the_recode_window_of_an_existing_project(self):
        project = db.session.get(VaProjectMaster, "TRN01")
        project.recode_window_minutes = 1440
        db.session.flush()
        self.assertEqual(svc.setup_training_project(), {"project": False, "cadre": False, "units": 0})
        self.assertEqual(project.recode_window_minutes, 60)

    def test_setup_is_idempotent(self):
        before = db.session.scalar(sa.select(sa.func.count()).select_from(MasOrgUnit))
        again = svc.setup_training_project()
        self.assertEqual(again, {"project": False, "cadre": False, "units": 0})
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MasOrgUnit)), before)

    def test_session_has_200_copies_in_20_slots_of_10(self):
        slots = self._session_sids()
        self.assertEqual(sorted(slots), list(range(1, 21)))
        self.assertTrue(all(len(sids) == 10 for sids in slots.values()))
        self.assertEqual(self.first["cases_total"], 200)
        self.assertEqual(self.first["session_code"], "S001")
        # Case n is trn-S001-n, in slot ((n-1)//10)+1, routed to that slot's unit.
        sub = db.session.get(VaSubmissions, "trn-S001-25")
        number_row = db.session.get(MapTrainingCase, "trn-S001-25")
        self.assertEqual(number_row.coder_slot, 3)
        unit = db.session.get(MasOrgUnit, sub.org_unit_id)
        self.assertEqual(unit.unit_code, "S001_C03")
        self.assertEqual(sub.va_form_id, self._trn_form_id())
        states = set(db.session.scalars(
            sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid.in_(
                sa.select(MapTrainingCase.va_sid)))
        ))
        self.assertEqual(states, {"ready_for_coding"})

    def test_first_eligible_cases_are_chosen_in_order_and_refused_consent_skipped(self):
        first = db.session.get(MapTrainingCase, "trn-S001-1")
        last = db.session.get(MapTrainingCase, "trn-S001-200")
        self.assertEqual(first.source_va_sid, "src-001")  # src-000 has no consent
        self.assertEqual(last.source_va_sid, "src-200")
        self.assertEqual(first.source_final_cod, "J18.9")
        self.assertIsNone(last.source_final_cod)

    def test_copies_are_pseudonymised_and_keep_other_answers(self):
        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(VaSubmissionPayloadVersion.va_sid == "trn-S001-1")
        )
        payload = version.payload_data
        self.assertTrue(payload["Id10017"])  # present before asserting absence
        self.assertNotEqual(payload["Id10017"], source_payload(1)["Id10017"])
        self.assertIn(payload["Id10017"], payload["Id10476"])
        self.assertNotIn("Kumarasamy", payload["Id10476"])
        self.assertNotIn("Temple Road", payload["Id10476"])
        self.assertEqual(payload["Id10099"], "Chest pain for two weeks")
        self.assertEqual(payload["Id10019"], "female")
        self.assertEqual(payload["sid"], "trn-S001-1")
        self.assertEqual(payload["form_def"], self._trn_form_id())
        self.assertNotIn("org_district_code", payload)
        self.assertEqual(payload["SubmitterName"], "Training interviewer")
        self.assertEqual(payload["SubmitterID"], "training-submitter")
        self.assertEqual(payload["DeviceID"], "training-device")
        self.assertNotIn("death_register_id", payload)
        every = " ".join(
            str(v.payload_data) for v in db.session.scalars(
                sa.select(VaSubmissionPayloadVersion).where(
                    VaSubmissionPayloadVersion.va_sid.like("trn-S001-%")))
        )
        for needle in (
            "Kumarasamy", "Temple Road", "REAL_DISTRICT", "Real Interviewer", "real-submitter-id",
            "real-device-id", "DR-REAL-1",
        ):
            self.assertNotIn(needle, every)

    def test_same_name_same_fake_inside_the_case(self):
        payload = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion.payload_data).where(
                VaSubmissionPayloadVersion.va_sid == "trn-S001-7")
        )
        self.assertIn(payload["Id10007"], f"{payload['Id10017']} {payload['Id10018']}")
        self.assertTrue(payload["Id10061"].endswith(payload["Id10018"]))

    def test_new_unique_ids_and_no_source_coding_copied(self):
        sub = db.session.get(VaSubmissions, "trn-S001-1")
        self.assertEqual(sub.va_uniqueid_masked, "T-S001-001")
        self.assertEqual(sub.va_data_collector, "Training interviewer")
        copied = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaFinalAssessments).where(
                VaFinalAssessments.va_sid.like("trn-S001-%"))
        )
        self.assertEqual(copied, 0)
        self.assertEqual(len({s for (s,) in db.session.execute(
            sa.select(VaSubmissions.va_uniqueid_masked).where(VaSubmissions.va_sid.like("trn-S001-%")))}), 200)

    def test_source_rows_are_not_modified(self):
        sub = db.session.get(VaSubmissions, "src-001")
        self.assertEqual(sub.va_data_collector, "Real Interviewer")
        payload = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion.payload_data).where(
                VaSubmissionPayloadVersion.va_sid == "src-001")
        )
        self.assertEqual(payload, source_payload(1))
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissions).where(
                VaSubmissions.va_form_id == SRC_FORM)), SOURCE_COUNT)

    def test_attachments_copied_with_same_bytes_and_new_storage_names(self):
        rows = db.session.scalars(
            sa.select(VaSubmissionAttachments).where(VaSubmissionAttachments.va_sid.like("trn-S001-%"))
        ).all()
        self.assertEqual({r.va_sid for r in rows}, {"trn-S001-1", "trn-S001-2", "trn-S001-3"})
        source_names = set(db.session.scalars(
            sa.select(VaSubmissionAttachments.storage_name).where(VaSubmissionAttachments.va_sid.like("src-%"))))
        for row in rows:
            self.assertNotIn(row.storage_name, source_names)
            self.assertTrue(row.exists_on_odk)
            record = resolve_attachment_record(row.storage_name)
            self.assertEqual(record.va_sid, row.va_sid)
            path = os.path.join(self._tmp.name, record.va_form_id, "media", row.storage_name)
            with open(path, "rb") as handle:
                number = int(row.va_sid.rsplit("-", 1)[1])
                self.assertEqual(handle.read(), self.source_bytes[f"src-{number:03d}"])

    def test_second_session_leaves_the_first_intact(self):
        before = hashlib.sha256(repr(sorted(
            (sid, str(p)) for sid, p in db.session.execute(
                sa.select(VaSubmissionPayloadVersion.va_sid, VaSubmissionPayloadVersion.payload_data).where(
                    VaSubmissionPayloadVersion.va_sid.like("trn-S001-%"))))).encode()).hexdigest()
        second = svc.create_training_session("Training two", self.admin, source_form_id=SRC_FORM)
        self.assertEqual(second["session_code"], "S002")
        self.assertEqual(len(svc.list_training_sessions()), 2)
        after = hashlib.sha256(repr(sorted(
            (sid, str(p)) for sid, p in db.session.execute(
                sa.select(VaSubmissionPayloadVersion.va_sid, VaSubmissionPayloadVersion.payload_data).where(
                    VaSubmissionPayloadVersion.va_sid.like("trn-S001-%"))))).encode()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapTrainingCase).where(
            MapTrainingCase.va_sid.like("trn-S002-%"))), 200)
        self.assertEqual(second["replacements"]["names"] > 0, True)
        self.assertNotEqual(second["org_unit_id"], self.first["org_unit_id"])

    def test_listing_and_detail_shapes(self):
        listed = svc.list_training_sessions()[0]
        self.assertEqual(listed["coder_slots_total"], 20)
        self.assertEqual(listed["cases_total"], 200)
        self.assertEqual(listed["cases_coded"], 0)
        self.assertEqual(set(listed["participants_by_role"]), set(svc.PARTICIPANT_ROLES))
        detail = svc.get_training_session("S001")
        self.assertEqual(len(detail["slots"]), 20)
        self.assertTrue(all(slot["cases"] == 10 for slot in detail["slots"]))
        keyed = svc.get_session_cases("S001")
        self.assertEqual(len(keyed), 200)
        self.assertEqual(keyed[0]["source_final_cod"], "J18.9")

    def test_safeguards(self):
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=""):
            for call in (
                svc.setup_training_project,
                lambda: svc.create_training_session("x", self.admin),
                lambda: svc.add_participant("S001", "a@b.c", "coder", self.admin),
            ):
                with self.assertRaises(svc.TrainingDemoError) as ctx:
                    call()
                self.assertEqual(ctx.exception.code, "target_not_configured")
        project = db.session.get(VaProjectMaster, "TRN01")
        project.project_structure_mode = "sites"
        db.session.flush()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.setup_training_project()
        self.assertEqual(ctx.exception.code, "invalid_target")
        project.project_structure_mode = "organization"
        db.session.flush()

    def test_creation_refuses_bad_input_and_non_admin(self):
        for name in ("", "   ", "x" * 201):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.create_training_session(name, self.admin, source_form_id=SRC_FORM)
            self.assertEqual(ctx.exception.code, "invalid_name")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("ok", self.base_coder_user, source_form_id=SRC_FORM)
        self.assertEqual(ctx.exception.code, "admin_required")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("ok", self.admin, source_form_id="NOSUCHFORM1")
        self.assertEqual(ctx.exception.code, "source_form_missing")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("ok", self.admin, source_form_id=self._trn_form_id())
        self.assertEqual(ctx.exception.code, "source_is_training")
        self.assertEqual(len(svc.list_training_sessions()), 1)  # nothing half-made

    def test_too_few_source_cases_refused_and_rolled_back(self):
        # Nine eligible cases (src-001..src-009): one slot needs ten distinct ones.
        db.session.execute(
            sa.update(VaSubmissions)
            .where(VaSubmissions.va_form_id == SRC_FORM, VaSubmissions.va_sid >= "src-010")
            .values(va_consent="no")
        )
        db.session.flush()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("short", self.admin, source_form_id=SRC_FORM)
        self.assertEqual(ctx.exception.code, "not_enough_source_cases")
        self.assertEqual(len(svc.list_training_sessions()), 1)


class SessionFailureTests(TrainingDemoTestBase):
    def test_session_code_collision_with_a_unit_is_a_fixed_error(self):
        levels = {level.level_code: level for level in svc.org.list_levels("TRN01")}
        chc = svc.org.find_unit_by_code("TRN01", svc.CHC_UNIT_CODE)
        svc.org.create_unit(
            "TRN01", org_level_id=levels["phc"].org_level_id, unit_code="S002", unit_name="Taken",
            parent_org_unit_id=chc.org_unit_id,
        )
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.create_training_session("clash", self.admin, source_form_id=SRC_FORM)
        self.assertEqual(ctx.exception.code, "session_unit_conflict")
        self.assertEqual(len(svc.list_training_sessions()), 1)

    def test_failed_create_removes_the_copied_attachment_objects(self):
        folder = os.path.join(self._tmp.name, self._trn_form_id(), "media")
        before = set(os.listdir(folder))
        self.assertEqual(len(before), 3)  # the first session's copies are there
        with mock.patch.object(svc, "VaSubmissionWorkflow", side_effect=RuntimeError("boom")), \
                mock.patch.object(svc, "_remove_objects", wraps=svc._remove_objects) as remover:
            with self.assertRaises(RuntimeError):
                svc.create_training_session("fails late", self.admin, source_form_id=SRC_FORM)
        self.assertEqual(len(remover.call_args.args[0]), 3)  # the copies had been written
        self.assertEqual(set(os.listdir(folder)), before)
        self.assertEqual(len(svc.list_training_sessions()), 1)


class CheckSourceTests(TrainingDemoTestBase):
    def test_counts_only_and_nothing_written(self):
        tables = (MasTrainingSession, MapTrainingCase, VaSubmissions, VaSubmissionPayloadVersion)

        def totals():
            return [db.session.scalar(sa.select(sa.func.count()).select_from(t)) for t in tables]

        before = totals()
        result = svc.check_source(SRC_FORM, 50)
        self.assertEqual(totals(), before)
        self.assertEqual(result["cases_checked"], 50)
        self.assertEqual(result["residual_cases"], 0)
        self.assertEqual(set(result["residual_by_type"]), {"names", "addresses", "identifiers", "phones"})
        self.assertGreater(result["replacements"]["names"], 0)
        self.assertGreater(result["replacements"]["text_replacements"], 0)
        self.assertNotIn("Kumarasamy", str(result))

    def test_cli_prints_counts_only(self):
        from app.commands.training_demo import training_demo_group

        runner = self.app.test_cli_runner()
        result = runner.invoke(training_demo_group, ["check-source", "--form-id", SRC_FORM, "--limit", "20"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('"cases_checked": 20', result.output)
        for needle in ("Kumarasamy", "Temple", "Ramesh"):
            self.assertNotIn(needle, result.output)


class CorpusListTests(TrainingDemoTestBase):
    def test_frozen_list_fixes_cases_and_order(self):
        import tempfile
        from pathlib import Path

        every = [row[0].va_sid for row in svc._load_source_rows(SRC_FORM, 5, strict=False)]
        self.assertEqual(len(every), 5)
        chosen = [every[4], every[0], every[2]]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, f"{SRC_FORM}.txt").write_text("# comment\n" + "\n".join(chosen) + "\n")
            with mock.patch.object(svc, "CORPUS_DIR", Path(folder)):
                rows = svc._load_source_rows(SRC_FORM, strict=False)
                self.assertEqual([row[0].va_sid for row in rows], chosen)
                with self.assertRaises(svc.TrainingDemoError):  # fewer than one slot's ten
                    svc._load_source_rows(SRC_FORM)
            # A listed case that is no longer eligible refuses the list.
            listed = [row[0].va_sid for row in svc._load_source_rows(SRC_FORM, 12)]
            Path(folder, f"{SRC_FORM}.txt").write_text("\n".join([*listed, "src-000"]) + "\n")
            with mock.patch.object(svc, "CORPUS_DIR", Path(folder)):
                self.assertEqual(len(svc._load_source_rows(SRC_FORM, 12)), 12)
                with self.assertRaises(svc.TrainingDemoError):
                    svc._load_source_rows(SRC_FORM)

    def test_real_corpus_list_has_200_distinct_ids(self):
        sids = svc._corpus_sids("UNSW01NC0101")
        self.assertIsNotNone(sids)
        self.assertEqual(len(sids), 200)
        self.assertEqual(len(set(sids)), len(sids))


class CoderSlotsTests(TrainingDemoTestBase):
    """A session's coder slot count is an input; beyond the sources, cases repeat."""

    def _wide_session(self, sources: int, coder_slots: int) -> dict:
        import tempfile
        from pathlib import Path

        corpus = [f"src-{i:03d}" for i in range(1, sources + 1)]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, f"{SRC_FORM}.txt").write_text("\n".join(corpus) + "\n")
            with mock.patch.object(svc, "CORPUS_DIR", Path(folder)):
                return svc.create_training_session(
                    "Wide", self.admin, source_form_id=SRC_FORM, coder_slots=coder_slots)

    def test_source_order_keeps_each_slot_distinct_and_slots_different(self):
        for coder_slots, available in ((100, 200), (60, 200), (7, 25), (12, 10), (9, 13)):
            order = svc._source_order(coder_slots, available)
            self.assertEqual(len(order), coder_slots * 10)
            slots = [order[k * 10:(k + 1) * 10] for k in range(coder_slots)]
            for chosen in slots:
                self.assertEqual(len(set(chosen)), 10, (coder_slots, available))
                self.assertTrue(all(0 <= i < available for i in chosen))
            if available % 10 == 0 and available > 10:
                self.assertEqual(len({frozenset(c) for c in slots}), coder_slots, (coder_slots, available))
        self.assertEqual(svc._source_order(20, 200), list(range(200)))  # the default is unchanged

    def test_more_slots_than_sources_copy_each_source_into_distinct_cases(self):
        summary = self._wide_session(sources=25, coder_slots=7)
        session_id = summary["training_session_id"]
        rows = db.session.execute(
            sa.select(MapTrainingCase.coder_slot, MapTrainingCase.source_va_sid, MapTrainingCase.va_sid,
                      MapTrainingCase.case_number)
            .where(MapTrainingCase.training_session_id == session_id)
        ).all()
        self.assertEqual(len(rows), 70)
        self.assertEqual(sorted(r.case_number for r in rows), list(range(1, 71)))
        self.assertEqual(len({r.va_sid for r in rows}), 70)
        by_slot: dict = {}
        for r in rows:
            by_slot.setdefault(r.coder_slot, []).append(r.source_va_sid)
        self.assertEqual(sorted(by_slot), list(range(1, 8)))
        for sources in by_slot.values():
            self.assertEqual(len(sources), 10)
            self.assertEqual(len(set(sources)), 10)  # no source twice in one slot
        self.assertEqual(len({frozenset(s) for s in by_slot.values()}), 7)
        repeated = [r for r in rows if r.source_va_sid == "src-001"]
        self.assertGreater(len(repeated), 1)
        # Each copy of a repeated source is its own submission, payload and answer key.
        sids = [r.va_sid for r in repeated]
        self.assertEqual(len(db.session.scalars(sa.select(VaSubmissions.va_sid).where(
            VaSubmissions.va_sid.in_(sids))).all()), len(sids))
        versions = db.session.scalars(sa.select(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid.in_(sids))).all()
        self.assertEqual(len(versions), len(sids))
        self.assertEqual(len({v.payload_data["instanceID"] for v in versions}), len(sids))
        subs = db.session.scalars(sa.select(VaSubmissions).where(VaSubmissions.va_sid.in_(sids))).all()
        self.assertEqual(len({s.active_payload_version_id for s in subs}), len(sids))
        self.assertTrue(all(db.session.get(MapTrainingCase, sid).source_final_cod == "J18.9" for sid in sids))
        # Attachments: one row and one stored object per copy.
        attachments = db.session.scalars(sa.select(VaSubmissionAttachments).where(
            VaSubmissionAttachments.va_sid.in_(sids))).all()
        self.assertEqual(sorted(a.va_sid for a in attachments), sorted(sids))
        self.assertEqual(len({a.storage_name for a in attachments}), len(sids))
        self.assertEqual(summary["attachments_copied"], sum(
            1 for r in rows if r.source_va_sid in ("src-001", "src-002", "src-003")))
        self.assertEqual((summary["coder_slots_total"], summary["cases_total"]), (7, 70))
        listed = {s["session_code"]: s for s in svc.list_training_sessions()}[summary["session_code"]]
        self.assertEqual((listed["coder_slots_total"], listed["cases_total"]), (7, 70))
        self.assertEqual([s["slot"] for s in summary["slots"]], list(range(1, 8)))

    def test_slots_fill_up_to_the_session_count_then_refuse(self):
        summary = self._wide_session(sources=25, coder_slots=2)
        coders = [self._user(f"wide{i}") for i in range(3)]
        for user, slot in zip(coders[:2], (1, 2), strict=True):
            self.assertEqual(svc.add_participant(summary["session_code"], user.email, "coder", self.admin)["coder_slot"],
                             slot)
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant(summary["session_code"], coders[2].email, "coder", self.admin)
        self.assertEqual(ctx.exception.code, "no_free_coder_slot")

    def test_coder_slots_outside_1_to_100_are_refused(self):
        for bad in (0, 101, -1, True, "20", 20.0, None):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.create_training_session("bad", self.admin, source_form_id=SRC_FORM, coder_slots=bad)
            self.assertEqual(ctx.exception.code, "invalid_coder_slots", bad)
        self.assertEqual(len(svc.list_training_sessions()), 1)

    def test_cli_takes_coder_slots(self):
        from app.commands.training_demo import training_demo_group

        runner = self.app.test_cli_runner()
        result = runner.invoke(training_demo_group, [
            "create-session", "--name", "x", "--coder-slots", "101", "--by", self.admin.email])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(len(svc.list_training_sessions()), 1)


class ParticipantTests(TrainingDemoTestBase):
    def test_coder_without_the_slots_language_is_refused(self):
        user = self._user("nohindi")
        db.session.execute(
            sa.update(VaSubmissions).where(VaSubmissions.va_sid == "trn-S001-3").values(va_narration_language="hindi")
        )
        db.session.commit()  # the refusal rolls back; keep the setup
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", user.email, "coder", self.admin)
        self.assertEqual(ctx.exception.code, "coder_language_missing")
        self.assertIn("Hindi", ctx.exception.message)
        self.assertNotIn("English", ctx.exception.message)
        self.assertFalse(svc.has_pending_onboarding(user.user_id))  # nothing was written
        user.vacode_language = ["English", "Hindi"]
        db.session.flush()
        self.assertEqual(svc.add_participant("S001", user.email, "coder", self.admin)["coder_slot"], 1)
        # other roles need no language
        svc.add_participant("S001", self._user("nolang").email, "interviewer", self.admin)


    def test_coder_gets_next_slot_and_sees_exactly_their_ten_cases(self):
        one, two = self._user("coderone"), self._user("codertwo")
        a = svc.add_participant("S001", one.email, "coder", self.admin)
        b = svc.add_participant("S001", two.email, "coder", self.admin)
        self.assertEqual((a["coder_slot"], b["coder_slot"]), (1, 2))
        slots = self._session_sids()
        mine, theirs = self._pick_list(one), self._pick_list(two)
        self.assertEqual(len(slots[1]), 10)
        self.assertEqual(mine, slots[1])
        self.assertEqual(theirs, slots[2])
        self.assertFalse(mine & theirs)
        # The coding scope predicate agrees (the pool never offers what pick refuses).
        allowed = set(db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(
                scope_filter(one, Action.CODE), VaSubmissions.va_sid.like("trn-S001-%"))))
        self.assertEqual(allowed, slots[1])

    def test_21st_coder_refused(self):
        for n in range(20):
            svc.add_participant("S001", self._user(f"c{n}").email, "coder", self.admin)
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", self._user("c21").email, "coder", self.admin)
        self.assertEqual(ctx.exception.code, "no_free_coder_slot")
        self.assertEqual(svc.get_training_session("S001")["coder_slots_used"], 20)

    def test_two_roles_at_once_write_both_participations_and_grants(self):
        user = self._user("both")
        result = svc.add_participant("S001", user.email, ["coder", "reviewer_data_manager", "coder"], self.admin)
        self.assertEqual([p["role"] for p in result["participants"]], ["coder", "reviewer_data_manager"])
        self.assertEqual(result["role"], "coder")
        rows = db.session.scalars(sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id)).all()
        self.assertEqual({r.role for r in rows}, {"coder", "reviewer_data_manager"})
        self.assertEqual(
            {g.role for g in self._grants(user, VaStatuses.active)},
            {VaAccessRoles.coder, VaAccessRoles.reviewer, VaAccessRoles.data_manager},
        )

    def test_one_refused_role_refuses_the_whole_call(self):
        user = self._user("nohindi2")
        db.session.execute(
            sa.update(VaSubmissions).where(VaSubmissions.va_sid == "trn-S001-3").values(va_narration_language="hindi")
        )
        db.session.commit()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", user.email, ["interviewer", "coder"], self.admin)
        self.assertEqual(ctx.exception.code, "coder_language_missing")
        self.assertEqual(
            db.session.scalars(sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id)).all(), [])
        self.assertEqual(self._grants(user), [])

    def test_empty_or_unknown_roles_are_refused(self):
        user = self._user("noroles")
        for roles, code in (([], "roles_empty"), ("", "roles_empty"), (["coder", "admin"], "invalid_role")):
            with self.assertRaises(svc.TrainingDemoError) as ctx:
                svc.add_participant("S001", user.email, roles, self.admin)
            self.assertEqual(ctx.exception.code, code)

    def test_reviewer_data_manager_gets_both_grants_and_sees_the_session(self):
        user = self._user("rdm")
        result = svc.add_participant("S001", user.email, "reviewer_data_manager", self.admin)
        grants = self._grants(user, VaStatuses.active)
        self.assertEqual({g.role for g in grants}, {VaAccessRoles.reviewer, VaAccessRoles.data_manager})
        self.assertTrue(all(g.scope_type == VaAccessScopeTypes.org_unit for g in grants))
        self.assertEqual({str(g.org_unit_id) for g in grants}, {self.first["org_unit_id"]})
        self.assertEqual(len(result["participant_id"]) > 0, True)
        visible = set(db.session.scalars(sa.select(VaSubmissions.va_sid).where(
            scope_filter(user, Action.LIST_DATA), VaSubmissions.va_sid.like("trn-S001-%"))))
        self.assertEqual(len(visible), 200)
        reviewable = set(db.session.scalars(sa.select(VaSubmissions.va_sid).where(
            scope_filter(user, Action.REVIEW), VaSubmissions.va_sid.like("trn-S001-%"))))
        self.assertEqual(len(reviewable), 200)

    def test_other_roles_get_one_grant_on_the_session_root(self):
        expected = {
            "death_reporter": VaAccessRoles.death_reporter,
            "interview_supervisor": VaAccessRoles.interview_supervisor,
            "interviewer": VaAccessRoles.interviewer,
        }
        for role, grant_role in expected.items():
            user = self._user(role)
            svc.add_participant("S001", user.email, role, self.admin)
            grants = self._grants(user)
            self.assertEqual([g.role for g in grants], [grant_role])
            self.assertEqual(str(grants[0].org_unit_id), self.first["org_unit_id"])
            self.assertIsNotNone(grants[0].cadre_id)

    def test_interviewer_and_death_reporter_reach_the_training_project(self):
        from app.services import web_intake_service as intake

        interviewer, reporter = self._user("iv"), self._user("dr")
        svc.add_participant("S001", interviewer.email, "interviewer", self.admin)
        svc.add_participant("S001", reporter.email, "death_reporter", self.admin)
        for context in (intake.interviewer_context(interviewer), intake.register_death_context(reporter)):
            self.assertEqual({entry["project_id"] for entry in context}, {"TRN01"})
            self.assertIn(self.first["org_unit_id"], {str(u["org_unit_id"]) for entry in context for u in entry["org_units"]})

    def test_unknown_email_refused_and_no_user_created(self):
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers))
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", "nobody.at.all@test.local", "coder", self.admin)
        self.assertEqual(ctx.exception.code, "unknown_user")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers)), before)
        inactive = self._user("gone")
        inactive.user_status = VaStatuses.deactive
        db.session.flush()
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", inactive.email, "coder", self.admin)
        self.assertEqual(ctx.exception.code, "user_inactive")

    def test_invalid_role_duplicate_and_non_admin(self):
        user = self._user("dup")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", user.email, "admin", self.admin)
        self.assertEqual(ctx.exception.code, "invalid_role")
        svc.add_participant("S001", user.email, "interviewer", self.admin)
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", user.email, "interviewer", self.admin)
        self.assertEqual(ctx.exception.code, "already_participant")
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", user.email, "coder", self.base_coder_user)
        self.assertEqual(ctx.exception.code, "admin_required")

    def test_other_project_grants_are_untouched(self):
        user = self.base_coder_user  # holds a coder grant on BASE01
        user.vacode_language = ["english"]
        before = [(g.grant_id, g.role, g.grant_status) for g in self._grants(user)]
        svc.add_participant("S001", user.email, "coder", self.admin)
        svc.remove_participant("S001", user.user_id, "coder", self.admin)
        svc.close_training_session("S001", self.admin)
        svc.reopen_training_session("S001", self.admin)
        base = [x for x in self._grants(user) if x.org_unit_id is None]
        self.assertEqual(before, [(g.grant_id, g.role, g.grant_status) for g in base])

    def test_remove_and_readd_flip_only_grant_status_and_keep_the_slot(self):
        user = self._user("flip")
        added = svc.add_participant("S001", user.email, "coder", self.admin)
        grant_ids = {g.grant_id for g in self._grants(user)}
        self.assertEqual(len(grant_ids), 1)
        svc.remove_participant("S001", user.user_id, "coder", self.admin)
        self.assertEqual({g.grant_status for g in self._grants(user)}, {VaStatuses.deactive})
        self.assertEqual(self._pick_list(user), set())
        again = svc.add_participant("S001", user.email, "coder", self.admin)
        self.assertEqual(again["coder_slot"], added["coder_slot"])
        self.assertEqual({g.grant_id for g in self._grants(user)}, grant_ids)
        self.assertEqual({g.grant_status for g in self._grants(user)}, {VaStatuses.active})
        self.assertEqual(len(self._pick_list(user)), 10)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapTrainingParticipant)
                                           .where(MapTrainingParticipant.user_id == user.user_id)), 1)

    def test_close_and_reopen_flip_grants_only(self):
        keep, gone = self._user("keep"), self._user("gone")
        svc.add_participant("S001", keep.email, "coder", self.admin)
        svc.add_participant("S001", gone.email, "interviewer", self.admin)
        svc.remove_participant("S001", gone.user_id, "interviewer", self.admin)
        cases = db.session.scalar(sa.select(sa.func.count()).select_from(MapTrainingCase))
        closed = svc.close_training_session("S001", self.admin)
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["grants_changed"], 1)
        self.assertEqual({g.grant_status for g in self._grants(keep)}, {VaStatuses.deactive})
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapTrainingCase)), cases)
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            svc.add_participant("S001", self._user("late").email, "coder", self.admin)
        self.assertEqual(ctx.exception.code, "session_closed")
        reopened = svc.reopen_training_session("S001", self.admin)
        self.assertEqual(reopened["status"], "active")
        self.assertEqual({g.grant_status for g in self._grants(keep)}, {VaStatuses.active})
        self.assertEqual({g.grant_status for g in self._grants(gone)}, {VaStatuses.deactive})
        self.assertEqual(len(self._pick_list(keep)), 10)

    def test_second_session_participants_are_separate(self):
        second = svc.create_training_session("Training two", self.admin, source_form_id=SRC_FORM)
        user = self._user("both")
        svc.add_participant("S001", user.email, "coder", self.admin)
        svc.add_participant(second["session_code"], user.email, "coder", self.admin)
        pick = self._pick_list(user)
        self.assertEqual(len(pick), 20)
        svc.close_training_session("S001", self.admin)
        self.assertEqual(len(self._pick_list(user)), 10)
        self.assertTrue(all("trn-S002-" in sid for sid in self._pick_list(user)))

    def test_answer_key_and_coded_counts_stay_off_the_pick_list(self):
        user = self._user("keycheck")
        svc.add_participant("S001", user.email, "coder", self.admin)
        rows = get_pick_available_forms(user, {self._trn_form_id()})
        self.assertTrue(rows)
        self.assertNotIn("source_final_cod", rows[0])

    def test_training_coding_is_not_counted_as_the_coders_output(self):
        from app.services.coder_dashboard_service import get_coder_output_summary

        coder = self._user("output")
        svc.add_participant("S001", coder.email, "coder", self.admin)
        db.session.add(VaFinalAssessments(
            va_sid="trn-S001-1", va_finassess_by=coder.user_id, va_conclusive_cod="J18.9"))
        db.session.flush()
        with mock.patch("app.services.coder_dashboard_service._cached_dashboard_project_value",
                        side_effect=lambda _u, _k, _p, compute: compute()):
            self.assertEqual(get_coder_output_summary(coder.user_id)["completed"], 0)
            self.assertEqual(get_coder_output_summary(coder.user_id, "TRN01")["completed"], 1)

    def test_coded_counts_follow_active_final_assessments(self):
        coder = self._user("coded")
        svc.add_participant("S001", coder.email, "coder", self.admin)
        db.session.add(VaFinalAssessments(
            va_sid="trn-S001-1", va_finassess_by=coder.user_id, va_conclusive_cod="J18.9"))
        db.session.flush()
        self.assertEqual(svc.list_training_sessions()[0]["cases_coded"], 1)
        detail = svc.get_training_session("S001")
        self.assertEqual(detail["slots"][0]["cases_coded"], 1)
        self.assertEqual(detail["slots"][0]["coder_name"], coder.name)


class OnboardingTests(TrainingDemoTestBase):
    def test_pending_until_started_then_never_again(self):
        user = self._user("onboard")
        self.assertFalse(svc.has_pending_onboarding(user.user_id))
        svc.add_participant("S001", user.email, "coder", self.admin)
        svc.add_participant("S001", user.email, "interviewer", self.admin)
        self.assertTrue(svc.has_pending_onboarding(user.user_id))
        self.assertEqual({p["role"] for p in svc.participations(user.user_id, pending_only=True)},
                         {"coder", "interviewer"})
        roles = svc.complete_onboarding(user.user_id)
        self.assertEqual(set(roles), {"coder", "interviewer"})
        self.assertFalse(svc.has_pending_onboarding(user.user_id))
        row = db.session.scalar(sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id))
        self.assertIsNotNone(row.onboarded_at)

    def test_closed_session_or_removed_participant_is_not_pending(self):
        user = self._user("closedonb")
        svc.add_participant("S001", user.email, "interviewer", self.admin)
        svc.close_training_session("S001", self.admin)
        self.assertFalse(svc.has_pending_onboarding(user.user_id))
        svc.reopen_training_session("S001", self.admin)
        self.assertTrue(svc.has_pending_onboarding(user.user_id))
        svc.remove_participant("S001", user.user_id, "interviewer", self.admin)
        self.assertFalse(svc.has_pending_onboarding(user.user_id))

    def test_complete_onboarding_leaves_closed_sessions_alone(self):
        user = self._user("closedstart")
        svc.add_participant("S001", user.email, "interviewer", self.admin)
        svc.close_training_session("S001", self.admin)
        self.assertEqual(svc.complete_onboarding(user.user_id), [])
        row = db.session.scalar(sa.select(MapTrainingParticipant).where(MapTrainingParticipant.user_id == user.user_id))
        self.assertIsNone(row.onboarded_at)
        svc.reopen_training_session("S001", self.admin)
        self.assertTrue(svc.has_pending_onboarding(user.user_id))
        self.assertEqual(svc.complete_onboarding(user.user_id), ["interviewer"])

    def test_session_row_status_is_the_only_flag_on_close(self):
        svc.close_training_session("S001", self.admin)
        row = db.session.scalar(sa.select(MasTrainingSession).where(MasTrainingSession.session_code == "S001"))
        self.assertEqual(row.status, "closed")
        svc.reopen_training_session("S001", self.admin)


class SplitPayloadTests(TrainingDemoTestBase):
    """With the payload PII split on, sealed fields are read joined and written through the one writer."""

    split = True

    def test_copy_seals_the_pseudonymised_values_not_the_originals(self):
        from app.services.payload_pii_accessor import get_full_payload, get_side_row

        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(VaSubmissionPayloadVersion.va_sid == "trn-S001-1")
        )
        self.assertNotIn("Id10017", version.payload_data)  # stripped from the stored payload
        self.assertIsNotNone(get_side_row(version))
        full = get_full_payload(version)
        self.assertTrue(full["Id10017"])
        self.assertNotEqual(full["Id10017"], source_payload(1)["Id10017"])
        self.assertIn(full["Id10017"], full["Id10476"])
        self.assertNotIn("Kumarasamy", str(full))
        source_full = get_full_payload(db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(VaSubmissionPayloadVersion.va_sid == "src-001")))
        self.assertEqual(source_full["Id10018"], "Kumarasamy")  # the source is untouched
