"""The queues' "Sort and filter" parameters (owner 2026-11-27).

``GET /api/v1/coding/available|history`` and ``/reviewing/available|history``
take ``sort``, ``state``, ``sex``, ``age_group``, ``language``,
``interviewed_from`` / ``interviewed_to``, ``interviewer`` and ``q``
(docs/policy/case-list-views.md, "Code and Review queue sort and filter").
Every one only narrows the caller's own list; the interviewer is matched only
where the caller sees personal data; the tiles ignore them; each list answers
the filtered ``total``. Four cases per list, all in the AZTA01 unit P1 of the
authz fixture (``coder_p1`` / ``reviewer_p1`` hold it with personal data,
``coder_ta`` / ``reviewer_ta`` are project-wide without):

====  ======  ===========  ========  ==============  =========================
case  sex     age (days)   language  interviewer     interviewed (UTC -> IST)
====  ======  ===========  ========  ==============  =========================
a     female  10 neonate   English   Meena Kumari    2026-03-01 10:00 (03-01)
b     male    3000 child   English   Ravi_Singh      2026-03-09 20:00 (03-10)
c     male    20000 adult  English   Meena Kumari    2026-03-20 10:00 (03-20)
d     female  unknown      Hindi     Collector       2026-03-15 10:00 (03-15)
====  ======  ===========  ========  ==============  =========================
"""
import uuid
from datetime import date, datetime

