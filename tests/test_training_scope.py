"""The Expo training scope: the training project and real work never mix.

Policy: docs/policy/training-demo-project.md, "Separation from real work".
Every list, count and allocation endpoint the Expo screens call leaves the
training project out by default and returns only it for ``training=1`` (which
needs the matching active participation).
"""
import uuid
from contextlib import contextmanager
from datetime import date
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MasTrainingSession,
    VaAccessRoles,
    VaAccessScopeTypes,
    MapUserNotification,
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaFinalAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import area_dashboard_service, notification_service, training_scope, user_home_service
from app.services import training_demo_service as svc
from app.services.coder_dashboard_service import get_coder_output_summary
from tests.training_demo_fixtures import TrainingDemoTestBase

REAL_SID = "src-005"


class TrainingScopeBase(TrainingDemoTestBase):
    """A trainee with coder slot 1 (10 training cases) who also codes one real case."""

    roles = ("coder",)

    def setUp(self):
        super().setUp()
        self.trainee = self._user("scope")
        svc.add_participant("S001", self.trainee.email, list(self.roles), self.admin)
        self.training_sids = self._session_sids()[1]
        # One real, ready case in a real (pick-and-choose) project the trainee also codes in.
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.coding_intake_mode = "pick_and_choose"
        db.session.add(VaSubmissionWorkflow(
            va_sid=REAL_SID, workflow_state="ready_for_coding", workflow_reason="test_seed",
            workflow_updated_by_role="vasystem",
        ))
        project_site = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.BASE_PROJECT_ID, VaProjectSites.site_id == self.BASE_SITE_ID))
        for role in (VaAccessRoles.coder, VaAccessRoles.reviewer):
            db.session.add(VaUserAccessGrants(
                user_id=self.trainee.user_id, role=role, scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site.project_site_id, grant_status=VaStatuses.active))
        db.session.commit()
        self._login(str(self.trainee.user_id))

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path, body=None):
        return self.client.post(path, json=body if body is not None else {}, headers=self._csrf_headers())

    def _case(self, project_id, site_id, org_unit_id, tag):
        death = VaDeathRegister(
            project_id=project_id, site_id=site_id, org_unit_id=org_unit_id,
            death_number=uuid.uuid4().int % 10**9, unique_id=f"SCOPE-{tag}-{uuid.uuid4().hex[:8]}",
            deceased_name="Scope Case", deceased_sex="female", date_of_death=date(2026, 1, 1),
            registered_by=self.trainee.user_id, source="register", status="registered",
        )
        db.session.add(death)
        db.session.commit()
        return str(death.death_id)

    def _training_death(self):
        session = db.session.get(MasTrainingSession, self.first["training_session_id"])
        return self._case("TRN01", svc._web_form().site_id, session.org_unit_id, "W")

    @contextmanager
    def training_visible(self):
        """The same query as if the feature were off: shows the training rows the
        scope hides, so an absence assertion is preceded by its presence."""
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=""):
            yield

    @contextmanager
    def scope(self, name):
        with self.app.test_request_context("/"):
            training_scope.use(name)
            yield


