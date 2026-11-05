"""The interviewer's name (``va_data_collector``) is staff identity: shown only
where the viewer has a PII grant (digitva-ssg7.11; docs/policy/access-control-model.md).
Pick list, coding allocation and the reviewer queue/history/dashboard."""
import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import reviewer_dashboard_service as reviewer
from app.services.coder_workflow_service import get_pick_available_forms, get_pick_available_page
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


class CollectorRedactionTests(CodingScopeFixtureMixin, BaseTestCase):

    def _unit(self):
        if not hasattr(self, "_phc"):
            self._phc = self._tree()[3]
        return self._phc

    def _tier3(self, role=VaAccessRoles.coder):
        unit = self._unit()
        self._grant(unit, role=role)
        return unit

    def _non_pii(self, role=VaAccessRoles.coder, scope=VaAccessScopeTypes.project):
        """A grant above the unit level on the tree project (Tier 1 / Tier 2)."""
        self._unit()
        kwargs = {"project_id": self.PROJECT}
        if scope == VaAccessScopeTypes.project_site:
            kwargs = {"project_site_id": db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE))}
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id, role=role, scope_type=scope,
            grant_status=VaStatuses.active, **kwargs))
        db.session.commit()

    def _collectors(self):
        user = self.base_coder_user
        forms = list(user.get_coder_va_forms())
        listed = get_pick_available_forms(user, forms)
        paged, _ = get_pick_available_page(user, forms, limit=10, offset=0)
        return [r["va_data_collector"] for r in listed], [r["va_data_collector"] for r in paged]

    def test_tier3_coder_sees_the_collector(self):
        unit = self._tier3()
        self._submission("csc-c1", unit=unit)
        self.assertEqual(self._collectors(), (["Collector"], ["Collector"]))

    def test_tier2_coder_gets_null_collector(self):
        unit = self._unit()
        self._submission("csc-c1", unit=unit)
        self._non_pii(scope=VaAccessScopeTypes.project_site)
        listed, paged = self._collectors()
        self.assertEqual((len(listed), len(paged)), (1, 1))  # present, then redacted
        self.assertEqual((listed, paged), ([None], [None]))

    def test_project_scope_coder_gets_null_collector(self):
        unit = self._unit()
        self._submission("csc-c1", unit=unit)
        self._non_pii()
        listed, paged = self._collectors()
        self.assertEqual((len(listed), len(paged)), (1, 1))
        self.assertEqual((listed, paged), ([None], [None]))

    def test_allocation_endpoint(self):
        unit = self._tier3()
        self._submission("csc-c1", unit=unit)
        self._hold("csc-c1")
        self._login(str(self.base_coder_user.user_id))
        body = self.client.get("/api/v1/coding/allocation").get_json()
        self.assertEqual(body["allocation"]["va_data_collector"], "Collector")
        db.session.execute(sa.delete(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.base_coder_user.user_id,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit))
        db.session.commit()
        self._non_pii()
        body = self.client.get("/api/v1/coding/allocation").get_json()
        self.assertEqual(body["allocation"]["va_sid"], "csc-c1")
        self.assertIsNone(body["allocation"]["va_data_collector"])

    def _hold(self, sid):
        import uuid
        from app.models import VaAllocation, VaAllocations
        db.session.add(VaAllocations(
            va_allocation_id=uuid.uuid4(), va_sid=sid, va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active))
        db.session.commit()

    def _reviewer_rows(self):
        user = self.base_coder_user
        avail, _ = reviewer.list_available(user, limit=50, offset=0)
        dash = reviewer.list_dashboard_forms(user)
        return avail, dash

    def test_reviewer_queue_and_dashboard(self):
        from app.models import VaSubmissionWorkflow
        unit = self._tier3(role=VaAccessRoles.reviewer)
        self._submission("csc-r1", unit=unit)
        db.session.execute(sa.update(VaSubmissionWorkflow).values(workflow_state="reviewer_eligible"))
        db.session.commit()
        avail, dash = self._reviewer_rows()
        self.assertEqual([r["va_data_collector"] for r in avail], ["Collector"])
        self.assertEqual([r["va_data_collector"] for r in dash], ["Collector"])
        db.session.execute(sa.delete(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.base_coder_user.user_id,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit))
        db.session.commit()
        self._non_pii(role=VaAccessRoles.reviewer)
        avail, dash = self._reviewer_rows()
        self.assertEqual([r["va_sid"] for r in avail], ["csc-r1"])
        self.assertEqual([r["va_data_collector"] for r in avail], [None])
        self.assertEqual([r["va_data_collector"] for r in dash], [None])
