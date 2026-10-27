"""KPI step 2, groups (c) blockers, (d) workforce and (e) quality / sync (digitva-0hul, digitva-r5s0).

C-23 blocked forms, C-21 utilization, C-15 / C-20 language, C-05 / C-06 and
C-03 on the coding-scope tree project (District > CHC > PHC One / PHC Two,
one site CS01). Every assertion on an absence is preceded by a guard that the
subject exists. Policy: docs/policy/kpis.md, access-control-model.md (Q5).
"""
import uuid
from unittest import mock
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSyncRun,
    VaUserAccessGrants,
)
from app.routes.api.dm_kpi.dm_kpi_coders import compute_c21
from app.routes.api.dm_kpi.dm_kpi_exclusions import compute_c05
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture


class DmKpiCdeBase(UnitScopeFixture, BaseTestCase):

    def setUp(self):
        super().setUp()
        self.levels, self.district, self.chc, self.phc_a, self.phc_b = self._tree()

    # -- fixtures ----------------------------------------------------------

    def _unique(self, label):
        return f"{label}.{uuid.uuid4().hex[:8]}@test.local"

    def _case(self, sid, state, unit=None, language="English", hours=None, reviewstate=None,
              form_id=None):
        """One submission in *state*, optionally aged *hours* in that state."""
        submission = self._sub(sid, unit=unit, form_id=form_id)
        submission.va_narration_language = language
        if reviewstate:
            submission.va_odk_reviewstate = reviewstate
        workflow = db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == sid)
        )
        workflow.workflow_state = state
        if hours is not None:
            workflow.workflow_updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
        db.session.commit()
        return submission

    def _dm(self, unit=None):
        """A unit DM, or a pair DM on the tree project's site."""
        if unit is not None:
            user = self._get_or_make_user(self._unique("cde.unit.dm"), "UnitScope123")
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=unit.org_unit_id, grant_status=VaStatuses.active,
            ))
        else:
            user = self._get_or_make_user(self._unique("cde.site.dm"), "UnitScope123")
            pair_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE))
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=pair_id, grant_status=VaStatuses.active,
            ))
        db.session.commit()
        return user

    def _coder(self, languages, unit=None, project=False):
        """A coder with a unit grant (*unit*) or a project grant (*project*)."""
        user = self._get_or_make_user(self._unique("cde.coder"), "Coder123")
        user.vacode_language = list(languages)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project if project else VaAccessScopeTypes.org_unit,
            project_id=self.PROJECT if project else None,
            org_unit_id=None if project else unit.org_unit_id,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _kpi(self, user, path):
        self._login(str(user.user_id))
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _rows(self, data):
        return {b["blockage_reason"]: b for b in data["breakdown"]}


