"""Per-unit coding gates: resolution, exclusion, and the on-screen reason.

Rules under test: ``app.services.org_grant_service.resolve_unit_coding_gates``
(inheritance) and ``app.services.coder_workflow_service``
(``_get_excluded_org_units_for_coding`` / ``_get_site_coding_error``), which
compose the unit gate with the existing site gate. Design record:
.tasks/org-per-unit-coding-gates.md. Policy:
docs/policy/organization-model.md ("Per-unit coding gates").
"""
import uuid
from datetime import UTC, datetime, timedelta

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
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services import org_grant_service as og
from app.services import organization_service as org
from app.services.coder_workflow_service import (
    AllocationError,
    _get_excluded_org_units_for_coding,
    _get_site_coding_error,
    allocate_random_form,
)
from app.services.workflow.definition import WORKFLOW_READY_FOR_CODING
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase

_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class OrgUnitCodingGateTests(BaseTestCase):
    PROJECT = f"UG{_RUN_SUFFIX}"
    SITE = f"S{_RUN_SUFFIX[:3]}"
    FORM_ID = f"F{_RUN_SUFFIX}00001"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)

        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Unit Gate Project",
                project_nickname="UnitGate",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Unit Gate Project",
                project_nickname="UnitGate",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE,
                site_name="Unit Gate Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=cls.SITE,
                project_id=cls.PROJECT,
                site_name="Unit Gate Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
                coding_enabled=True,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                odk_form_id="TEST_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.flush()

        # District D01 > CHC C01 > PHC P01 > Sub-centre S01, plus sibling CHC C02.
        org.seed_default_organization(cls.PROJECT)
        lv = {level.level_code: level for level in org.list_levels(cls.PROJECT)}
        district = org.create_unit(
            cls.PROJECT, org_level_id=lv["district"].org_level_id,
            unit_code="D01", unit_name="District One",
        )
        cls.chc = org.create_unit(
            cls.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="Yelahanka CHC",
        )
        cls.phc = org.create_unit(
            cls.PROJECT, org_level_id=lv["phc"].org_level_id,
            parent_org_unit_id=cls.chc.org_unit_id, unit_code="P01", unit_name="Yelahanka PHC",
        )
        cls.subcentre = org.create_unit(
            cls.PROJECT, org_level_id=lv["subcentre"].org_level_id,
            parent_org_unit_id=cls.phc.org_unit_id, unit_code="S01", unit_name="Yelahanka Sub-centre",
        )
        cls.sibling_chc = org.create_unit(
            cls.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C02", unit_name="Sibling CHC",
        )

        cls.coder_user = cls._get_or_make_user(
            f"unitgate.coder{_RUN_SUFFIX.lower()}@test.local", "UnitGateCoder123"
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.coder_user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=district.org_unit_id,
                notes="unit gate test coder grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def _submission(self, sid: str, *, org_unit_id=None, form_id=None) -> VaSubmissions:
        sub = VaSubmissions(
            va_sid=sid,
            va_form_id=form_id or self.FORM_ID,
            va_submission_date=datetime.now(UTC),
            va_odk_updatedat=datetime.now(UTC),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=sid,
            va_uniqueid_real=None,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
            org_unit_id=org_unit_id,
            org_unit_resolution="manual" if org_unit_id else None,
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def _allocation_today(self, sid: str, user_id) -> None:
        db.session.add(
            VaAllocations(
                va_allocation_id=uuid.uuid4(),
                va_sid=sid,
                va_allocated_to=user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
                va_allocation_createdat=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        db.session.flush()

    # -- resolve_unit_coding_gates: inheritance -----------------------------

    def test_nearest_gated_ancestor_wins(self):
        org.set_unit_coding_gate(self.PROJECT, self.chc.org_unit_id, coding_enabled=False)
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=True)
        db.session.commit()

        gates = og.resolve_unit_coding_gates(
            {self.chc.org_unit_id, self.phc.org_unit_id, self.subcentre.org_unit_id, self.sibling_chc.org_unit_id}
        )

        # CHC resolves to its own gate.
        self.assertEqual(gates[self.chc.org_unit_id].org_unit_id, self.chc.org_unit_id)
        # PHC's own gate overrides the inherited CHC gate.
        self.assertEqual(gates[self.phc.org_unit_id].org_unit_id, self.phc.org_unit_id)
        self.assertTrue(gates[self.phc.org_unit_id].coding_enabled)
        # Sub-centre has no gate of its own: nearest gated ancestor is PHC, not CHC.
        self.assertEqual(gates[self.subcentre.org_unit_id].org_unit_id, self.phc.org_unit_id)
        # A unit with no gated ancestor at all is simply absent -- not closed.
        self.assertNotIn(self.sibling_chc.org_unit_id, gates)

    # -- _get_excluded_org_units_for_coding ----------------------------------

    def test_closed_unit_excluded_while_sibling_stays_open(self):
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=False)
        db.session.commit()

        self._submission("uuid:closed-unit", org_unit_id=self.phc.org_unit_id)
        self._submission("uuid:open-sibling", org_unit_id=self.sibling_chc.org_unit_id)
        db.session.commit()

        excluded = _get_excluded_org_units_for_coding([self.FORM_ID], self.coder_user)

        self.assertIn(self.phc.org_unit_id, excluded)
        self.assertNotIn(self.sibling_chc.org_unit_id, excluded)

    def test_unit_gate_cannot_open_a_site_the_project_has_closed(self):
        ps = db.session.scalar(
            db.select(VaProjectSites).where(
                VaProjectSites.project_id == self.PROJECT, VaProjectSites.site_id == self.SITE
            )
        )
        ps.coding_enabled = False
        sub = self._submission("uuid:site-closed-unit-open", org_unit_id=self.phc.org_unit_id)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_READY_FOR_CODING)
        # The unit gate is wide open -- it must not override the closed site.
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=True)
        db.session.commit()

        try:
            with self.assertRaises(AllocationError):
                allocate_random_form(self.coder_user, project_id=self.PROJECT)
        finally:
            ps.coding_enabled = True
            db.session.commit()

    def test_daily_limit_counted_once_across_gated_subtree(self):
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=True, daily_coder_limit=1)
        db.session.commit()

        sub_phc = self._submission("uuid:phc-allocated-today", org_unit_id=self.phc.org_unit_id)
        self._submission("uuid:subcentre-candidate", org_unit_id=self.subcentre.org_unit_id)
        db.session.commit()
        # One allocation already made today against a PHC-level submission.
        self._allocation_today(sub_phc.va_sid, self.coder_user.user_id)
        db.session.commit()

        excluded = _get_excluded_org_units_for_coding([self.FORM_ID], self.coder_user)

        # The sub-centre submission shares the PHC gate's ceiling -- the same
        # count blocks it too, without a separate per-unit counter.
        self.assertIn(self.subcentre.org_unit_id, excluded)

    def test_project_with_no_org_tree_is_unaffected(self):
        no_tree_project = f"NT{_RUN_SUFFIX}"
        no_tree_form = f"NF{_RUN_SUFFIX}0001"
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=no_tree_project,
                project_code=no_tree_project,
                project_name="No Tree Project",
                project_nickname="NoTree",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=no_tree_project,
                project_code=no_tree_project,
                project_name="No Tree Project",
                project_nickname="NoTree",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        # Flush the two project rows before adding anything that references
        # them. SQLAlchemy normally orders inserts by table dependency, but
        # this metadata has a table-sort cycle (it warns about
        # mas_org_level/va_project_master), and when it cannot sort it falls
        # back to insertion order -- so va_forms was being INSERTed before
        # va_research_projects and failing fk_va_forms_project_id.
        db.session.flush()
        # va_sites.site_id is a bare primary key (not composite with
        # project_id) -- the row registered for cls.SITE in setUpClass
        # already satisfies va_forms.site_id's FK here; inserting a second
        # VaSites row for the same site_id would violate that PK.
        db.session.add(
            VaProjectSites(
                project_id=no_tree_project,
                site_id=self.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
                coding_enabled=True,
            )
        )
        db.session.add(
            VaForms(
                form_id=no_tree_form,
                project_id=no_tree_project,
                site_id=self.SITE,
                odk_form_id="TEST_FORM_NT",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.flush()
        # Attach the submission to the no-tree project's own form. Passing
        # form_id matters: the helper defaults to cls.FORM_ID, which belongs to
        # the project that DOES have a tree, so a submission created without it
        # would leave no_tree_form with no rows at all and the assertion below
        # would hold for the wrong reason.
        self._submission("uuid:no-tree-submission", form_id=no_tree_form)
        # A live gate elsewhere in the fixture. Without this the assertion
        # cannot distinguish "gates correctly skipped this project" from
        # "gates are not running at all".
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=False)
        self._submission("uuid:no-tree-control", org_unit_id=self.phc.org_unit_id)
        db.session.commit()

        # Positive control: the gate is in force for the project that has a tree.
        self.assertEqual(
            _get_excluded_org_units_for_coding([self.FORM_ID], self.coder_user),
            {self.phc.org_unit_id},
        )
        # The no-tree project's form is untouched by it.
        self.assertEqual(_get_excluded_org_units_for_coding([no_tree_form], self.coder_user), set())

    # -- waivers --------------------------------------------------------------

    def test_coding_tester_waives_unit_gate(self):
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=False)
        tester = self._get_or_make_user(
            f"unitgate.tester{_RUN_SUFFIX.lower()}@test.local", "UnitGateTester123"
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=tester.user_id,
                role=VaAccessRoles.coding_tester,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                notes="unit gate test tester grant",
                grant_status=VaStatuses.active,
            )
        )
        self._submission("uuid:tester-waived-unit", org_unit_id=self.phc.org_unit_id)
        db.session.commit()

        excluded = _get_excluded_org_units_for_coding([self.FORM_ID], tester)

        self.assertEqual(excluded, set())

    def test_project_pi_waives_unit_gate(self):
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=False)
        pi_user = self._get_or_make_user(
            f"unitgate.pi{_RUN_SUFFIX.lower()}@test.local", "UnitGatePi123"
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=pi_user.user_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                notes="unit gate test pi grant",
                grant_status=VaStatuses.active,
            )
        )
        self._submission("uuid:pi-waived-unit", org_unit_id=self.phc.org_unit_id)
        db.session.commit()

        excluded = _get_excluded_org_units_for_coding([self.FORM_ID], pi_user)

        self.assertEqual(excluded, set())

    # -- on-screen reason names the unit --------------------------------------

    def test_site_coding_error_names_the_unit(self):
        org.set_unit_coding_gate(self.PROJECT, self.phc.org_unit_id, coding_enabled=False)
        db.session.commit()

        message = _get_site_coding_error(
            self.PROJECT, self.SITE, self.coder_user, org_unit_id=self.phc.org_unit_id
        )

        self.assertEqual(message, "Coding is currently disabled for Yelahanka PHC.")

    def test_site_coding_error_falls_back_to_site_reason_without_a_unit_gate(self):
        # No unit gate anywhere: the site's own reason is unaffected by the
        # optional org_unit_id parameter.
        message = _get_site_coding_error(
            self.PROJECT, self.SITE, self.coder_user, org_unit_id=self.sibling_chc.org_unit_id
        )

        self.assertEqual(message, "Coding is not available for this site.")