class CodingScopeTests(TrainingScopeBase):
    def test_the_subject_exists_in_both_projects(self):
        # Present before asserting absence: unscoped, the service sees both.
        listed = {r["va_sid"] for r in svc_pick(self.trainee)}
        self.assertTrue(self.training_sids <= listed)
        self.assertIn(REAL_SID, listed)

    def test_normal_lists_and_counts_exclude_training(self):
        available = self.get("/api/v1/coding/available?limit=200").get_json()
        sids = {row["va_sid"] for row in available["forms"]}
        self.assertEqual(sids, {REAL_SID})
        self.assertEqual(self.get("/api/v1/coding/available").get_json()["count"], 1)
        stats = self.get("/api/v1/coding/stats").get_json()
        self.assertEqual(stats["pick_ready"], 1)
        projects = self.get("/api/v1/coding/projects").get_json()
        self.assertEqual(projects["projects"], [self.BASE_PROJECT_ID])
        # Asking for the training project by id in the normal scope finds nothing.
        by_id = self.get("/api/v1/coding/available?limit=50&project_id=TRN01").get_json()
        self.assertEqual(by_id["forms"], [])
        self.assertEqual(self.get("/api/v1/coding/stats?project_id=TRN01").get_json()["pick_ready"], 0)
        self.assertEqual(self.get("/api/v1/coding/history?limit=50&project_id=TRN01").get_json()["history"], [])

    def test_training_scope_returns_only_training(self):
        available = self.get("/api/v1/coding/available?limit=200&training=1").get_json()
        self.assertEqual({row["va_sid"] for row in available["forms"]}, self.training_sids)
        self.assertEqual(self.get("/api/v1/coding/stats?training=1").get_json()["pick_ready"], 10)
        self.assertEqual(self.get("/api/v1/coding/projects?training=1").get_json()["projects"], ["TRN01"])
        # Another project's id inside the training scope finds nothing.
        other = self.get(f"/api/v1/coding/available?limit=50&training=1&project_id={self.BASE_PROJECT_ID}")
        self.assertEqual(other.get_json()["forms"], [])

    def test_bad_value_is_a_400(self):
        response = self.get("/api/v1/coding/available?training=maybe")
        self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))

    def test_training_scope_needs_the_participation(self):
        self._login(self.base_coder_id)
        for path in ("available", "stats", "projects", "history", "allocation"):
            response = self.get(f"/api/v1/coding/{path}?training=1")
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.get_json()["code"], "forbidden")
        # The normal scope is unaffected.
        self.assertEqual(self.get("/api/v1/coding/available").status_code, 200)

    def test_training_scope_needs_an_active_session_and_role(self):
        reviewer_only = self._user("rev")
        svc.add_participant("S001", reviewer_only.email, ["interviewer"], self.admin)
        self._login(str(reviewer_only.user_id))
        self.assertEqual(self.get("/api/v1/coding/stats?training=1").status_code, 403)  # wrong role
        svc.close_training_session("S001", self.admin)
        self._login(str(self.trainee.user_id))
        self.assertEqual(self.get("/api/v1/coding/stats?training=1").status_code, 403)  # closed session

    def test_pick_across_the_line_is_refused(self):
        sid = sorted(self.training_sids)[0]
        normal = self.client.post("/api/v1/coding/allocation", json={"sid": sid}, headers=self._csrf_headers())
        self.assertEqual((normal.status_code, normal.get_json()["code"]), (409, "not_available"))
        scoped = self.client.post(
            "/api/v1/coding/allocation?training=1", json={"sid": REAL_SID}, headers=self._csrf_headers())
        self.assertEqual((scoped.status_code, scoped.get_json()["code"]), (409, "not_available"))
        # Neither attempt allocated anything.
        self.assertIsNone(self.get("/api/v1/coding/allocation").get_json()["allocation"])
        self.assertIsNone(self.get("/api/v1/coding/allocation?training=1").get_json()["allocation"])

    def test_pick_inside_the_scope_and_the_allocation_stays_in_it(self):
        sid = sorted(self.training_sids)[0]
        made = self.client.post(
            "/api/v1/coding/allocation?training=1", json={"sid": sid}, headers=self._csrf_headers())
        self.assertEqual(made.status_code, 201, made.get_json())
        self.assertEqual(self.get("/api/v1/coding/allocation?training=1").get_json()["allocation"]["va_sid"], sid)
        # The normal scope neither shows it nor resumes it.
        self.assertIsNone(self.get("/api/v1/coding/allocation").get_json()["allocation"])
        # And a held training case does not block a real pick (digitva-rcwt).
        real = self.client.post("/api/v1/coding/allocation", json={"sid": REAL_SID}, headers=self._csrf_headers())
        self.assertEqual(real.status_code, 201, real.get_json())

    def _held(self, user_id):
        return {
            (row.va_sid, row.va_allocation_training)
            for row in db.session.scalars(sa.select(VaAllocations).where(
                VaAllocations.va_allocated_to == user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active))
        }

    def test_each_side_holds_its_own_case_in_either_order(self):
        sid = sorted(self.training_sids)[0]
        for first, second in (((REAL_SID, ""), (sid, "?training=1")), ((sid, "?training=1"), (REAL_SID, ""))):
            for sid_, query in (first, second):
                made = self.client.post(f"/api/v1/coding/allocation{query}", json={"sid": sid_},
                                        headers=self._csrf_headers())
                self.assertEqual(made.status_code, 201, (sid_, made.get_json()))
            self.assertEqual(self._held(self.trainee.user_id), {(REAL_SID, False), (sid, True)})
            # Each side shows and resumes its own case only.
            self.assertEqual(self.get("/api/v1/coding/allocation").get_json()["allocation"]["va_sid"], REAL_SID)
            self.assertEqual(self.get("/api/v1/coding/allocation?training=1").get_json()["allocation"]["va_sid"], sid)
            resumed = self.client.post("/api/v1/coding/allocation?training=1", json={}, headers=self._csrf_headers())
            self.assertEqual(resumed.get_json().get("va_sid"), sid)
            # Releasing one side leaves the other held.
            released = self.client.post("/api/v1/coding/allocation/release?training=1", headers=self._csrf_headers())
            self.assertEqual((released.status_code, released.get_json()["va_sid"]), (200, sid))
            self.assertEqual(self._held(self.trainee.user_id), {(REAL_SID, False)})
            self.assertIsNone(self.get("/api/v1/coding/allocation?training=1").get_json()["allocation"])
            released = self.client.post("/api/v1/coding/allocation/release", headers=self._csrf_headers())
            self.assertEqual((released.status_code, released.get_json()["va_sid"]), (200, REAL_SID))
            self.assertEqual(self._held(self.trainee.user_id), set())
            # Back to ready for the second order.
            for released_sid in (sid, REAL_SID):
                db.session.execute(sa.update(VaSubmissionWorkflow).where(
                    VaSubmissionWorkflow.va_sid == released_sid).values(workflow_state="ready_for_coding"))
            db.session.commit()

    def test_demo_start_releases_only_its_own_side(self):
        from app.services.coder_workflow_service import AllocationError, start_demo_allocation

        sid = sorted(self.training_sids)[0]
        for scope, released in ((training_scope.EXCLUDE, False), (training_scope.ONLY, True)):
            held = VaAllocations(
                va_sid=sid, va_allocated_to=self.trainee.user_id, va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active, va_allocation_training=True)
            db.session.add(held)
            db.session.commit()
            with self.scope(scope):
                try:
                    start_demo_allocation(self.trainee)
                except AllocationError:
                    pass  # no demo form to start: only the release matters here
                db.session.flush()
            db.session.refresh(held)
            self.assertEqual(held.va_allocation_status == VaStatuses.deactive, released, scope)
            db.session.rollback()
            db.session.delete(db.session.get(VaAllocations, held.va_allocation_id))
            db.session.commit()

    def test_recode_and_code_now_are_refused_across_the_line(self):
        sid = sorted(self.training_sids)[0]
        for known in (sid, REAL_SID):  # both exist: the refusal is the scope, not a missing row
            self.assertIsNotNone(db.session.get(VaSubmissions, known))
        for path, query, target in (
            ("recode", "", sid), ("recode", "?training=1", REAL_SID),
            ("submissions/{}/code-now", "", sid), ("submissions/{}/code-now", "?training=1", REAL_SID),
            ("initial", "", sid), ("initial", "?training=1", REAL_SID),
            ("finalize", "", sid), ("finalize", "?training=1", REAL_SID),
            ("not-codeable", "", sid), ("not-codeable", "?training=1", REAL_SID),
            ("submissions/{}/send-back", "", sid), ("submissions/{}/send-back", "?training=1", REAL_SID),
            ("submissions/{}/smartva", "", sid), ("submissions/{}/smartva", "?training=1", REAL_SID),
        ):
            response = self.post(f"/api/v1/coding/{path.format(target) if '{}' in path else path + '/' + target}{query}")
            self.assertEqual((response.status_code, response.get_json()["code"]), (409, "not_available"), path)
        for query, target in (("", sid), ("?training=1", REAL_SID)):
            get_sv = self.get(f"/api/v1/coding/submissions/{target}/smartva{query}")
            self.assertEqual((get_sv.status_code, get_sv.get_json()["code"]), (409, "not_available"))
        # Inside its own scope the same call is not refused for the scope.
        inside = self.post(f"/api/v1/coding/recode/{sid}?training=1")
        self.assertNotEqual(inside.get_json().get("code"), "not_available")
        inside = self.post(f"/api/v1/coding/submissions/{REAL_SID}/code-now")
        self.assertNotEqual(inside.get_json().get("code"), "not_available")

    def test_history_and_output_summary_split_by_scope(self):
        sid = sorted(self.training_sids)[0]
        for coded in (sid, REAL_SID):
            db.session.add(VaFinalAssessments(va_sid=coded, va_finassess_by=self.trainee.user_id,
                                              va_conclusive_cod="J18.9"))
        db.session.commit()
        training = {r["va_sid"] for r in self.get("/api/v1/coding/history?training=1").get_json()["history"]}
        real = {r["va_sid"] for r in self.get("/api/v1/coding/history").get_json()["history"]}
        self.assertEqual(training, {sid})  # both rows exist: each scope shows its own
        self.assertEqual(real, {REAL_SID})
        with self.scope(training_scope.ONLY):
            self.assertEqual(get_coder_output_summary(self.trainee.user_id)["completed"], 1)
        with self.scope(training_scope.EXCLUDE):
            self.assertEqual(get_coder_output_summary(self.trainee.user_id)["completed"], 1)
        with self.scope(training_scope.ONLY):
            self.assertEqual(get_coder_output_summary(self.trainee.user_id, "TRN01")["completed"], 1)
            self.assertEqual(get_coder_output_summary(self.trainee.user_id, self.BASE_PROJECT_ID)["completed"], 0)


