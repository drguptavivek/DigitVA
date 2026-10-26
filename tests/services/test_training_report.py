"""Training report: cause groups, per-coder counts, agreement, staff counts,
authorization, query count and CSV (digitva-vd0g.2)."""

import csv
import io
import unittest
import uuid
from contextlib import contextmanager
from datetime import date

import sqlalchemy as sa
from sqlalchemy import event

from app import db
from app.models import (
    MapCaseTransition,
    MapTrainingCase,
    MapTrainingParticipant,
    VaDeathRegister,
    VaFinalAssessments,
    VaSubmissionWorkflow,
    VaWebIntakeDraft,
)
from app.services import training_demo_service as svc
from app.services import training_report_service as reports
from app.services.training_cause_groups import va_cause_of
from tests.training_demo_fixtures import SRC_FORM, TrainingDemoTestBase

PNEUMONIA = "CA40.0 Pneumonia due to Streptococcus pneumoniae"  # VAs-01.02
DIABETES = "5A11 Type 2 diabetes mellitus"  # VAs-03.03


@contextmanager
def count_selects():
    statements = []

    def before(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.session.get_bind()
    target = getattr(engine, "engine", engine)
    event.listen(target, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(target, "before_cursor_execute", before)


class CauseGroupTests(unittest.TestCase):
    def test_icd10_range_single_code_and_ambiguity(self):
        self.assertEqual(va_cause_of("J18.9 Pneumonia, unspecified"), "VAs-01.02")
        self.assertEqual(va_cause_of("I21.9"), "VAs-04.01")
        self.assertEqual(va_cause_of("K70.2"), "VAs-06.02")  # single code beats the K70-K93 range
        self.assertEqual(va_cause_of("A33"), "VAs-10.05")  # single code beats A33-A35
        self.assertEqual(va_cause_of("A34"), "VAs-01.08")
        self.assertIsNone(va_cause_of("P95"))  # fresh and macerated stillbirth: ambiguous
        self.assertIsNone(va_cause_of("V89.2"))  # not in the annex

    def test_icd11_code_and_stem_fallback(self):
        self.assertEqual(va_cause_of(PNEUMONIA), "VAs-01.02")
        self.assertEqual(va_cause_of("1G40 Sepsis"), "VAs-01.01")
        self.assertEqual(va_cause_of(DIABETES), "VAs-03.03")
        self.assertEqual(va_cause_of("CA40.0Z unknown extension"), "VAs-01.02")

    def test_icd11_cluster_maps_by_its_recorded_primary_stem(self):
        """digitva-443q: WHO's causing condition, not the first stem."""
        cluster = "5A11/CA40.0 Diabetes with pneumonia"
        self.assertEqual(va_cause_of(cluster), "VAs-03.03")  # no provenance: the first stem
        self.assertEqual(va_cause_of(cluster, {"primary_stem": "CA40.0"}), "VAs-01.02")
        # A malformed recorded stem falls back to the first stem.
        self.assertEqual(va_cause_of(cluster, {"primary_stem": "not a code"}), "VAs-03.03")
        self.assertEqual(va_cause_of(cluster, {"code": "5A11/CA40.0"}), "VAs-03.03")
        # ICD-10 values never read provenance.
        self.assertEqual(va_cause_of("J18.9", {"primary_stem": "5A11"}), "VAs-01.02")

    def test_empty_and_malformed_values(self):
        for value in (None, "", "   ", "not a code", "J1"):
            self.assertIsNone(va_cause_of(value))


class ReportTestBase(TrainingDemoTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = svc.create_training_session("Training two", cls.admin, source_form_id=SRC_FORM)
        db.session.commit()

    def _add(self, tag, role, code="S001"):
        user = self._user(tag)
        svc.add_participant(code, user.email, role, self.admin)
        return user

    def _code(self, number, text, user, session="S001", provenance=None):
        sid = f"trn-{session}-{number}"
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=user.user_id, va_conclusive_cod=text, icd11_provenance=provenance))
        db.session.flush()

    def _key(self, number, text):
        db.session.get(MapTrainingCase, f"trn-S001-{number}").source_final_cod = text
        db.session.flush()


class ReportTests(ReportTestBase):
    def test_counts_completion_and_agreement(self):
        a = self._add("coder.a", "coder")  # slot 1: cases 1-10
        b = self._add("coder.b", "coder")  # slot 2: cases 11-20
        self._key(2, "J18.9")
        self._key(3, None)
        self._code(1, PNEUMONIA, a)  # source J18.9 (fixture): same VA cause
        self._code(2, DIABETES, a)  # J18.9 vs diabetes: differs
        self._code(3, PNEUMONIA, a)  # no reference cause: unmappable
        db.session.execute(
            sa.update(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == "trn-S001-4")
            .values(workflow_state="coder_step1_saved")
        )
        for number in range(11, 21):
            self._key(number, "J18.9")
            self._code(number, PNEUMONIA, b)
        db.session.flush()

        report = reports.training_session_report("S001", self.admin)
        rows = {c["email"]: c for c in report["coders"]}
        first, second = rows[a.email], rows[b.email]
        self.assertEqual((first["slot"], first["coded"], first["in_progress"], first["not_started"]), (1, 3, 1, 6))
        self.assertFalse(first["completed"])
        self.assertEqual((first["compared"], first["matched"], first["unmappable"]), (2, 1, 1))
        self.assertEqual(first["agreement_pct"], 50.0)
        self.assertIsNotNone(first["last_activity"])
        self.assertEqual((second["coded"], second["not_started"], second["agreement_pct"]), (10, 0, 100.0))
        self.assertTrue(second["completed"])
        self.assertEqual(report["totals"]["coded"], 13)
        self.assertEqual(report["totals"]["coders_completed"], 1)
        self.assertEqual((report["totals"]["compared"], report["totals"]["unmappable"]), (12, 1))
        self.assertEqual(report["totals"]["agreement_pct"], round(100 * 11 / 12, 1))
        by_case = {c["case_number"]: c for c in report["cases"]}
        self.assertEqual(len(by_case), 13)
        self.assertEqual(
            (by_case[1]["match"], by_case[1]["trainee_code"], by_case[1]["trainee_group"],
             by_case[1]["reference_group"]),
            ("yes", "CA40.0", "VAs-01.02", "VAs-01.02"),
        )
        self.assertEqual(by_case[1]["trainee_title"], "Pneumonia due to Streptococcus pneumoniae")
        self.assertEqual((by_case[2]["match"], by_case[2]["trainee_group"]), ("no", "VAs-03.03"))
        self.assertEqual(by_case[3]["match"], "unmappable")
        self.assertEqual(by_case[3]["coder_name"], a.name)

    def test_a_cluster_is_compared_and_shown_by_its_primary_stem(self):
        a = self._add("coder.ps", "coder")
        self._key(1, "J18.9")
        self._code(1, "5A11/CA40.0 Diabetes with pneumonia", a,
                   provenance={"conclusive": {"code": "5A11/CA40.0", "primary_stem": "CA40.0"}})
        db.session.flush()
        case = next(c for c in reports.training_session_report("S001", self.admin)["cases"]
                    if c["case_number"] == 1)
        self.assertEqual(
            (case["match"], case["trainee_code"], case["trainee_group"], case["trainee_title"]),
            ("yes", "CA40.0", "VAs-01.02", "Diabetes with pneumonia"),
        )

    def test_nothing_coded_and_no_participants(self):
        report = reports.training_session_report("S001", self.admin)
        self.assertEqual((report["coders"], report["cases"], report["staff"]), ([], [], []))
        self.assertEqual(report["totals"]["coded"], 0)
        self.assertIsNone(report["totals"]["agreement_pct"])
        coder = self._add("idle", "coder")
        row = reports.training_session_report("S001", self.admin)["coders"][0]
        self.assertEqual((row["coded"], row["in_progress"], row["not_started"], row["last_activity"]), (0, 0, 10, None))
        self.assertIsNone(row["agreement_pct"])
        self.assertEqual(row["email"], coder.email)

    def test_other_session_and_tester_assessments_do_not_count(self):
        a = self._add("coder.iso", "coder")
        self._code(1, PNEUMONIA, a, session="S002")
        db.session.add(VaFinalAssessments(
            va_sid="trn-S001-2", va_finassess_by=a.user_id, va_conclusive_cod=PNEUMONIA, is_tester=True))
        db.session.flush()
        report = reports.training_session_report("S001", self.admin)
        self.assertEqual(report["totals"]["coded"], 0)
        self.assertEqual(reports.training_session_report("S002", self.admin)["totals"]["coded"], 1)

    def test_non_coder_counts(self):
        reporter = self._add("reporter", "death_reporter")
        interviewer = self._add("interviewer", "interviewer")
        supervisor = self._add("supervisor", "interview_supervisor")
        form = svc._web_form()
        root = svc.get_training_session("S001")["org_unit_id"]
        other_root = svc.get_training_session("S002")["org_unit_id"]
        deaths = []
        for index, unit in enumerate((root, root, other_root)):
            death = VaDeathRegister(
                project_id="TRN01", site_id=form.site_id, org_unit_id=uuid.UUID(unit),
                death_number=uuid.uuid4().int % 10**9, unique_id=f"RPT-{uuid.uuid4().hex[:12]}",
                deceased_name="Synthetic Person", deceased_sex="male", date_of_death=date(2026, 1, 1),
                registered_by=reporter.user_id, source="register", status="registered",
                started_by_user_id=interviewer.user_id if index == 0 else None,
            )
            db.session.add(death)
            deaths.append(death)
        db.session.flush()
        db.session.add(VaWebIntakeDraft(
            project_id="TRN01", site_id=form.site_id, death_id=deaths[0].death_id, form_id=form.form_id,
            user_id=interviewer.user_id, unique_id=f"RPT-{uuid.uuid4().hex[:12]}", status="submitted",
            meta={}, prefill={},
        ))
        grant_id = self._grants(supervisor)[0].grant_id
        for death, grant in ((deaths[0], grant_id), (deaths[1], None), (deaths[2], grant_id)):
            db.session.add(MapCaseTransition(
                death_id=death.death_id, action="move", to_state="scheduled",
                actor_user_id=supervisor.user_id, authorizing_grant_id=grant,
            ))
        db.session.flush()

        staff = {s["role"]: s for s in reports.training_session_report("S001", self.admin)["staff"]}
        self.assertEqual(staff["death_reporter"]["deaths_registered"], 2)  # the S002 death is not counted
        self.assertEqual(
            (staff["interviewer"]["interviews_started"], staff["interviewer"]["interviews_submitted"]), (1, 1))
        self.assertEqual(staff["interview_supervisor"]["supervisor_actions"], 1)  # only the grant-backed move
        self.assertEqual(staff["interviewer"]["deaths_registered"], 0)

    def test_query_count_is_fixed(self):
        self._add("q.one", "coder")
        with count_selects() as one:
            reports.training_session_report("S001", self.admin)
        for tag in ("q.two", "q.three", "q.four", "q.five"):
            self._add(tag, "coder")
        self._add("q.dm", "reviewer_data_manager")
        with count_selects() as five:
            reports.training_session_report("S001", self.admin)
        self.assertEqual(len(one), len(five), (len(one), len(five)))
        self.assertLessEqual(len(five), 9, five)  # 7 report queries + the viewer lookup

    def test_csv_export_shapes_and_no_source_identifier(self):
        coder = self._add("csv.coder", "coder")
        self._code(1, PNEUMONIA, coder)
        report = reports.training_session_report("S001", self.admin)
        coders = list(csv.reader(io.StringIO(reports.coders_csv(report))))
        self.assertEqual(coders[0][:6], ["name", "email", "slot", "status", "coded", "target"])
        self.assertEqual((coders[1][1], coders[1][4], coders[1][5]), (coder.email, "1", "10"))
        cases = list(csv.reader(io.StringIO(reports.cases_csv(report))))
        self.assertEqual(cases[0][0], "case_number")
        self.assertEqual((cases[1][0], cases[1][8]), ("1", "yes"))
        self.assertNotIn("src-", reports.coders_csv(report) + reports.cases_csv(report) + str(report))

    def test_csv_cells_cannot_become_formulas(self):
        coder = self._add("csv.formula", "coder")
        coder.name = "=HYPERLINK(\"http://x\")"
        db.session.flush()
        report = reports.training_session_report("S001", self.admin)
        self.assertIn("'=HYPERLINK", reports.coders_csv(report))


class ReportAuthorizationTests(ReportTestBase):
    def _denied(self, user, code="S001"):
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            reports.training_session_report(code, user)
        self.assertEqual(ctx.exception.code, "report_forbidden")

    def test_admin_and_the_sessions_own_reviewer_data_manager_may_read(self):
        manager = self._add("rdm.own", "reviewer_data_manager")
        self.assertEqual(reports.training_session_report("S001", manager)["session"]["session_code"], "S001")
        self.assertEqual(reports.training_session_report("S001", self.admin)["session"]["session_code"], "S001")
        ref = svc.get_training_session("S001")["training_session_id"]
        self.assertEqual(reports.training_session_report(ref, manager)["session"]["session_code"], "S001")

    def test_everyone_else_is_refused(self):
        other_manager = self._add("rdm.other", "reviewer_data_manager", code="S002")
        self._denied(other_manager)
        for tag, role in (("coder", "coder"), ("interviewer", "interviewer"),
                          ("reporter", "death_reporter"), ("supervisor", "interview_supervisor")):
            self._denied(self._add(f"deny.{tag}", role))
        self._denied(self.base_coder_user)  # no participation at all
        self._denied(other_manager, "S404")  # an unknown session is the same refusal, not a probe
        self.assertEqual(reports.training_session_report("S002", other_manager)["session"]["session_code"], "S002")

    def test_removed_manager_is_refused_and_admin_gets_not_found(self):
        manager = self._add("rdm.removed", "reviewer_data_manager")
        svc.remove_participant("S001", manager.user_id, "reviewer_data_manager", self.admin)
        self._denied(manager)
        with self.assertRaises(svc.TrainingDemoError) as ctx:
            reports.training_session_report("S404", self.admin)
        self.assertEqual(ctx.exception.code, "session_not_found")

    def test_session_list_per_viewer(self):
        manager = self._add("rdm.list", "reviewer_data_manager", code="S002")
        self.assertEqual([s["session_code"] for s in reports.sessions_for_viewer(manager)], ["S002"])
        self.assertEqual({s["session_code"] for s in reports.sessions_for_viewer(self.admin)}, {"S001", "S002"})
        self.assertEqual(reports.sessions_for_viewer(self.base_coder_user), [])
        self.assertEqual(db.session.scalar(
            sa.select(sa.func.count()).select_from(MapTrainingParticipant).where(
                MapTrainingParticipant.user_id == manager.user_id)), 1)
