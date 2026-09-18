"""Routing a submission to an organization unit.

Rules live in app/services/org_unit_routing_service.py; policy in
docs/policy/organization-model.md. Covers the deepest-code-wins rule, the
mapping fallback, idempotence, the manual pin outranking sync, and the data
manager's unrouted queue.
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
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
    VaUserAccessGrants,
)
from app.services import org_unit_routing_service as routing
from app.services import organization_service as org
from tests.base import BaseTestCase


class OrgUnitRoutingFixtureMixin:
    """One project with a site, a form and a tree, shared by both test classes."""

    PROJECT = "ORT001"
    SITE = "OT01"
    FORM_ID = "ORT001OT0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=cls.PROJECT,
                    project_code=cls.PROJECT,
                    project_name="Routing Project",
                    project_nickname="Routing",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(
                VaSiteMaster(
                    site_id=cls.SITE,
                    site_abbr=cls.SITE,
                    site_name="Routing Site",
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
        db.session.flush()
        if db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.PROJECT,
                VaProjectSites.site_id == cls.SITE,
            )
        ) is None:
            db.session.add(
                VaProjectSites(
                    project_id=cls.PROJECT,
                    site_id=cls.SITE,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                )
            )
        # va_forms still points at the legacy project/site registry.
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(
                VaResearchProjects(
                    project_id=cls.PROJECT,
                    project_code=cls.PROJECT,
                    project_name="Routing Research Project",
                    project_nickname="RoutingResearch",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(
                VaSites(
                    site_id=cls.SITE,
                    project_id=cls.PROJECT,
                    site_name="Routing Site",
                    site_abbr=cls.SITE,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.PROJECT,
                    site_id=cls.SITE,
                    odk_form_id="ROUTING_FORM",
                    odk_project_id="77",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(
            sa.delete(VaSubmissions).where(VaSubmissions.va_form_id == self.FORM_ID)
        )
        db.session.execute(
            sa.delete(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == self.PROJECT
            )
        )
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _tree(self):
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="D01", unit_name="District One",
        )
        chc = org.create_unit(
            self.PROJECT, org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One",
        )
        phc = org.create_unit(
            self.PROJECT, org_level_id=levels["phc"].org_level_id,
            parent_org_unit_id=chc.org_unit_id, unit_code="P01", unit_name="PHC One",
        )
        db.session.commit()
        return district, chc, phc

    def _mapping(self, org_unit_id=None):
        mapping = MapProjectSiteOdk(
            project_id=self.PROJECT,
            site_id=self.SITE,
            odk_project_id=77,
            odk_form_id="ROUTING_FORM",
            org_unit_id=org_unit_id,
        )
        db.session.add(mapping)
        db.session.commit()
        return mapping

    def _submission(self, sid="routing-sid-1"):
        now = datetime.now(UTC)
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="routing test",
            va_instance_name=sid,
            va_uniqueid_real=sid,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=40,
            va_deceased_gender="male",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.commit()
        return submission

    def _context(self, fallback=None):
        return routing.RoutingContext(self.PROJECT, fallback_org_unit_id=fallback)


class OrgUnitRoutingTests(OrgUnitRoutingFixtureMixin, BaseTestCase):
    """Resolution rules, applying them to a submission, and the constraints."""

    # -- resolution --------------------------------------------------------

    def test_deepest_answered_code_wins(self):
        _, chc, phc = self._tree()
        context = self._context()
        outcome = routing.resolve_org_unit_from_payload(
            context,
            {"org_district_code": "D01", "org_chc_code": "C01", "org_phc_code": "P01"},
        )
        self.assertEqual(outcome.org_unit_id, phc.org_unit_id)
        self.assertEqual(outcome.resolution, routing.RESOLUTION_FORM_FIELD)
        self.assertEqual(outcome.level_code, "phc")

        # Blank deeper answers fall through to the deepest answered one.
        outcome = routing.resolve_org_unit_from_payload(
            context,
            {"org_district_code": "D01", "org_chc_code": "C01", "org_phc_code": "  "},
        )
        self.assertEqual(outcome.org_unit_id, chc.org_unit_id)
        self.assertEqual(outcome.level_code, "chc")

    def test_codes_are_case_insensitive_and_group_paths_are_tolerated(self):
        _, _, phc = self._tree()
        context = self._context()
        outcome = routing.resolve_org_unit_from_payload(context, {"org_phc_code": "p01"})
        self.assertEqual(outcome.org_unit_id, phc.org_unit_id)

        outcome = routing.resolve_org_unit_from_payload(
            context, {"consent_group/org_unit_group/org_phc_code": "P01"}
        )
        self.assertEqual(outcome.org_unit_id, phc.org_unit_id)

    def test_unknown_inactive_and_wrong_level_codes_do_not_route(self):
        _, chc, phc = self._tree()
        context = self._context()

        outcome = routing.resolve_org_unit_from_payload(context, {"org_phc_code": "NOPE"})
        self.assertFalse(outcome.routed)
        self.assertEqual(outcome.unmatched_code, "NOPE")
        self.assertEqual(outcome.level_code, "phc")

        # A real code in the wrong level's field is not trusted.
        outcome = routing.resolve_org_unit_from_payload(context, {"org_phc_code": "C01"})
        self.assertFalse(outcome.routed)

        # Deactivating the PHC removes it from routing; the CHC code still works.
        org.set_unit_active(self.PROJECT, phc.org_unit_id, False)
        db.session.commit()
        outcome = routing.resolve_org_unit_from_payload(
            self._context(), {"org_phc_code": "P01", "org_chc_code": "C01"}
        )
        self.assertEqual(outcome.org_unit_id, chc.org_unit_id)

    def test_a_project_without_a_tree_is_left_alone(self):
        context = self._context()
        self.assertFalse(context.has_tree)
        outcome = routing.resolve_submission_org_unit(context, {"org_phc_code": "P01"})
        self.assertFalse(outcome.routed)
        self.assertIsNone(outcome.resolution)

    def test_fallback_unit_is_used_only_when_the_payload_resolves_nothing(self):
        district, _, phc = self._tree()
        context = self._context(fallback=district.org_unit_id)

        outcome = routing.resolve_submission_org_unit(context, {"org_phc_code": "P01"})
        self.assertEqual(outcome.org_unit_id, phc.org_unit_id)
        self.assertEqual(outcome.resolution, routing.RESOLUTION_FORM_FIELD)

        outcome = routing.resolve_submission_org_unit(context, {"Id10019": "male"})
        self.assertEqual(outcome.org_unit_id, district.org_unit_id)
        self.assertEqual(outcome.resolution, routing.RESOLUTION_MAPPING_FALLBACK)

        # An inactive fallback is no fallback.
        org.set_unit_active(self.PROJECT, district.org_unit_id, False)
        db.session.commit()
        outcome = routing.resolve_submission_org_unit(
            self._context(fallback=district.org_unit_id), {}
        )
        self.assertFalse(outcome.routed)

    def test_fallback_from_another_project_is_refused(self):
        self._tree()
        other = "ORT002"
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, other) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=other, project_code=other, project_name="Other",
                    project_nickname="Other", project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                )
            )
            db.session.commit()
        org.seed_default_organization(other)
        other_levels = {lv.level_code: lv for lv in org.list_levels(other)}
        foreign = org.create_unit(
            other, org_level_id=other_levels["district"].org_level_id,
            unit_code="X01", unit_name="Foreign District",
        )
        db.session.commit()
        outcome = routing.resolve_submission_org_unit(
            self._context(fallback=foreign.org_unit_id), {}
        )
        self.assertFalse(outcome.routed)

    # -- applying to a submission ------------------------------------------

    def test_routing_is_idempotent_and_reports_changes(self):
        _, _, phc = self._tree()
        submission = self._submission()
        context = self._context()
        payload = {"org_phc_code": "P01"}

        outcome = routing.resolve_submission_org_unit(context, payload)
        self.assertTrue(routing.apply_routing(submission, outcome))
        db.session.commit()
        self.assertEqual(submission.org_unit_id, phc.org_unit_id)

        # Re-running the same payload changes nothing.
        self.assertFalse(routing.apply_routing(submission, outcome))

    def test_a_manual_pin_survives_later_routing(self):
        district, chc, phc = self._tree()
        submission = self._submission()
        context = self._context()

        routing.route_submission(submission, context=context, payload={"org_phc_code": "P01"})
        db.session.commit()
        self.assertEqual(submission.org_unit_id, phc.org_unit_id)

        routing.pin_submission_org_unit(
            submission,
            chc.org_unit_id,
            actor_user_id=self.base_admin_user.user_id,
            project_id=self.PROJECT,
        )
        db.session.commit()
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_MANUAL)
        self.assertIsNotNone(submission.org_unit_pinned_at)

        # A later sync with a different payload must not move it.
        routing.route_submission(
            submission, context=context, payload={"org_district_code": "D01"}
        )
        db.session.commit()
        self.assertEqual(submission.org_unit_id, chc.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_MANUAL)

        # Clearing the pin lets routing take over again.
        routing.clear_pin(submission)
        db.session.commit()
        routing.route_submission(submission, context=context, payload={"org_district_code": "D01"})
        db.session.commit()
        self.assertEqual(submission.org_unit_id, district.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_FORM_FIELD)

    def test_pinning_rejects_a_unit_outside_the_project(self):
        self._tree()
        submission = self._submission()
        with self.assertRaises(org.OrganizationError):
            routing.pin_submission_org_unit(
                submission,
                "not-a-uuid",
                actor_user_id=self.base_admin_user.user_id,
                project_id=self.PROJECT,
            )

    def test_context_caches_levels_and_unit_codes(self):
        self._tree()
        context = self._context()
        payload = {"org_phc_code": "P01"}
        routing.resolve_org_unit_from_payload(context, payload)

        # A second resolution issues no further unit query: the cache answers.
        statements = []
        def record(conn, cursor, statement, parameters, ctx, executemany):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            routing.resolve_org_unit_from_payload(context, payload)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(statements, [])

    def test_mapping_supplies_the_fallback_through_context_for_form(self):
        district, _, _ = self._tree()
        self._mapping(org_unit_id=district.org_unit_id)
        form = db.session.get(VaForms, self.FORM_ID)
        context = routing.context_for_form(form)
        self.assertTrue(context.has_tree)
        self.assertEqual(context.fallback_org_unit_id, district.org_unit_id)
        outcome = routing.resolve_submission_org_unit(context, {})
        self.assertEqual(outcome.org_unit_id, district.org_unit_id)

    # -- database constraints ----------------------------------------------

    def test_database_rejects_a_unit_without_a_resolution(self):
        _, _, phc = self._tree()
        submission = self._submission()
        submission.org_unit_id = phc.org_unit_id
        submission.org_unit_resolution = None
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_database_rejects_pin_metadata_without_a_manual_resolution(self):
        _, _, phc = self._tree()
        submission = self._submission()
        submission.org_unit_id = phc.org_unit_id
        submission.org_unit_resolution = routing.RESOLUTION_FORM_FIELD
        submission.org_unit_pinned_by = self.base_admin_user.user_id
        submission.org_unit_pinned_at = datetime.now(UTC)
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_database_rejects_an_unknown_resolution_value(self):
        _, _, phc = self._tree()
        submission = self._submission()
        submission.org_unit_id = phc.org_unit_id
        submission.org_unit_resolution = "guessed"
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()


class UnroutedQueueApiTests(OrgUnitRoutingFixtureMixin, BaseTestCase):
    """The data manager's unrouted queue and manual pin endpoint."""

    def _grant_dm(self):
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == self.base_coder_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.data_manager,
                VaUserAccessGrants.project_id == self.PROJECT,
            )
        )
        if existing is None:
            db.session.add(
                VaUserAccessGrants(
                    user_id=self.base_coder_user.user_id,
                    role=VaAccessRoles.data_manager,
                    scope_type=VaAccessScopeTypes.project,
                    project_id=self.PROJECT,
                    grant_status=VaStatuses.active,
                )
            )
            db.session.commit()

    def test_queue_lists_unrouted_and_fallback_submissions(self):
        district, _, _ = self._tree()
        self._grant_dm()
        unrouted = self._submission("queue-unrouted")
        fallback = self._submission("queue-fallback")
        routing.apply_routing(
            fallback,
            routing.RoutingOutcome(
                org_unit_id=district.org_unit_id,
                resolution=routing.RESOLUTION_MAPPING_FALLBACK,
            ),
        )
        routed = self._submission("queue-routed")
        routing.route_submission(
            routed, context=self._context(), payload={"org_district_code": "D01"}
        )
        db.session.commit()

        self._login(str(self.base_coder_user.user_id))
        response = self.client.get(
            f"/api/v1/data-management/submissions/unrouted?project={self.PROJECT}"
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        sids = {row["va_sid"] for row in response.get_json()["submissions"]}
        self.assertIn("queue-unrouted", sids)
        self.assertIn("queue-fallback", sids)
        self.assertNotIn("queue-routed", sids)

        only_unrouted = self.client.get(
            f"/api/v1/data-management/submissions/unrouted?project={self.PROJECT}&include=unrouted"
        )
        sids = {row["va_sid"] for row in only_unrouted.get_json()["submissions"]}
        self.assertEqual(sids, {"queue-unrouted"})

    def test_queue_excludes_submissions_outside_the_managers_scope(self):
        self._tree()
        self._submission("queue-out-of-scope")
        db.session.commit()
        # base_coder_user holds no data_manager grant on this project here.
        self._login(str(self.base_coder_user.user_id))
        response = self.client.get("/api/v1/data-management/submissions/unrouted")
        self.assertIn(response.status_code, (200, 403))
        if response.status_code == 200:
            sids = {row["va_sid"] for row in response.get_json()["submissions"]}
            self.assertNotIn("queue-out-of-scope", sids)

    def test_manager_pins_and_clears_a_submission_unit(self):
        _, chc, _ = self._tree()
        self._grant_dm()
        submission = self._submission("queue-pin-me")
        self._login(str(self.base_coder_user.user_id))

        response = self.client.post(
            "/api/v1/data-management/submissions/queue-pin-me/org-unit",
            json={"org_unit_id": str(chc.org_unit_id)},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["unit_code"], "C01")
        db.session.expire_all()
        submission = db.session.get(VaSubmissions, "queue-pin-me")
        self.assertEqual(submission.org_unit_id, chc.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_MANUAL)
        self.assertEqual(submission.org_unit_pinned_by, self.base_coder_user.user_id)

        cleared = self.client.post(
            "/api/v1/data-management/submissions/queue-pin-me/org-unit",
            json={"org_unit_id": None},
            headers=self._csrf_headers(),
        )
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        db.session.expire_all()
        submission = db.session.get(VaSubmissions, "queue-pin-me")
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_MAPPING_FALLBACK)
        self.assertIsNone(submission.org_unit_pinned_by)

    def test_pin_is_refused_without_a_data_manager_grant(self):
        _, chc, _ = self._tree()
        self._submission("queue-scope-check")
        self._login(str(self.base_coder_user.user_id))
        denied = self.client.post(
            "/api/v1/data-management/submissions/queue-scope-check/org-unit",
            json={"org_unit_id": str(chc.org_unit_id)},
            headers=self._csrf_headers(),
        )
        self.assertIn(denied.status_code, (302, 403))
        db.session.expire_all()
        self.assertIsNone(
            db.session.get(VaSubmissions, "queue-scope-check").org_unit_id
        )

    def test_pin_is_refused_for_a_unit_in_another_project(self):
        self._tree()
        self._grant_dm()
        self._submission("queue-foreign-unit")
        other = "ORT003"
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, other) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=other, project_code=other, project_name="Other",
                    project_nickname="Other", project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                )
            )
            db.session.commit()
        org.seed_default_organization(other)
        other_levels = {lv.level_code: lv for lv in org.list_levels(other)}
        foreign = org.create_unit(
            other, org_level_id=other_levels["district"].org_level_id,
            unit_code="Z01", unit_name="Foreign District",
        )
        db.session.commit()

        self._login(str(self.base_coder_user.user_id))
        refused = self.client.post(
            "/api/v1/data-management/submissions/queue-foreign-unit/org-unit",
            json={"org_unit_id": str(foreign.org_unit_id)},
            headers=self._csrf_headers(),
        )
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertIn("not found in this submission", refused.get_json()["error"])