class ReviewingScopeTests(TrainingScopeBase):
    roles = ("reviewer_data_manager",)

    def setUp(self):
        super().setUp()
        # Both a training case and the real one wait for review.
        self.training_sid = sorted(self._session_sids()[1])[0]
        for sid in (self.training_sid, REAL_SID):
            db.session.execute(sa.update(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == sid).values(workflow_state="reviewer_eligible"))
        db.session.commit()

    def test_normal_review_lists_and_counts_exclude_training(self):
        # The subject exists: the training case is in the trainee's review reach, unscoped.
        scoped = self.get("/api/v1/reviewing/available?training=1").get_json()
        self.assertIn(self.training_sid, {c["va_sid"] for c in scoped["cases"]})
        normal = self.get("/api/v1/reviewing/available").get_json()
        self.assertNotIn(self.training_sid, {c["va_sid"] for c in normal["cases"]})
        stats = self.get("/api/v1/reviewing/stats").get_json()
        trained = self.get("/api/v1/reviewing/stats?training=1").get_json()
        self.assertEqual(stats["in_scope"], 205)  # the 205 real source cases, none of the 200 copies
        self.assertEqual(trained["in_scope"], 10 * 20)  # the whole session: 20 slots of 10, nothing real
        self.assertEqual(stats["available"], 1)
        self.assertEqual(trained["available"], 1)  # the one training case made eligible
        self.assertEqual(
            [p["project_id"] for p in self.get("/api/v1/reviewing/projects").get_json()["project_options"]],
            [self.BASE_PROJECT_ID])
        self.assertEqual(
            [p["project_id"] for p in self.get("/api/v1/reviewing/projects?training=1").get_json()["project_options"]],
            ["TRN01"])
        self.assertEqual(self.get("/api/v1/reviewing/available?project_id=TRN01").get_json()["cases"], [])

    def test_a_held_real_review_does_not_block_a_training_one_and_back(self):
        started = self.client.post(f"/api/v1/reviewing/allocation/{REAL_SID}", headers=self._csrf_headers())
        self.assertEqual(started.status_code, 201, started.get_json())
        started = self.client.post(f"/api/v1/reviewing/allocation/{self.training_sid}?training=1",
                                   headers=self._csrf_headers())
        self.assertEqual(started.status_code, 201, started.get_json())
        self.assertEqual(self.get("/api/v1/reviewing/allocation").get_json()["allocation"]["va_sid"], REAL_SID)
        self.assertEqual(
            self.get("/api/v1/reviewing/allocation?training=1").get_json()["allocation"]["va_sid"], self.training_sid)
        released = self.client.post("/api/v1/reviewing/allocation/release?training=1", headers=self._csrf_headers())
        self.assertEqual(released.get_json()["va_sid"], self.training_sid)
        self.assertEqual(self.get("/api/v1/reviewing/allocation").get_json()["allocation"]["va_sid"], REAL_SID)
        self.assertIsNone(self.get("/api/v1/reviewing/allocation?training=1").get_json()["allocation"])

    def test_dm_surfaces_leave_training_out(self):
        # The trainee holds a data-manager grant on TRN01: present when the exclusion is off.
        training_sids = self._session_sids()[1]
        with self.training_visible():
            shown = {r["va_sid"] for r in self.get("/api/v1/data-management/submissions?size=100").get_json()["data"]}
            self.assertTrue(training_sids & shown, shown)
            self.assertIn("TRN01", self.get("/api/v1/data-management/filter-options").get_json()["projects"])
        grid = self.get("/api/v1/data-management/submissions?size=100").get_json()["data"]
        self.assertFalse({r["va_sid"] for r in grid} & training_sids)
        self.assertNotIn("TRN01", self.get("/api/v1/data-management/filter-options").get_json()["projects"])
        # The CSV: asked for the training project by id, it is empty unless the exclusion is off.
        with self.training_visible():
            export = self.get("/api/v1/data-management/submissions/export.csv?project=TRN01")
            self.assertEqual(export.status_code, 200)
            self.assertTrue([sid for sid in training_sids if sid in export.get_data(as_text=True)])
        export = self.get("/api/v1/data-management/submissions/export.csv?project=TRN01,TRN01")
        self.assertEqual(export.status_code, 200)
        self.assertFalse([sid for sid in training_sids if sid in export.get_data(as_text=True)])

    def test_review_scope_needs_the_participation_and_allocation_stays_in_scope(self):
        self.assertEqual(
            self.client.post(f"/api/v1/reviewing/allocation/{self.training_sid}",
                             headers=self._csrf_headers()).status_code, 409)
        self._login(self.base_coder_id)
        self.assertEqual(self.get("/api/v1/reviewing/available?training=1").status_code, 403)
        self.assertEqual(self.get("/api/v1/reviewing/stats?training=1").status_code, 403)


