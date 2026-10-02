"""Data-manager surfaces on the authz module: what stage 3 changes on purpose.

digitva-0wc stage 3 (.tasks/digitva-0wc-design.md section 7) moves the DM
grid, triage, sync, the unrouted queue, pinning and the KPI scope onto
``app.services.authz``. These tests pin the decisions it implements:

- Every data manager of a tree project sees the project's unrouted queue and
  pins only into their own subtree; a project-wide one pins anywhere
  (owner 2026-10-02, design 2.3; the ``reaches_whole_site`` shortcut is gone).
- Admin's unrouted queue is tree projects only.
- project_pi on a tree project acts as a data manager (pages, triage,
  single-submission sync, pin); on a site project it does not.
- The In-charge (site_pi at a unit) opens the data-manager gate.
- System-level sync KPIs need a project or site grant (digitva-38lp).
- The KPI cache key follows the grants (no collision between scopes).
- Admin opens /data-management/view/<sid> (F11).
"""
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa
from flask_login import login_user

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import org_unit_routing_service as routing
from app.services.authz import Action, Grant, ResolvedGrants, can, resolve_grants, scope_filter
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

R = VaAccessRoles


class DmAuthzStageThreeTests(UnitScopeFixture, BaseTestCase):
    """CSC001: District D01 > CHC C01 > PHC P01, P02 (a tree project), and the
    base project BASE01 (a site project, no tree)."""

    SITE_FORM_ID = "BASE01BS01S3"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        now = datetime.now(UTC)
        if db.session.get(VaForms, cls.SITE_FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.SITE_FORM_ID, project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID, odk_form_id="STAGE3_SITE_FORM",
                odk_project_id="93", form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        _, self.district, self.chc, self.phc_a, self.phc_b = self._tree()
        self._sub("csc-s3-unrouted")
        self._sub("csc-s3-phc-a", unit=self.phc_a)
        self._sub("csc-s3-phc-b", unit=self.phc_b)
        fallback_a = self._sub("csc-s3-fallback-a")
        fallback_b = self._sub("csc-s3-fallback-b")
        for submission, unit in ((fallback_a, self.phc_a), (fallback_b, self.phc_b)):
            routing.apply_routing(submission, routing.RoutingOutcome(
                org_unit_id=unit.org_unit_id,
                resolution=routing.RESOLUTION_MAPPING_FALLBACK,
            ))
        db.session.commit()
        self._site_submission("base-s3-unrouted")

    # -- fixtures ----------------------------------------------------------

    def _site_submission(self, sid):
        now = datetime.now(UTC)
        if db.session.get(VaSubmissions, sid) is None:
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=self.SITE_FORM_ID, va_submission_date=now,
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
            db.session.commit()

    def _project_user(self, key, role, project_id=None):
        user = self._get_or_make_user(f"stage3.{key}@test.local", "Stage3Test123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=project_id or self.PROJECT, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _unit_user(self, key, unit, role=R.data_manager):
        return self._user_with(f"stage3.{key}@test.local", role, unit)

    def _queue(self, user, include="fallback"):
        self._login(str(user.user_id))
        response = self.client.get(
            "/api/v1/data-management/submissions/unrouted"
            f"?project={self.PROJECT}&include={include}"
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return {row["va_sid"] for row in response.get_json()["submissions"]}

    def _pin(self, user, sid, unit):
        self._login(str(user.user_id))
        return self.client.post(
            f"/api/v1/data-management/submissions/{sid}/org-unit",
            json={"org_unit_id": str(unit.org_unit_id)},
            headers=self._csrf_headers(),
        )

    def _unit_of(self, sid):
        db.session.expire_all()
        return db.session.get(VaSubmissions, sid).org_unit_id

    def _workflow(self, sid):
        return db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == sid)
        )

    def _set_state(self, sid, state):
        self._workflow(sid).workflow_state = state
        db.session.commit()

    # -- the unrouted queue and pinning ------------------------------------

    def test_a_unit_data_manager_sees_the_projects_unrouted_queue(self):
        dm = self._unit_user("unit.queue", self.chc)
        listed = self._queue(dm)
        self.assertIn("csc-s3-unrouted", listed)        # decision: every DM of the project
        self.assertIn("csc-s3-fallback-a", listed)      # fallback inside the subtree
        self.assertNotIn("csc-s3-phc-a", listed)        # routed by its own payload
        self.assertEqual(self._queue(dm, include="unrouted"), {"csc-s3-unrouted"})

    def test_a_unit_data_manager_never_sees_another_units_fallback_case(self):
        dm = self._unit_user("unit.queue.narrow", self.phc_a)
        listed = self._queue(dm)
        self.assertIn("csc-s3-fallback-a", listed)
        self.assertNotIn("csc-s3-fallback-b", listed)

    def test_a_unit_data_manager_pins_only_into_their_own_subtree(self):
        dm = self._unit_user("unit.pin", self.chc)
        pinned = self._pin(dm, "csc-s3-unrouted", self.phc_a)
        self.assertEqual(pinned.status_code, 200, pinned.get_json())
        self.assertEqual(self._unit_of("csc-s3-unrouted"), self.phc_a.org_unit_id)

        refused = self._pin(dm, "csc-s3-fallback-a", self.district)
        self.assertEqual(refused.status_code, 403, refused.get_json())
        self.assertEqual(self._unit_of("csc-s3-fallback-a"), self.phc_a.org_unit_id)

    def test_a_unit_data_manager_cannot_pin_a_case_routed_outside_their_subtree(self):
        dm = self._unit_user("unit.pin.outside", self.phc_a)
        refused = self._pin(dm, "csc-s3-phc-b", self.phc_a)
        self.assertEqual(refused.status_code, 403, refused.get_json())
        self.assertEqual(self._unit_of("csc-s3-phc-b"), self.phc_b.org_unit_id)

    def test_a_project_data_manager_pins_anywhere_in_the_project(self):
        dm = self._project_user("project.pin", R.data_manager)
        response = self._pin(dm, "csc-s3-phc-a", self.district)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._unit_of("csc-s3-phc-a"), self.district.org_unit_id)

    def test_admins_unrouted_queue_is_tree_projects_only(self):
        admin = self.base_admin_user
        listed = set(db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(scope_filter(admin, Action.LIST_UNROUTED))
        ).all())
        self.assertIn("csc-s3-unrouted", listed)
        self.assertNotIn("base-s3-unrouted", listed)
        self.assertNotIn("csc-s3-phc-a", listed)
        self.assertTrue(can(admin, Action.LIST_UNROUTED, self.PROJECT))
        self.assertFalse(can(admin, Action.LIST_UNROUTED, self.BASE_PROJECT_ID))

    # -- project_pi --------------------------------------------------------

    def test_project_pi_on_a_tree_project_acts_as_a_data_manager(self):
        pi = self._project_user("pi.tree", R.project_pi)
        self.assertTrue(pi.is_data_manager())
        self._login(str(pi.user_id))

        self.assertEqual(self.client.get("/data-management/dashboard").status_code, 200)
        self.assertEqual(self.client.get("/data-management/view/csc-s3-phc-a").status_code, 200)
        self.assertIn("csc-s3-unrouted", self._queue(pi))

        self._set_state("csc-s3-phc-a", "screening_pending")
        passed = self.client.post(
            "/api/v1/data-management/submissions/csc-s3-phc-a/screening-pass",
            headers=self._csrf_headers(),
        )
        self.assertEqual(passed.status_code, 200, passed.get_json())

        with patch("app.tasks.sync_tasks.run_single_submission_sync.delay") as delay:
            delay.return_value.id = "task-stage3"
            synced = self.client.post(
                "/api/v1/data-management/submissions/csc-s3-phc-b/sync",
                headers=self._csrf_headers(),
            )
        self.assertEqual(synced.status_code, 202, synced.get_json())

        pinned = self._pin(pi, "csc-s3-unrouted", self.district)
        self.assertEqual(pinned.status_code, 200, pinned.get_json())
        self.assertTrue(can(pi, Action.SYNC_FORM, self.FORM_ID))

    def test_project_pi_on_a_site_project_cannot_triage(self):
        pi = self._project_user("pi.site", R.project_pi, self.BASE_PROJECT_ID)
        self.assertTrue(can(pi, Action.VIEW, "base-s3-unrouted"))  # subject is reachable
        self.assertFalse(pi.is_data_manager())
        self.assertFalse(can(pi, Action.TRIAGE, "base-s3-unrouted"))
        self._set_state("base-s3-unrouted", "screening_pending")
        self._login(str(pi.user_id))
        refused = self.client.post(
            "/api/v1/data-management/submissions/base-s3-unrouted/screening-pass",
            headers=self._csrf_headers(),
        )
        self.assertIn(refused.status_code, (302, 403))
        db.session.expire_all()
        self.assertEqual(self._workflow("base-s3-unrouted").workflow_state, "screening_pending")
        self.assertEqual(self.client.get("/data-management/dashboard").status_code, 403)

    def test_the_in_charge_opens_the_data_manager_gate(self):
        base = resolve_grants(self.base_coder_user)
        incharge = ResolvedGrants(
            user_id=self.base_coder_user.user_id,
            is_admin=False,
            grants=(Grant(
                role=R.site_pi, scope_type=VaAccessScopeTypes.org_unit,
                project_id=self.PROJECT, org_unit_id=self.chc.org_unit_id,
            ), *base.grants),
            projects=base.projects,
        )
        with patch("app.services.authz.predicates.resolve_grants", return_value=incharge):
            self.assertTrue(self.base_coder_user.is_data_manager())

    # -- digitva-38lp: system-level sync KPIs ------------------------------

    def test_system_level_sync_kpis_refuse_a_unit_only_data_manager(self):
        dm = self._unit_user("unit.38lp", self.chc)
        self._login(str(dm.user_id))
        prefix = "/api/v1/analytics/dm-kpi/sync"
        self.assertEqual(self.client.get(f"{prefix}/status").status_code, 403)
        self.assertEqual(self.client.get(f"{prefix}/smartva-failure-rate").status_code, 403)
        health = self.client.get(f"{prefix}/attachment-health")
        self.assertEqual(health.status_code, 200)
        self.assertIsNone(health.get_json()["d_sh_01"])

    def test_system_level_sync_kpis_stay_open_to_a_project_data_manager(self):
        dm = self._project_user("project.38lp", R.data_manager)
        self._login(str(dm.user_id))
        prefix = "/api/v1/analytics/dm-kpi/sync"
        self.assertEqual(self.client.get(f"{prefix}/status").status_code, 200)
        self.assertEqual(self.client.get(f"{prefix}/smartva-failure-rate").status_code, 200)

    # -- KPI cache ---------------------------------------------------------

    def _kpi_digest(self, user):
        from app.routes.api.dm_kpi.dm_kpi_scope import dm_scope

        with self.app.test_request_context("/"):
            login_user(user)
            return dm_scope().digest()

    def test_the_kpi_cache_key_follows_the_grants(self):
        unit_a = self._unit_user("digest.a", self.phc_a)
        unit_b = self._unit_user("digest.b", self.phc_b)
        pi = self._project_user("digest.pi", R.project_pi)
        digests = {self._kpi_digest(u) for u in (unit_a, unit_b, pi)}
        self.assertEqual(len(digests), 3)

        before = self._kpi_digest(unit_a)
        db.session.add(VaUserAccessGrants(
            user_id=unit_a.user_id, role=R.data_manager,
            scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc_b.org_unit_id,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertNotEqual(self._kpi_digest(unit_a), before)

    # -- F11 ---------------------------------------------------------------

    def test_admin_passes_the_data_manager_view_check(self):
        self.assertTrue(can(self.base_admin_user, Action.TRIAGE, "csc-s3-phc-a"))
        self._login(self.base_admin_id)
        response = self.client.get("/data-management/view/csc-s3-phc-a")
        self.assertEqual(response.status_code, 200)
