"""The "Site and unit" filter of the coding and reviewing queue lists (bead digitva-lqmo).

``site_id`` and ``org_unit_id`` on ``GET /api/v1/coding/available|history``
and ``/reviewing/available|history`` only narrow what the caller's own scope
already lists: a site matches the form's site, a unit itself and its subtree.
The AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2, D2) and the AZSP01 site project
come from the authz fixture.
"""
from datetime import datetime

from app import db
from app.models import (
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import org_unit_routing_service as routing
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from tests.authz.fixture import FORMS, SIDS, SP, AuthzFixtureMixin, P, R
from tests.base import BaseTestCase

CODED_AT = datetime(2026, 5, 1, 12, 0, 0)  # naive UTC, as the columns are


class _PlaceFilterBase(AuthzFixtureMixin, BaseTestCase):
    """Every fixture case in *STATE*, plus two finished cases (P1 and its
    sub-centre SC1) whose final ``_finish`` writes (the history rows)."""

    STATE = WORKFLOW_READY_FOR_CODING
    AVAILABLE = ""
    HISTORY = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for sid in SIDS:
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state=cls.STATE,
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))
        for sid, unit_key in (("hx-p1", "P1"), ("hx-sc1", "SC1")):
            cls._add_case(sid, unit_key)
            cls._finish(sid)
        db.session.commit()

    @classmethod
    def _add_case(cls, sid, unit_key, state=None):
        """A tree case routed to *unit_key*; *state* adds its workflow row."""
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=FORMS["ta1"][0], va_submission_date=CODED_AT,
            va_odk_updatedat=CODED_AT, va_data_collector="Collector",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English",
            va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
            org_unit_id=cls.units[unit_key].org_unit_id,
            org_unit_resolution=routing.RESOLUTION_FORM_FIELD,
        ))
        db.session.flush()
        if state:
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state=state,
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))

    def _sids(self, user_key, path, **params):
        self._login(str(self.users[user_key].user_id))
        response = self.client.get(path, query_string={"limit": 200, **params})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        return {row["va_sid"] for row in body.get("forms", body.get("cases", body.get("history", [])))}

    def _unit(self, key):
        return str(self.units[key].org_unit_id)

    def _stats(self, user_key, **params):
        self._login(str(self.users[user_key].user_id))
        response = self.client.get(self.STATS, query_string=params)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _assert_stats_malformed_are_400_and_blank_is_unchanged(self, user_key):
        self._login(str(self.users[user_key].user_id))
        for params in ({"org_unit_id": "not-a-uuid"}, {"site_id": "x" * 65}, {"site_id": "AZS1;--"}):
            with self.subTest(params=params):
                response = self.client.get(self.STATS, query_string=params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["code"], "invalid_request")
        plain = self.client.get(self.STATS).get_json()
        self.assertEqual(self.client.get(self.STATS, query_string={"site_id": "", "org_unit_id": " "}).get_json(), plain)

    # -- shared cases ------------------------------------------------------

    def _assert_unit_filter_is_its_subtree(self, user_key):
        everything = self._sids(user_key, self.AVAILABLE)
        # Present first: the parent C1, the unit P1, its sub-centre SC1 and its sibling P2.
        self.assertTrue({"ta-c1", "ta-p1", "ta-sc1", "ta-p2"} <= everything)
        self.assertEqual(self._sids(user_key, self.AVAILABLE, org_unit_id=self._unit("P1")),
                         {"ta-p1", "ta-sc1"})
        self.assertEqual(self._sids(user_key, self.AVAILABLE, org_unit_id=self._unit("SC1")), {"ta-sc1"})

    def _assert_place_outside_reach_adds_nothing(self, user_key, own, outside):
        everything = self._sids(user_key, self.AVAILABLE)
        self.assertEqual(everything & {"ta-p1", "ta-sc1"}, {"ta-p1", "ta-sc1"})
        self.assertNotIn("ta-p2", everything)
        self.assertEqual(self._sids(user_key, self.AVAILABLE, org_unit_id=self._unit(outside)), set())
        # An ancestor unit spans more than the grant: still only the grant's own cases.
        self.assertEqual(self._sids(user_key, self.AVAILABLE, org_unit_id=self._unit("D1")), everything)
        self.assertTrue({"ta-p1", "ta-sc1"} <= self._sids(user_key, self.AVAILABLE, org_unit_id=self._unit(own)))

    def _assert_site_filter(self, user_key, *, kept, dropped):
        everything = self._sids(user_key, self.AVAILABLE)
        self.assertIn(kept, everything)
        self.assertIn(dropped, everything)
        site = FORMS[SIDS[kept][0]][2]
        narrowed = self._sids(user_key, self.AVAILABLE, site_id=site)
        self.assertIn(kept, narrowed)
        self.assertNotIn(dropped, narrowed)
        self.assertLessEqual(narrowed, everything)

    def _assert_site_outside_reach_adds_nothing(self, user_key, outside_sid):
        everything = self._sids(user_key, self.AVAILABLE)
        self.assertIn("sp-1", everything)
        self.assertNotIn(outside_sid, everything)
        self.assertEqual(self._sids(user_key, self.AVAILABLE, site_id=FORMS[SIDS[outside_sid][0]][2]), set())

    def _assert_history_unit_filter(self, user_key):
        everything = self._sids(user_key, self.HISTORY)
        self.assertTrue({"hx-p1", "hx-sc1"} <= everything)
        self.assertEqual(self._sids(user_key, self.HISTORY, org_unit_id=self._unit("SC1")), {"hx-sc1"})
        self.assertEqual(self._sids(user_key, self.HISTORY, org_unit_id=self._unit("P1")) & {"hx-p1", "hx-sc1"},
                         {"hx-p1", "hx-sc1"})
        self.assertEqual(self._sids(user_key, self.HISTORY, site_id="AZS3"), set())

    def _rows(self, user_key, path):
        self._login(str(self.users[user_key].user_id))
        body = self.client.get(path, query_string={"limit": 200}).get_json()
        return {row["va_sid"]: row for row in body.get("forms", body.get("cases", body.get("history", [])))}

    def _assert_items_carry_the_narration_language(self, user_key):
        """The additive ``va_narration_language`` (the card's pill) beside the old keys."""
        available = self._rows(user_key, self.AVAILABLE)
        history = self._rows(user_key, self.HISTORY)
        old = {"va_sid", "va_uniqueid_masked", "va_form_id", "project_id", "site_id", "va_submission_date",
               "va_deceased_age", "va_deceased_gender"}
        for item in (available["ta-sc1"], history["hx-sc1"]):
            self.assertTrue(old <= item.keys(), item.keys())
            self.assertEqual(item["va_narration_language"], "English")
            self.assertEqual(item["va_deceased_age"], 42)

    def _assert_malformed_values_are_400(self, user_key):
        self._login(str(self.users[user_key].user_id))
        for path in (self.AVAILABLE, self.HISTORY):
            for params in ({"org_unit_id": "not-a-uuid"}, {"site_id": "x" * 65}, {"site_id": "AZ S1"},
                           {"site_id": "AZS1;--"}):
                with self.subTest(path=path, params=params):
                    response = self.client.get(path, query_string={"limit": 50, **params})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["code"], "invalid_request")

    def _assert_no_param_is_unchanged(self, user_key):
        self._login(str(self.users[user_key].user_id))
        for path in (self.AVAILABLE, self.HISTORY):
            with self.subTest(path=path):
                plain = self.client.get(path, query_string={"limit": 200}).get_json()
                blank = self.client.get(path, query_string={"limit": 200, "site_id": "", "org_unit_id": " "}).get_json()
                self.assertTrue(plain.get("forms", plain.get("cases", plain.get("history"))))
                self.assertEqual(blank, plain)