class DefaultExcludeTests(TrainingScopeBase):
    """EXCLUDE is the default for every request: no scope set, no leak."""

    def test_a_plain_request_and_the_cli_differ(self):
        self.assertIsNone(training_scope.current())  # no request: the CLI and Celery see everything
        with self.app.test_request_context("/"):
            self.assertEqual(training_scope.current(), training_scope.EXCLUDE)
        with self.app.test_request_context("/"):
            training_scope.use(training_scope.ALL)
            self.assertEqual(training_scope.conditions(db.literal_column("x")), [])

    def test_trainer_tools_run_unfiltered_and_the_rest_excluded(self):
        for path, expected in (
            ("/admin/api/training/sessions", training_scope.ALL),
            ("/admin/panels/training-sessions", training_scope.ALL),
            ("/data-management/training/S001", training_scope.ALL),
            ("/coding/", training_scope.EXCLUDE),
            ("/admin/api/other", training_scope.EXCLUDE),
        ):
            with self.app.test_request_context(path):
                self.app.preprocess_request()
                self.assertEqual(training_scope.current(), expected, path)

    def test_flask_coding_start_never_allocates_training(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.coding_intake_mode = "random"
        db.session.commit()
        # Present: with no scope (the CLI) the pool offers the training cases too.
        self.assertTrue(self.training_sids & {r["va_sid"] for r in svc_pick(self.trainee)})
        self.client.post("/coding/start", headers=self._csrf_headers())
        held = self._held_sides()
        self.assertTrue(held)  # the request did allocate
        self.assertEqual({training for _, training in held}, {False})
        self.assertFalse({sid for sid, _ in held} & self.training_sids)

    def _held_sides(self):
        return {
            (row.va_sid, row.va_allocation_training)
            for row in db.session.scalars(sa.select(VaAllocations).where(
                VaAllocations.va_allocated_to == self.trainee.user_id,
                VaAllocations.va_allocation_status == VaStatuses.active))
        }


class DmKpiScopeTests(TrainingScopeBase):
    roles = ("reviewer_data_manager",)

    def test_kpi_scope_leaves_the_training_grant_out(self):
        from app.routes.api.dm_kpi import dm_kpi_scope
        from app.services import data_management_service

        def projects(scope):
            return set(scope.project_ids) | set(scope.unit_project_ids) | {pair[0] for pair in scope.pairs}

        raw, filtered = [], []
        real = dm_kpi_scope.dm_grant_scope

        def spy(user):
            raw.append(data_management_service._dm_grant_scope(user))
            filtered.append(real(user))
            return filtered[-1]

        with mock.patch.object(dm_kpi_scope, "dm_grant_scope", spy):
            response = self.get("/api/v1/analytics/dm-kpi/grid/")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:200])
        self.assertIn("TRN01", projects(raw[0]))  # present before asserting absent
        self.assertNotIn("TRN01", projects(filtered[0]))