from app import db
from app.models import (
    VaCoderReview,
    VaDeathRegister,
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import org_unit_routing_service as routing
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.services.viewer_pii_service import pii_scope
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from tests.authz.fixture import FORMS, TA, AuthzFixtureMixin, R, U
from tests.base import BaseTestCase

CASES = {
    "a": ("female", 10, "English", "Meena Kumari", datetime(2026, 3, 1, 10, 0)),
    "b": ("male", 3000, "English", "Ravi_Singh", datetime(2026, 3, 9, 20, 0)),
    "c": ("male", 20000, "English", "Meena Kumari", datetime(2026, 3, 20, 10, 0)),
    "d": ("female", None, "Hindi", "Collector", datetime(2026, 3, 15, 10, 0)),
}


def _at(day):
    return datetime(2026, 5, day, 12, 0)


class _SortFilterBase(AuthzFixtureMixin, BaseTestCase):
    """``qfa-*`` cases in *AVAILABLE_STATE* and ``qfh-*`` cases finished by
    the PII user (their history rows), each as ``CASES``."""

    AVAILABLE_STATE = ""
    PII = NON_PII = NON_PII_AVAILABLE = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for key in CASES:
            cls._add_case(f"qfa-{key}", key, cls.AVAILABLE_STATE)
            cls._add_case(f"qfh-{key}", key, cls._history_state(key))
        db.session.flush()
        cls._seed_history()
        db.session.commit()

    @classmethod
    def _add_case(cls, sid, key, state):
        sex, age_days, language, interviewer, interviewed = CASES[key]
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=FORMS["ta1"][0], va_submission_date=interviewed,
            va_odk_updatedat=interviewed, va_data_collector=interviewer,
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid.upper(),
            va_consent="yes", va_narration_language=language,
            va_deceased_age=42, va_deceased_gender=sex, va_deceased_age_normalized_days=age_days,
            va_summary=[], va_catcount={}, va_category_list=[],
            org_unit_id=cls.units["P1"].org_unit_id,
            org_unit_resolution=routing.RESOLUTION_FORM_FIELD,
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state,
            workflow_reason="test_seed", workflow_updated_by_role="vasystem",
        ))

    @classmethod
    def _final(cls, sid, user_key, day, status=VaStatuses.active):
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=cls.users[user_key].user_id, va_conclusive_cod="R99",
            va_finassess_status=status, va_finassess_createdat=_at(day),
        ))

    # -- requests ------------------------------------------------------------

    def _get(self, user_key, path, **params):
        self._login(str(self.users[user_key].user_id))
        return self.client.get(path, query_string={"limit": 200, **params})

    def _body(self, user_key, path, **params):
        response = self._get(user_key, path, **params)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    @staticmethod
    def _items(body):
        return body.get("forms", body.get("cases", body.get("history", [])))

    def _order(self, user_key, path, prefix, **params):
        """Our *prefix* cases in the list's order, as their letter."""
        return [row["va_sid"][-1] for row in self._items(self._body(user_key, path, **params))
                if row["va_sid"].startswith(prefix)]

    def _mine(self, user_key, path, prefix, **params):
        return set(self._order(user_key, path, prefix, **params))

    def _lists(self):
        """(path, prefix, the PII user's unfiltered cases) of both lists."""
        return ((self.AVAILABLE, "qfa-", set(self.AVAILABLE_CASES)), (self.HISTORY, "qfh-", set(self.HISTORY_CASES)))

    # -- shared cases --------------------------------------------------------

    def _assert_filters(self):
        for path, prefix, everything in self._lists():
            with self.subTest(path=path):
                # Present first: the unfiltered list holds every one of our cases.
                self.assertEqual(self._mine(self.PII, path, prefix), everything)
                expect = {
                    (("sex", "female"),): {"a", "d"},
                    (("sex", "male"),): {"b", "c"},
                    (("age_group", "neonate"),): {"a"},
                    (("age_group", "child"),): {"b"},
                    (("age_group", "adult"),): {"c"},
                    (("age_group", ("neonate", "adult")),): {"a", "c"},
                    (("language", "english"),): {"a", "b", "c"},
                    (("language", ("English", "hindi")),): {"a", "b", "c"},
                    # b was interviewed at 20:00 UTC on 9 March: 10 March in the caller's zone (IST).
                    (("interviewed_from", "2026-03-10"), ("interviewed_to", "2026-03-10")): {"b"},
                    (("interviewed_to", "2026-03-09"),): {"a"},
                    (("interviewed_from", "2026-03-15"),): {"c", "d"},
                    (("interviewer", "meena"),): {"a", "c"},
                    (("interviewer", "ravi_"),): {"b"},
                    (("q", "meena kumari"),): {"a", "c"},
                    (("q", prefix + "b"),): {"b"},
                    (("q", (prefix + "c").upper()),): {"c"},
                    # LIKE wildcards are literal: none of our ids or names holds them.
                    (("q", "%"),): set(),
                    (("q", "qf_"),): set(),
                    (("sex", "female"), ("language", "english")): {"a"},
                }
                for params, cases in expect.items():
                    with self.subTest(params=params):
                        query = {name: list(value) if isinstance(value, tuple) else value for name, value in params}
                        self.assertEqual(self._mine(self.PII, path, prefix, **query), cases & everything)

    def _assert_language_outside_the_callers_is_nothing(self):
        for path, prefix, everything in self._lists():
            with self.subTest(path=path):
                if "d" in everything:
                    # Present first: the Hindi case is listed unfiltered (a history has no language rule).
                    self.assertIn("d", self._mine(self.PII, path, prefix))
                self.assertEqual(self._mine(self.PII, path, prefix, language="hindi"), set())
                self.assertEqual(self._body(self.PII, path, language="hindi")["total"], 0)

    def _assert_sorts(self):
        for path, prefix, everything in self._lists():
            with self.subTest(path=path):
                orders = {
                    "interviewed_asc": ["a", "b", "d", "c"],
                    "interviewed_desc": ["c", "d", "b", "a"],
                    "age_asc": ["a", "b", "c", "d"],
                    # Unknown age sorts last both ways.
                    "age_desc": ["c", "b", "a", "d"],
                }
                for sort, order in orders.items():
                    with self.subTest(sort=sort):
                        self.assertEqual(self._order(self.PII, path, prefix, sort=sort),
                                         [case for case in order if case in everything])

    def _assert_default_order_is_unchanged(self):
        for path, prefix, order in ((self.AVAILABLE, "qfa-", self.AVAILABLE_CASES),
                                    (self.HISTORY, "qfh-", self.HISTORY_CASES)):
            with self.subTest(path=path):
                self.assertEqual(self._order(self.PII, path, prefix), list(order))
                blank = {name: "" for name in ("sort", "state", "sex", "age_group", "language",
                                               "interviewed_from", "interviewed_to", "interviewer", "q")}
                self.assertEqual(self._body(self.PII, path, **blank), self._body(self.PII, path))

    def _assert_total(self):
        for path, prefix, everything in self._lists():
            with self.subTest(path=path):
                body = self._body(self.PII, path, sex="male")
                self.assertEqual({row["va_sid"][-1] for row in self._items(body)
                                  if row["va_sid"].startswith(prefix)}, {"b", "c"} & everything)
                self.assertEqual(body["total"], len(self._items(body)))
                page = self._body(self.PII, path, sex="male", limit=1)
                self.assertEqual((page["count"], page["total"]), (1, body["total"]))
                self.assertEqual(page["has_more"], body["total"] > 1)
                self.assertEqual(self._body(self.PII, path)["total"], len(self._items(self._body(self.PII, path))))

    def _assert_malformed_are_400(self):
        bad = (
            {"sort": "newest"}, {"sex": "other"}, {"age_group": "elder"}, {"language": "no such!"},
            {"interviewed_from": "2026-13-01"}, {"interviewed_to": "yesterday"},
            {"interviewed_from": "2026-03-10", "interviewed_to": "2026-03-09"},
            {"state": "pending"}, {"interviewer": "x" * 129}, {"q": "x" * 129},
            {"age_group": ["adult"] * 21},
        )
        for path in (self.AVAILABLE, self.HISTORY):
            for params in bad:
                with self.subTest(path=path, params=params):
                    response = self._get(self.PII, path, **params)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["code"], "invalid_request")

    def _assert_non_pii_caller_never_matches_interviewer_or_name(self):
        """A caller without personal-data access in the project finds a case by
        its id only: interviewer and name terms match nothing, so narrowing
        cannot reveal who interviewed the case or who died. History: a
        project-wide (Tier 1) grant; Available: the mentoring-institute
        member's P1 grant (Tier 2), since AZTA01 codes at the PHC."""
        self._author_non_pii("qfh-a")
        for number, sid in ((991001, "qfh-a"), (991003, "qfa-a")):
            db.session.add(VaDeathRegister(
                project_id=TA, site_id=FORMS["ta1"][2], death_number=number,
                unique_id=f"QF-{uuid.uuid4().hex[:8]}", deceased_name="Asha Rao", has_deceased_name=True,
                deceased_sex="female", date_of_death=date(2026, 2, 20),
                registered_by=self.users["interviewer_p1"].user_id, source="direct", status="submitted", va_sid=sid,
            ))
        db.session.commit()
        for path, prefix, user_key in ((self.HISTORY, "qfh-", self.NON_PII),
                                       (self.AVAILABLE, "qfa-", self.NON_PII_AVAILABLE)):
            with self.subTest(path=path):
                # The subject: a caller without personal data in the project, who lists case a unfiltered.
                self.assertFalse(pii_scope(self.users[user_key]).sees(TA))
                self.assertIn("a", self._mine(user_key, path, prefix))
                for params in ({"interviewer": "Meena Kumari"}, {"interviewer": "meena"},
                               {"q": "Meena Kumari"}, {"q": "Asha Rao"}):
                    with self.subTest(params=params):
                        body = self._body(user_key, path, **params)
                        self.assertEqual({r["va_sid"] for r in self._items(body) if r["va_sid"].startswith(prefix)},
                                         set())
                        self.assertEqual(body["total"], 0)
                self.assertEqual(self._mine(user_key, path, prefix, q=prefix + "a"), {"a"})
        # The same interviewer term finds the case for a caller who sees personal data.
        self.assertIn("a", self._mine(self.PII, self.HISTORY, "qfh-", interviewer="Meena Kumari"))
        # As built the deceased's name is searched for nobody, so the name term above proves no gate.
        self.assertEqual(self._mine(self.PII, self.HISTORY, "qfh-", q="Asha Rao"), set())

    def _assert_confirmed_duplicate_stays_out(self):
        self.assertIn("a", self._mine(self.PII, self.AVAILABLE, "qfa-", sex="female"))
        db.session.add(VaDeathRegister(
            project_id=TA, site_id=FORMS["ta1"][2], death_number=991002, unique_id=f"QF-{uuid.uuid4().hex[:8]}",
            deceased_name="Asha Rao", has_deceased_name=True, deceased_sex="female", date_of_death=date(2026, 2, 20),
            registered_by=self.users["interviewer_p1"].user_id, source="direct", status="duplicate", va_sid="qfa-a",
        ))
        db.session.commit()
        for params in ({"sex": "female"}, {"q": "qfa-a"}, {"sort": "age_asc"}, {"age_group": "neonate"}):
            with self.subTest(params=params):
                body = self._body(self.PII, self.AVAILABLE, **params)
                self.assertNotIn("qfa-a", {row["va_sid"] for row in self._items(body)})
        self.assertEqual(self._body(self.PII, self.AVAILABLE, q="qfa-a")["total"], 0)

    def _mark_duplicate(self, sid, number):
        db.session.add(VaDeathRegister(
            project_id=TA, site_id=FORMS["ta1"][2], death_number=number, unique_id=f"QF-{uuid.uuid4().hex[:8]}",
            deceased_name="Asha Rao", has_deceased_name=True, deceased_sex="female", date_of_death=date(2026, 2, 20),
            registered_by=self.users["interviewer_p1"].user_id, source="direct", status="duplicate", va_sid=sid,
        ))
        db.session.commit()

    def _stats(self):
        self._login(str(self.users[self.PII].user_id))
        return self.client.get(self.STATS).get_json()

    def _assert_confirmed_duplicate_leaves_the_history_and_its_tiles(self):
        """Owner 2026-11-27: a confirmed duplicate leaves My coded cases and
        Reviewed by me, and the tiles that count them, as it leaves Available."""
        filtered = ({}, {"sex": "male"}, {"sort": "age_asc"}, {"q": "qfh-b"})
        # Present first: in the list (with and without filters), its total and every tile.
        for params in filtered:
            with self.subTest(params=params, when="before"):
                self.assertIn("b", self._mine(self.PII, self.HISTORY, "qfh-", **params))
        before_total = self._body(self.PII, self.HISTORY)["total"]
        before = self._stats()
        for number, sid in enumerate(self.TILE_CASES.values(), start=991010):
            self._mark_duplicate(sid, number)
        self._bust_cache()
        for params in filtered:
            with self.subTest(params=params, when="after"):
                body = self._body(self.PII, self.HISTORY, **params)
                self.assertFalse({row["va_sid"] for row in self._items(body)} & set(self.TILE_CASES.values()))
        self.assertEqual(self._body(self.PII, self.HISTORY)["total"], before_total - len(self.TILE_CASES))
        self.assertEqual(self._body(self.PII, self.HISTORY, q="qfh-b")["total"], 0)
        after = self._stats()
        for tile in self.TILE_CASES:
            with self.subTest(tile=tile):
                self.assertEqual(after[tile], before[tile] - 1)

    def _bust_cache(self):
        """The tiles' and unpaged history's dashboard cache (ponytail: a
        confirmation does not bust it, so it lags up to its TTL)."""

    def _assert_tiles_ignore_the_filters(self):
        self._login(str(self.users[self.PII].user_id))
        plain = self.client.get(self.STATS).get_json()
        self.assertGreater(plain[self.TILE], 0)
        for params in ({"sex": "female"}, {"q": "nothing-matches"}, {"interviewer": "x"}, {"state": "coded"},
                       {"sort": "bogus"}, {"language": "hindi"}):
            with self.subTest(params=params):
                response = self.client.get(self.STATS, query_string=params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), plain)

    def _assert_states_partition(self, path, prefix, expected):
        """Each ``state`` value answers exactly its cases; the values together answer the list."""
        everything = self._mine(self.PII, path, prefix)
        self.assertEqual(everything, set().union(*expected.values()))
        for state, cases in expected.items():
            with self.subTest(state=state):
                self.assertEqual(self._mine(self.PII, path, prefix, state=state), cases)
        self.assertEqual(self._mine(self.PII, path, prefix, state=list(expected)), everything)

    def _assert_states_match_the_pill(self, path, pill):
        """The SQL twin: every row a ``state`` returns shows that pill (``pill(row)``)."""
        for state in self.STATES[path]:
            with self.subTest(state=state):
                rows = self._items(self._body(self.PII, path, state=state))
                self.assertTrue(rows, state)
                self.assertEqual({pill(row) for row in rows}, {state})


