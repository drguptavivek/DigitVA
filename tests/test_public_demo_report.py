"""Public demo report page and own-response downloads (digitva-77v5.3).

Policy: docs/policy/public-demo.md sections 5 and 6. Built on the demo
project that ``tests.test_public_demo.PublicDemoBase`` sets up with the flag on.
"""
import csv
import io
import json
from unittest import mock

import sqlalchemy as sa

from app import cache, db
from app.models import (
    AuthSecurityEvent,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaReviewerFinalAssessments,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import public_demo_report_service as reports
from app.services.workflow import definition as wf
from tests import test_public_demo as base

CERTIFICATE = {
    "Part1": [
        {"Conditions": [{"Text": "Pneumonia", "Code": "CA40", "Interval": "P3D"}]},
        {"Conditions": [{"Text": "Diabetes", "Code": "5A11"}]},
    ],
    "Part2": {"Conditions": [{"Text": "Smoking"}]},
}


class DemoSeedMixin:
    """A demo case with its payload, SmartVA result and final assessments."""

    def _full(self, owner, sid, *, state="ready_for_coding", smartva=None, coder=None,
              reviewer=None, answers=None, age_years=None, sex=None):
        self._case(owner, sid, state)
        submission = db.session.get(VaSubmissions, sid)
        version = VaSubmissionPayloadVersion(
            va_sid=sid, payload_fingerprint=sid, version_status="active",
            payload_data=answers if answers is not None else {"Id10017": "Asha"},
        )
        db.session.add(version)
        db.session.flush()
        submission.active_payload_version_id = version.payload_version_id
        if age_years is not None:
            submission.va_deceased_age_normalized_years = age_years
        if sex is not None:
            submission.va_deceased_gender = sex
        if smartva is not None:
            db.session.add(VaSmartvaResults(
                va_sid=sid, payload_version_id=version.payload_version_id,
                va_smartva_cause1=smartva[0], va_smartva_likelihood1=smartva[1],
                va_smartva_cause2="Stroke", va_smartva_likelihood2="0.2",
                va_smartva_cause1icd="A41",
            ))
        for model, spec, by, status in (
            (VaFinalAssessments, coder, "va_finassess_by", "va_finassess_status"),
            (VaReviewerFinalAssessments, reviewer, "va_rfinassess_by", "va_rfinassess_status"),
        ):
            if spec is None:
                continue
            code, title = spec["code"], spec["title"]
            db.session.add(model(
                va_sid=sid, payload_version_id=version.payload_version_id,
                va_conclusive_cod=f"{code} {spec.get('typed', title)}",
                icd11_provenance={"conclusive": {"code": code, "title": title}},
                doris_certificate=spec.get("certificate"), **{by: owner.user_id},
            ))
        db.session.commit()


class ReportBase(DemoSeedMixin, base.PublicDemoBase):
    def setUp(self):
        super().setUp()
        self.alice = self._account("rep.alice")
        self.bob = self._account("rep.bob")

    def _get(self, user, url):
        self._login(str(user.user_id))
        return self.client.get(url)


class FlagAndAudienceTests(ReportBase):
    URLS = (
        "/public-demo/cases",
        "/public-demo/cases/rep-a/report",
        "/api/v1/public-demo/my-responses.csv",
        "/api/v1/public-demo/my-responses.json",
    )

    def setUp(self):
        super().setUp()
        self._full(self.alice, "rep-a")

    def test_flag_off_is_404_everywhere(self):
        # Present with the flag on, then absent with it off.
        self.assertEqual(self._get(self.alice, "/public-demo/cases/rep-a/report").status_code, 200)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            for url in self.URLS:
                with self.subTest(url=url):
                    self.assertEqual(self._get(self.alice, url).status_code, 404)

    def test_a_user_who_is_not_a_demo_account_gets_404(self):
        self.assertEqual(self._get(self.alice, "/public-demo/cases").status_code, 200)
        for user_id in (self.base_admin_id, str(self.base_coder_user.user_id)):
            for url in self.URLS:
                with self.subTest(user=user_id, url=url):
                    self._login(user_id)
                    self.assertEqual(self.client.get(url).status_code, 404)

    def test_anonymous_is_sent_to_sign_in(self):
        self.client.get("/public-demo/cases")  # warm
        with self.client.session_transaction() as session:
            session.clear()
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (302, 401))


