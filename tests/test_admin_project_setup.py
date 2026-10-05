"""Project Setup home panel (epic digitva-r1p).

One page per project: admin only (the Projects panel's gate), 404 for an
unknown project, and each section hosts an existing panel locked to that
project (its template included, not copied). The panels' scripts find their
elements by id, so every panel appears once and no id repeats on the page.
"""

import re
from collections import Counter
from datetime import UTC, datetime

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase

# Plain ids only; ids built in JS string concatenation are not page ids.
_ID_RE = re.compile(r'\sid="([A-Za-z][\w-]*)"')


class ProjectSetupPanelTests(BaseTestCase):
    ORG_PROJECT = "SETOR1"
    OTHER_PROJECT = "SETOT1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, mode in ((cls.ORG_PROJECT, "organization"), (cls.OTHER_PROJECT, "sites")):
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Setup {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                    project_structure_mode=mode,
                )
            )
        db.session.commit()

    def _setup_body(self, project_id=None):
        self._login(self.base_admin_id)
        response = self.client.get(self._url(project_id))
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _url(self, project_id=None):
        return f"/admin/panels/project-setup/{project_id or self.BASE_PROJECT_ID}"

    def test_it_redirects_unauthenticated(self):
        self.assertIn(self.client.get(self._url()).status_code, [301, 302])

    def test_a_project_pi_is_refused_even_for_their_own_project(self):
        self._login(self.base_project_pi_id)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_a_coder_is_refused(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_an_unknown_project_is_404(self):
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(self._url("NOPE99")).status_code, 404)

    def test_it_renders_for_an_admin(self):
        self._login(self.base_admin_id)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        body = response.get_data(as_text=True)
        for marker in (
            'id="panel-project-setup"',
            f'data-project-id="{self.BASE_PROJECT_ID}"',
            "/web-intake-readiness",
            "Active sites",
            'data-section="overview"',
            'data-section="basics"',
            'data-section="sync"',
            'id="panel-project-forms"',
            'id="panel-access-grants"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_basics_embeds_the_projects_form_locked_to_the_project(self):
        self._login(self.base_admin_id)
        body = self.client.get(self._url()).get_data(as_text=True)
        self.assertIn(f'data-locked-project="{self.BASE_PROJECT_ID}"', body)
        self.assertIn('id="project-submit-btn"', body)
        # One form, not a copy: the Projects panel's form ids appear once.
        self.assertEqual(body.count('id="project-name-input"'), 1)

    def test_the_projects_panel_itself_is_not_locked(self):
        self._login(self.base_admin_id)
        body = self.client.get("/admin/panels/projects").get_data(as_text=True)
        self.assertIn('data-locked-project=""', body)
        self.assertIn("project-setup-btn", body)

    def test_the_shell_restores_a_setup_panel_from_the_url(self):
        self._login(self.base_admin_id)
        body = self.client.get("/admin/").get_data(as_text=True)
        self.assertIn(r"^\/admin\/panels\/project-setup\/[A-Za-z0-9_-]+$", body)

    # -- phase 2: Structure and Coding -----------------------------------------

    def test_no_id_repeats_on_the_setup_page(self):
        for project_id in (self.BASE_PROJECT_ID, self.ORG_PROJECT):
            with self.subTest(project=project_id):
                ids = _ID_RE.findall(self._setup_body(project_id))
                self.assertIn("panel-project-setup", ids)
                repeated = [i for i, n in Counter(ids).items() if n > 1]
                self.assertEqual(repeated, [])

    def test_sites_project_structure_hosts_project_sites_locked(self):
        body = self._setup_body()
        self.assertEqual(body.count('id="panel-project-sites"'), 1)
        self.assertIn(
            f'id="panel-project-sites" data-locked-project="{self.BASE_PROJECT_ID}"', body
        )
        # A sites project has no organization tree.
        self.assertNotIn('id="panel-organization"', body)
        self.assertNotIn('id="setup-coding-scope-slot"', body)
        # Coding points at the site coding gate hosted under Structure.
        self.assertIn('data-jump-to="panel-project-sites"', body)

    def test_org_project_structure_hosts_organization_and_sites_locked(self):
        body = self._setup_body(self.ORG_PROJECT)
        self.assertIn(
            f'id="panel-organization" class="org-no-project" data-locked-project="{self.ORG_PROJECT}"',
            body,
        )
        self.assertIn(
            f'id="panel-project-sites" data-locked-project="{self.ORG_PROJECT}"', body
        )
        # The org script opens on the locked project, not ?project_id=.
        self.assertIn(f'var PROJECT_ID = "{self.ORG_PROJECT}";', body)
        # Coding scope is moved into Coding; unit gates are reached from Coding.
        self.assertIn('id="org-coding-scope"', body)
        self.assertIn('id="setup-coding-scope-slot"', body)
        self.assertIn('data-jump-org-tab="units"', body)
        self.assertNotIn(f'data-locked-project="{self.BASE_PROJECT_ID}"', body)

    def test_readiness_coding_scope_links_to_coding(self):
        self.assertIn("coding_scope: 'coding'", self._setup_body())

    def test_standalone_structure_panels_are_not_locked(self):
        self._login(self.base_admin_id)
        for url, root in (
            ("/admin/panels/project-sites", "panel-project-sites"),
            (f"/admin/panels/organization?project_id={self.ORG_PROJECT}", "panel-organization"),
        ):
            with self.subTest(url=url):
                body = self.client.get(url).get_data(as_text=True)
                self.assertIn(f'id="{root}"', body)
                self.assertIn('data-locked-project=""', body)
        org_body = self.client.get(
            f"/admin/panels/organization?project_id={self.ORG_PROJECT}"
        ).get_data(as_text=True)
        self.assertIn(f'var PROJECT_ID = "{self.ORG_PROJECT}";', org_body)
        self.assertIn("Pick an organization-mode project above", org_body)

    # -- phase 3: Data collection and People -----------------------------------

    def test_data_collection_and_people_host_their_panels_locked(self):
        body = self._setup_body()
        for root in (
            "panel-project-forms",
            "panel-odk-connections",
            "panel-access-grants",
            "panel-people-roles",
            "panel-project-pi",
        ):
            with self.subTest(panel=root):
                self.assertEqual(body.count(f'id="{root}"'), 1)
                self.assertIn(
                    f'id="{root}" data-locked-project="{self.BASE_PROJECT_ID}"', body
                )
        self.assertNotIn(f'data-locked-project="{self.OTHER_PROJECT}"', body)
        # The PI assign form's project is fixed to this one.
        self.assertIn(
            f'<option value="{self.BASE_PROJECT_ID}" selected>{self.BASE_PROJECT_ID}</option>',
            body,
        )

    def test_standalone_data_and_people_panels_are_not_locked(self):
        self._login(self.base_admin_id)
        for url, root in (
            ("/admin/panels/project-forms", "panel-project-forms"),
            ("/admin/panels/odk-connections", "panel-odk-connections"),
            ("/admin/panels/access-grants", "panel-access-grants"),
            ("/admin/panels/project-pi", "panel-project-pi"),
        ):
            with self.subTest(url=url):
                body = self.client.get(url).get_data(as_text=True)
                self.assertIn(f'id="{root}" data-locked-project=""', body)
        pi_body = self.client.get("/admin/panels/project-pi").get_data(as_text=True)
        self.assertIn("Loading projects…", pi_body)

    def test_the_grants_list_the_people_section_loads_is_the_projects_own(self):
        other = VaUserAccessGrants(
            user_id=self.base_coder_user.user_id,
            role=VaAccessRoles.project_pi,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.OTHER_PROJECT,
            notes="other project pi",
            grant_status=VaStatuses.active,
        )
        db.session.add(other)
        db.session.commit()
        self._login(self.base_admin_id)

        def grant_ids(project_id):
            response = self.client.get(f"/admin/api/access-grants?project_id={project_id}")
            self.assertEqual(response.status_code, 200)
            return {g["grant_id"] for g in response.get_json()["grants"]}

        self.assertIn(str(other.grant_id), grant_ids(self.OTHER_PROJECT))
        base_ids = grant_ids(self.BASE_PROJECT_ID)
        self.assertTrue(base_ids)
        self.assertNotIn(str(other.grant_id), base_ids)

    # -- phase 4: Sync & activity ------------------------------------------------

    def test_sync_section_hosts_attachments_locked_and_lazy_activity(self):
        body = self._setup_body()
        self.assertIn(
            f'id="panel-attachments" data-locked-project="{self.BASE_PROJECT_ID}"', body
        )
        # The overview is fetched for this project: its filter holds only it.
        self.assertIn(
            f'<option value="{self.BASE_PROJECT_ID}" selected>{self.BASE_PROJECT_ID}</option>',
            body,
        )
        self.assertIn('id="att-s3-upload-card"', body)
        self.assertIn(
            f'hx-get="/admin/panels/activity?project_id={self.BASE_PROJECT_ID}&locked=1"',
            body,
        )
        # Data Sync is app-wide: linked, not hosted.
        self.assertIn('data-panel-link="/admin/panels/sync"', body)
        self.assertNotIn('id="panel-sync"', body)

    def test_standalone_attachments_panel_is_not_locked(self):
        self._login(self.base_admin_id)
        body = self.client.get("/admin/panels/attachments").get_data(as_text=True)
        self.assertIn('id="panel-attachments" data-locked-project=""', body)
        self.assertIn('<option value="">All projects</option>', body)
        self.assertNotIn(' d-none" id="att-s3-upload-card"', body)

    def test_locked_activity_is_pinned_and_swaps_in_place(self):
        self._login(self.base_admin_id)
        body = self.client.get(
            f"/admin/panels/activity?project_id={self.BASE_PROJECT_ID}&locked=1"
        ).get_data(as_text=True)
        self.assertIn(f'data-locked-project="{self.BASE_PROJECT_ID}"', body)
        self.assertIn(
            f'<input type="hidden" name="project_id" value="{self.BASE_PROJECT_ID}">', body
        )
        self.assertIn('hx-target="#setup-activity"', body)
        self.assertNotIn('hx-target="#admin-panel"', body)

    def test_standalone_activity_is_not_locked(self):
        self._login(self.base_admin_id)
        body = self.client.get(
            f"/admin/panels/activity?project_id={self.BASE_PROJECT_ID}"
        ).get_data(as_text=True)
        self.assertIn('data-locked-project=""', body)
        self.assertIn('hx-target="#admin-panel"', body)
        self.assertNotIn('hx-target="#setup-activity"', body)
        self.assertNotIn('name="locked"', body)

    def test_the_attachments_overview_the_sync_section_loads_is_the_projects_own(self):
        self._login(self.base_admin_id)

        def project_ids(project_id):
            response = self.client.get(f"/admin/api/attachments/overview?project_id={project_id}")
            self.assertEqual(response.status_code, 200)
            return {p["project_id"] for p in response.get_json()["projects"]}

        everything = self.client.get("/admin/api/attachments/overview").get_json()
        all_ids = {p["project_id"] for p in everything["projects"]}
        self.assertIn(self.OTHER_PROJECT, all_ids)
        self.assertIn(self.BASE_PROJECT_ID, all_ids)
        self.assertEqual(project_ids(self.BASE_PROJECT_ID), {self.BASE_PROJECT_ID})

    def test_locked_activity_offers_only_the_projects_sites(self):
        now = datetime.now(UTC)
        self._ensure_base_research_project_and_site()
        db.session.add(
            VaResearchProjects(
                project_id=self.OTHER_PROJECT,
                project_code=self.OTHER_PROJECT,
                project_name="Other research",
                project_nickname="Other",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id="SO01",
                project_id=self.OTHER_PROJECT,
                site_name="Other site",
                site_abbr="SO01",
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        for form_id, project_id, site_id in (
            ("BASE01BS0101", self.BASE_PROJECT_ID, self.BASE_SITE_ID),
            ("SETOT1SO0101", self.OTHER_PROJECT, "SO01"),
        ):
            db.session.add(
                VaForms(
                    form_id=form_id,
                    project_id=project_id,
                    site_id=site_id,
                    odk_form_id=form_id,
                    odk_project_id="1",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.commit()
        self._login(self.base_admin_id)
        url = f"/admin/panels/activity?project_id={self.BASE_PROJECT_ID}"

        unlocked = self.client.get(url).get_data(as_text=True)
        self.assertIn(f'<option value="{self.BASE_SITE_ID}"', unlocked)
        self.assertIn('<option value="SO01"', unlocked)

        locked = self.client.get(url + "&locked=1").get_data(as_text=True)
        self.assertIn(f'<option value="{self.BASE_SITE_ID}"', locked)
        self.assertNotIn('<option value="SO01"', locked)
