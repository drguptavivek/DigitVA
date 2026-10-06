"""Opt-in paging of GET /api/v1/coding/available and /coding/history, and of
GET /api/v1/workflow/events/<sid> (digitva-k5a6, digitva-cuq1).

Without ``limit`` the bodies are unchanged (the web dashboard reads them
whole); with ``limit`` they page without gap or repeat across ties, bounded
in SQL, a constant number of queries whatever the table size.
"""

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import event

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
)
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:3].upper()
PICK_A = f"PA{_SUFFIX}"
PICK_B = f"PB{_SUFFIX}"  # the coder holds no grant here
PICK_C = f"PC{_SUFFIX}"
DEMO = f"PD{_SUFFIX}"
SUBMITTED = datetime(2026, 1, 1, tzinfo=timezone.utc)
TIED_AT = datetime(2026, 5, 1, 12, 0, 0)  # naive, as the columns are
PAGE_FIELDS = {"count", "limit", "offset", "has_more"}


class _QueryCounter:
    def __enter__(self):
        self.statements = []
        event.listen(db.engine, "before_cursor_execute", self._count)
        return self

    def __exit__(self, *exc):
        event.remove(db.engine, "before_cursor_execute", self._count)

    def _count(self, conn, cursor, statement, *args):
        self.statements.append(statement)

    @property
    def count(self):
        return len(self.statements)