class OwnershipTests(ReportBase):
    def setUp(self):
        super().setUp()
        self._full(self.alice, "rep-alice")
        self._full(self.bob, "rep-bob")

    def test_list_and_report_show_only_the_callers_cases(self):
        page = self._get(self.alice, "/public-demo/cases")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("/public-demo/cases/rep-alice/report", body)  # own present first
        self.assertNotIn("rep-bob", body)
        self.assertIn('href="/public-demo/cases"', body)  # the navbar's "My reports"
        self.assertEqual(self._get(self.alice, "/public-demo/cases/rep-alice/report").status_code, 200)

    def test_another_users_and_unknown_cases_are_one_404(self):
        self.assertEqual(self._get(self.bob, "/public-demo/cases/rep-bob/report").status_code, 200)
        other = self._get(self.alice, "/public-demo/cases/rep-bob/report")
        unknown = self._get(self.alice, "/public-demo/cases/rep-nope/report")
        self.assertEqual((other.status_code, unknown.status_code), (404, 404))
        self.assertNotIn(b"rep-bob", other.data)


class PipelineTests(ReportBase):
    def test_every_workflow_state_is_mapped(self):
        self.assertEqual(set(reports.PIPELINE), set(wf.ALL_WORKFLOW_STATES))

    def test_each_state_renders_its_label(self):
        self._full(self.alice, "rep-p")
        for state in sorted(wf.ALL_WORKFLOW_STATES):
            with self.subTest(state=state):
                db.session.execute(sa.update(VaSubmissionWorkflow).where(
                    VaSubmissionWorkflow.va_sid == "rep-p").values(workflow_state=state))
                db.session.commit()
                page = self._get(self.alice, "/public-demo/cases/rep-p/report")
                self.assertEqual(page.status_code, 200)
                self.assertIn(reports.PIPELINE[state][1], page.get_data(as_text=True))

    def test_named_stages_of_the_demo_flow(self):
        labels = {s: reports.pipeline(s)["label"] for s in (
            "smartva_pending", "ready_for_coding", "coding_in_progress", "coder_finalized",
            "reviewer_finalized", "consent_refused")}
        self.assertEqual(labels, {
            "smartva_pending": "Waiting for SmartVA",
            "ready_for_coding": "Ready to code",
            "coding_in_progress": "Being coded",
            "coder_finalized": "Coded, waiting for the review window",
            "reviewer_finalized": "Reviewed",
            "consent_refused": "Not analysable (consent refused or incomplete)",
        })