class CodingPlaceFilterTests(_PlaceFilterBase):
    STATE = WORKFLOW_READY_FOR_CODING
    AVAILABLE = "/api/v1/coding/available"
    HISTORY = "/api/v1/coding/history"
    STATS = "/api/v1/coding/stats"

    def test_stats_follow_a_unit_subtree(self):
        everything = self._stats("tester_c1")
        self.assertEqual(everything["pick_ready"], len(self._sids("tester_c1", self.AVAILABLE)))
        self.assertGreaterEqual(everything["pick_ready"], 4)
        narrowed = self._stats("tester_c1", org_unit_id=self._unit("P1"))
        self.assertEqual(narrowed["pick_ready"], 2)
        self.assertEqual((narrowed["has_pick_mode"], narrowed["has_random_mode"]),
                         (everything["has_pick_mode"], everything["has_random_mode"]))
        # The coder's own outputs narrow too: two finals, one of them in SC1.
        self.assertEqual(self._stats("coder_p1")["completed"], 2)
        self.assertEqual(self._stats("coder_p1", org_unit_id=self._unit("SC1"))["completed"], 1)

    def test_stats_follow_a_site(self):
        self.assertEqual(self._stats("coder_sp")["pick_ready"], 2)
        self.assertEqual(self._stats("coder_sp", site_id="AZS3")["pick_ready"], 1)

    def test_stats_for_a_place_outside_reach_count_nothing(self):
        self.assertEqual(self._stats("coder_p1")["pick_ready"], 2)
        self.assertEqual(self._stats("coder_p1", org_unit_id=self._unit("P2"))["pick_ready"], 0)
        self.assertEqual(self._stats("coder_sp1", site_id="AZS3")["pick_ready"], 0)

    def test_stats_refuse_malformed_places_and_answer_blank_ones_unchanged(self):
        self._assert_stats_malformed_are_400_and_blank_is_unchanged("coder_p1")

    @classmethod
    def _finish(cls, sid):
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=WORKFLOW_CODER_FINALIZED,
            workflow_reason="test_seed", workflow_updated_by_role="vasystem",
        ))
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=cls.users["coder_p1"].user_id, va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active, va_finassess_createdat=CODED_AT,
        ))

    def test_a_unit_filter_matches_the_unit_and_its_subtree(self):
        # coding_tester is exempt from the PHC coding level, so a C1 tester lists C1's whole subtree.
        self._assert_unit_filter_is_its_subtree("tester_c1")

    def test_a_unit_outside_the_coders_reach_adds_nothing(self):
        self._assert_place_outside_reach_adds_nothing("coder_p1", own="P1", outside="P2")

    def test_a_site_filter_matches_that_site(self):
        self._assert_site_filter("coder_sp", kept="sp-3", dropped="sp-1")

    def test_a_site_outside_the_coders_reach_adds_nothing(self):
        self._assert_site_outside_reach_adds_nothing("coder_sp1", "sp-3")

    def test_history_pages_narrow_to_the_place(self):
        self._assert_history_unit_filter("coder_p1")

    def test_the_unpaged_history_refuses_a_place_and_the_unpaged_list_applies_it(self):
        self._login(str(self.users["coder_p1"].user_id))
        response = self.client.get(self.HISTORY, query_string={"org_unit_id": self._unit("P1")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")
        unpaged = self.client.get(self.AVAILABLE, query_string={"org_unit_id": self._unit("SC1")}).get_json()
        self.assertEqual({row["va_sid"] for row in unpaged["forms"]}, {"ta-sc1"})

    def test_items_carry_the_narration_language(self):
        self._assert_items_carry_the_narration_language("coder_p1")

    def test_malformed_values_are_400(self):
        self._assert_malformed_values_are_400("coder_p1")

    def test_no_place_answers_exactly_what_it_did(self):
        self._assert_no_param_is_unchanged("coder_p1")


class ReviewingPlaceFilterTests(_PlaceFilterBase):
    STATE = WORKFLOW_REVIEWER_ELIGIBLE
    AVAILABLE = "/api/v1/reviewing/available"
    HISTORY = "/api/v1/reviewing/history"
    STATS = "/api/v1/reviewing/stats"

    def test_stats_follow_a_unit_subtree(self):
        everything = self._stats("reviewer_p1")
        self.assertEqual(everything["available"], len(self._sids("reviewer_p1", self.AVAILABLE)))
        self.assertGreaterEqual(everything["available"], 2)
        self.assertEqual(everything["completed"], 2)
        narrowed = self._stats("reviewer_p1", org_unit_id=self._unit("SC1"))
        # SC1 holds ta-sc1 (eligible), hx-sc1 (finished by this reviewer) and two cases being coded.
        self.assertEqual((narrowed["available"], narrowed["completed"], narrowed["in_scope"]), (1, 1, 4))
        self.assertLess(narrowed["in_scope"], everything["in_scope"])

    def test_stats_follow_a_site(self):
        everything = self._stats("reviewer_sp")
        self.assertEqual(everything["available"], 2)
        self.assertEqual(self._stats("reviewer_sp", site_id="AZS3")["available"], 1)

    def test_stats_for_a_place_outside_reach_count_nothing(self):
        self.assertGreaterEqual(self._stats("reviewer_p1")["available"], 2)
        self.assertEqual(self._stats("reviewer_p1", org_unit_id=self._unit("P2")),
                         {"in_scope": 0, "completed": 0, "available": 0, "pending_coding": 0, "allocation": None,
                          "languages": {"mine": ["English"]}})
        self.assertEqual(self._stats("reviewer_sp1", site_id="AZS3")["available"], 0)

    def test_stats_refuse_malformed_places_and_answer_blank_ones_unchanged(self):
        self._assert_stats_malformed_are_400_and_blank_is_unchanged("reviewer_p1")

    def test_stats_carry_the_reviewers_languages(self):
        self.assertEqual(self._stats("reviewer_p1")["languages"], {"mine": list(self.users["reviewer_p1"].vacode_language or [])})

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A project-wide reviewer of the site project, to narrow between two of its sites.
        user = cls._get_or_make_user("authz.reviewer_sp@test.local", "AuthzTest123")
        db.session.add(cls._grant_row(user, R.reviewer, P, SP))
        cls.users["reviewer_sp"] = user
        # Pending coding: waiting (ready), being coded (in progress, Step 1 saved); a coder final is not pending.
        cls._add_case("pc-p1", "P1", WORKFLOW_READY_FOR_CODING)
        cls._add_case("pc-sc1", "SC1", WORKFLOW_CODING_IN_PROGRESS)
        cls._add_case("pc-sc1b", "SC1", WORKFLOW_CODER_STEP1_SAVED)
        cls._add_case("pc-cf", "P1", WORKFLOW_CODER_FINALIZED)
        db.session.commit()

    def test_pending_coding_counts_only_cases_before_the_coders_final(self):
        # reviewer_eligible (the fixture cases), reviewer_finalized (hx-) and coder_finalized (pc-cf) are left out.
        everything = self._stats("reviewer_p1")
        self.assertEqual(everything["pending_coding"], 3)
        self.assertGreater(everything["in_scope"], everything["pending_coding"])
        self.assertEqual(self._stats("reviewer_p1", org_unit_id=self._unit("SC1"))["pending_coding"], 2)
        self.assertEqual(self._stats("reviewer_p1", org_unit_id=self._unit("P2"))["pending_coding"], 0)
        # Outside the review reach nothing counts: reviewer_sp1 holds only the site project's AZS1.
        self.assertEqual(self._stats("reviewer_sp1")["pending_coding"], 0)

    @classmethod
    def _finish(cls, sid):
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=WORKFLOW_REVIEWER_FINALIZED,
            workflow_reason="test_seed", workflow_updated_by_role="vasystem",
        ))
        db.session.add(VaReviewerFinalAssessments(
            va_sid=sid, va_rfinassess_by=cls.users["reviewer_p1"].user_id, va_conclusive_cod="R99",
        ))

    def test_the_access_summary_carries_review_reach(self):
        self._login(str(self.users["reviewer_p1"].user_id))
        body = self.client.get("/api/v1/me/access").get_json()
        project = next(p for p in body["projects"] if p["project_id"] == "AZTA01")
        self.assertEqual(project["actions"]["review"],
                         {"project": False, "site_ids": [], "org_unit_ids": [self._unit("P1")]})

    def test_a_unit_filter_matches_the_unit_and_its_subtree(self):
        everything = self._sids("reviewer_p1", self.AVAILABLE)
        self.assertEqual(everything & {"ta-p1", "ta-sc1"}, {"ta-p1", "ta-sc1"})
        self.assertEqual(self._sids("reviewer_p1", self.AVAILABLE, org_unit_id=self._unit("SC1")), {"ta-sc1"})

    def test_a_unit_outside_the_reviewers_reach_adds_nothing(self):
        self._assert_place_outside_reach_adds_nothing("reviewer_p1", own="P1", outside="P2")

    def test_a_site_outside_the_reviewers_reach_adds_nothing(self):
        self._assert_site_outside_reach_adds_nothing("reviewer_sp1", "sp-3")

    def test_a_site_filter_matches_that_site(self):
        self._assert_site_filter("reviewer_sp", kept="sp-3", dropped="sp-1")

    def test_history_pages_narrow_to_the_place(self):
        self._assert_history_unit_filter("reviewer_p1")

    def test_items_carry_the_narration_language(self):
        self._assert_items_carry_the_narration_language("reviewer_p1")

    def test_malformed_values_are_400(self):
        self._assert_malformed_values_are_400("reviewer_p1")

    def test_no_place_answers_exactly_what_it_did(self):
        self._assert_no_param_is_unchanged("reviewer_p1")
