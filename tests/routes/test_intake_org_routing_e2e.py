"""End-to-end: a web submission routes to its unit and reaches only its coders.

WP3 of docs/planning/web-capture-project-configuration-plan.md. The pieces are
each covered elsewhere — ``_require_scope`` in tests/services/test_web_intake_service.py,
the HTTP flow in tests/routes/test_intake_api.py, the coding scope filter in
tests/test_coding_scope_enforcement.py — but nothing followed one questionnaire
from the interviewer's browser to a unit-scoped coder's pick list. That is what
the "project-scoped interviewer produces an unroutable case" defect row was
about, so it is what this file proves.

The chain under test (docs/policy/organization-model.md, routing and coding
scope): the interviewer names a unit -> ``_unit_context`` writes the path's
``org_<level_code>_code`` answers into the stored payload -> routing reads them
back and stamps ``va_submissions.org_unit_id`` -> ``_org_unit_scope_filter``
offers the case only to coders whose grants cover that unit.
"""
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.models.va_submission_payload_versions import PAYLOAD_VERSION_STATUS_ACTIVE
from app.services import organization_service as org
from app.services.coder_workflow_service import get_pick_available_forms
from app.services.org_unit_routing_service import RESOLUTION_FORM_FIELD
from app.services.runtime_form_sync_service import (
    _ensure_legacy_project_site_rows,
    ensure_web_runtime_form,
)
from app.services.workflow.transitions import mark_smartva_completed
from tests.base import BaseTestCase