class ReportContentTests(ReportBase):
    def test_bare_case_has_placeholders_and_demo_label(self):
        self._full(self.alice, "rep-bare", state="smartva_pending", age_years=42, sex="female")
        body = self._get(self.alice, "/public-demo/cases/rep-bare/report").get_data(as_text=True)
        self.assertIn("rep-bare", body)  # subject present before the absences
        self.assertIn("42 years", body)
        self.assertIn("Female", body)
        self.assertIn("Waiting for SmartVA", body)
        self.assertIn("Not available yet.", body)
        self.assertIn("Not coded yet.", body)
        self.assertIn("Not reviewed yet.", body)
        self.assertIn("not a medical certificate", body)
        self.assertIn("@media print", body)
        self.assertIn("window.print()", body)

    def test_smartva_coder_and_reviewer_sections(self):
        self._full(
            self.alice, "rep-full", state="reviewer_finalized", smartva=("Sepsis", "0.61"),
            coder={"code": "1G40", "title": "Sepsis without septic shock",
                   "typed": "my own typed words", "certificate": CERTIFICATE},
            reviewer={"code": "BA41", "title": "Acute myocardial infarction"},
        )
        body = self._get(self.alice, "/public-demo/cases/rep-full/report").get_data(as_text=True)
        for text in ("Sepsis", "0.61", "Stroke", "A41", "1G40", "Sepsis without septic shock",
                     "Pneumonia", "CA40", "Diabetes", "Smoking", "BA41",
                     "Acute myocardial infarction", "Reviewed"):
            self.assertIn(text, body)
        # The title is the stored provenance title, not what was typed after the code.
        self.assertNotIn("my own typed words", body)

    def test_a_failed_smartva_run_is_said_plainly(self):
        self._full(self.alice, "rep-fail", smartva=("x", "1"))
        db.session.execute(sa.update(VaSmartvaResults).where(VaSmartvaResults.va_sid == "rep-fail").values(
            va_smartva_outcome="failed"))
        db.session.commit()
        body = self._get(self.alice, "/public-demo/cases/rep-fail/report").get_data(as_text=True)
        self.assertIn("could not produce a result", body)

    def test_a_stale_final_for_an_older_payload_is_not_shown(self):
        self._full(self.alice, "rep-stale", coder={"code": "1G40", "title": "Sepsis"})
        db.session.execute(sa.update(VaFinalAssessments).where(VaFinalAssessments.va_sid == "rep-stale").values(
            payload_version_id=None))
        submission = db.session.get(VaSubmissions, "rep-stale")
        self.assertIsNotNone(submission.active_payload_version_id)
        db.session.commit()
        body = self._get(self.alice, "/public-demo/cases/rep-stale/report").get_data(as_text=True)
        self.assertIn("Not coded yet.", body)

    def _extra_final(self, model, sid, code, **values):
        """One more active final of the case, on its active payload version."""
        version = db.session.get(VaSubmissions, sid).active_payload_version_id
        by = "va_finassess_by" if model is VaFinalAssessments else "va_rfinassess_by"
        row = model(va_sid=sid, payload_version_id=version, va_conclusive_cod=f"{code} x",
                    icd11_provenance={"conclusive": {"code": code, "title": f"T {code}"}},
                    **{by: self.alice.user_id}, **values)
        db.session.add(row)
        db.session.commit()
        return row

    def _shown(self, sid):
        found = reports.own_reports(self.alice, va_sid=sid)[0]
        return (found["coder"] or {}).get("code"), (found["reviewer"] or {}).get("code")

    def test_the_pointed_to_coder_final_wins_over_a_newer_one_and_hides_the_reviewer(self):
        # The authority rule of final_cod_authority_service.get_authoritative_final_cod_record.
        self._full(self.alice, "rep-auth", state="reviewer_finalized",
                   coder={"code": "1G40", "title": "Old"}, reviewer={"code": "BA41", "title": "AMI"})
        older = db.session.scalar(sa.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == "rep-auth"))
        older.va_finassess_status = VaStatuses.deactive  # one active final per case and payload version
        db.session.commit()
        self._extra_final(VaFinalAssessments, "rep-auth", "8B20")  # newer, active, not authoritative
        self.assertEqual(self._shown("rep-auth"), ("8B20", "BA41"))  # no pointer: the newest rows
        pointer = VaFinalCodAuthority(va_sid="rep-auth", authoritative_final_assessment_id=older.va_finassess_id,
                                      authority_reason="test", authority_source_role="coder")
        db.session.add(pointer)
        db.session.commit()
        self.assertEqual(self._shown("rep-auth"), ("1G40", None))
        from app.services.final_cod_authority_service import get_authoritative_final_cod_record

        record = get_authoritative_final_cod_record("rep-auth")
        self.assertEqual((record.source_role, record.coder_final_assessment_id), ("coder", older.va_finassess_id))

    def test_the_pointed_to_reviewer_final_wins_and_names_the_coder_final_it_superseded(self):
        self._full(self.alice, "rep-auth2", state="reviewer_finalized",
                   coder={"code": "1G40", "title": "Sepsis"}, reviewer={"code": "BA41", "title": "AMI"})
        coder = db.session.scalar(sa.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == "rep-auth2"))
        reviewer = db.session.scalar(sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == "rep-auth2"))
        reviewer.supersedes_coder_final_assessment_id = coder.va_finassess_id
        coder.va_finassess_status = VaStatuses.deactive
        reviewer.va_rfinassess_status = VaStatuses.deactive
        db.session.commit()
        self._extra_final(VaFinalAssessments, "rep-auth2", "8B20")  # newer coder final, not the superseded one
        newer_reviewer = self._extra_final(VaReviewerFinalAssessments, "rep-auth2", "5A11")
        db.session.add(VaFinalCodAuthority(
            va_sid="rep-auth2", authoritative_reviewer_final_assessment_id=reviewer.va_rfinassess_id,
            authority_reason="test", authority_source_role="reviewer"))
        db.session.commit()
        self.assertIsNotNone(newer_reviewer.va_rfinassess_id)
        self.assertEqual(self._shown("rep-auth2"), ("1G40", "BA41"))

    def test_a_pointer_to_a_stale_payload_version_is_ignored_as_the_service_does(self):
        self._full(self.alice, "rep-auth3", coder={"code": "1G40", "title": "A"})
        older = db.session.scalar(sa.select(VaFinalAssessments).where(VaFinalAssessments.va_sid == "rep-auth3"))
        older.va_finassess_status = VaStatuses.deactive
        db.session.commit()
        self._extra_final(VaFinalAssessments, "rep-auth3", "8B20")
        older.payload_version_id = None  # no longer on the active payload version
        db.session.add(VaFinalCodAuthority(
            va_sid="rep-auth3", authoritative_final_assessment_id=older.va_finassess_id,
            authority_reason="test", authority_source_role="coder"))
        db.session.commit()
        self.assertEqual(self._shown("rep-auth3"), ("8B20", None))

    def test_query_count_does_not_grow_with_cases(self):
        def count_for(n):
            for i in range(n):
                self._full(self.alice, f"rep-q{n}-{i}", smartva=("Sepsis", "0.6"),
                           coder={"code": "1G40", "title": "Sepsis"},
                           reviewer={"code": "BA41", "title": "AMI"})
            statements = []

            def capture(conn, cursor, statement, parameters, context, executemany):
                if statement.startswith("SELECT"):
                    statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", capture)
            try:
                found = reports.own_reports(self.alice, with_answers=True)
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", capture)
            return len(found), len(statements)

        (one, queries_one), (four, queries_four) = count_for(1), count_for(3)
        self.assertEqual((one, four), (1, 4))
        self.assertEqual(queries_one, queries_four)
        # 6 reads of its own (cases, SmartVA, coder, reviewer, authority pointers,
        # answers), plus the grant resolution (the grant cache is off in tests).
        self.assertLessEqual(queries_four, 10)


