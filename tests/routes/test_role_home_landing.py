"""Login landing for the role home (docs/policy/expo-client.md, "Role home and login landing").

Roster rows follow docs/current-state/test-project-tst001.md. A field, coding
or data manager role lands on the Expo role home at /app/ while the export is
present; without the export, the old landing applies. admin, project_pi and
collaborators keep today's landing. Effective roles come from authz, so a
site_pi held at an org unit (the In-charge) derives data_manager and
interview_supervisor.
"""
from datetime import UTC, datetime
from unittest import mock

from flask import url_for

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

R = VaAccessRoles
PROJECT, SITE = "RLH001", "RL01"
PASSWORD = "Landing123"


class RoleHomeLandingTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=PROJECT, project_code=PROJECT, project_name=PROJECT, project_nickname=PROJECT,
            project_status=VaStatuses.active, project_registered_at=now, project_updated_at=now,
            web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=SITE, site_name=SITE, site_abbr=SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=PROJECT, site_id=SITE, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(PROJECT, SITE)
        org.seed_default_organization(PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(PROJECT)}

        def unit(code, level, parent=None):
            return org.create_unit(
                PROJECT, org_level_id=levels[level].org_level_id,
                parent_org_unit_id=parent.org_unit_id if parent else None, unit_code=code, unit_name=code,
            )

        dst = unit("DST", "district")
        cls.ch1 = unit("CH1", "chc", dst)
        cls.ph1 = unit("PH1", "phc", cls.ch1)
        cls.sca = unit("SCA", "subcentre", cls.ph1)
        db.session.commit()

    def setUp(self):
        super().setUp()
        # The export is a build artifact; these tests assume it is present.
        patcher = mock.patch("app.routes.expo_client.export_ready", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _user(self, key, *grants):
        """*grants* are (role, unit-or-None); None is a project-scope grant."""
        user = self._get_or_make_user(f"rlh.{key}@test.local", PASSWORD)
        for role, unit in grants:
            if role == R.admin:
                scope = dict(scope_type=VaAccessScopeTypes.global_scope)
            elif unit is None:
                scope = dict(scope_type=VaAccessScopeTypes.project, project_id=PROJECT)
            else:
                scope = dict(scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id)
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, grant_status=VaStatuses.active, **scope,
            ))
        db.session.commit()
        return user

    def _landing(self, user):
        with self.app.test_request_context():
            return db.session.get(VaUsers, user.user_id).landing_url()

    def _app_url(self):
        with self.app.test_request_context():
            return url_for("expo_client.expo_index")

    def test_field_and_coding_roles_land_on_the_role_home(self):
        app_url = self._app_url()
        cases = {
            "death_reporter": [(R.death_reporter, self.sca)],
            "interviewer": [(R.interviewer, self.sca)],
            "interview_supervisor": [(R.interview_supervisor, self.ch1)],
            "coder": [(R.coder, self.ch1)],
            "reviewer": [(R.reviewer, self.ch1)],
            "supervisor_coder": [(R.interview_supervisor, self.ch1), (R.coder, self.ch1)],
            "supervisor_reviewer": [(R.interview_supervisor, self.ch1), (R.reviewer, self.ch1)],
        }
        for key, grants in cases.items():
            with self.subTest(roster=key):
                user = self._user(key, *grants)
                self.assertEqual(self._landing(user), app_url)

    def test_a_data_manager_alone_lands_on_the_role_home(self):
        user = self._user("dm", (R.data_manager, None))
        self.assertEqual(self._landing(user), self._app_url())

    def test_without_the_export_a_coder_keeps_the_old_landing(self):
        user = self._user("coder_no_export", (R.coder, self.ch1))
        with mock.patch("app.routes.expo_client.export_ready", return_value=False):
            with self.app.test_request_context():
                expected = url_for("coding.dashboard")
            self.assertEqual(self._landing(user), expected)

    def test_a_data_manager_with_a_field_role_lands_on_the_role_home(self):
        user = self._user("dm_coder", (R.data_manager, None), (R.coder, self.ch1))
        self.assertEqual(self._landing(user), self._app_url())

    def test_an_in_charge_at_a_unit_lands_on_the_role_home(self):
        # site_pi at a unit derives data_manager and interview_supervisor (authz).
        user = self._user("in_charge", (R.site_pi, self.ch1))
        self.assertEqual(self._landing(user), self._app_url())

    def test_admin_project_pi_and_collaborators_land_on_the_role_home(self):
        # Owner 2026-10-22 (digitva-7kez): every user lands on /app/ when the
        # export exists; their old landing stays as the no-export fallback.
        cases = {
            "admin": ((R.admin, None), "va_main.va_index"),
            "project_pi": ((R.project_pi, None), "data_management.dashboard"),
            "collaborator_pii": ((R.collaborator_pii, None), "data_management.dashboard"),
        }
        for key, (grant, endpoint) in cases.items():
            with self.subTest(roster=key):
                user = self._user(key, grant)
                self.assertEqual(self._landing(user), self._app_url())
                with mock.patch("app.routes.expo_client.export_ready", return_value=False):
                    with self.app.test_request_context():
                        expected = url_for(endpoint)
                    self.assertEqual(self._landing(user), expected)

    def test_the_new_death_page_opens_for_a_death_reporter(self):
        user = self._user("reporter_page", (R.death_reporter, self.sca))
        self._login(str(user.user_id))
        self.assertEqual(self.client.get("/intake/deaths/new").status_code, 200)

    def test_a_death_reporter_has_a_report_a_death_menu_link(self):
        # Owner, 2026-10-14: death reporters reach the web form from the top menu.
        link = 'href="/intake/deaths/new"'
        reporter = self._user("reporter_menu", (R.death_reporter, self.sca))
        self._login(str(reporter.user_id))
        page = self.client.get("/help").get_data(as_text=True)
        self.assertIn(link, page)
        self.assertIn("Report a death", page)

        coder = self._user("coder_menu", (R.coder, self.ch1))
        self._login(str(coder.user_id))
        self.assertNotIn(link, self.client.get("/help").get_data(as_text=True))

    def test_the_new_death_page_refuses_a_user_with_neither_role(self):
        user = self._user("coder_page", (R.coder, self.ch1))
        self._login(str(user.user_id))
        self.assertEqual(self.client.get("/intake/deaths/new").status_code, 403)

    def test_user_with_no_roles_lands_on_the_role_home(self):
        user = self._user("no_roles")
        self.assertEqual(self._landing(user), self._app_url())
        with mock.patch("app.routes.expo_client.export_ready", return_value=False):
            with self.app.test_request_context():
                expected = url_for("va_main.va_index")
            self.assertEqual(self._landing(user), expected)

    def test_force_password_change_redirects_to_landing_url(self):
        user = self._user("new_onboarded_user")
        user.pw_reset_t_and_c = False
        db.session.commit()
        self._login(str(user.user_id))
        resp = self.client.post(
            "/profile/force-password-change",
            data={"accept_terms": "y"},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], self._app_url())
