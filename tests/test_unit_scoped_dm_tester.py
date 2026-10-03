"""Unit-scoped data_manager and coding_tester grants (stage 2 of digitva-djd).

A data_manager or coding_tester grant at an organization unit covers that
unit's whole subtree on every surface, exactly as a project or project-site
grant covers its own scope, and nothing outside it. Coverage is decided per
submission by ``VaSubmissions.org_unit_id``. Policy:
docs/policy/access-control-model.md, "Role To Scope Rules".
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services import authz
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


class UnitScopeFixture(CodingScopeFixtureMixin):
    """The coding-scope tree project plus a second form of the same site."""

    OTHER_FORM_ID = "CSC001CS0102"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaForms, cls.OTHER_FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.OTHER_FORM_ID, project_id=cls.PROJECT, site_id=cls.SITE,
                odk_form_id="CODING_SCOPE_FORM_2", odk_project_id="91",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(VaSubmissions).where(
            VaSubmissions.va_form_id == self.OTHER_FORM_ID
        ))
        db.session.commit()

    def _user_with(self, email, role, unit):
        user = self._get_or_make_user(email, "UnitScope123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    INACTIVE_PAIR_SITE = "CS09"
    INACTIVE_PAIR_FORM_ID = "CSC001CS0901"

    def _inactive_pair_form(self):
        """A form of the tree project on site CS09, whose (project, site)
        pair is deactivated. Seeded per test (rolled back with it); returns
        the ``VaProjectSites`` row so a test can flip its status."""
        now = datetime.now(UTC)
        site = self.INACTIVE_PAIR_SITE
        db.session.add(VaSiteMaster(
            site_id=site, site_abbr=site, site_name="Inactive Pair Site",
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=site, project_id=self.PROJECT, site_name="Inactive Pair Site",
            site_abbr=site, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        pair = VaProjectSites(
            project_id=self.PROJECT, site_id=site,
            project_site_status=VaStatuses.deactive,
            project_site_registered_at=now, project_site_updated_at=now,
        )
        db.session.add(pair)
        db.session.flush()
        db.session.add(VaForms(
            form_id=self.INACTIVE_PAIR_FORM_ID, project_id=self.PROJECT, site_id=site,
            odk_form_id="CODING_SCOPE_FORM_INACTIVE", odk_project_id="91",
            form_type="WHO VA 2022", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.commit()
        return pair

    def _sub(self, sid, unit=None, form_id=None):
        submission = self._submission(sid, unit=unit)
        if form_id:
            submission.va_form_id = form_id
            db.session.commit()
        return submission


class UnitGrantFormResolutionTests(UnitScopeFixture, BaseTestCase):
    """_get_granted_va_forms: a unit grant yields only forms under its subtree."""

    def test_unit_grant_yields_only_forms_with_submissions_in_the_subtree(self):
        _, _, _, phc_a, phc_b = self._tree()
        self._sub("csc-a", unit=phc_a)
        self._sub("csc-b", unit=phc_b, form_id=self.OTHER_FORM_ID)
        tester = self._user_with("unit.tester@test.local", VaAccessRoles.coding_tester, phc_a)
        dm = self._user_with("unit.dm@test.local", VaAccessRoles.data_manager, phc_a)

        for user, forms in (
            (tester, tester.get_coding_tester_va_forms()),
            (dm, dm.get_data_manager_va_forms()),
        ):
            with self.subTest(user=user.email):
                self.assertIn(self.FORM_ID, forms)
                self.assertNotIn(self.OTHER_FORM_ID, forms)

    def test_the_mapping_fallback_unit_also_places_a_form_in_the_subtree(self):
        from app.models import MapProjectSiteOdk

        _, _, _, phc_a, phc_b = self._tree()
        db.session.add(MapProjectSiteOdk(
            project_id=self.PROJECT, site_id=self.SITE, odk_project_id=91,
            odk_form_id="CODING_SCOPE_FORM_2", org_unit_id=phc_b.org_unit_id,
        ))
        db.session.commit()
        tester = self._user_with("unit.tester2@test.local", VaAccessRoles.coding_tester, phc_b)
        self.assertIn(self.OTHER_FORM_ID, tester.get_coding_tester_va_forms())
        self.assertNotIn(self.FORM_ID, tester.get_coding_tester_va_forms())

    def test_a_unit_grant_with_nothing_in_its_subtree_still_opens_the_role_gate(self):
        _, _, _, phc_a, _ = self._tree()
        tester = self._user_with("unit.tester3@test.local", VaAccessRoles.coding_tester, phc_a)
        dm = self._user_with("unit.dm3@test.local", VaAccessRoles.data_manager, phc_a)
        self.assertEqual(tester.get_coding_tester_va_forms() - self._demo_forms(), set())
        self.assertTrue(tester.is_coding_tester())
        self.assertTrue(dm.is_data_manager())

    @staticmethod
    def _demo_forms():
        from app.services.demo_project_service import get_coder_demo_project_form_ids

        return get_coder_demo_project_form_ids()


class UnitCodingTesterTests(UnitScopeFixture, BaseTestCase):
    """A unit coding_tester codes and opens its own subtree only."""

    def test_pick_list_offers_the_testers_subtree_and_nothing_else(self):
        from app.services.coder_workflow_service import get_pick_available_forms

        _, _, chc, phc_a, phc_b = self._tree()
        self._sub("csc-tester-in", unit=phc_a)
        self._sub("csc-tester-out", unit=phc_b, form_id=self.OTHER_FORM_ID)
        self._sub("csc-tester-sibling-same-form", unit=chc)
        tester = self._user_with("unit.tester.pick@test.local", VaAccessRoles.coding_tester, phc_a)

        offered = {
            r["va_sid"]
            for r in get_pick_available_forms(tester, [self.FORM_ID, self.OTHER_FORM_ID])
        }
        self.assertIn("csc-tester-in", offered)
        self.assertNotIn("csc-tester-out", offered)
        # Same form as the tester's own death, but the CHC is above the PHC.
        self.assertNotIn("csc-tester-sibling-same-form", offered)

    def test_tester_bypass_of_the_coder_unit_check_is_its_own_subtree(self):
        from app.services.authz import Action, can

        _, _, chc, phc_a, _ = self._tree()
        self._sub("csc-cover-in", unit=phc_a)
        self._sub("csc-cover-above", unit=chc)
        self._sub("csc-cover-unrouted")
        tester = self._user_with("unit.tester.cover@test.local", VaAccessRoles.coding_tester, phc_a)

        self.assertTrue(can(tester, Action.CODE, "csc-cover-in"))
        self.assertFalse(can(tester, Action.CODE, "csc-cover-above"))
        self.assertFalse(can(tester, Action.CODE, "csc-cover-unrouted"))

    def test_pick_allocation_refuses_a_unit_tester_outside_the_subtree(self):
        from app.services.coder_workflow_service import AllocationError, allocate_pick_form

        _, _, chc, phc_a, _ = self._tree()
        self._sub("csc-alloc-in", unit=phc_a)
        self._sub("csc-alloc-above", unit=chc)
        tester = self._user_with("unit.tester.alloc@test.local", VaAccessRoles.coding_tester, phc_a)
        self.assertTrue(authz.can(tester, authz.Action.CODE, "csc-alloc-in"))

        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(tester, "csc-alloc-above")
        self.assertIn("outside your coding scope", str(ctx.exception))

        result = allocate_pick_form(tester, "csc-alloc-in")
        self.assertEqual(result.va_sid, "csc-alloc-in")


class CodingWaiverTests(BaseTestCase):
    """coding_gate_waivers keys every waiver on the (project, site) pair."""

    def test_site_pi_waiver_does_not_cross_projects(self):
        from app.services.authz import CodingWaivers

        waivers = CodingWaivers(
            pi_projects=frozenset(),
            pi_pairs=frozenset({("P1", "S1")}),
            tester_projects=frozenset(),
            tester_pairs=frozenset(),
            tester_unit_ids=frozenset({"unit-x"}),
        )
        self.assertTrue(waivers.waives("P1", "S1"))
        self.assertFalse(waivers.waives("P2", "S1"))
        self.assertTrue(waivers.waives("P2", "S1", "unit-x"))
        self.assertFalse(waivers.is_tester("P2", "S1"))


class UnitDataManagerRouteTests(UnitScopeFixture, BaseTestCase):
    """A unit-only data manager reaches the data-management surfaces."""

    UNROUTED = "/api/v1/data-management/submissions/unrouted"

    def test_unit_data_manager_reaches_pages_that_used_to_refuse_them(self):
        from tests.routes.test_data_manager_dashboard import DataManagerDashboardTests

        # The dashboard reads the analytics MVs; per-test isolation rolls DDL
        # back, so build them here (docs/policy/test-harness.md).
        DataManagerDashboardTests._create_analytics_mvs(self, "ix_test_unit_dm_pages")
        _, district, _, _, _ = self._tree()
        dm = self._user_with("unit.dm.pages@test.local", VaAccessRoles.data_manager, district)
        self._login(str(dm.user_id))
        for url in ("/data-management/", "/intake/supervision", "/data-management/users"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_unrouted_queue_lists_unrouted_and_fallbacks_inside_the_subtree_only(self):
        """Owner 2026-10-02 (digitva-0wc stage 3): every data manager of a
        tree project sees its unrouted cases (was: project/site DMs only);
        fallback-routed cases still stop at the subtree."""
        from app.services.org_unit_routing_service import RESOLUTION_MAPPING_FALLBACK

        _, _, _, phc_a, phc_b = self._tree()
        mine = self._sub("csc-fallback-mine", unit=phc_a)
        theirs = self._sub("csc-fallback-theirs", unit=phc_b)
        for sub in (mine, theirs):
            sub.org_unit_resolution = RESOLUTION_MAPPING_FALLBACK
        self._sub("csc-unrouted")
        db.session.commit()
        dm = self._user_with("unit.dm.queue@test.local", VaAccessRoles.data_manager, phc_a)
        self._login(str(dm.user_id))

        sids = {
            row["va_sid"]
            for row in self.client.get(f"{self.UNROUTED}?project={self.PROJECT}")
            .get_json()["submissions"]
        }
        self.assertIn("csc-fallback-mine", sids)
        self.assertNotIn("csc-fallback-theirs", sids)
        self.assertIn("csc-unrouted", sids)

    def test_unit_data_manager_pins_only_inside_the_subtree(self):
        _, _, chc, phc_a, phc_b = self._tree()
        self._sub("csc-pin-mine", unit=phc_a)
        self._sub("csc-pin-theirs", unit=phc_b)
        dm = self._user_with("unit.dm.pin@test.local", VaAccessRoles.data_manager, phc_a)
        self._login(str(dm.user_id))

        def pin(sid, unit):
            return self.client.post(
                f"/api/v1/data-management/submissions/{sid}/org-unit",
                json={"org_unit_id": str(unit.org_unit_id)},
                headers=self._csrf_headers(),
            )

        self.assertEqual(pin("csc-pin-theirs", phc_a).status_code, 403)
        self.assertEqual(pin("csc-pin-mine", chc).status_code, 403)
        self.assertEqual(db.session.get(VaSubmissions, "csc-pin-mine").org_unit_id, phc_a.org_unit_id)
        self.assertEqual(pin("csc-pin-mine", phc_a).status_code, 200)

    def test_unit_only_data_manager_cannot_open_an_arbitrary_account(self):
        _, district, _, _, _ = self._tree()
        dm = self._user_with("unit.dm.accounts@test.local", VaAccessRoles.data_manager, district)
        outsider = self._get_or_make_user("unit.dm.outsider@test.local", "UnitScope123")
        self._login(str(dm.user_id))

        self.assertEqual(
            self.client.get(f"/data-management/api/users/{outsider.user_id}").status_code, 404
        )
        found = self.client.get("/data-management/api/users?query=unit.dm.outsider").get_json()
        self.assertEqual(found["users"], [])


class DataManagerUserSearchTests(BaseTestCase):
    """The project data manager's full user search (digitva-jkd)."""

    def setUp(self):
        super().setUp()
        from app import limiter

        limiter.reset()
        self.dm = self._get_or_make_user("search.dm@test.local", "SearchDm123")
        db.session.add(VaUserAccessGrants(
            user_id=self.dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=self.BASE_PROJECT_ID,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(self.dm.user_id))

    def _search(self, query):
        return self.client.get(
            "/data-management/api/users", query_string={"query": query}
        ).get_json()

    def test_wildcards_in_the_query_match_literally(self):
        self._get_or_make_user("percent%user@test.local", "SearchDm123")
        self._get_or_make_user("plainuser@test.local", "SearchDm123")
        # Would match "t\\u" if the backslash were read as LIKE's escape.
        self._get_or_make_user("tuser.search@test.local", "SearchDm123")
        emails = {u["email"] for u in self._search("%user")["users"]}
        self.assertIn("percent%user@test.local", emails)
        self.assertNotIn("plainuser@test.local", emails)
        self.assertEqual(self._search("_lainuser")["users"], [])
        self.assertEqual(self._search("t\\u")["users"], [])

    def test_more_than_the_limit_is_flagged_not_silently_dropped(self):
        for n in range(26):
            self._get_or_make_user(f"bulk.search.{n:02d}@test.local", "SearchDm123")
        body = self._search("bulk.search.")
        self.assertEqual(len(body["users"]), 25)
        self.assertTrue(body["truncated"])
        narrow = self._search("bulk.search.0")
        self.assertEqual(len(narrow["users"]), 10)
        self.assertFalse(narrow["truncated"])


class CrossUnitSubmissionScopeTests(UnitScopeFixture, BaseTestCase):
    """Surfaces that used to stop at the form: a form spans several units, so
    each one must also check the submission's own routed unit (digitva-djd).

    Every case seeds one submission inside the grantee's unit as well, so the
    form-level check passes and the refusal comes from the per-submission one.
    """

    def _seed(self):
        _, _, _, phc_a, phc_b = self._tree()
        self._sub("csc-x-mine", unit=phc_a)
        self._sub("csc-x-theirs", unit=phc_b)
        return phc_a, phc_b

    def _project_grant(self, email, role):
        user = self._get_or_make_user(email, "UnitScope123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _events_status(self, user, sid):
        self._login(str(user.user_id))
        return self.client.get(f"/api/v1/workflow/events/{sid}").status_code

    # -- attachments -------------------------------------------------------

    def test_unit_reviewer_attachment_access_stops_at_their_unit(self):
        from app.services.attachment_service import can_access_submission_attachment

        phc_a, _ = self._seed()
        reviewer = self._user_with("x.reviewer.att@test.local", VaAccessRoles.reviewer, phc_a)
        self.assertTrue(authz.can(reviewer, authz.Action.REVIEW, "csc-x-mine"))
        self.assertTrue(can_access_submission_attachment(
            reviewer, va_form_id=self.FORM_ID, va_sid="csc-x-mine"))
        self.assertFalse(can_access_submission_attachment(
            reviewer, va_form_id=self.FORM_ID, va_sid="csc-x-theirs"))

    # -- workflow events ---------------------------------------------------

    def test_workflow_events_stop_at_the_callers_unit(self):
        phc_a, _ = self._seed()
        for role in (VaAccessRoles.data_manager, VaAccessRoles.coder, VaAccessRoles.reviewer):
            user = self._user_with(f"x.events.{role.value}@test.local", role, phc_a)
            with self.subTest(role=role.value):
                self.assertEqual(self._events_status(user, "csc-x-mine"), 200)
                self.assertEqual(self._events_status(user, "csc-x-theirs"), 403)

    def test_workflow_events_unchanged_for_project_grants(self):
        self._seed()
        for role in (VaAccessRoles.data_manager, VaAccessRoles.coder, VaAccessRoles.reviewer):
            user = self._project_grant(f"x.events.project.{role.value}@test.local", role)
            with self.subTest(user=user.email):
                self.assertEqual(self._events_status(user, "csc-x-theirs"), 200)

    # -- page shells -------------------------------------------------------

    def test_coder_view_shell_refuses_another_units_submission(self):
        phc_a, _ = self._seed()
        coder = self._user_with("x.coder.view@test.local", VaAccessRoles.coder, phc_a)
        self._login(str(coder.user_id))
        self.assertNotEqual(self.client.get("/coding/view/csc-x-mine").status_code, 403)
        self.assertEqual(self.client.get("/coding/view/csc-x-theirs").status_code, 403)

    def test_reviewer_view_shell_refuses_another_units_submission(self):
        phc_a, _ = self._seed()
        reviewer = self._user_with("x.reviewer.view@test.local", VaAccessRoles.reviewer, phc_a)
        self._login(str(reviewer.user_id))
        self.assertNotEqual(self.client.get("/reviewing/view/csc-x-mine").status_code, 403)
        self.assertEqual(self.client.get("/reviewing/view/csc-x-theirs").status_code, 403)

    # -- form sync ---------------------------------------------------------

    def test_unit_only_data_manager_cannot_sync_or_preview_a_whole_form(self):
        from app.tasks.sync_tasks import _authorize_data_manager_form_sync

        _, district, _, _, _ = self._tree()
        self._sub("csc-x-sync", unit=district)
        dm = self._user_with("x.dm.sync@test.local", VaAccessRoles.data_manager, district)
        # The subject: the unit grant does reach submissions of this form.
        self.assertTrue(db.session.scalar(sa.select(sa.exists().where(
            VaSubmissions.va_form_id == self.FORM_ID,
            authz.scope_filter(dm, authz.Action.LIST_DATA),
        ))))
        self._login(str(dm.user_id))

        self.assertEqual(self.client.post(
            f"/api/v1/data-management/forms/{self.FORM_ID}/sync",
            headers=self._csrf_headers(),
        ).status_code, 403)
        self.assertEqual(self.client.post(
            "/api/v1/data-management/sync/preview", json={}, headers=self._csrf_headers(),
        ).status_code, 403)
        with self.assertRaises(PermissionError):
            _authorize_data_manager_form_sync(
                str(dm.user_id), db.session.get(VaForms, self.FORM_ID))

    def test_project_data_manager_keeps_form_sync(self):
        from app.services.authz import Action, can
        from app.tasks.sync_tasks import _authorize_data_manager_form_sync

        dm = self._project_grant("x.dm.project.sync@test.local", VaAccessRoles.data_manager)
        self.assertTrue(can(dm, Action.SYNC_FORM, self.FORM_ID))
        _authorize_data_manager_form_sync(str(dm.user_id), db.session.get(VaForms, self.FORM_ID))

    def test_unit_only_data_manager_does_not_see_other_managers_form_runs(self):
        import json

        from app.models import MapProjectSiteOdk, VaSyncRun

        _, district, _, _, _ = self._tree()
        # dm_scoped_forms lists mapped forms only.
        db.session.add(MapProjectSiteOdk(
            project_id=self.PROJECT, site_id=self.SITE, odk_project_id=91,
            odk_form_id="CODING_SCOPE_FORM",
        ))
        self._sub("csc-x-runs", unit=district)
        dm = self._user_with("x.dm.runs@test.local", VaAccessRoles.data_manager, district)
        other = self._project_grant("x.dm.runs.other@test.local", VaAccessRoles.data_manager)
        now = datetime.now(UTC)
        for user in (other, dm):
            db.session.add(VaSyncRun(
                triggered_by="data-manager", triggered_user_id=user.user_id,
                started_at=now, status="success", records_added=7, records_updated=3,
                progress_log=json.dumps([{"msg": f"[{self.FORM_ID}] started"}]),
            ))
        db.session.commit()

        def runs_for(user):
            self._login(str(user.user_id))
            return self.client.get("/api/v1/data-management/sync/runs").get_json()["runs"]

        self.assertEqual(len([r for r in runs_for(other) if r["target"] == self.FORM_ID]), 2)
        # Only the run the unit manager triggered themselves.
        self.assertEqual(len([r for r in runs_for(dm) if r["target"] == self.FORM_ID]), 1)

    def test_dashboard_hides_form_sync_from_a_unit_only_data_manager(self):
        from tests.routes.test_data_manager_dashboard import DataManagerDashboardTests

        DataManagerDashboardTests._create_analytics_mvs(self, "ix_test_unit_dm_sync_btn")
        _, district, _, _, _ = self._tree()
        unit_dm = self._user_with("x.dm.btn@test.local", VaAccessRoles.data_manager, district)
        project_dm = self._project_grant("x.dm.btn.project@test.local", VaAccessRoles.data_manager)
        for user, shown in ((project_dm, True), (unit_dm, False)):
            self._login(str(user.user_id))
            html = self.client.get("/data-management/").get_data(as_text=True)
            with self.subTest(user=user.email):
                self.assertEqual("dm-open-sync-modal-btn" in html, shown)
