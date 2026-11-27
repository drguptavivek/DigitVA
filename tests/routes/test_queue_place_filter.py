"""The "Site and unit" filter of the coding and reviewing queue lists (bead digitva-lqmo).

``site_id`` and ``org_unit_id`` on ``GET /api/v1/coding/available|history``
and ``/reviewing/available|history`` only narrow what the caller's own scope
already lists: a site matches the form's site, a unit itself and its subtree.
The AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2, D2) and the AZSP01 site project
come from the authz fixture.
"""
import uuid
from datetime import date, datetime, timedelta

from app import db
from app.models import (
    MasOrgUnit,
    VaDeathRegister,
    VaFinalAssessments,
    VaProjectMaster,
    VaReviewerFinalAssessments,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.models.mas_languages import MasLanguages
from app.services import org_unit_routing_service as routing
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from tests.authz.fixture import FORMS, SIDS, SP, TA, AuthzFixtureMixin, P, R
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

    def _assert_nonpii_place_answers_nothing(self, user_key):
        """A caller without personal-data access in the project (a Tier 1
        project-scope grant) gets no rows and zero counts for any place: a unit
        filter would otherwise reveal which unit each listable case is in."""
        self._author("ta-c1", user_key)
        # Present first: without a place the caller lists their C1 case and counts it.
        self.assertIn("ta-c1", self._sids(user_key, self.HISTORY))
        self.assertGreater(self._stats(user_key)["completed"], 0)
        for place in ({"org_unit_id": self._unit("C1")}, {"org_unit_id": self._unit("D1")},
                      {"site_id": FORMS[SIDS["ta-c1"][0]][2]}):
            with self.subTest(place=place):
                self.assertEqual(self._sids(user_key, self.HISTORY, **place), set())
                self.assertEqual(self._sids(user_key, self.AVAILABLE, **place), set())
                self.assertEqual(self._stats(user_key, **place)["completed"], 0)

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

    def _assert_card_keys(self, user_key, nonpii_key, *, add_active_final):
        """The card keys (owner 2026-11-27) on Available and history rows, beside the old keys,
        and the deceased's name only for a caller with personal-data access."""
        earlier = CODED_AT - timedelta(days=2)
        if add_active_final:
            db.session.add(VaFinalAssessments(
                va_sid="hx-sc1", va_finassess_by=self.users["coder_p1"].user_id, va_conclusive_cod="R99",
                va_finassess_status=VaStatuses.active, va_finassess_createdat=CODED_AT,
            ))
        # The recode deactivated the first final and kept it.
        db.session.add(VaFinalAssessments(
            va_sid="hx-sc1", va_finassess_by=self.users["coder_p1"].user_id, va_conclusive_cod="R98",
            va_finassess_status=VaStatuses.deactive, va_finassess_createdat=earlier,
        ))
        # Another coder's final on the same case (a training standard case) and a demo final never count.
        db.session.add(VaFinalAssessments(
            va_sid="hx-sc1", va_finassess_by=self.users["coder_c1"].user_id, va_conclusive_cod="R96",
            va_finassess_status=VaStatuses.deactive, va_finassess_createdat=earlier - timedelta(days=3),
        ))
        db.session.add(VaFinalAssessments(
            va_sid="hx-sc1", va_finassess_by=self.users["coder_p1"].user_id, va_conclusive_cod="R95",
            va_finassess_status=VaStatuses.deactive, va_finassess_createdat=earlier - timedelta(days=4),
            demo_expires_at=earlier,
        ))
        # Tester output never counts as a coding.
        db.session.add(VaFinalAssessments(
            va_sid="hx-sc1", va_finassess_by=self.users["tester_c1"].user_id, va_conclusive_cod="R97",
            va_finassess_status=VaStatuses.deactive, va_finassess_createdat=earlier - timedelta(days=5), is_tester=True,
        ))
        sub = db.session.get(VaSubmissions, "hx-sc1")
        sub.va_deceased_age_normalized_days = 12.5
        for number, sid, name in ((990001, "hx-sc1", "Asha Rao"), (990002, "ta-p1", "Bela Das")):
            db.session.add(VaDeathRegister(
                project_id=TA, site_id=FORMS["ta1"][2], death_number=number, unique_id=f"QC-{uuid.uuid4().hex[:8]}",
                deceased_name=name, has_deceased_name=True, deceased_sex="female", date_of_death=date(2026, 4, 20),
                registered_by=self.users["interviewer_p1"].user_id, source="direct", status="submitted", va_sid=sid,
            ))
        # A cancelled duplicate register row never gives the date.
        db.session.add(VaDeathRegister(
            project_id=TA, site_id=FORMS["ta1"][2], death_number=990003, unique_id=f"QC-{uuid.uuid4().hex[:8]}",
            deceased_name="Asha Rao", has_deceased_name=True, deceased_sex="female", date_of_death=date(2026, 1, 1),
            registered_by=self.users["interviewer_p1"].user_id, source="direct", status="cancelled", va_sid="hx-sc1",
        ))
        db.session.commit()
        available = self._rows(user_key, self.AVAILABLE)
        history = self._rows(user_key, self.HISTORY)
        old = {"va_sid", "va_uniqueid_masked", "va_form_id", "project_id", "site_id", "va_submission_date",
               "va_deceased_age", "va_deceased_gender", "va_narration_language"}
        project = db.session.get(VaProjectMaster, TA)
        nickname = (project.project_nickname or "").strip() or project.project_name
        unit_name = db.session.get(MasOrgUnit, self.units["SC1"].org_unit_id).unit_name
        fresh = available["ta-sc1"]
        self.assertTrue(old <= fresh.keys(), fresh.keys())
        self.assertEqual((fresh["unit_name"], fresh["project_nickname"]), (unit_name, nickname))
        self.assertEqual(fresh["site_name"], db.session.get(VaSiteMaster, FORMS["ta1"][2]).site_name)
        self.assertEqual((fresh["date_of_death"], fresh["first_coded_at"], fresh["last_coded_at"], fresh["recoded"]),
                         (None, None, None, False))
        self.assertIsNone(fresh["va_deceased_age_normalized_days"])
        coded = history["hx-sc1"]
        self.assertTrue(old <= coded.keys(), coded.keys())
        self.assertEqual(coded["va_deceased_age"], 42)
        self.assertEqual(coded["va_deceased_age_normalized_days"], 12.5)
        self.assertEqual(coded["date_of_death"], "2026-04-20")
        self.assertEqual(coded["first_coded_at"], "2026-04-29T12:00:00+00:00")
        self.assertEqual(coded["last_coded_at"], "2026-05-01T12:00:00+00:00")
        self.assertTrue(coded["recoded"])
        # A unit-scope (in-system) coder or reviewer holds personal-data access: the name.
        self.assertEqual(coded["deceased_name"], "Asha Rao")
        # A project-scope one (Tier 1) does not: no name key at all on their own history row.
        self._author("ta-p1", nonpii_key)
        plain = self._rows(nonpii_key, self.HISTORY)["ta-p1"]
        self.assertEqual(plain["date_of_death"], "2026-04-20")
        self.assertNotIn("deceased_name", plain)
        # Nor any place key (owner 2026-11-27): no unit, site or project name without personal-data access.
        for item in (plain, *self._rows(nonpii_key, self.AVAILABLE).values()):
            for key in ("unit_name", "site_name", "project_nickname"):
                self.assertNotIn(key, item)
            self.assertIn("date_of_death", item)

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

    def _author(self, sid, user_key):
        """*user_key*'s active final on *sid* (a history row of theirs)."""
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=self.users[user_key].user_id, va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active, va_finassess_createdat=CODED_AT,
        ))
        db.session.commit()

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

    def test_items_carry_the_card_keys_and_names_only_with_pii(self):
        self._assert_card_keys("coder_p1", "coder_ta", add_active_final=False)

    def test_a_place_answers_nothing_without_personal_data_access(self):
        self._assert_nonpii_place_answers_nothing("coder_ta")

    def test_the_unpaged_lists_carry_the_card_keys(self):
        self._login(str(self.users["coder_p1"].user_id))
        for path, key in ((self.AVAILABLE, "forms"), (self.HISTORY, "history")):
            rows = self.client.get(path).get_json()[key]
            self.assertTrue(rows, path)
            self.assertTrue({"unit_name", "site_name", "project_nickname", "date_of_death", "recoded"} <= rows[0].keys(), path)

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

    def test_pending_coding_leaves_out_a_confirmed_duplicate(self):
        before = self._stats("reviewer_p1")
        self.assertEqual(before["pending_coding"], 3)  # pc-p1 is among them
        db.session.add(VaDeathRegister(
            project_id=TA, site_id=FORMS["ta1"][2], death_number=990004, unique_id=f"QC-{uuid.uuid4().hex[:8]}",
            deceased_name="Asha Rao", has_deceased_name=True, deceased_sex="female", date_of_death=date(2026, 1, 1),
            registered_by=self.users["interviewer_p1"].user_id, source="direct", status="duplicate", va_sid="pc-p1",
        ))
        db.session.commit()
        after = self._stats("reviewer_p1")
        self.assertEqual(after["pending_coding"], 2)
        self.assertEqual(after["in_scope"], before["in_scope"] - 1)

    def _author(self, sid, user_key):
        """*user_key*'s active reviewer final on *sid* (a history row of theirs)."""
        db.session.add(VaReviewerFinalAssessments(
            va_sid=sid, va_rfinassess_by=self.users[user_key].user_id, va_conclusive_cod="R99",
        ))
        db.session.commit()

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
        # Personal-data access per project: a unit (in-system) grant has it, a project-wide one does not.
        self.assertIs(project["pii_visible"], True)
        self._login(str(self.users["reviewer_ta"].user_id))
        body = self.client.get("/api/v1/me/access").get_json()
        self.assertIs(next(p for p in body["projects"] if p["project_id"] == "AZTA01")["pii_visible"], False)

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

    def test_items_carry_the_card_keys_and_names_only_with_pii(self):
        self._assert_card_keys("reviewer_p1", "reviewer_ta", add_active_final=True)

    def test_a_place_answers_nothing_without_personal_data_access(self):
        self._assert_nonpii_place_answers_nothing("reviewer_ta")

    def test_a_reviewer_saves_their_own_languages_and_a_user_with_neither_role_is_refused(self):
        url = "/api/v1/profile/languages"
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English", is_active=True))
            db.session.commit()
        self._login(str(self.users["reviewer_p1"].user_id))
        saved = self.client.patch(url, json={"languages": ["english"]}, headers=self._csrf_headers())
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(self.client.patch(url, json={"languages": []}, headers=self._csrf_headers()).status_code, 400)
        self._login(str(self.users["interviewer_p1"].user_id))
        refused = self.client.patch(url, json={"languages": ["english"]}, headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 403)
        db.session.expire_all()
        self.assertEqual(db.session.get(type(self.users["reviewer_p1"]), self.users["reviewer_p1"].user_id).vacode_language, ["english"])

    def test_malformed_values_are_400(self):
        self._assert_malformed_values_are_400("reviewer_p1")

    def test_no_place_answers_exactly_what_it_did(self):
        self._assert_no_param_is_unchanged("reviewer_p1")
