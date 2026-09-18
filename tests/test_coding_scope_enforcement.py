"""Unit-scoped coding and reviewing eligibility (phase 4).

A coder assigned at or below the project's coding scope level codes inside
their own unit's subtree; one assigned above it codes only when the project
sets above_scope_coding_mode = 'code_any'. Projects without an organization
tree are untouched. Policy: docs/policy/organization-model.md.
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import org_grant_service as grants
from app.services import organization_service as org
from app.services import org_unit_routing_service as routing
from app.services.coder_workflow_service import get_pick_available_forms
from tests.base import BaseTestCase


class CodingScopeFixtureMixin:
    """A tree project (District > CHC > PHC > Sub-centre) with one form."""

    PROJECT = "CSC001"
    SITE = "CS01"
    FORM_ID = "CSC001CS0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="Coding Scope Project", project_nickname="CodingScope",
                project_status=VaStatuses.active, coding_intake_mode="pick_and_choose",
                project_registered_at=now, project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE, site_abbr=cls.SITE, site_name="Coding Scope Site",
                site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        if db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == cls.PROJECT,
            VaProjectSites.site_id == cls.SITE,
        )) is None:
            db.session.add(VaProjectSites(
                project_id=cls.PROJECT, site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="Coding Scope Project", project_nickname="CodingScope",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE, project_id=cls.PROJECT, site_name="Coding Scope Site",
                site_abbr=cls.SITE, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.PROJECT, site_id=cls.SITE,
                odk_form_id="CODING_SCOPE_FORM", odk_project_id="91",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid.like("csc-%")
        ))
        db.session.execute(sa.delete(VaSubmissions).where(
            VaSubmissions.va_form_id == self.FORM_ID
        ))
        db.session.execute(sa.delete(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.base_coder_user.user_id,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
        ))
        project = db.session.get(VaProjectMaster, self.PROJECT)
        project.coding_scope_level_id = None
        project.above_scope_coding_mode = "view_only"
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _tree(self):
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="D01", unit_name="District One")
        chc = org.create_unit(
            self.PROJECT, org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One")
        phc_a = org.create_unit(
            self.PROJECT, org_level_id=levels["phc"].org_level_id,
            parent_org_unit_id=chc.org_unit_id, unit_code="P01", unit_name="PHC One")
        phc_b = org.create_unit(
            self.PROJECT, org_level_id=levels["phc"].org_level_id,
            parent_org_unit_id=chc.org_unit_id, unit_code="P02", unit_name="PHC Two")
        db.session.commit()
        return levels, district, chc, phc_a, phc_b

    def _submission(self, sid, unit=None):
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="Collector",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English",
            va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
            org_unit_id=unit.org_unit_id if unit else None,
            org_unit_resolution=routing.RESOLUTION_FORM_FIELD if unit else None,
        )
        db.session.add(submission)
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state="ready_for_coding",
            workflow_reason="test_seed", workflow_updated_by_role="vasystem",
        ))
        db.session.commit()
        return submission

    def _grant(self, unit, role=VaAccessRoles.coder, cadre_code="MO"):
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        grant = VaUserAccessGrants(
            user_id=self.base_coder_user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id,
            cadre_id=cadres[cadre_code].cadre_id if role == VaAccessRoles.coder else None,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    def _set_scope(self, level, mode="view_only"):
        project = db.session.get(VaProjectMaster, self.PROJECT)
        project.coding_scope_level_id = level.org_level_id
        project.above_scope_coding_mode = mode
        db.session.commit()


class CodingScopeResolutionTests(CodingScopeFixtureMixin, BaseTestCase):
    """codeable_unit_ids applies the project's scope level and above-scope mode."""

    def test_without_a_scope_level_a_grant_covers_its_whole_subtree(self):
        _, district, chc, phc_a, phc_b = self._tree()
        self._grant(chc, cadre_code="SMO")
        units = grants.codeable_unit_ids(
            self.base_coder_user.user_id, VaAccessRoles.coder
        )
        self.assertEqual(
            units, {chc.org_unit_id, phc_a.org_unit_id, phc_b.org_unit_id}
        )
        self.assertNotIn(district.org_unit_id, units)

    def test_a_grant_at_the_scope_level_codes_its_own_subtree(self):
        levels, _, _, phc_a, _ = self._tree()
        self._grant(phc_a)
        self._set_scope(levels["phc"])
        units = grants.codeable_unit_ids(
            self.base_coder_user.user_id, VaAccessRoles.coder
        )
        self.assertEqual(units, {phc_a.org_unit_id})

    def test_a_grant_above_the_scope_level_codes_nothing_by_default(self):
        levels, _, chc, _, _ = self._tree()
        self._grant(chc, cadre_code="SMO")
        self._set_scope(levels["phc"])  # CHC is shallower than PHC
        self.assertEqual(
            grants.codeable_unit_ids(self.base_coder_user.user_id, VaAccessRoles.coder),
            set(),
        )

    def test_above_scope_code_any_restores_the_whole_subtree(self):
        levels, _, chc, phc_a, phc_b = self._tree()
        self._grant(chc, cadre_code="SMO")
        self._set_scope(levels["phc"], mode="code_any")
        self.assertEqual(
            grants.codeable_unit_ids(self.base_coder_user.user_id, VaAccessRoles.coder),
            {chc.org_unit_id, phc_a.org_unit_id, phc_b.org_unit_id},
        )

    def test_a_grant_below_the_scope_level_is_unaffected(self):
        levels, _, _, phc_a, _ = self._tree()
        subcentre = org.create_unit(
            self.PROJECT,
            org_level_id=levels["subcentre"].org_level_id,
            parent_org_unit_id=phc_a.org_unit_id,
            unit_code="S01", unit_name="Sub-centre One",
        )
        db.session.commit()
        self._grant(subcentre, cadre_code="CHO")
        self._set_scope(levels["phc"])
        self.assertEqual(
            grants.codeable_unit_ids(self.base_coder_user.user_id, VaAccessRoles.coder),
            {subcentre.org_unit_id},
        )