class InterviewScopeTests(TrainingScopeBase):
    roles = ("death_reporter", "interviewer", "interview_supervisor")

    def test_intake_lists_follow_the_scope(self):
        # The same endpoints answer 200 in both scopes for a participant, 403 only for training=1 without it.
        for path in ("/api/v1/intake/cases", "/api/v1/intake/supervision/cases"):
            self.assertEqual(self.get(path).status_code, 200, path)
            self.assertEqual(self.get(path + "?training=1").status_code, 200, path)
        self.assertEqual(self.get("/api/v1/intake/drafts?training=1").status_code, 200)
        self._login(self.base_coder_id)
        for path in ("/api/v1/intake/cases", "/api/v1/intake/supervision/cases", "/api/v1/intake/deaths"):
            self.assertEqual(self.get(path + "?training=1").status_code, 403, path)

    def test_cases_are_split_by_project(self):
        session = db.session.get(MasTrainingSession, self.first["training_session_id"])
        form = svc._web_form()
        training_id = self._case("TRN01", form.site_id, session.org_unit_id, "T")
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.web_intake_mode = "both"
        project_site = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.BASE_PROJECT_ID, VaProjectSites.site_id == self.BASE_SITE_ID))
        db.session.add(VaUserAccessGrants(
            user_id=self.trainee.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project_site, project_site_id=project_site.project_site_id,
            grant_status=VaStatuses.active))
        real_id = self._case(self.BASE_PROJECT_ID, self.BASE_SITE_ID, None, "R")
        scoped = {c["death_id"] for c in self.get("/api/v1/intake/cases?training=1").get_json()["cases"]}
        self.assertEqual(scoped, {training_id})  # the subject exists in the training scope
        self.assertEqual(self.get(f"/api/v1/intake/cases/{training_id}?training=1").status_code, 200)
        self.assertEqual(self.get(f"/api/v1/intake/cases/{training_id}").status_code, 404)
        self.assertEqual(self.get(f"/api/v1/intake/cases/{training_id}/possible-duplicates?training=1").status_code, 200)
        self.assertEqual(self.get(f"/api/v1/intake/cases/{training_id}/possible-duplicates").status_code, 404)
        normal = {c["death_id"] for c in self.get("/api/v1/intake/cases").get_json()["cases"]}
        self.assertIn(real_id, normal)
        self.assertNotIn(training_id, normal)
        by_id = self.get("/api/v1/intake/cases?project_id=TRN01").get_json()["cases"]
        self.assertEqual(by_id, [])
        supervised = {c["death_id"] for c in self.get("/api/v1/intake/supervision/cases?training=1").get_json()["cases"]}
        self.assertIn(training_id, supervised)
        self.assertNotIn(training_id, {
            c["death_id"] for c in self.get("/api/v1/intake/supervision/cases").get_json()["cases"]})
        self.assertEqual(self.get(f"/api/v1/intake/supervision/cases/{training_id}?training=1").status_code, 200)
        self.assertEqual(self.get(f"/api/v1/intake/supervision/cases/{training_id}").status_code, 404)
        self.assertEqual(self.get(f"/api/v1/intake/supervision/cases/{training_id}/possible-duplicates?training=1").status_code, 200)
        self.assertEqual(self.get(f"/api/v1/intake/supervision/cases/{training_id}/possible-duplicates").status_code, 404)

    def test_training_form_configuration_is_scoped(self):
        options = self.get("/api/v1/organization/TRN01/form-options?training=1")
        self.assertEqual(options.status_code, 200, options.get_json())
        options_json = options.get_json()
        self.assertTrue(options_json["intake_note"])
        self.assertIn("intake_screen", options_json["enabled_extensions"])
        form_types = options_json["form_types"]
        instrument_code = next(item["instrument_code"] for item in form_types if item["is_default"])
        self.assertEqual(self.get("/api/v1/organization/TRN01/form-options").status_code, 403)
        self.assertEqual(
            self.get(f"/api/v1/organization/{self.BASE_PROJECT_ID}/form-options?training=1").status_code,
            403,
        )
        definition = self.get(
            f"/api/v1/instruments/{instrument_code}/definition?project_id=TRN01&training=1"
        )
        self.assertEqual(definition.status_code, 200, definition.get_json())
        self.assertEqual(
            self.get(f"/api/v1/instruments/{instrument_code}/definition?project_id=TRN01").status_code,
            403,
        )
        self.assertEqual(
            self.get("/api/v1/intake/identifier-types?project_id=TRN01&training=1").status_code,
            200,
        )
        self.assertEqual(
            self.get("/api/v1/intake/identifier-types?project_id=TRN01").status_code,
            403,
        )
        consent_cfg = self.get("/api/v1/intake/consent-config?project_id=TRN01&training=1")
        self.assertEqual(consent_cfg.status_code, 200, consent_cfg.get_json())
        self.assertTrue(consent_cfg.get_json()["consent_required"])
        self.assertEqual(
            self.get("/api/v1/intake/consent-config?project_id=TRN01").status_code,
            403,
        )
        self.assertEqual(
            self.get("/api/v1/intake/projects/TRN01/prefill-policy?training=1").status_code,
            200,
        )
        self.assertEqual(
            self.get("/api/v1/intake/projects/TRN01/prefill-policy").status_code,
            403,
        )

    def test_registered_deaths_and_drafts_follow_the_scope(self):
        training_id = self._training_death()
        draft = self.post("/api/v1/intake/drafts?training=1", {
            "project_id": "TRN01", "site_id": svc._web_form().site_id, "death_id": training_id})
        self.assertEqual(draft.status_code, 201, draft.get_json())
        draft_id = draft.get_json()["draft"]["draft_id"]
        scoped = {d["death_id"] for d in self.get("/api/v1/intake/deaths?registered=mine&training=1").get_json()["deaths"]}
        self.assertIn(training_id, scoped)  # the subject exists in the training scope
        self.assertNotIn(training_id, {d["death_id"] for d in self.get("/api/v1/intake/deaths?registered=mine").get_json()["deaths"]})
        scoped = {d["draft_id"] for d in self.get("/api/v1/intake/drafts?training=1").get_json()["drafts"]}
        self.assertIn(draft_id, scoped)
        self.assertEqual(self.get(f"/api/v1/intake/drafts/{draft_id}?training=1").status_code, 200)
        self.assertEqual(self.get(f"/api/v1/intake/drafts/{draft_id}").status_code, 404)
        self.assertNotIn(draft_id, {d["draft_id"] for d in self.get("/api/v1/intake/drafts").get_json()["drafts"]})

    def test_a_replayed_client_draft_id_cannot_cross_the_line(self):
        training_id = self._training_death()
        site = svc._web_form().site_id
        draft = self.post("/api/v1/intake/drafts?training=1", {
            "project_id": "TRN01", "site_id": site, "death_id": training_id}).get_json()["draft"]["draft_id"]
        client_id = uuid.uuid4()
        db.session.execute(sa.update(VaWebIntakeDraft).where(
            VaWebIntakeDraft.draft_id == uuid.UUID(draft)).values(client_draft_id=client_id))
        db.session.commit()
        self.assertEqual(  # present: the id finds the training draft
            db.session.scalar(sa.select(VaWebIntakeDraft.project_id).where(
                VaWebIntakeDraft.client_draft_id == client_id)), "TRN01")
        body = {"project_id": self.BASE_PROJECT_ID, "site_id": self.BASE_SITE_ID, "client_draft_id": str(client_id)}
        refused = self.post("/api/v1/intake/submissions", body)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "training_scope"))
        # Without a project at all the id alone is refused too, and the training side is not.
        alone = self.post("/api/v1/intake/submissions", {"client_draft_id": str(client_id)})
        self.assertEqual((alone.status_code, alone.get_json()["code"]), (409, "training_scope"))
        inside = self.post("/api/v1/intake/submissions?training=1", {"client_draft_id": str(client_id)})
        self.assertNotEqual((inside.get_json() or {}).get("code"), "training_scope")

    def test_writes_across_the_line_are_refused(self):
        training_id = self._training_death()
        site = svc._web_form().site_id
        draft = self.post("/api/v1/intake/drafts?training=1", {
            "project_id": "TRN01", "site_id": site, "death_id": training_id}).get_json()["draft"]["draft_id"]
        refused = (409, "training_scope")

        def code(response):
            return response.status_code, (response.get_json() or {}).get("code")

        body = {"project_id": "TRN01", "site_id": site}
        real_body = {"project_id": self.BASE_PROJECT_ID, "site_id": self.BASE_SITE_ID}
        # Normal scope (what the phone app sends) cannot write into training ...
        for path, payload in (
            ("/api/v1/intake/deaths", body), ("/api/v1/intake/drafts", body), ("/api/v1/intake/drafts/sync", body),
            ("/api/v1/intake/submissions", body),
        ):
            self.assertEqual(code(self.post(path, payload)), refused, path)
            # ... and the same call inside the scope is not refused for it.
            self.assertNotEqual(code(self.post(f"{path}?training=1", payload))[1], "training_scope", path)
            # The training scope cannot write a real project.
            self.assertEqual(code(self.post(f"{path}?training=1", real_body)), refused, path)
        # By id: an existing training draft and death.
        self.assertEqual(code(self.post(f"/api/v1/intake/drafts/{draft}/discard")), refused)
        self.assertEqual(code(self.post(f"/api/v1/intake/drafts/{draft}/submit", {})), refused)
        self.assertEqual(code(self.client.patch(
            f"/api/v1/intake/deaths/{training_id}", json={}, headers=self._csrf_headers())), refused)
        self.assertEqual(code(self.post(f"/api/v1/intake/cases/{training_id}/attempts", {})), refused)
        self.assertNotEqual(code(self.post(f"/api/v1/intake/drafts/{draft}/discard?training=1"))[1], "training_scope")
        # Training scope needs the participation, as for reads.
        self._login(self.base_coder_id)
        self.assertEqual(self.post("/api/v1/intake/drafts?training=1", body).status_code, 403)