class CodingPagingTests(BaseTestCase):
    @classmethod
    def _seed_project(cls, project_id, mode, *, demo=False):
        now = datetime.now(timezone.utc)
        site_id = f"{project_id[1]}{_SUFFIX}"  # site ids are 4 characters
        form_id = f"{project_id}{site_id}01"
        db.session.add(
            VaProjectMaster(
                project_id=project_id, project_code=project_id,
                project_name=f"Project {project_id}", project_nickname=project_id,
                coding_intake_mode=mode, project_status=VaStatuses.active,
                demo_training_enabled=demo,
                project_registered_at=now, project_updated_at=now,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=project_id, project_code=project_id,
                project_name=f"Project {project_id}", project_nickname=project_id,
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            )
        )
        db.session.add(
            VaSites(
                site_id=site_id, project_id=project_id, site_name=f"Site {site_id}",
                site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=project_id, site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            )
        )
        db.session.add(
            VaForms(
                form_id=form_id, project_id=project_id, site_id=site_id,
                odk_form_id=f"FORM_{project_id}", odk_project_id="11",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            )
        )
        db.session.flush()
        return form_id

    @classmethod
    def _add_submission(cls, sid, form_id, state="ready_for_coding"):
        db.session.add(
            VaSubmissions(
                va_sid=sid, va_form_id=form_id,
                va_submission_date=SUBMITTED, va_odk_updatedat=SUBMITTED,
                va_data_collector="Collector", va_odk_reviewstate=None,
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English",
                va_deceased_age=42, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid, workflow_state=state,
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            )
        )

    @classmethod
    def _grant(cls, user, project_id, role=VaAccessRoles.coder):
        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == project_id
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=user.user_id, role=role,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id, notes="paging test",
                grant_status=VaStatuses.active,
            )
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coder = cls._make_user(f"paging.coder.{_SUFFIX}@test.local", "Paging123")
        cls.other = cls._make_user(f"paging.other.{_SUFFIX}@test.local", "Paging123")
        cls.form_a = cls._seed_project(PICK_A, "pick_and_choose")
        cls.form_b = cls._seed_project(PICK_B, "pick_and_choose")
        cls.form_c = cls._seed_project(PICK_C, "pick_and_choose")
        cls.form_d = cls._seed_project(DEMO, "random_form_allocation", demo=True)
        for project in (PICK_A, PICK_C):
            cls._grant(cls.coder, project)
        cls._grant(cls.other, PICK_B)

        # Pick pool: 7 + 2 reachable, 3 in a project the coder holds no grant on.
        # Identical submission date and masked-id prefix, so ties are everywhere.
        for i in range(7):
            cls._add_submission(f"pg-a-{i}", cls.form_a)
        for i in range(2):
            cls._add_submission(f"pg-c-{i}", cls.form_c)
        for i in range(3):
            cls._add_submission(f"pg-b-{i}", cls.form_b)

        # History: 5 finals in A (3 at one instant), 1 in C, a review at the same
        # instant on the first final's case, a review in A, 2 live demo finals,
        # and a final by another user that must never show.
        offsets = [0, 0, 0, 5, 9]
        for i, minutes in enumerate(offsets):
            sid = f"hist-a-{i}"
            cls._add_submission(sid, cls.form_a, WORKFLOW_CODER_FINALIZED)
            cls._final(sid, cls.coder, TIED_AT + timedelta(minutes=minutes))
        cls._add_submission("hist-c-0", cls.form_c, WORKFLOW_CODER_FINALIZED)
        cls._final("hist-c-0", cls.coder, TIED_AT + timedelta(minutes=2))
        cls._add_submission("hist-nc-0", cls.form_a, WORKFLOW_NOT_CODEABLE_BY_CODER)
        db.session.add(
            VaCoderReview(
                va_sid="hist-nc-0", va_creview_by=cls.coder.user_id,
                va_creview_reason="form_is_empty", va_creview_status=VaStatuses.active,
                va_creview_createdat=TIED_AT,
            )
        )
        db.session.add(
            VaCoderReview(
                va_sid="hist-a-0", va_creview_by=cls.coder.user_id,
                va_creview_reason="form_is_empty", va_creview_status=VaStatuses.active,
                va_creview_createdat=TIED_AT,
            )
        )
        cls._add_submission("hist-x-0", cls.form_a, WORKFLOW_CODER_FINALIZED)
        cls._final("hist-x-0", cls.other, TIED_AT)
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
        for i in range(2):
            sid = f"hist-d-{i}"
            cls._add_submission(sid, cls.form_d, WORKFLOW_CODER_FINALIZED)
            cls._final(
                sid, cls.coder, TIED_AT + timedelta(days=1), demo_expires_at=expires
            )

        # One case with 7 workflow events, 4 at the same instant.
        cls._add_submission("ev-1", cls.form_a)
        for i in range(7):
            cls._event("ev-1", i, SUBMITTED + timedelta(seconds=0 if i < 4 else i))
        db.session.commit()
        cls.coder_id = str(cls.coder.user_id)

    @classmethod
    def _final(cls, sid, user, created, demo_expires_at=None):
        db.session.add(
            VaFinalAssessments(
                va_sid=sid, va_finassess_by=user.user_id, va_conclusive_cod="R99",
                va_finassess_status=VaStatuses.active,
                va_finassess_createdat=created, demo_expires_at=demo_expires_at,
            )
        )

    @classmethod
    def _event(cls, sid, n, created):
        db.session.add(
            VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id=f"t{n}", previous_state="a",
                current_state="b", actor_kind="user", actor_role="vacoder",
                transition_reason=f"r{n}", event_created_at=created,
            )
        )

    def setUp(self):
        super().setUp()
        self._login(self.coder_id)

    def _get(self, path, **params):
        return self.client.get(path, query_string=params)

    def _pages(self, path, key, limit, **params):
        """Every page of *path*, walked by offset: [(body, ...)]."""
        pages, offset = [], 0
        while True:
            response = self._get(path, limit=limit, offset=offset, **params)
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            pages.append(body)
            if not body["has_more"]:
                return pages
            offset += limit
            self.assertLess(len(pages), 50, "paging does not terminate")

    # ------------------------------------------------------------------
    # /coding/available
    # ------------------------------------------------------------------

    def test_available_unparameterised_body_is_unchanged(self):
        body = self._get("/api/v1/coding/available").get_json()
        self.assertEqual(set(body), {"forms", "count"})
        sids = [r["va_sid"] for r in body["forms"] if r["va_sid"].startswith("pg-")]
        self.assertEqual(len(sids), 9)
        self.assertEqual(body["count"], len(body["forms"]))
        self.assertEqual(
            set(body["forms"][0]),
            {
                "va_sid", "va_uniqueid_masked", "va_form_id", "project_id",
                "site_id", "va_submission_date", "va_data_collector",
                "va_deceased_age", "va_deceased_gender",
            },
        )
        self.assertNotIn("pg-b-0", sids)

    def test_available_pages_cover_the_full_list_once_in_order(self):
        full = self._get("/api/v1/coding/available").get_json()["forms"]
        for limit in (1, 2, 4, 200):
            pages = self._pages("/api/v1/coding/available", "forms", limit)
            for body in pages:
                self.assertEqual(set(body), {"forms"} | PAGE_FIELDS)
                self.assertEqual(body["count"], len(body["forms"]))
                self.assertLessEqual(body["count"], limit)
            self.assertEqual([r for b in pages for r in b["forms"]], full)
            self.assertFalse(pages[-1]["has_more"])
            self.assertTrue(all(b["has_more"] for b in pages[:-1]))

    def test_available_offset_past_the_end_is_an_empty_last_page(self):
        body = self._get("/api/v1/coding/available", limit=5, offset=10_000).get_json()
        self.assertEqual(body["forms"], [])
        self.assertFalse(body["has_more"])

    def test_available_project_filter_narrows_and_never_widens(self):
        pages = self._pages("/api/v1/coding/available", "forms", 3, project_id=PICK_C.lower())
        rows = [r for b in pages for r in b["forms"]]
        self.assertEqual(sorted(r["va_sid"] for r in rows), ["pg-c-0", "pg-c-1"])
        # A project the coder holds no grant on answers empty, paged or not.
        paged = self._get("/api/v1/coding/available", limit=5, project_id=PICK_B).get_json()
        self.assertEqual((paged["forms"], paged["has_more"]), ([], False))
        whole = self._get("/api/v1/coding/available", project_id=PICK_B).get_json()
        self.assertEqual(whole, {"forms": [], "count": 0})
        # Unpaged, the filter is the only change.
        whole_c = self._get("/api/v1/coding/available", project_id=PICK_C).get_json()
        self.assertEqual(set(whole_c), {"forms", "count"})
        self.assertEqual({r["project_id"] for r in whole_c["forms"]}, {PICK_C})

    def test_available_query_count_is_bounded_and_independent_of_pool_size(self):
        self._get("/api/v1/coding/available", limit=2)  # warm the session
        with _QueryCounter() as small:
            self._get("/api/v1/coding/available", limit=2)
        for i in range(20):
            self._add_submission(f"pg-a-extra-{i}", self.form_a)
        db.session.flush()
        with _QueryCounter() as large:
            body = self._get("/api/v1/coding/available", limit=2).get_json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(small.count, large.count)
        self.assertLessEqual(large.count, 25)

    def test_pick_ready_count_equals_the_list_and_does_not_grow_with_rows(self):
        from app.services.coder_workflow_service import (
            get_coder_ready_stats,
            get_pick_available_forms,
        )

        forms = [self.form_a, self.form_c]
        listed = get_pick_available_forms(self.coder, forms)
        self.assertEqual(len([r for r in listed if r["va_sid"].startswith("pg-")]), 9)
        self.assertEqual(get_coder_ready_stats(self.coder)["pick_ready"], len(listed))
        self._get("/api/v1/coding/stats")  # warm the session
        with _QueryCounter() as small:
            self._get("/api/v1/coding/stats")
        for i in range(20):
            self._add_submission(f"pg-a-stat-{i}", self.form_a)
        db.session.flush()
        with _QueryCounter() as large:
            stats = self._get("/api/v1/coding/stats").get_json()
        self.assertEqual(stats["pick_ready"], len(listed) + 20)
        self.assertEqual(
            stats["pick_ready"], len(get_pick_available_forms(self.coder, forms))
        )
        self.assertEqual(small.count, large.count)

    # ------------------------------------------------------------------
    # /coding/history
    # ------------------------------------------------------------------

    def test_history_unparameterised_body_is_unchanged(self):
        body = self._get("/api/v1/coding/history").get_json()
        self.assertEqual(set(body), {"history", "count"})
        self.assertEqual(body["count"], len(body["history"]))
        real = [r for r in body["history"] if not r.get("is_demo")]
        demo = [r for r in body["history"] if r.get("is_demo")]
        self.assertEqual(len(demo), 2)
        self.assertEqual(body["history"][:2], demo)
        # 5 + 1 finals and 2 reviews; the other user's final is not here.
        self.assertEqual(len(real), 8)
        self.assertNotIn("hist-x-0", {r["va_sid"] for r in real})
        self.assertEqual(
            set(real[0]),
            {
                "project_id", "site_id", "va_submission_date", "va_form_id",
                "va_sid", "va_uniqueid_masked", "va_deceased_age",
                "va_deceased_gender", "va_coding_date", "va_code_status",
                "is_tester", "recodeable",
            },
        )
        self.assertEqual(
            set(demo[0]),
            (set(real[0]) - {"is_tester"}) | {"demo_expires_at", "is_demo"},
        )

    def test_history_pages_equal_the_full_list_without_gap_or_repeat(self):
        full = self._get("/api/v1/coding/history").get_json()["history"]

        def identity(row):
            return (row["va_sid"], row["va_code_status"], row["va_coding_date"])

        for limit in (1, 2, 3, 4, 200):
            pages = self._pages("/api/v1/coding/history", "history", limit)
            rows = [r for b in pages for r in b["history"]]
            for body in pages:
                self.assertEqual(set(body), {"history"} | PAGE_FIELDS)
                self.assertEqual(body["count"], len(body["history"]))
                self.assertLessEqual(body["count"], limit)
            self.assertEqual(len(rows), len(full))
            self.assertEqual(len({identity(r) for r in rows}), len(rows), "repeat")
            # The same rows, key for key (ties may order differently, never rows).
            self.assertEqual(
                sorted(rows, key=identity), sorted(full, key=identity)
            )
            self.assertFalse(pages[-1]["has_more"])
            self.assertTrue(all(b["has_more"] for b in pages[:-1]))
            # Demo first, then newest coding date first.
            real = [r for r in rows if not r.get("is_demo")]
            self.assertEqual([bool(r.get("is_demo")) for r in rows], [True, True] + [False] * 8)
            dates = [r["va_coding_date"] for r in real]
            self.assertEqual(dates, sorted(dates, reverse=True))

    def test_history_page_order_is_deterministic_across_ties(self):
        first = [
            (r["va_sid"], r["va_code_status"])
            for b in self._pages("/api/v1/coding/history", "history", 3)
            for r in b["history"]
        ]
        second = [
            (r["va_sid"], r["va_code_status"])
            for b in self._pages("/api/v1/coding/history", "history", 3)
            for r in b["history"]
        ]
        self.assertEqual(first, second)

    def test_history_project_filter_narrows_and_never_widens(self):
        rows = [
            r
            for b in self._pages("/api/v1/coding/history", "history", 2, project_id=PICK_C)
            for r in b["history"]
        ]
        self.assertEqual([r["va_sid"] for r in rows], ["hist-c-0"])
        for project in (PICK_B, "NOPE99"):
            paged = self._get("/api/v1/coding/history", limit=5, project_id=project).get_json()
            self.assertEqual((paged["history"], paged["has_more"]), ([], False))
            whole = self._get("/api/v1/coding/history", project_id=project).get_json()
            self.assertEqual(whole, {"history": [], "count": 0})
        demo = self._get("/api/v1/coding/history", limit=5, project_id=DEMO).get_json()
        self.assertTrue(all(r["is_demo"] for r in demo["history"]))
        self.assertEqual(len(demo["history"]), 2)

    def test_history_other_users_rows_never_show(self):
        self._login(str(self.other.user_id))
        pages = self._pages("/api/v1/coding/history", "history", 5)
        self.assertEqual([r for b in pages for r in b["history"]], [])

    def test_history_query_count_is_bounded_and_independent_of_history_size(self):
        self._get("/api/v1/coding/history", limit=2)  # warm the session
        with _QueryCounter() as small:
            self._get("/api/v1/coding/history", limit=2)
        for i in range(25):
            sid = f"hist-a-extra-{i}"
            self._add_submission(sid, self.form_a, WORKFLOW_CODER_FINALIZED)
            self._final(sid, self.coder, TIED_AT + timedelta(minutes=30 + i))
        db.session.flush()
        with _QueryCounter() as large:
            body = self._get("/api/v1/coding/history", limit=2, offset=3).get_json()
        self.assertEqual(body["count"], 2)
        self.assertTrue(body["has_more"])
        self.assertEqual(small.count, large.count)
        self.assertLessEqual(large.count, 25)

    # ------------------------------------------------------------------
    # bad parameters, both list routes
    # ------------------------------------------------------------------

    def test_bad_parameters_answer_400_invalid_request(self):
        bad = [
            {"limit": "0"}, {"limit": "201"}, {"limit": "-1"}, {"limit": "x"},
            {"limit": ""}, {"limit": "5", "offset": "-1"},
            {"limit": "5", "offset": "x"}, {"limit": "5", "offset": "1000001"},
            {"offset": "5"}, {"project_id": "P" * 65},
        ]
        for path in ("/api/v1/coding/available", "/api/v1/coding/history"):
            for params in bad:
                response = self._get(path, **params)
                self.assertEqual(response.status_code, 400, (path, params))
                body = response.get_json()
                self.assertEqual(body["code"], "invalid_request", (path, params))
                self.assertIn("error", body)

    # ------------------------------------------------------------------
    # /workflow/events/<sid>
    # ------------------------------------------------------------------

    def _events_url(self, sid="ev-1"):
        return f"/api/v1/workflow/events/{sid}"

    def test_events_unparameterised_body_is_unchanged(self):
        body = self._get(self._events_url()).get_json()
        self.assertEqual(set(body), {"va_sid", "events"})
        self.assertEqual(len(body["events"]), 7)
        self.assertEqual(
            set(body["events"][0]),
            {
                "event_id", "transition_id", "previous_state", "current_state",
                "actor_kind", "actor_role", "transition_reason", "event_created_at",
            },
        )
        stamps = [e["event_created_at"] for e in body["events"]]
        self.assertEqual(stamps, sorted(stamps), "oldest first, as before")

    def test_events_pages_are_newest_first_without_gap_or_repeat_across_ties(self):
        full = self._get(self._events_url()).get_json()["events"]
        for limit in (1, 2, 3, 7, 200):
            seen, cursor, pages = [], None, 0
            while True:
                params = {"limit": limit}
                if cursor:
                    params["cursor"] = cursor
                body = self._get(self._events_url(), **params).get_json()
                self.assertEqual(set(body), {"va_sid", "events", "limit", "next_cursor"})
                self.assertLessEqual(len(body["events"]), limit)
                seen += body["events"]
                pages += 1
                cursor = body["next_cursor"]
                if cursor is None:
                    break
                self.assertEqual(len(body["events"]), limit)
                self.assertLess(pages, 20)
            ids = [e["event_id"] for e in seen]
            self.assertEqual(len(set(ids)), len(ids), "repeat")
            self.assertEqual(set(ids), {e["event_id"] for e in full}, "gap")
            stamps = [e["event_created_at"] for e in seen]
            self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_events_last_page_has_no_cursor_and_exact_fit_has_none_either(self):
        body = self._get(self._events_url(), limit=7).get_json()
        self.assertEqual((len(body["events"]), body["next_cursor"]), (7, None))
        empty = self._get(self._events_url("hist-a-0"), limit=5).get_json()
        self.assertEqual((empty["events"], empty["next_cursor"]), ([], None))

    def test_events_bad_parameters_answer_400_invalid_request(self):
        cursor = self._get(self._events_url(), limit=2).get_json()["next_cursor"]
        bad = [
            {"limit": "0"}, {"limit": "201"}, {"limit": "x"}, {"limit": ""},
            {"limit": "2", "cursor": "not-a-cursor"},
            {"limit": "2", "cursor": "!!!"},
            {"cursor": cursor},
        ]
        for params in bad:
            response = self._get(self._events_url(), **params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.get_json()["code"], "invalid_request", params)

    def test_events_authorization_is_unchanged(self):
        # PICK_B submissions are outside the coder's grants: 403 whatever the paging.
        self._add_submission("ev-b", self.form_b)
        self._event("ev-b", 0, SUBMITTED)
        db.session.flush()
        for params in ({}, {"limit": 5}):
            self.assertEqual(self._get(self._events_url("ev-b"), **params).status_code, 403)
        self.assertEqual(self._get(self._events_url("nope"), limit=5).status_code, 404)

    def test_events_query_count_is_independent_of_history_length(self):
        self._get(self._events_url(), limit=3)  # warm the session
        with _QueryCounter() as short:
            self._get(self._events_url(), limit=3)
        for i in range(30):
            self._event("ev-1", 100 + i, SUBMITTED + timedelta(minutes=i))
        db.session.flush()
        with _QueryCounter() as long_:
            body = self._get(self._events_url(), limit=3).get_json()
        self.assertEqual(len(body["events"]), 3)
        self.assertEqual(short.count, long_.count)