class CodingSortFilterTests(_SortFilterBase):
    AVAILABLE = "/api/v1/coding/available"
    HISTORY = "/api/v1/coding/history"
    STATS = "/api/v1/coding/stats"
    TILE = "pick_ready"
    AVAILABLE_STATE = WORKFLOW_READY_FOR_CODING
    PII, NON_PII, NON_PII_AVAILABLE = "coder_p1", "coder_ta", "mentor"
    # The pick list leaves out a language outside the coder's (d); default order is by interview date here.
    AVAILABLE_CASES = ("a", "b", "c")
    # Newest coding first: d (4 May), b (3 May), c (not codeable, 2 May), a (1 May).
    HISTORY_CASES = ("d", "b", "c", "a")
    STATES = {HISTORY: ("coded", "recoded", "not_codeable")}
    # Tile -> the history case it counts: the Coded tile a final, Not codeable a review.
    TILE_CASES = {"completed": "qfh-b", "not_codeable": "qfh-c"}

    @classmethod
    def _history_state(cls, key):
        return WORKFLOW_NOT_CODEABLE_BY_CODER if key == "c" else WORKFLOW_CODER_FINALIZED

    @classmethod
    def _seed_history(cls):
        cls._final("qfh-a", "coder_p1", 1)
        cls._final("qfh-b", "coder_p1", 3)
        cls._final("qfh-b", "coder_p1", 1, VaStatuses.deactive)  # the recode kept the first final
        db.session.add(VaCoderReview(
            va_sid="qfh-c", va_creview_by=cls.users["coder_p1"].user_id, va_creview_reason="no_info",
            va_creview_status=VaStatuses.active, va_creview_createdat=_at(2),
        ))
        cls._final("qfh-d", "coder_p1", 4)

    def _author_non_pii(self, sid):
        self._final(sid, self.NON_PII, 5)
        db.session.commit()

    def test_each_filter_narrows_both_lists(self):
        self._assert_filters()

    def test_a_language_outside_the_coders_matches_nothing(self):
        self._assert_language_outside_the_callers_is_nothing()

    def test_each_sort_orders_both_lists(self):
        self._assert_sorts()

    def test_no_parameter_keeps_each_lists_own_order(self):
        self._assert_default_order_is_unchanged()

    def test_total_is_the_filtered_size(self):
        self._assert_total()

    def test_malformed_values_are_400(self):
        self._assert_malformed_are_400()

    def test_available_offers_no_state(self):
        response = self._get(self.PII, self.AVAILABLE, state="coded")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")

    def test_states_without_a_pill_are_refused(self):
        # Owner 2026-11-27: no card shows In progress or Reviewed, so they are not options.
        for state in ("in_progress", "reviewed", "in_review"):
            with self.subTest(state=state):
                self.assertEqual(self._get(self.PII, self.HISTORY, state=state).status_code, 400)

    def test_each_state_answers_exactly_its_pill(self):
        self._assert_states_partition(self.HISTORY, "qfh-",
                                      {"coded": {"a", "d"}, "recoded": {"b"}, "not_codeable": {"c"}})

    def test_the_state_filter_is_the_pills_twin(self):
        def pill(row):
            if row["va_code_status"] == "Not Codeable":
                return "not_codeable"
            return "recoded" if row["recoded"] else "coded"

        self._assert_states_match_the_pill(self.HISTORY, pill)

    def test_a_non_pii_coder_finds_by_case_id_only(self):
        self._assert_non_pii_caller_never_matches_interviewer_or_name()

    def test_a_confirmed_duplicate_stays_out_with_filters_on(self):
        self._assert_confirmed_duplicate_stays_out()

    def test_a_confirmed_duplicate_leaves_the_history_and_its_tiles(self):
        self._assert_confirmed_duplicate_leaves_the_history_and_its_tiles()

    def test_the_unpaged_history_leaves_out_a_confirmed_duplicate(self):
        self._login(str(self.users[self.PII].user_id))
        self.assertIn("qfh-b", {row["va_sid"] for row in self.client.get(self.HISTORY).get_json()["history"]})
        self._mark_duplicate("qfh-b", 991020)
        self._bust_cache()
        self.assertNotIn("qfh-b", {row["va_sid"] for row in self.client.get(self.HISTORY).get_json()["history"]})

    def _bust_cache(self):
        bust_coder_dashboard_cache(self.users[self.PII].user_id)

    def test_the_tiles_ignore_the_filters(self):
        self._assert_tiles_ignore_the_filters()

    def test_the_unpaged_history_refuses_filters_and_the_unpaged_list_applies_them(self):
        self._login(str(self.users[self.PII].user_id))
        response = self.client.get(self.HISTORY, query_string={"sex": "male"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")
        # The unpaged bodies keep their keys: no ``total``, their ``count`` is the whole list.
        self.assertEqual(set(self.client.get(self.HISTORY).get_json()), {"history", "count"})
        unpaged = self.client.get(self.AVAILABLE, query_string={"sex": "male", "sort": "interviewed_desc"}).get_json()
        mine = [row["va_sid"] for row in unpaged["forms"] if row["va_sid"].startswith("qfa-")]
        self.assertEqual(mine, ["qfa-c", "qfa-b"])
        self.assertEqual(set(unpaged), {"forms", "count"})


class ReviewingSortFilterTests(_SortFilterBase):
    AVAILABLE = "/api/v1/reviewing/available"
    HISTORY = "/api/v1/reviewing/history"
    STATS = "/api/v1/reviewing/stats"
    TILE = "available"
    AVAILABLE_STATE = WORKFLOW_REVIEWER_ELIGIBLE
    PII, NON_PII, NON_PII_AVAILABLE = "reviewer_p1", "reviewer_ta", "mentor"
    AVAILABLE_CASES = ("a", "b", "c")
    # Newest review first.
    HISTORY_CASES = ("d", "b", "c", "a")
    STATES = {AVAILABLE: ("coded", "recoded")}
    TILE_CASES = {"completed": "qfh-b"}

    @classmethod
    def _history_state(cls, key):
        return WORKFLOW_REVIEWER_FINALIZED

    @classmethod
    def _seed_history(cls):
        # The mentoring-institute member also reviews at P1 (a Tier 2 grant: no personal data).
        db.session.add(cls._grant_row(cls.users["mentor"], R.reviewer, U, "P1"))
        for key, day in (("a", 1), ("b", 3), ("c", 2), ("d", 4)):
            db.session.add(VaReviewerFinalAssessments(
                va_sid=f"qfh-{key}", va_rfinassess_by=cls.users["reviewer_p1"].user_id, va_conclusive_cod="R99",
                va_rfinassess_createdat=_at(day),
            ))
        # Available pills: a coded once; b recoded by its coder; c's active final is coder_c1's
        # (one final), so an earlier final by another coder does not make it a recode.
        cls._final("qfa-a", "coder_p1", 1)
        cls._final("qfa-b", "coder_p1", 3)
        cls._final("qfa-b", "coder_p1", 2, VaStatuses.deactive)
        cls._final("qfa-c", "coder_c1", 3)
        cls._final("qfa-c", "coder_p1", 1, VaStatuses.deactive)
        cls._final("qfa-c", "coder_p1", 2, VaStatuses.deactive)

    def _author_non_pii(self, sid):
        db.session.add(VaReviewerFinalAssessments(
            va_sid=sid, va_rfinassess_by=self.users[self.NON_PII].user_id, va_conclusive_cod="R99",
            va_rfinassess_createdat=_at(5),
        ))
        db.session.commit()

    def test_each_filter_narrows_both_lists(self):
        self._assert_filters()

    def test_a_language_outside_the_reviewers_matches_nothing(self):
        self._assert_language_outside_the_callers_is_nothing()

    def test_each_sort_orders_both_lists(self):
        self._assert_sorts()

    def test_no_parameter_keeps_each_lists_own_order(self):
        self._assert_default_order_is_unchanged()

    def test_total_is_the_filtered_size(self):
        self._assert_total()

    def test_malformed_values_are_400(self):
        self._assert_malformed_are_400()

    def test_states_without_a_pill_are_refused(self):
        # Owner 2026-11-27: Reviewed by me offers no state (every row is Reviewed).
        for path, state in ((self.HISTORY, "in_review"), (self.HISTORY, "reviewed"), (self.AVAILABLE, "reviewed"),
                            (self.HISTORY, "coded"), (self.AVAILABLE, "in_review")):
            with self.subTest(path=path, state=state):
                self.assertEqual(self._get(self.PII, path, state=state).status_code, 400)

    def test_each_state_answers_exactly_its_pill(self):
        self._assert_states_partition(self.AVAILABLE, "qfa-", {"coded": {"a", "c"}, "recoded": {"b"}})

    def test_the_state_filter_is_the_pills_twin(self):
        self._assert_states_match_the_pill(self.AVAILABLE, lambda row: "recoded" if row["recoded"] else "coded")

    def test_a_non_pii_reviewer_finds_by_case_id_only(self):
        self._assert_non_pii_caller_never_matches_interviewer_or_name()

    def test_a_confirmed_duplicate_stays_out_with_filters_on(self):
        self._assert_confirmed_duplicate_stays_out()

    def test_the_tiles_ignore_the_filters(self):
        self._assert_tiles_ignore_the_filters()

    def test_a_confirmed_duplicate_leaves_the_history_and_its_tiles(self):
        self._assert_confirmed_duplicate_leaves_the_history_and_its_tiles()