class BlockedFormsTests(DmKpiCdeBase):

    def test_coded_cases_are_not_blocked_even_with_a_missing_language_or_odk_flag(self):
        self._case("csc-cde-coded", "coder_finalized", unit=self.phc_a, language="", reviewstate="hasIssues")
        self._case("csc-cde-screen", "screening_pending", unit=self.phc_a)
        # Guard: the coded case is in the data and would match both old row conditions.
        coded = db.session.execute(sa.text(
            "SELECT COUNT(*) FROM va_submissions s JOIN va_submission_workflow w ON w.va_sid = s.va_sid "
            "WHERE s.va_sid = 'csc-cde-coded' AND w.workflow_state = 'coder_finalized' "
            "AND s.va_narration_language = '' AND s.va_odk_reviewstate = 'hasIssues'"
        )).scalar()
        self.assertEqual(coded, 1)

        data = self._kpi(self._dm(), "exclusions/blocked")
        rows = self._rows(data)

        self.assertEqual(data["total_blocked"], 1)
        self.assertIn("screening_pending", rows)
        self.assertNotIn("missing_language", rows)
        self.assertNotIn("odk_has_issues", rows)

    def test_pending_flags_count_and_every_row_has_an_owner_and_an_age(self):
        self._case("csc-cde-lang", "ready_for_coding", unit=self.phc_a, language="", hours=30)
        self._case("csc-cde-odk", "ready_for_coding", unit=self.phc_a, reviewstate="hasIssues", hours=10)
        self._case("csc-cde-sync", "attachment_sync_pending", unit=self.phc_a, hours=50)
        self._case("csc-cde-svapending", "smartva_pending", unit=self.phc_a, hours=2)
        self._case("csc-cde-upstream", "finalized_upstream_changed", unit=self.phc_a, hours=4)
        self._coder(["English"], project=True)

        data = self._kpi(self._dm(), "exclusions/blocked")
        rows = self._rows(data)

        for reason in ("missing_language", "odk_has_issues", "attachment_sync_pending",
                       "smartva_pending", "finalized_upstream_changed"):
            with self.subTest(reason=reason):
                self.assertIn(reason, rows)
                self.assertEqual(rows[reason]["count"], 1)
                self.assertTrue(rows[reason]["owner"])
                self.assertGreaterEqual(rows[reason]["age_max_hours"], rows[reason]["age_p50_hours"])
        self.assertAlmostEqual(rows["attachment_sync_pending"]["age_p50_hours"], 50, delta=0.5)
        self.assertAlmostEqual(rows["odk_has_issues"]["age_max_hours"], 10, delta=0.5)
        self.assertEqual(rows["missing_language"]["owner"], "data manager")
        # Five distinct cases; the ODK-flagged and missing-language cases share no case.
        self.assertEqual(data["total_blocked"], 5)

    def test_a_case_in_two_rows_counts_once_in_the_total(self):
        self._case("csc-cde-both", "ready_for_coding", unit=self.phc_a, language="", reviewstate="hasIssues")
        self._coder(["English"], project=True)

        data = self._kpi(self._dm(), "exclusions/blocked")
        rows = self._rows(data)

        self.assertEqual((rows["missing_language"]["count"], rows["odk_has_issues"]["count"]), (1, 1))
        self.assertEqual(data["total_blocked"], 1)

    def test_no_coder_at_unit_row_follows_the_cases_own_unit(self):
        self._case("csc-cde-nocoder", "ready_for_coding", unit=self.phc_a)
        self._case("csc-cde-covered", "ready_for_coding", unit=self.phc_b)
        self._coder(["English"], unit=self.phc_b)
        dm = self._dm()

        rows = self._rows(self._kpi(dm, "exclusions/blocked"))
        self.assertEqual(rows["no_coder_at_unit"]["count"], 1)
        self.assertEqual(rows["no_coder_at_unit"]["owner"], "coder supervisor or in-charge")

        # A coder at the CHC above PHC One covers that case too (a new DM: new cache key).
        self._coder(["English"], unit=self.chc)
        rows = self._rows(self._kpi(self._dm(), "exclusions/blocked"))
        self.assertNotIn("no_coder_at_unit", rows)

    def test_a_deactivated_coder_does_not_cover_a_unit(self):
        self._case("csc-cde-deact", "ready_for_coding", unit=self.phc_a)
        coder = self._coder(["English"], unit=self.phc_a)
        # Guard: while active, the coder covers the case and counts in C-21.
        dm = self._dm()
        self.assertNotIn("no_coder_at_unit", self._rows(self._kpi(dm, "exclusions/blocked")))
        self.assertEqual(self._kpi(dm, "coders/utilization")["total_coders"], 1)

        coder.user_status = VaStatuses.deactive
        db.session.commit()
        dm = self._dm()  # a new DM: new cache key
        self.assertEqual(self._rows(self._kpi(dm, "exclusions/blocked"))["no_coder_at_unit"]["count"], 1)
        self.assertEqual(self._kpi(dm, "coders/utilization")["total_coders"], 0)

    def test_a_training_unit_grant_leaves_blocked_and_coder_counts(self):
        # A second project stands in as training; PHC One is its only unit.
        training_id = self.BASE_PROJECT_ID
        self.phc_a.project_id = training_id
        db.session.commit()
        self._case("csc-cde-real", "screening_pending", unit=self.phc_b)
        self._case("csc-cde-train", "screening_pending", unit=self.phc_a)
        self._coder(["English"], unit=self.phc_a)
        dm = self._dm(self.phc_b)
        db.session.add(VaUserAccessGrants(
            user_id=dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.phc_a.org_unit_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()

        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=training_id):
            data = self._kpi(dm, "exclusions/blocked")
            coders = self._kpi(dm, "coders/utilization")["total_coders"]

        self.assertIn("screening_pending", self._rows(data))  # the real case is present
        self.assertEqual(data["total_blocked"], 1)
        self.assertEqual(coders, 0)

    def test_a_coder_above_the_scope_level_does_not_cover_a_unit_on_a_view_only_project(self):
        self._case("csc-cde-viewonly", "ready_for_coding", unit=self.phc_a)
        self._coder(["English"], unit=self.chc)
        # Guard: with no scope level the CHC coder covers PHC One.
        self.assertNotIn("no_coder_at_unit", self._rows(self._kpi(self._dm(), "exclusions/blocked")))

        self._set_scope(self.levels["phc"], mode="view_only")
        rows = self._rows(self._kpi(self._dm(), "exclusions/blocked"))
        self.assertEqual(rows["no_coder_at_unit"]["count"], 1)

    def test_language_gap_row_counts_ready_cases_without_a_matching_coder(self):
        self._case("csc-cde-hindi", "ready_for_coding", unit=self.phc_a, language="Hindi")
        self._case("csc-cde-eng", "ready_for_coding", unit=self.phc_a, language="English")
        self._coder(["english"], unit=self.phc_a)

        rows = self._rows(self._kpi(self._dm(), "exclusions/blocked"))

        self.assertEqual(rows["language_gap"]["count"], 1)
        self.assertEqual(rows["language_gap"]["owner"], "coder supervisor or in-charge")

    def test_soft_gate_not_codeable_is_a_separate_count_outside_the_total(self):
        self._case("csc-cde-soft", "not_codeable_by_coder", unit=self.phc_a)
        self._case("csc-cde-soft-dm", "not_codeable_by_data_manager", unit=self.phc_a)

        data = self._kpi(self._dm(), "exclusions/blocked")

        self.assertEqual(data["soft_gate_not_codeable"], 2)
        self.assertEqual(data["total_blocked"], 0)
        self.assertEqual(data["breakdown"], [])

    def test_intake_source_splits_every_row(self):
        form = db.session.get(VaForms, self.OTHER_FORM_ID)
        form.form_source = "web"
        db.session.commit()
        self._case("csc-cde-odk-src", "screening_pending", unit=self.phc_a)
        self._case("csc-cde-web-src", "screening_pending", unit=self.phc_a, form_id=self.OTHER_FORM_ID)

        row = self._rows(self._kpi(self._dm(), "exclusions/blocked"))["screening_pending"]

        self.assertEqual(row["count"], 2)
        self.assertEqual(row["intake_source"], {"odk": 1, "web": 1})

    def test_by_unit_slices_the_same_blocked_set(self):
        self._case("csc-cde-u1", "screening_pending", unit=self.phc_a)
        self._case("csc-cde-u2", "screening_pending", unit=self.phc_a)
        self._case("csc-cde-u3", "screening_pending", unit=self.phc_b)

        rows = self._kpi(self._dm(), "exclusions/blocked?by=unit")["rows"]
        by_unit = {r["org_unit_id"]: r["total_blocked"] for r in rows}

        self.assertEqual(by_unit[str(self.phc_a.org_unit_id)], 2)
        self.assertEqual(by_unit[str(self.phc_b.org_unit_id)], 1)

    def test_an_unknown_by_is_refused(self):
        self._login(str(self._dm().user_id))
        response = self.client.get("/api/v1/analytics/dm-kpi/exclusions/blocked?by=coder")
        self.assertEqual(response.status_code, 400)


class CoverageAndLanguageTests(DmKpiCdeBase):

    def _fleet(self):
        """A project coder, coders at PHC One, PHC Two, the CHC and the district."""
        return {
            "project": self._coder(["English"], project=True),
            "phc_a": self._coder(["English"], unit=self.phc_a),
            "phc_b": self._coder(["English"], unit=self.phc_b),
            "chc": self._coder(["English"], unit=self.chc),
            "district": self._coder(["English"], unit=self.district),
        }

    def _total(self, user):
        return self._kpi(user, "coders/utilization")["total_coders"]

    def test_a_unit_dm_counts_fewer_coders_than_a_pair_dm(self):
        self._fleet()
        self._case("csc-cde-cov", "ready_for_coding", unit=self.phc_a)

        pair_total = self._total(self._dm())
        unit_total = self._total(self._dm(self.phc_a))

        # The pair DM holds the project's coders; the PHC One DM excludes PHC Two's.
        self.assertEqual(pair_total, 5)
        self.assertEqual(unit_total, 4)

    def test_view_only_ancestors_above_the_scope_level_do_not_cover(self):
        self._fleet()
        self._set_scope(self.levels["phc"], mode="view_only")
        # Project, CHC and district grants sit above the PHC scope level: they code nothing.
        self.assertEqual(self._total(self._dm(self.phc_a)), 1)

        self._set_scope(self.levels["phc"], mode="code_any")
        self.assertEqual(self._total(self._dm(self.phc_a)), 4)

    def test_utilization_counts_covering_coders_with_an_active_allocation(self):
        fleet = self._fleet()
        self._case("csc-cde-alloc", "coding_in_progress", unit=self.phc_a)
        db.session.add(VaAllocations(
            va_sid="csc-cde-alloc", va_allocated_to=fleet["phc_a"].user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        db.session.commit()

        data = self._kpi(self._dm(self.phc_a), "coders/utilization")

        self.assertEqual((data["active_count"], data["total_coders"]), (1, 4))
        self.assertEqual(data["rate"], 25.0)

    def test_utilization_by_language_is_the_coder_pool_per_language(self):
        self._coder(["English", "Hindi"], project=True)
        self._coder(["english"], unit=self.phc_a)
        self._coder([], unit=self.phc_a)  # no languages: covers any
        self._case("csc-cde-pool", "ready_for_coding", unit=self.phc_a)

        data = self._kpi(self._dm(), "coders/utilization?by=language")
        pool = {r["language"]: r["coders"] for r in data["rows"]}

        # english: 2 explicit (case-folded together) + 1 any-language coder; hindi: 1 + 1.
        self.assertEqual(pool["english"], 3)
        self.assertEqual(pool["hindi"], 2)

    def test_english_matches_english_whatever_the_case(self):
        self._case("csc-cde-case", "ready_for_coding", unit=self.phc_a, language="English")
        self._coder(["english"], unit=self.phc_a)

        gap = self._kpi(self._dm(), "language/gap")
        english = [lang for lang in gap["languages"] if lang["language"].lower() == "english"]

        self.assertEqual(len(english), 1)
        self.assertEqual(english[0]["coders_available"], 1)
        self.assertFalse(english[0]["gap"])
        self.assertEqual(gap["gap_cases"], 0)

    def test_a_coder_with_no_languages_covers_any_language(self):
        self._case("csc-cde-marathi", "ready_for_coding", unit=self.phc_a, language="Marathi")
        hindi_only = self._coder(["Hindi"], unit=self.phc_a)
        dm = self._dm()
        # Guard: the coder exists and is counted, but does not match Marathi.
        gap = self._kpi(dm, "language/gap")
        self.assertEqual(self._total(dm), 1)
        self.assertEqual(gap["gap_cases"], 1)

        hindi_only.vacode_language = []
        db.session.commit()
        # A new DM, so a new cache key: the KPI cache would serve the first answer.
        gap = self._kpi(self._dm(), "language/gap")
        self.assertEqual(gap["gap_cases"], 0)

    def test_c20_counts_the_pending_states_and_c15_only_the_ready_pool(self):
        self._case("csc-cde-ready", "ready_for_coding", unit=self.phc_a, language="Hindi")
        self._case("csc-cde-svapend", "smartva_pending", unit=self.phc_a, language="Marathi")
        dm = self._dm()

        pendency = {lang["language"] for lang in self._kpi(dm, "language/pendency")["languages"]}
        gap = {lang["language"] for lang in self._kpi(dm, "language/gap")["languages"]}

        self.assertEqual(pendency, {"Hindi", "Marathi"})  # guard: Marathi exists as pending
        self.assertEqual(gap, {"Hindi"})


class NotCodeableTests(DmKpiCdeBase):

    def _review(self, sid, kind, reason):
        if kind == "coder":
            db.session.add(VaCoderReview(
                va_sid=sid, va_creview_by=self.base_coder_user.user_id,
                va_creview_reason=reason, va_creview_status=VaStatuses.active,
            ))
        else:
            db.session.add(VaDataManagerReview(
                va_sid=sid, va_dmreview_by=self.base_admin_user.user_id,
                va_dmreview_reason=reason, va_dmreview_status=VaStatuses.active,
            ))
        db.session.commit()

    def _seed(self):
        self._case("csc-cde-nc1", "not_codeable_by_coder", unit=self.phc_a)
        self._case("csc-cde-nc2", "not_codeable_by_coder", unit=self.phc_a)
        self._case("csc-cde-nc3", "not_codeable_by_data_manager", unit=self.phc_a)
        self._case("csc-cde-ok", "ready_for_coding", unit=self.phc_a)
        self._review("csc-cde-nc1", "coder", "no_info")
        self._review("csc-cde-nc2", "coder", "narration_language")
        self._review("csc-cde-nc3", "dm", "submission_incomplete")

    def test_by_actor_counts_active_review_rows_per_actor(self):
        self._seed()
        data = self._kpi(self._dm(), "exclusions/not-codeable?by=actor")
        rows = {r["actor"]: r["count"] for r in data["rows"]}

        self.assertEqual(rows["coder"], 2)
        self.assertEqual(rows["data_manager"], 1)
        self.assertEqual(rows["screening_rejected"], 0)

    def test_by_reason_splits_coder_and_dm_reasons(self):
        self._seed()
        data = self._kpi(self._dm(), "exclusions/not-codeable?by=reason")
        rows = {(r["actor"], r["reason"]): r["count"] for r in data["rows"]}

        self.assertEqual(rows[("coder", "no_info")], 1)
        self.assertEqual(rows[("coder", "narration_language")], 1)
        self.assertEqual(rows[("data_manager", "submission_incomplete")], 1)

    def test_the_summary_carries_the_coder_and_dm_shares(self):
        self._seed()
        data = self._kpi(self._dm(), "exclusions/not-codeable")

        self.assertEqual(data["count"], 3)
        self.assertEqual((data["coder"]["count"], data["dm"]["count"]), (2, 1))
        self.assertEqual(data["all_synced"], 4)

    def test_legacy_routes_keep_their_shapes(self):
        self._seed()
        dm = self._dm()
        rates = self._kpi(dm, "exclusions/rates")
        breakdown = self._kpi(dm, "exclusions/breakdown")

        self.assertEqual(rates["not_codeable_overall"]["count"], 3)
        self.assertEqual(rates["coder_not_codeable"]["count"], 2)
        self.assertEqual(rates["dm_not_codeable"]["count"], 1)
        self.assertEqual(breakdown["by_actor"]["coder"], 2)
        self.assertEqual({r["reason"] for r in breakdown["coder_reasons"]}, {"no_info", "narration_language"})
        self.assertEqual([r["reason"] for r in breakdown["dm_reasons"]], ["submission_incomplete"])

    def test_c06_by_reason_is_always_present(self):
        self._case("csc-cde-refused", "consent_refused", unit=self.phc_a)

        data = self._kpi(self._dm(), "exclusions/not-analysable?by=reason")

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["by_reason"]["refused"], 1)
        self.assertEqual(data["by_reason"]["respondent_unavailable"], 0)

    def test_compute_functions_take_a_scope_a_period_and_a_by(self):
        self._seed()
        from flask_login import login_user

        from app.routes.api.dm_kpi.dm_kpi_scope import dm_scope

        with self.app.test_request_context("/"):
            login_user(self._dm())
            scope = dm_scope()
            self.assertEqual(compute_c05(scope, None, None)["count"], 3)
            self.assertEqual(compute_c21(scope, None, None)["active_count"], 0)
            with self.assertRaises(ValueError):
                compute_c05(scope, None, "coder")


class SyncHealthTests(DmKpiCdeBase):

    def _run(self, status, days_ago):
        started = datetime.now(UTC) - timedelta(days=days_ago)
        db.session.add(VaSyncRun(
            triggered_by="scheduled", started_at=started,
            finished_at=started + timedelta(minutes=1), status=status,
        ))

    def test_error_rate_over_seven_days_and_the_last_run_status(self):
        db.session.execute(sa.delete(VaSyncRun))
        self._run("success", 0.5)
        self._run("partial", 1)
        self._run("error", 2)
        self._run("success", 3)
        self._run("error", 30)  # outside the 7-day window, inside the cumulative one
        db.session.commit()
        dm = self._dm()

        data = self._kpi(dm, "sync/status")

        self.assertEqual((data["runs_7d"]["total"], data["runs_7d"]["errors"]), (4, 2))
        self.assertEqual(data["error_rate_7d"], 50.0)
        self.assertEqual(data["rate"], 50.0)
        self.assertEqual(data["last_status"], "success")
        self.assertEqual(data["latest_run"]["status"], "success")
        self.assertEqual((data["runs_cumulative"]["total"], data["runs_cumulative"]["errors"]), (5, 3))

        cumulative = self._kpi(dm, "sync/status?period=cumulative")
        self.assertEqual(cumulative["rate"], 60.0)

    def test_no_runs_is_a_zero_rate_with_no_status(self):
        db.session.execute(sa.delete(VaSyncRun))
        db.session.commit()

        data = self._kpi(self._dm(), "sync/status")

        self.assertEqual((data["rate"], data["runs"], data["last_status"]), (0.0, 0, None))