class DownloadTests(ReportBase):
    CSV = "/api/v1/public-demo/my-responses.csv"
    JSON = "/api/v1/public-demo/my-responses.json"

    def setUp(self):
        super().setUp()
        self._full(
            self.alice, "rep-dl-a", state="reviewer_finalized", smartva=("Sepsis", "0.61"),
            coder={"code": "1G40", "title": "Sepsis"}, reviewer={"code": "BA41", "title": "AMI"},
            answers={"Id10017": "Asha", "note": "=1+1"},
        )
        self._full(self.bob, "rep-dl-b", answers={"Id10017": "Bhim"})
        cache.delete(f"public-demo-export:{self.alice.user_id}")

    def _rows(self, response):
        text = response.get_data(as_text=True).lstrip("﻿")
        return list(csv.DictReader(io.StringIO(text)))

    def test_csv_has_only_the_callers_cases_and_report_fields(self):
        response = self._get(self.alice, self.CSV)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        rows = self._rows(response)
        self.assertEqual([r["va_sid"] for r in rows], ["rep-dl-a"])  # own present, bob's absent
        row = rows[0]
        self.assertEqual(
            (row["state"], row["smartva_cause"], row["smartva_likelihood"], row["coder_icd11_code"],
             row["coder_icd11_title"], row["reviewer_icd11_code"], row["reviewer_icd11_title"]),
            ("reviewer_finalized", "Sepsis", "0.61", "1G40", "Sepsis", "BA41", "AMI"),
        )
        self.assertEqual(json.loads(row["answers_json"]), {"Id10017": "Asha", "note": "=1+1"})
        self.assertNotIn("Bhim", response.get_data(as_text=True))

    def test_json_has_only_the_callers_cases(self):
        response = self._get(self.alice, self.JSON)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["count"], 1)
        case = data["cases"][0]
        self.assertEqual(case["va_sid"], "rep-dl-a")
        self.assertEqual(case["answers"]["Id10017"], "Asha")
        self.assertEqual(case["coder"], {"code": "1G40", "title": "Sepsis"})
        self.assertEqual(case["reviewer"], {"code": "BA41", "title": "AMI"})
        self.assertNotIn("Bhim", response.get_data(as_text=True))

    def test_formula_cells_are_neutralised(self):
        for value in ("=SUM(A1)", "+1", "-1", "@cmd", "\tx"):
            self.assertEqual(reports.safe_cell(value), "'" + value)
        self._full(self.alice, "rep-dl-x", coder={"code": "1G40", "title": "=HYPERLINK(\"http://x\")"})
        rows = {r["va_sid"]: r for r in self._rows(self._get(self.alice, self.CSV))}
        self.assertEqual(rows["rep-dl-x"]["coder_icd11_title"], "'=HYPERLINK(\"http://x\")")

    def test_rate_limit_is_shared_by_both_formats_and_per_user(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_DOWNLOAD_RATE_LIMIT="2 per hour"):
            first = self._get(self.alice, self.CSV).status_code
            second = self._get(self.alice, self.JSON).status_code
            third = self._get(self.alice, self.CSV).status_code
            other = self._get(self.bob, self.CSV).status_code
        self.assertEqual((first, second, third, other), (200, 200, 429, 200))

    def test_one_download_at_a_time(self):
        key = f"public-demo-export:{self.alice.user_id}"
        self.assertTrue(cache.add(key, 1, timeout=60))
        try:
            busy = self._get(self.alice, self.CSV)
            self.assertEqual(busy.status_code, 429)
            self.assertEqual(busy.get_json()["code"], "export_in_progress")
            self.assertEqual(self._get(self.bob, self.CSV).status_code, 200)  # another user is not blocked
        finally:
            cache.delete(key)
        self.assertEqual(self._get(self.alice, self.CSV).status_code, 200)
        self.assertTrue(cache.add(key, 1, timeout=60))  # the finished download freed its slot
        cache.delete(key)

    def test_a_refused_download_frees_its_slot(self):
        key = f"public-demo-export:{self.base_admin_id}"
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(self.CSV).status_code, 404)
        self.assertTrue(cache.add(key, 1, timeout=60))
        cache.delete(key)

    def test_each_download_is_audited_with_counts_only(self):
        self._get(self.alice, self.CSV)
        self._get(self.alice, self.JSON)
        events = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == self.alice.user_id,
            AuthSecurityEvent.event_type == "public_demo_download",
        ).order_by(AuthSecurityEvent.occurred_at)).all()
        self.assertEqual([e.detail for e in events], [
            {"format": "csv", "cases": 1}, {"format": "json", "cases": 1}])
        self.assertNotIn("rep-dl-a", json.dumps([e.detail for e in events]))
        # A refused (404) request writes no event.
        before = db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "public_demo_download"))
        self._login(self.base_admin_id)
        self.client.get(self.CSV)
        after = db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "public_demo_download"))
        self.assertEqual(before, after)