class HomeCountsTests(TrainingScopeBase):
    roles = ("coder", "death_reporter", "interview_supervisor", "reviewer_data_manager")

    def setUp(self):
        super().setUp()
        # A stand-in for the analytics snapshot (a materialized view in production).
        db.session.execute(sa.text(
            "CREATE TEMP TABLE va_submission_analytics_core_mv (va_sid text, project_id text, site_id text, "
            "org_unit_id uuid, workflow_state text, odk_missing boolean, submission_date date, "
            "submission_at timestamptz)"))
        self.addCleanup(lambda: db.session.execute(sa.text("DROP TABLE IF EXISTS pg_temp.va_submission_analytics_core_mv")))

    def _two_deaths(self):
        training_id = self._training_death()
        real_id = self._case(self.BASE_PROJECT_ID, self.BASE_SITE_ID, None, "H")
        return training_id, real_id

    def test_home_and_activity_leave_training_out(self):
        training_id, real_id = self._two_deaths()
        db.session.add(VaFinalAssessments(
            va_sid=sorted(self.training_sids)[0], va_finassess_by=self.trainee.user_id, va_conclusive_cod="J18.9"))
        db.session.commit()
        home = self.get("/api/v1/me/home").get_json()
        self.assertEqual(home["blocks"]["coder"]["ready"], 1)
        activity = self.get("/api/v1/me/activity").get_json()
        # The training coding exists: with the exclusion off it is counted.
        with self.training_visible():
            visible = self.get("/api/v1/me/activity").get_json()
        self.assertIn("TRN01", visible["by_project"])
        self.assertNotIn("TRN01", activity["by_project"])

    def test_death_reporter_and_supervisor_blocks_count_only_their_side(self):
        self._two_deaths()
        self._training_death()  # two training deaths, one real
        for scope, registered, open_cases in ((training_scope.ONLY, 2, 2), (training_scope.EXCLUDE, 1, 0)):
            with self.scope(scope):
                self.assertEqual(user_home_service._death_reporter_block(self.trainee)["registered"], registered)
                self.assertEqual(user_home_service._supervisor_block(self.trainee)["open"], open_cases)

    def test_data_manager_block_counts_only_the_side(self):
        session = db.session.get(MasTrainingSession, self.first["training_session_id"])
        db.session.execute(sa.text(
            "INSERT INTO va_submission_analytics_core_mv VALUES "
            "('t-1', 'TRN01', :site, :unit, 'ready_for_coding', false, now(), now())"),
            {"site": svc._web_form().site_id, "unit": session.org_unit_id})
        with self.scope(training_scope.ONLY):
            self.assertEqual(user_home_service._data_manager_block(self.trainee)["ready_for_coding"], 1)
        with self.scope(training_scope.EXCLUDE):
            self.assertEqual(user_home_service._data_manager_block(self.trainee)["ready_for_coding"], 0)

    def test_kpis_leave_training_out_and_the_cache_does_not_leak(self):
        self._two_deaths()
        cache_keys = [f"{area_dashboard_service.HOME_KPI_CACHE_PREFIX}{self.trainee.user_id}"]
        from app import cache
        for _ in range(2):  # the second read is served from the cache
            projects = self.get("/api/v1/me/kpis").get_json()["projects"]
            self.assertNotIn("TRN01", [p["project_id"] for p in projects])
        self.assertNotIn("TRN01", [p["project_id"] for p in (cache.get(cache_keys[0]) or [])])
        # Present once the exclusion is off: the trainee's area does hold the training project.
        cache.delete(cache_keys[0])
        with self.training_visible():
            self.assertIn("TRN01", [p for p, _ in area_dashboard_service.candidate_projects(self.trainee)])
        self.assertNotIn("TRN01", [p for p, _ in area_dashboard_service.candidate_projects(self.trainee)])

    def test_cases_list_and_filters_leave_training_out(self):
        training_id, real_id = self._two_deaths()
        with self.training_visible():
            ids = {c["death_id"] for c in self.get("/api/v1/cases?limit=100").get_json()["cases"]}
            self.assertIn(training_id, ids)
            self.assertIn("TRN01", [p["project_id"] for p in self.get("/api/v1/cases/filter-options").get_json()["projects"]])
        ids = {c["death_id"] for c in self.get("/api/v1/cases?limit=100").get_json()["cases"]}
        self.assertNotIn(training_id, ids)
        self.assertNotIn("TRN01", [p["project_id"] for p in self.get("/api/v1/cases/filter-options").get_json()["projects"]])
        self.assertEqual(self.get("/api/v1/cases?limit=100&project_id=TRN01").get_json()["cases"], [])

    def test_notifications_leave_training_out_and_the_cursor_moves_on(self):
        for project_id in ("TRN01", self.BASE_PROJECT_ID, "TRN01"):
            notification_service.notify([self.trainee.user_id], "case_reopened", project_id=project_id)
        db.session.commit()
        rows = db.session.scalars(sa.select(MapUserNotification).where(
            MapUserNotification.user_id == self.trainee.user_id).order_by(MapUserNotification.id)).all()
        self.assertEqual([r.project_id for r in rows], ["TRN01", self.BASE_PROJECT_ID, "TRN01"])
        polled = self.get("/api/v1/me/notifications?after=0").get_json()
        self.assertEqual([n["project_id"] for n in polled["notifications"]], [self.BASE_PROJECT_ID])
        self.assertEqual(polled["next_cursor"], rows[-1].id)  # past the hidden rows: no re-poll forever


