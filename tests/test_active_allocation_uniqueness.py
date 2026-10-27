"""One active coding allocation per coder (bead digitva-igq7).

Two concurrent allocation requests from one coder both passed the
"already holds one?" check and both inserted. The partial unique index
``uq_va_allocations_active_to_for`` now refuses the second insert and the
allocator resumes the first, as its own pre-check would. The race is
simulated by holding an allocation and making the pre-check miss it once.
"""
import uuid
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaProjectMaster,
    VaStatuses,
    VaSubmissionsAuditlog,
)
from app.services import coder_workflow_service as cws
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_pick_form,
    allocate_random_form,
    get_active_coding_allocation,
    release_own_coding_allocation,
)
from app.services.workflow.intake_modes import CODING_INTAKE_PICK, CODING_INTAKE_RANDOM
from app.services.workflow.state_store import get_submission_workflow_state
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


class ActiveAllocationUniquenessTests(CodingScopeFixtureMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        self.user = self.base_coder_user
        _, _, _, phc_a, _ = self._tree()
        self._grant(phc_a)
        self._submission("csc-held", unit=phc_a)
        self._submission("csc-other", unit=phc_a)
        self.held = VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid="csc-held",
            va_allocated_to=self.user.user_id, va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active,
        )
        db.session.add(self.held)
        db.session.commit()

    def _active(self):
        return db.session.scalars(sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == self.user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )).all()

    def _missed_precheck(self):
        """The pre-check misses the held allocation once (the other request
        had not committed yet); later reads see it."""
        real = cws.get_active_coding_allocation
        missed = []

        def lookup(user_id):
            if not missed:
                missed.append(user_id)
                return None
            return real(user_id)

        return mock.patch.object(cws, "get_active_coding_allocation", side_effect=lookup)

    def test_index_refuses_a_second_active_allocation(self):
        self.assertEqual(self._active(), ["csc-held"])
        db.session.add(VaAllocations(
            va_sid="csc-other", va_allocated_to=self.user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.flush()
        db.session.rollback()

    def test_a_deactive_row_does_not_count(self):
        db.session.add(VaAllocations(
            va_sid="csc-other", va_allocated_to=self.user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.deactive,
        ))
        db.session.flush()
        self.assertEqual(self._active(), ["csc-held"])

    def test_pick_race_on_another_case_refuses_and_writes_nothing(self):
        formcount = self.user.vacode_formcount
        with self._missed_precheck(), self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(self.user, "csc-other")
        self.assertEqual(ctx.exception.code, "allocation_exists")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self._active(), ["csc-held"])
        self.assertEqual(self.user.vacode_formcount, formcount)
        self.assertEqual(get_submission_workflow_state("csc-other"), "ready_for_coding")
        self.assertIsNone(db.session.scalar(sa.select(VaSubmissionsAuditlog.va_audit_id).where(
            VaSubmissionsAuditlog.va_sid == "csc-other"
        )))

    def test_pick_race_on_the_same_case_resumes(self):
        with self._missed_precheck():
            result = allocate_pick_form(self.user, "csc-held")
        self.assertEqual((result.va_sid, result.actiontype), ("csc-held", "varesumecoding"))
        self.assertEqual(self._active(), ["csc-held"])

    def test_random_race_resumes_the_held_allocation(self):
        db.session.get(VaProjectMaster, self.PROJECT).coding_intake_mode = CODING_INTAKE_RANDOM
        db.session.commit()
        try:
            with self._missed_precheck():
                result = allocate_random_form(self.user)
        finally:
            db.session.get(VaProjectMaster, self.PROJECT).coding_intake_mode = CODING_INTAKE_PICK
            db.session.commit()
        self.assertEqual((result.va_sid, result.actiontype), ("csc-held", "varesumecoding"))
        self.assertEqual(self._active(), ["csc-held"])

    def test_resume_is_stable(self):
        for _ in range(3):
            self.assertEqual(get_active_coding_allocation(self.user.user_id), "csc-held")
            self.assertEqual(allocate_pick_form(self.user, "csc-held").actiontype, "varesumecoding")

    def test_release_then_allocate(self):
        db.session.execute(sa.update(VaAllocations).where(
            VaAllocations.va_allocation_id == self.held.va_allocation_id
        ).values(va_allocation_status=VaStatuses.deactive))
        result = allocate_pick_form(self.user, "csc-other")
        self.assertEqual(result.va_sid, "csc-other")
        self.assertEqual(release_own_coding_allocation(self.user), "csc-other")
        self.assertEqual(self._active(), [])
        self.assertEqual(allocate_pick_form(self.user, "csc-held").va_sid, "csc-held")
        self.assertEqual(self._active(), ["csc-held"])