class PickListScopeTests(CodingScopeFixtureMixin, BaseTestCase):
    """The pick list offers only submissions inside the coder's units."""

    def _pick(self):
        forms = self.base_coder_user.get_coder_va_forms()
        return {
            row["va_sid"]
            for row in get_pick_available_forms(self.base_coder_user, list(forms))
        }

    def test_only_submissions_in_the_coders_subtree_are_offered(self):
        _, district, chc, phc_a, phc_b = self._tree()
        self._grant(phc_a)
        self._submission("csc-in-scope", unit=phc_a)
        self._submission("csc-sibling", unit=phc_b)
        self._submission("csc-above", unit=chc)
        self._submission("csc-unrouted")

        offered = self._pick()
        self.assertIn("csc-in-scope", offered)
        self.assertNotIn("csc-sibling", offered)
        self.assertNotIn("csc-above", offered)
        # An unrouted submission belongs to nobody until a DM routes it.
        self.assertNotIn("csc-unrouted", offered)

    def test_a_coder_with_no_unit_grant_is_offered_nothing_from_a_tree_project(self):
        _, _, _, phc_a, _ = self._tree()
        self._submission("csc-orphan", unit=phc_a)
        self.assertEqual(self._pick(), set())

    def test_the_scope_level_narrows_what_is_offered(self):
        levels, _, chc, phc_a, _ = self._tree()
        self._grant(chc, cadre_code="SMO")
        self._submission("csc-at-chc", unit=chc)
        self._submission("csc-at-phc", unit=phc_a)

        # No scope level: the whole subtree.
        self.assertEqual(self._pick(), {"csc-at-chc", "csc-at-phc"})

        # Scope at PHC with the default mode: a CHC grant codes nothing.
        self._set_scope(levels["phc"])
        self.assertEqual(self._pick(), set())

        # code_any hands the subtree back.
        self._set_scope(levels["phc"], mode="code_any")
        self.assertEqual(self._pick(), {"csc-at-chc", "csc-at-phc"})


