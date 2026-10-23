"""Concurrent coding allocation answers 409, never 500 (digitva-kxit).

Staging load test: two coders allocated the same case; the loser hit
WorkflowTransitionError and the route returned 500. These tests use a second
real connection, so the fixtures are committed (isolate_in_transaction =
False) and deleted in tearDownClass. See tests/base.py.
"""

import threading
import time
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import coder_workflow_service as cws
from app.services.coder_workflow_service import AllocationError
from tests.base import BaseTestCase

# (project_id, site_id, form_id, sid, intake_mode)
FIXTURES = [
    ("RAC01", "RA01", "RAC01RA0101", "race-pick-1", "pick_and_choose"),
    ("RAC02", "RA02", "RAC02RA0201", "race-random-1", "random_form_allocation"),
]
PICK_SID = "race-pick-1"
RANDOM_SID = "race-random-1"


class CodingAllocationRaceTests(BaseTestCase):
    isolate_in_transaction = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        cls.coder_a = cls._make_user("race.a@test.local", "RaceCoderA123")
        cls.coder_b = cls._make_user("race.b@test.local", "RaceCoderB123")
        for project_id, site_id, form_id, sid, mode in FIXTURES:
            db.session.add_all([
                VaProjectMaster(
                    project_id=project_id, project_code=project_id,
                    project_name=project_id, project_nickname=project_id,
                    coding_intake_mode=mode, project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=project_id, project_code=project_id,
                    project_name=project_id, project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=site_id, site_name=site_id, site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now, site_updated_at=now,
                ),
                VaSites(
                    site_id=site_id, project_id=project_id, site_name=site_id,
                    site_abbr=site_id, site_status=VaStatuses.active,
                    site_registered_at=now, site_updated_at=now,
                ),
            ])
            db.session.flush()
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=site_id,
                odk_form_id=f"FORM_{project_id}", odk_project_id="11",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
            db.session.flush()
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=form_id, va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="Collector",
                va_odk_reviewstate=None, va_instance_name=sid,
                va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
                va_narration_language="English", va_deceased_age=42,
                va_deceased_gender="male", va_summary=[], va_catcount={},
                va_category_list=[],
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state="ready_for_coding",
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))
            project_site_id = db.session.scalar(
                sa.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == project_id,
                    VaProjectSites.site_id == site_id,
                )
            )
            for user in (cls.coder_a, cls.coder_b):
                db.session.add(VaUserAccessGrants(
                    user_id=user.user_id, role=VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site_id, notes="race coder",
                    grant_status=VaStatuses.active,
                ))
        db.session.commit()
        cls.coder_a_id = cls.coder_a.user_id
        cls.coder_b_id = cls.coder_b.user_id

    @classmethod
    def tearDownClass(cls):
        try:
            db.session.rollback()
            sids = [f[3] for f in FIXTURES]
            for table in reversed(db.metadata.sorted_tables):
                if "va_sid" in table.c and table.name != "va_submissions":
                    db.session.execute(sa.delete(table).where(table.c.va_sid.in_(sids)))
            db.session.execute(sa.delete(VaSubmissions).where(VaSubmissions.va_sid.in_(sids)))
            db.session.execute(sa.delete(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id.in_([cls.coder_a_id, cls.coder_b_id])
            ))
            db.session.execute(sa.delete(VaUsers).where(
                VaUsers.user_id.in_([cls.coder_a_id, cls.coder_b_id])
            ))
            for model, column in (
                (VaForms, VaForms.form_id), (VaProjectSites, VaProjectSites.project_id),
                (VaSites, VaSites.project_id), (VaResearchProjects, VaResearchProjects.project_id),
                (VaProjectMaster, VaProjectMaster.project_id),
            ):
                keys = [f[2] if model is VaForms else f[0] for f in FIXTURES]
                db.session.execute(sa.delete(model).where(column.in_(keys)))
            db.session.execute(sa.delete(VaSiteMaster).where(
                VaSiteMaster.site_id.in_([f[1] for f in FIXTURES])
            ))
            db.session.commit()
        finally:
            super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._reset(PICK_SID)
        self._reset(RANDOM_SID)

    def _reset(self, sid):
        db.session.rollback()
        db.session.execute(sa.delete(VaAllocations).where(VaAllocations.va_sid == sid))
        db.session.execute(
            sa.update(VaSubmissionWorkflow)
            .where(VaSubmissionWorkflow.va_sid == sid)
            .values(workflow_state="ready_for_coding", workflow_reason="test_reset")
        )
        db.session.execute(
            sa.update(VaUsers)
            .where(VaUsers.user_id.in_([self.coder_a_id, self.coder_b_id]))
            .values(vacode_formcount=0)
        )
        db.session.commit()

    def _active_allocations(self, sid):
        db.session.rollback()
        return db.session.scalars(
            sa.select(VaAllocations).where(
                VaAllocations.va_sid == sid,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        ).all()

    def _in_thread(self, name, fn, results):
        """Run *fn(user_id)* in its own app context (own session, own connection)."""
        def run():
            with self.app.app_context():
                try:
                    results[name] = ("ok", fn())
                except Exception as exc:  # noqa: BLE001 - the test inspects it
                    results[name] = ("error", exc)
                finally:
                    db.session.remove()
        thread = threading.Thread(target=run, name=name)
        thread.start()
        return thread

    def test_pick_loser_of_a_race_gets_409_held_by_another(self):
        a_locked, b_reached, release_a = (threading.Event() for _ in range(3))
        real = cws._create_coding_allocation

        def parked(*args, **kwargs):
            name = threading.current_thread().name
            if name == "B":
                b_reached.set()
            real(*args, **kwargs)
            if name == "A":
                # Holding the workflow row lock, uncommitted.
                a_locked.set()
                assert release_a.wait(20)

        results = {}
        cws._create_coding_allocation = parked
        try:
            thread_a = self._in_thread("A", lambda: cws.allocate_pick_form(
                db.session.get(VaUsers, self.coder_a_id), PICK_SID), results)
            self.assertTrue(a_locked.wait(20), results)
            thread_b = self._in_thread("B", lambda: cws.allocate_pick_form(
                db.session.get(VaUsers, self.coder_b_id), PICK_SID), results)
            self.assertTrue(b_reached.wait(20), results)
            time.sleep(0.5)  # B is now waiting on A's row lock
            release_a.set()
            thread_a.join(30)
            thread_b.join(30)
        finally:
            cws._create_coding_allocation = real
            release_a.set()

        self.assertEqual(results["A"][0], "ok", results["A"])
        self.assertEqual(results["A"][1].va_sid, PICK_SID)
        self.assertEqual(results["B"][0], "error")
        error = results["B"][1]
        self.assertIsInstance(error, AllocationError, repr(error))
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.code, "held_by_another")
        active = self._active_allocations(PICK_SID)
        self.assertEqual([a.va_allocated_to for a in active], [self.coder_a_id])

    def test_random_pick_skips_a_case_another_coder_has_locked(self):
        lock_conn = db.engine.connect()
        try:
            lock_tx = lock_conn.begin()
            lock_conn.execute(
                sa.select(VaSubmissionWorkflow.va_sid)
                .where(VaSubmissionWorkflow.va_sid == RANDOM_SID)
                .with_for_update()
            )
            results = {}
            thread = self._in_thread("R", lambda: cws.allocate_random_form(
                db.session.get(VaUsers, self.coder_b_id), project_id="RAC02"), results)
            thread.join(15)
            # Without SKIP LOCKED the pick would block on the held row.
            self.assertFalse(thread.is_alive(), "random pick blocked on a locked case")
            self.assertEqual(results["R"][0], "error")
            self.assertIsInstance(results["R"][1], AllocationError)
            self.assertIn("No forms are available", results["R"][1].message)
        finally:
            lock_tx.rollback()
            lock_conn.close()

        results = {}
        self._in_thread("R2", lambda: cws.allocate_random_form(
            db.session.get(VaUsers, self.coder_b_id), project_id="RAC02"), results).join(30)
        self.assertEqual(results["R2"][0], "ok", results["R2"])
        self.assertEqual(results["R2"][1].va_sid, RANDOM_SID)

    def test_random_pick_taken_before_the_transition_is_409(self):
        """A state change the lock did not stop (a writer that skips the lock)."""
        from app.services.workflow.transitions import WorkflowTransitionError

        def refuse(*_args, **_kwargs):
            raise WorkflowTransitionError("Transition coding_started not allowed")

        original = cws._create_coding_allocation
        cws._create_coding_allocation = refuse
        try:
            user = db.session.get(VaUsers, self.coder_b_id)
            with self.assertRaises(AllocationError) as caught:
                cws.allocate_random_form(user, project_id="RAC02")
        finally:
            cws._create_coding_allocation = original
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.code, "not_available")

    def test_same_user_random_and_pick_of_one_case_do_not_deadlock(self):
        """Random locks the workflow row then inserts the allocation; the pick
        used to insert first then lock, so one user firing both on one case
        deadlocked (digitva-nw4b). Random is parked holding the row lock; the
        pick then reaches its allocation step and must wait on the lock, not
        insert."""
        r_locked, p_reached, release_r = (threading.Event() for _ in range(3))
        real = cws._create_coding_allocation

        def parked(*args, **kwargs):
            name = threading.current_thread().name
            if name == "P":
                p_reached.set()
            else:
                r_locked.set()
                assert release_r.wait(20)
            return real(*args, **kwargs)

        results = {}
        cws._create_coding_allocation = parked
        try:
            thread_r = self._in_thread("R", lambda: cws.allocate_random_form(
                db.session.get(VaUsers, self.coder_a_id), project_id="RAC02"), results)
            self.assertTrue(r_locked.wait(20), results)
            thread_p = self._in_thread("P", lambda: cws.allocate_pick_form(
                db.session.get(VaUsers, self.coder_a_id), RANDOM_SID, own_case=True), results)
            self.assertTrue(p_reached.wait(20), results)
            time.sleep(0.5)  # P is now past its checks, waiting on R's row lock
            release_r.set()
            thread_r.join(30)
            thread_p.join(30)
        finally:
            cws._create_coding_allocation = real
            release_r.set()

        self.assertEqual(results["R"][0], "ok", results.get("R"))
        self.assertEqual(results["P"][0], "ok", results.get("P"))
        self.assertEqual(results["R"][1].actiontype, "vastartcoding")
        self.assertEqual(results["P"][1].actiontype, "varesumecoding")
        active = self._active_allocations(RANDOM_SID)
        self.assertEqual([a.va_allocated_to for a in active], [self.coder_a_id])

    def test_deadlock_escaping_an_allocation_path_is_409_conflict(self):
        class _Deadlock(Exception):
            pgcode = "40P01"

        def deadlock(*_args, **_kwargs):
            raise sa.exc.OperationalError("INSERT", {}, _Deadlock())

        original = cws._create_coding_allocation
        cws._create_coding_allocation = deadlock
        try:
            user = db.session.get(VaUsers, self.coder_b_id)
            for call in (
                lambda: cws.allocate_random_form(user, project_id="RAC02"),
                lambda: cws.allocate_pick_form(user, PICK_SID),
            ):
                with self.assertRaises(AllocationError) as caught:
                    call()
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(caught.exception.code, "conflict")
        finally:
            cws._create_coding_allocation = original

    def test_other_operational_errors_are_not_masked_as_conflicts(self):
        class _Other(Exception):
            pgcode = "57014"

        def fail(*_args, **_kwargs):
            raise sa.exc.OperationalError("INSERT", {}, _Other())

        original = cws._create_coding_allocation
        cws._create_coding_allocation = fail
        try:
            user = db.session.get(VaUsers, self.coder_b_id)
            with self.assertRaises(sa.exc.OperationalError):
                cws.allocate_pick_form(user, PICK_SID)
        finally:
            cws._create_coding_allocation = original