class IntakeOrgRoutingEndToEndTests(BaseTestCase):
    """Project ROUTE1 has a two-level tree (district > block) with units A and B.

    The coding scope level is the leaf, so a coder granted on one block codes
    that block and nothing else.
    """

    PROJECT_ID = "ROUTE1"
    SITE_ID = "RT01"

    DISTRICT_CODE = "ROUTED01"
    UNIT_A_CODE = "ROUTEA01"
    UNIT_B_CODE = "ROUTEB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)

        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="Routing End To End",
            project_nickname="RouteE2E",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
            web_intake_mode="both",
            coding_intake_mode="pick_and_choose",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="Routing End To End Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)

        # This project collects only on the web, so there is no ODK mapping to
        # seed a va_forms row. Materialise the web form the way enabling web
        # intake does: the interviewer role gate resolves through va_forms, so
        # without it the project-scoped grant opens nothing.
        cls.web_form = ensure_web_runtime_form(cls.PROJECT_ID, cls.SITE_ID)
        cls.district_level = org.create_level(
            cls.PROJECT_ID, level_code="district", level_name="District", depth=1
        )
        cls.block_level = org.create_level(
            cls.PROJECT_ID, level_code="block", level_name="Block", depth=2
        )
        cls.district = org.create_unit(
            cls.PROJECT_ID,
            org_level_id=cls.district_level.org_level_id,
            unit_code=cls.DISTRICT_CODE,
            unit_name="Routing District",
        )
        cls.unit_a = org.create_unit(
            cls.PROJECT_ID,
            org_level_id=cls.block_level.org_level_id,
            parent_org_unit_id=cls.district.org_unit_id,
            unit_code=cls.UNIT_A_CODE,
            unit_name="Routing Block A",
        )
        cls.unit_b = org.create_unit(
            cls.PROJECT_ID,
            org_level_id=cls.block_level.org_level_id,
            parent_org_unit_id=cls.district.org_unit_id,
            unit_code=cls.UNIT_B_CODE,
            unit_name="Routing Block B",
        )
        # The leaf is the coding scope level, so a block grant codes its own
        # block; anything above it would be view-only.
        project = db.session.get(VaProjectMaster, cls.PROJECT_ID)
        project.coding_scope_level_id = cls.block_level.org_level_id
        project.above_scope_coding_mode = "view_only"
        db.session.flush()

        cls.interviewer = cls._get_or_make_user(
            "route.interviewer@test.local", "RouteE2E123"
        )
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
            notes="routing e2e interviewer grant",
            grant_status=VaStatuses.active,
        ))
        cls.coder_a = cls._get_or_make_user("route.coder.a@test.local", "RouteE2E123")
        cls.coder_b = cls._get_or_make_user("route.coder.b@test.local", "RouteE2E123")
        for coder, unit in ((cls.coder_a, cls.unit_a), (cls.coder_b, cls.unit_b)):
            db.session.add(VaUserAccessGrants(
                user_id=coder.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=unit.org_unit_id,
                notes="routing e2e coder grant",
                grant_status=VaStatuses.active,
            ))
        db.session.commit()

        cls.interviewer_id = str(cls.interviewer.user_id)

    # ── helpers ────────────────────────────────────────────────────────────

    def _submit_through_the_browser(self, org_unit_id):
        """Register -> start -> save sections -> submit, all over HTTP.

        Returns the created ``va_sid``. Mirrors the happy path in
        tests/routes/test_intake_api.py::test_register_list_start_save_and_submit,
        with the organization unit named at registration.
        """
        self._login(self.interviewer_id)

        registered = self.client.post(
            "/intake/api/deaths",
            json={
                "project_id": self.PROJECT_ID,
                "site_id": self.SITE_ID,
                "org_unit_id": str(org_unit_id),
                "deceased_name": "Rekha Patel",
                "deceased_sex": "female",
                "date_of_death": (date.today() - timedelta(days=7)).isoformat(),
                "age_years": 68,
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(registered.status_code, 201, registered.get_json())
        death = registered.get_json()["death"]
        self.assertEqual(death["org_unit_id"], str(org_unit_id))

        started = self.client.post(
            "/intake/api/drafts",
            json={
                "project_id": self.PROJECT_ID,
                "site_id": self.SITE_ID,
                "death_id": death["death_id"],
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(started.status_code, 201, started.get_json())
        draft = started.get_json()["draft"]
        self.assertEqual(draft["org_unit_id"], str(org_unit_id))

        saved = self.client.patch(
            f"/intake/api/drafts/{draft['draft_id']}",
            json={
                "sections": {
                    "consent": {"Id10013": "yes"},
                    "background": {"Id10019": "female"},
                },
                "current_section": "background",
                "meta": {"schemaVersion": 1, "formVersion": "2022"},
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(saved.status_code, 200, saved.get_json())

        submitted = self.client.post(
            f"/intake/api/drafts/{draft['draft_id']}/submit",
            json={
                "completion": {
                    "valid": True,
                    "issues": [],
                    "data": {
                        "Id10013": "yes",
                        "Id10019": "female",
                        "finalAgeInYears": "68",
                        "narr_language": "english",
                    },
                }
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        return submitted.get_json()["va_sid"]

    def _pick_list(self, coder):
        """The va_sids this coder is offered in pick-and-choose mode."""
        return {
            row["va_sid"]
            for row in get_pick_available_forms(coder, list(coder.get_coder_va_forms()))
        }

    # ── the route, end to end ──────────────────────────────────────────────

    def test_a_web_submission_routes_to_its_unit_and_reaches_only_its_coders(self):
        va_sid = self._submit_through_the_browser(self.unit_b.org_unit_id)

        # (a) the submission exists, and it is attributed to unit B.
        submission = db.session.get(VaSubmissions, va_sid)
        self.assertIsNotNone(submission, "the submission row must exist before anything else")
        self.assertEqual(submission.org_unit_id, self.unit_b.org_unit_id)
        self.assertEqual(submission.org_unit_resolution, RESOLUTION_FORM_FIELD)

        # (b) the stored payload carries a code for every level on B's path,
        # under the field name the instrument contract derives from the level
        # code — never a hardcoded name, or the form and the router would
        # disagree about where the answer lives.
        payload = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion.payload_data).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        self.assertIsNotNone(payload)
        self.assertEqual(
            {
                org.odk_field_name_for_level("district"): self.DISTRICT_CODE,
                org.odk_field_name_for_level("block"): self.UNIT_B_CODE,
            },
            {
                field: payload.get(field)
                for field in (
                    org.odk_field_name_for_level("district"),
                    org.odk_field_name_for_level("block"),
                )
            },
        )
        # Sibling A is on another branch, so its code must not appear at all.
        self.assertNotIn(self.UNIT_A_CODE, payload.values())

        # SmartVA is what carries a synced case into the coder pool; run the
        # same transition here so the pick list is asked the real question.
        mark_smartva_completed(va_sid)
        db.session.commit()

        # (c) the coder scoped to B is offered it...
        self.assertIn(va_sid, self._pick_list(self.coder_b))

        # ...and (d) the coder scoped to A is not. Assert A's form access first,
        # so the absence is the unit filter's doing and not an empty form set.
        self.assertIn(submission.va_form_id, self.coder_a.get_coder_va_forms())
        self.assertNotIn(va_sid, self._pick_list(self.coder_a))

    # ── a tree project always needs a unit, at the HTTP layer too ──────────
    #
    # The service-level rule is covered in
    # tests/services/test_web_intake_service.py
    # (test_project_scoped_interviewer_in_tree_project_refused_without_unit, and
    # the deactivated-unit refusal beside it). Neither is reachable from
    # tests/routes/test_intake_api.py, whose projects have no organization
    # tree — so this asserts that the refusal survives the route layer instead
    # of being swallowed into a 500 or a silently unrouted death.

    def test_registering_without_a_unit_is_refused_over_http(self):
        self._login(self.interviewer_id)
        response = self.client.post(
            "/intake/api/deaths",
            json={
                "project_id": self.PROJECT_ID,
                "site_id": self.SITE_ID,
                "deceased_name": "Unrouted Case",
                "deceased_sex": "male",
                "date_of_death": (date.today() - timedelta(days=3)).isoformat(),
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("organization unit", response.get_json()["error"])
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
            ),
            0,
            "a refused registration must leave nothing behind",
        )