class NonTreeProjectsAreUntouchedTests(BaseTestCase):
    """A project with no organization tree keeps the form-and-site model."""

    PROJECT = "CSN001"
    SITE = "CN01"
    FORM_ID = "CSN001CN0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="No Tree Project", project_nickname="NoTree",
                project_status=VaStatuses.active, coding_intake_mode="pick_and_choose",
                project_registered_at=now, project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE, site_abbr=cls.SITE, site_name="No Tree Site",
                site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        project_site = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == cls.PROJECT,
            VaProjectSites.site_id == cls.SITE,
        ))
        if project_site is None:
            project_site = VaProjectSites(
                project_id=cls.PROJECT, site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            )
            db.session.add(project_site)
            db.session.flush()
        cls.project_site_id = project_site.project_site_id
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="No Tree Project", project_nickname="NoTree",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE, project_id=cls.PROJECT, site_name="No Tree Site",
                site_abbr=cls.SITE, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.PROJECT, site_id=cls.SITE,
                odk_form_id="NO_TREE_FORM", odk_project_id="92",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    def test_a_project_site_coder_still_sees_its_unrouted_submissions(self):
        """The regression guard: no tree means no unit filtering, as before.

        Its submissions carry no org_unit_id at all, which in a tree project
        would make them unreachable. Here they must still be offered.
        """
        now = datetime.now(UTC)
        sid = "csn-no-tree"
        if db.session.get(VaSubmissions, sid) is None:
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="Collector",
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English",
                va_deceased_age=42, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state="ready_for_coding",
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))
        if db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.base_coder_user.user_id,
            VaUserAccessGrants.role == VaAccessRoles.coder,
            VaUserAccessGrants.project_site_id == self.project_site_id,
        )) is None:
            db.session.add(VaUserAccessGrants(
                user_id=self.base_coder_user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=self.project_site_id,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()

        forms = self.base_coder_user.get_coder_va_forms()
        self.assertIn(self.FORM_ID, forms)
        offered = {
            row["va_sid"]
            for row in get_pick_available_forms(self.base_coder_user, list(forms))
        }
        self.assertIn(sid, offered)


class SubmissionLevelGateTests(CodingScopeFixtureMixin, BaseTestCase):
    """Opening one submission directly is gated, not just the list."""

    def test_scope_check_accepts_only_submissions_in_the_coders_units(self):
        _, district, chc, phc_a, phc_b = self._tree()
        self._grant(phc_a)
        self._submission("csc-mine", unit=phc_a)
        self._submission("csc-theirs", unit=phc_b)
        self._submission("csc-nowhere")

        user = self.base_coder_user
        self.assertTrue(grants.submission_within_org_scope(
            user, "csc-mine", VaAccessRoles.coder))
        self.assertFalse(grants.submission_within_org_scope(
            user, "csc-theirs", VaAccessRoles.coder))
        self.assertFalse(grants.submission_within_org_scope(
            user, "csc-nowhere", VaAccessRoles.coder))
        self.assertFalse(grants.submission_within_org_scope(
            user, "csc-does-not-exist", VaAccessRoles.coder))

    def test_a_reviewer_grant_does_not_confer_coding_scope(self):
        _, _, _, phc_a, _ = self._tree()
        self._grant(phc_a, role=VaAccessRoles.reviewer)
        self._submission("csc-reviewable", unit=phc_a)

        user = self.base_coder_user
        self.assertTrue(grants.submission_within_org_scope(
            user, "csc-reviewable", VaAccessRoles.reviewer))
        self.assertFalse(grants.submission_within_org_scope(
            user, "csc-reviewable", VaAccessRoles.coder))

    def test_allocation_refuses_a_submission_outside_scope(self):
        from app.services.coder_workflow_service import (
            AllocationError,
            allocate_pick_form,
        )

        _, _, _, phc_a, phc_b = self._tree()
        self._grant(phc_a)
        self._submission("csc-outside", unit=phc_b)

        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(self.base_coder_user, "csc-outside")
        self.assertIn("outside your coding scope", str(ctx.exception))


class CodingScopeSettingsApiTests(CodingScopeFixtureMixin, BaseTestCase):
    """The admin API for the project's coding scope level and above-scope mode."""

    def _patch(self, body):
        return self.client.put(
            f"/admin/api/projects/{self.PROJECT}",
            json=body,
            headers=self._csrf_headers(),
        )

    def test_admin_sets_and_clears_the_scope_level(self):
        levels, _, _, _, _ = self._tree()
        self._login(str(self.base_admin_id))

        response = self._patch({
            "coding_scope_level_id": str(levels["phc"].org_level_id),
            "above_scope_coding_mode": "code_any",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        project = db.session.get(VaProjectMaster, self.PROJECT)
        db.session.refresh(project)
        self.assertEqual(project.coding_scope_level_id, levels["phc"].org_level_id)
        self.assertEqual(project.above_scope_coding_mode, "code_any")

        cleared = self._patch({"coding_scope_level_id": None})
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        db.session.refresh(project)
        self.assertIsNone(project.coding_scope_level_id)

    def test_a_level_from_another_project_is_refused(self):
        self._tree()
        other = "CSC002"
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, other) is None:
            db.session.add(VaProjectMaster(
                project_id=other, project_code=other, project_name="Other",
                project_nickname="Other", project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.commit()
        org.seed_default_organization(other)
        db.session.commit()
        foreign = {lv.level_code: lv for lv in org.list_levels(other)}["phc"]

        self._login(str(self.base_admin_id))
        response = self._patch({"coding_scope_level_id": str(foreign.org_level_id)})
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found in this project", response.get_json()["error"])

    def test_an_invalid_above_scope_mode_is_refused(self):
        self._login(str(self.base_admin_id))
        response = self._patch({"above_scope_coding_mode": "whatever"})
        self.assertEqual(response.status_code, 400)

    def test_a_scope_level_requires_pick_and_choose_intake(self):
        levels, _, _, _, _ = self._tree()
        self._login(str(self.base_admin_id))
        response = self._patch({
            "coding_scope_level_id": str(levels["phc"].org_level_id),
            "coding_intake_mode": "random_form_allocation",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("pick-and-choose", response.get_json()["error"])

        # And the rule holds when the intake mode is switched afterwards.
        self.assertEqual(
            self._patch({
                "coding_scope_level_id": str(levels["phc"].org_level_id)
            }).status_code,
            200,
        )
        later = self._patch({"coding_intake_mode": "random_form_allocation"})
        self.assertEqual(later.status_code, 400)
        self.assertIn("pick-and-choose", later.get_json()["error"])


class ProjectUpdateIsAllOrNothingTests(CodingScopeFixtureMixin, BaseTestCase):
    """A rejected project update leaves no field changed.

    Validation runs before any assignment, so an error cannot leave the
    rejected values on the ORM object for a later flush to persist.
    """

    def _put(self, body):
        return self.client.put(
            f"/admin/api/projects/{self.PROJECT}",
            json=body,
            headers=self._csrf_headers(),
        )

    def test_a_rejected_field_discards_the_valid_fields_sent_with_it(self):
        self._login(str(self.base_admin_id))
        project = db.session.get(VaProjectMaster, self.PROJECT)
        original_name = project.project_name

        response = self._put({
            "project_name": "Renamed by a request that should fail",
            "coding_intake_mode": "nonsense",
        })
        self.assertEqual(response.status_code, 400)

        db.session.expire_all()
        project = db.session.get(VaProjectMaster, self.PROJECT)
        self.assertEqual(project.project_name, original_name)

    def test_a_rejected_scope_combination_discards_the_whole_request(self):
        levels, _, _, _, _ = self._tree()
        self._login(str(self.base_admin_id))
        project = db.session.get(VaProjectMaster, self.PROJECT)
        self.assertEqual(project.coding_intake_mode, "pick_and_choose")

        response = self._put({
            "coding_scope_level_id": str(levels["phc"].org_level_id),
            "coding_intake_mode": "random_form_allocation",
            "narrative_qa_enabled": True,
        })
        self.assertEqual(response.status_code, 400)

        db.session.expire_all()
        project = db.session.get(VaProjectMaster, self.PROJECT)
        self.assertIsNone(project.coding_scope_level_id)
        self.assertEqual(project.coding_intake_mode, "pick_and_choose")
        self.assertFalse(project.narrative_qa_enabled)

    def test_a_valid_update_still_applies_every_field(self):
        levels, _, _, _, _ = self._tree()
        self._login(str(self.base_admin_id))
        response = self._put({
            "project_nickname": "ScopedProject",
            "coding_scope_level_id": str(levels["phc"].org_level_id),
            "above_scope_coding_mode": "code_any",
        })
        self.assertEqual(response.status_code, 200, response.get_json())

        db.session.expire_all()
        project = db.session.get(VaProjectMaster, self.PROJECT)
        self.assertEqual(project.project_nickname, "ScopedProject")
        self.assertEqual(project.coding_scope_level_id, levels["phc"].org_level_id)
        self.assertEqual(project.above_scope_coding_mode, "code_any")


class AreaOverviewTests(CodingScopeFixtureMixin, BaseTestCase):
    """A grant above the coding scope level oversees its subtree read-only."""

    def _login_coder(self):
        self._login(str(self.base_coder_user.user_id))

    def test_a_view_only_grant_sees_its_subtree_but_codes_nothing(self):
        levels, _, chc, phc_a, phc_b = self._tree()
        self._grant(chc, cadre_code="SMO")
        self._set_scope(levels["phc"])  # the CHC grant is above the scope level
        self._submission("csc-area-chc", unit=chc)
        self._submission("csc-area-phc", unit=phc_a)

        user = self.base_coder_user
        self.assertEqual(
            grants.codeable_unit_ids(user.user_id, VaAccessRoles.coder), set()
        )
        self.assertEqual(
            grants.viewable_unit_ids(user.user_id, VaAccessRoles.coder),
            {chc.org_unit_id, phc_a.org_unit_id, phc_b.org_unit_id},
        )
        self.assertTrue(grants.has_view_only_scope(user.user_id, VaAccessRoles.coder))

        self._login_coder()
        response = self.client.get("/coding/area")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("csc-area-chc", body)
        self.assertIn("csc-area-phc", body)
        self.assertIn("view only", body)

    def test_the_view_page_opens_inside_the_area_and_is_refused_outside(self):
        levels, _, chc, phc_a, phc_b = self._tree()
        self._grant(phc_a)
        self._set_scope(levels["phc"])
        self._submission("csc-area-mine", unit=phc_a)
        self._submission("csc-area-theirs", unit=phc_b)

        self._login_coder()
        allowed = self.client.get("/coding/area/csc-area-mine")
        self.assertEqual(allowed.status_code, 200)

        refused = self.client.get("/coding/area/csc-area-theirs")
        self.assertIn(refused.status_code, (302, 403))

    def test_viewing_does_not_make_a_submission_codeable(self):
        from app.services.coder_workflow_service import (
            AllocationError,
            allocate_pick_form,
        )

        levels, _, chc, phc_a, _ = self._tree()
        self._grant(chc, cadre_code="SMO")
        self._set_scope(levels["phc"])
        self._submission("csc-area-look-only", unit=phc_a)

        user = self.base_coder_user
        # Visible…
        self.assertTrue(grants.submission_within_org_view_scope(
            user, "csc-area-look-only", VaAccessRoles.coder))
        # …but not codeable, and allocation refuses it.
        self.assertFalse(grants.submission_within_org_scope(
            user, "csc-area-look-only", VaAccessRoles.coder))
        with self.assertRaises(AllocationError):
            allocate_pick_form(user, "csc-area-look-only")

        # And it is still absent from the pick list.
        from app.services.coder_workflow_service import get_pick_available_forms

        forms = user.get_coder_va_forms()
        offered = {
            row["va_sid"]
            for row in get_pick_available_forms(user, list(forms))
        }
        self.assertNotIn("csc-area-look-only", offered)

    def test_a_coder_inside_the_scope_sees_the_same_page_with_coding_allowed(self):
        levels, _, _, phc_a, _ = self._tree()
        self._grant(phc_a)
        self._set_scope(levels["phc"])
        self._submission("csc-area-codeable", unit=phc_a)

        user = self.base_coder_user
        self.assertFalse(grants.has_view_only_scope(user.user_id, VaAccessRoles.coder))

        self._login_coder()
        response = self.client.get("/coding/area")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csc-area-codeable", response.get_data(as_text=True))

    def test_a_user_with_no_unit_grant_gets_an_empty_area(self):
        """An admin holds no unit grant, so the area is empty rather than open."""
        self._tree()
        self._submission("csc-area-none", unit=None)
        self._login(str(self.base_admin_id))
        response = self.client.get("/coding/area")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("no area to show", body)
        self.assertNotIn("csc-area-none", body)
