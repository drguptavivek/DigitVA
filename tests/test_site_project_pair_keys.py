"""A site_id is not unique across projects: checks key on (project_id, site_id).

One site S is linked to two projects P and Q. A grant at (P, S) must never
open, count or reopen anything of (Q, S). Bead digitva-d5s.
"""
import uuid
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
from app.services.coder_workflow_service import allocate_random_form
from app.services.sitepi_reporting_service import get_sitepi_dashboard_data
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:3].upper()


class SiteProjectPairKeyTests(BaseTestCase):
    PROJECT_P = f"PP{_SUFFIX}"
    PROJECT_Q = f"PQ{_SUFFIX}"
    SITE = f"X{_SUFFIX}"
    FORM_P = f"FP{_SUFFIX}0001"
    FORM_Q = f"FQ{_SUFFIX}0001"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.PROJECT_P, cls.PROJECT_Q):
            for model in (VaProjectMaster, VaResearchProjects):
                db.session.add(model(
                    project_id=project_id, project_code=project_id,
                    project_name=f"Pair Key {project_id}", project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE, site_abbr=cls.SITE, site_name="Shared Site",
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE, project_id=cls.PROJECT_P, site_name="Shared Site",
            site_abbr=cls.SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        cls.project_site_ids = {}
        for project_id in (cls.PROJECT_P, cls.PROJECT_Q):
            ps = VaProjectSites(
                project_id=project_id, site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
                coding_enabled=True,
            )
            db.session.add(ps)
            db.session.flush()
            cls.project_site_ids[project_id] = ps.project_site_id
        for form_id, project_id in ((cls.FORM_P, cls.PROJECT_P), (cls.FORM_Q, cls.PROJECT_Q)):
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=cls.SITE,
                odk_form_id=f"PAIR_{form_id}", odk_project_id="1",
                form_type="WHO_2022_VA", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.commit()

    def _grant(self, user, role, project_id):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=self.project_site_ids[project_id],
            notes="pair key test", grant_status=VaStatuses.active,
        ))
        db.session.flush()

    def _submission(self, sid, form_id):
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form_id, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="pairkey",
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
        db.session.flush()

    # -- Site PI dashboard --------------------------------------------------

    def test_sitepi_dashboard_counts_only_its_own_projects_submissions(self):
        self._submission("pairkey-p-1", self.FORM_P)
        self._submission("pairkey-q-1", self.FORM_Q)
        self._submission("pairkey-q-2", self.FORM_Q)
        db.session.commit()

        data = get_sitepi_dashboard_data(self.PROJECT_P, self.SITE)

        self.assertEqual(data["total_submissions"], 1)
        self.assertEqual([r["va_sid"] for r in data["submission_rows"]], ["pairkey-p-1"])

    def test_sitepi_dashboard_lists_only_coders_granted_on_its_own_pair(self):
        coder_q = self._make_user(f"pairkey.coderq{_SUFFIX.lower()}@test.local", "PairKey123")
        self._grant(coder_q, VaAccessRoles.coder, self.PROJECT_Q)
        db.session.commit()

        names_q = [r["coder_name"] for r in get_sitepi_dashboard_data(self.PROJECT_Q, self.SITE)["coder_kpis"]]
        names_p = [r["coder_name"] for r in get_sitepi_dashboard_data(self.PROJECT_P, self.SITE)["coder_kpis"]]
        self.assertIn(coder_q.name, names_q)
        self.assertNotIn(coder_q.name, names_p)

    def test_sitepi_route_refuses_the_same_site_in_another_project(self):
        pi = self._make_user(f"pairkey.pi{_SUFFIX.lower()}@test.local", "PairKey123")
        self._grant(pi, VaAccessRoles.site_pi, self.PROJECT_P)
        db.session.commit()
        self._login(str(pi.user_id))

        dashboard = self.client.get("/sitepi/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(f"{self.PROJECT_P}:{self.SITE}".encode(), dashboard.data)
        self.assertNotIn(f"{self.PROJECT_Q}:{self.SITE}".encode(), dashboard.data)

        own = self.client.get(f"/sitepi/data?siteSelect={self.PROJECT_P}:{self.SITE}")
        self.assertEqual(own.status_code, 200)
        other = self.client.get(f"/sitepi/data?siteSelect={self.PROJECT_Q}:{self.SITE}")
        self.assertEqual(other.status_code, 403)
        bare = self.client.get(f"/sitepi/data?siteSelect={self.SITE}")
        self.assertEqual(bare.status_code, 403)

    # -- Random allocation site gate ------------------------------------------

    def test_a_closed_site_in_one_project_does_not_close_it_in_another(self):
        coder = self._make_user(f"pairkey.coder{_SUFFIX.lower()}@test.local", "PairKey123")
        self._grant(coder, VaAccessRoles.coder, self.PROJECT_P)
        self._grant(coder, VaAccessRoles.coder, self.PROJECT_Q)
        db.session.execute(
            sa.update(VaProjectSites)
            .where(VaProjectSites.project_site_id == self.project_site_ids[self.PROJECT_Q])
            .values(coding_enabled=False)
        )
        self._submission("pairkey-p-open", self.FORM_P)
        self._submission("pairkey-q-closed", self.FORM_Q)
        db.session.commit()
        db.session.refresh(coder)

        result = allocate_random_form(coder)

        self.assertEqual(result.va_sid, "pairkey-p-open")