class SyncRoutesSubmissionsTests(OrgUnitRoutingFixtureMixin, BaseTestCase):
    """Routing runs inside the ODK sync loop, on create and on payload change."""

    def _record(self, instance_id: str, **payload_extras):
        now = datetime.now(UTC)
        record = {
            "KEY": instance_id,
            "sid": f"{instance_id}-{self.FORM_ID.lower()}",
            "form_def": self.FORM_ID,
            "SubmissionDate": now.isoformat(),
            "updatedAt": now.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": "hasIssues",
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes",
            "language": "English",
            "finalAgeInYears": "42",
            "Id10019": "male",
            "isNeonatal": "0",
            "isChild": "0",
            "isAdult": "1",
        }
        record.update(payload_extras)
        return record

    def _sync(self, records):
        from app.services.va_data_sync.va_data_sync_01_odkcentral import (
            _upsert_form_submissions,
        )

        amended = set()
        result = _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            records,
            amended,
            {},
            enrich_payloads=False,
        )
        db.session.commit()
        return result

    def test_sync_routes_a_new_submission_from_its_unit_code(self):
        _, _, phc = self._tree()
        self._mapping()
        self._sync([self._record("uuid:route-new", org_phc_code="P01")])

        submission = db.session.get(
            VaSubmissions, f"uuid:route-new-{self.FORM_ID.lower()}"
        )
        self.assertIsNotNone(submission)
        self.assertEqual(submission.org_unit_id, phc.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_FORM_FIELD)

    def test_sync_falls_back_to_the_mappings_unit_and_re_routes_on_change(self):
        district, chc, _ = self._tree()
        self._mapping(org_unit_id=district.org_unit_id)
        sid = f"uuid:route-change-{self.FORM_ID.lower()}"

        self._sync([self._record("uuid:route-change")])
        submission = db.session.get(VaSubmissions, sid)
        self.assertEqual(submission.org_unit_id, district.org_unit_id)
        self.assertEqual(
            submission.org_unit_resolution, routing.RESOLUTION_MAPPING_FALLBACK
        )

        # The interviewer corrects the form: the next sync moves the death.
        self._sync([self._record("uuid:route-change", org_chc_code="C01")])
        db.session.expire_all()
        submission = db.session.get(VaSubmissions, sid)
        self.assertEqual(submission.org_unit_id, chc.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_FORM_FIELD)

    def test_sync_leaves_a_pinned_submission_alone(self):
        district, chc, phc = self._tree()
        self._mapping()
        sid = f"uuid:route-pinned-{self.FORM_ID.lower()}"
        self._sync([self._record("uuid:route-pinned", org_phc_code="P01")])

        submission = db.session.get(VaSubmissions, sid)
        routing.pin_submission_org_unit(
            submission,
            chc.org_unit_id,
            actor_user_id=self.base_admin_user.user_id,
            project_id=self.PROJECT,
        )
        db.session.commit()

        self._sync([self._record("uuid:route-pinned", org_district_code="D01")])
        db.session.expire_all()
        submission = db.session.get(VaSubmissions, sid)
        self.assertEqual(submission.org_unit_id, chc.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, routing.RESOLUTION_MANUAL)

    def test_sync_leaves_a_project_without_a_tree_unrouted(self):
        self._mapping()
        self._sync([self._record("uuid:route-no-tree", org_phc_code="P01")])
        submission = db.session.get(
            VaSubmissions, f"uuid:route-no-tree-{self.FORM_ID.lower()}"
        )
        self.assertIsNone(submission.org_unit_id)
        self.assertIsNone(submission.org_unit_resolution)