class MeAndStartTests(TrainingDemoTestBase):
    def test_me_reports_areas_by_role_and_access_carries_the_menu(self):
        user = self._user("menu")
        svc.add_participant("S001", user.email, ["coder", "death_reporter", "interviewer"], self.admin)
        self._login(str(user.user_id))
        body = self.client.get("/api/v1/training/me").get_json()
        self.assertEqual(body["areas"], ["interview", "coding"])
        self.assertTrue(body["pending"])
        self.assertEqual(body["project_id"], "TRN01")
        self.assertEqual(sorted(p["role"] for p in body["participations"]), ["coder", "death_reporter", "interviewer"])
        access = self.client.get("/api/v1/me/access").get_json()
        training = access["training"]
        self.assertEqual((training["project_id"], training["areas"], training["pending"]),
                         ("TRN01", ["interview", "coding"], True))
        # The training project sits in `training.project`, never in the normal project list or roles.
        self.assertEqual(training["project"]["project_id"], "TRN01")
        self.assertEqual(len(training["project"]["actions"]["interview"][0]["org_units"]), 1)
        self.assertEqual(len(training["project"]["actions"]["register_death"][0]["org_units"]), 1)
        self.assertNotIn("TRN01", [p["project_id"] for p in access["projects"]])
        self.assertEqual(access["roles"], [])  # a trainee holds no real role

    def test_a_real_role_survives_and_the_training_one_is_not_counted(self):
        user = self._user("both")
        svc.add_participant("S001", user.email, ["coder"], self.admin)
        self._login(str(user.user_id))
        self.assertEqual(self.client.get("/api/v1/me/access").get_json()["roles"], [])
        self._login(self.base_coder_id)  # a real coder: roles intact, training menu empty
        access = self.client.get("/api/v1/me/access").get_json()
        self.assertIn("coder", access["roles"])
        self.assertEqual(access["training"]["areas"], [])
        self.assertIsNone(access["training"]["project"])

    def test_non_participant_has_no_areas(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/api/v1/training/me").get_json()["areas"], [])
        self.assertEqual(self.client.get("/api/v1/me/access").get_json()["training"]["areas"], [])

    def test_review_area_for_reviewer_data_manager(self):
        user = self._user("rdm")
        svc.add_participant("S001", user.email, ["reviewer_data_manager"], self.admin)
        self._login(str(user.user_id))
        self.assertEqual(self.client.get("/api/v1/training/me").get_json()["areas"], ["review"])

    def test_start_records_onboarding_and_needs_csrf(self):
        user = self._user("start")
        svc.add_participant("S001", user.email, ["coder"], self.admin)
        self._login(str(user.user_id))
        self.assertEqual(self.client.post("/api/v1/training/me/start").status_code, 400)  # no CSRF token
        done = self.client.post("/api/v1/training/me/start", headers=self._csrf_headers())
        self.assertEqual(done.status_code, 200)
        self.assertFalse(done.get_json()["pending"])
        self.assertTrue(all(p["onboarded_at"] for p in done.get_json()["participations"]))
        again = self.client.post("/api/v1/training/me/start", headers=self._csrf_headers())
        self.assertEqual(again.status_code, 200)

    def test_anonymous_is_refused(self):
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        with self.client.session_transaction() as sess:
            sess.clear()
        self.assertEqual(self.client.get("/api/v1/training/me").status_code, 401)


def svc_pick(user):
    from app.services.coder_workflow_service import get_pick_available_forms

    form_ids = user.get_coder_va_forms()
    return get_pick_available_forms(user, form_ids)
