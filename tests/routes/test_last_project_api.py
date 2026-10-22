"""last_project_id on GET /api/v1/coding/projects and GET /api/v1/reviewing/projects.

The project of the user's newest allocation for their own role (any status),
returned only when that project is among their project options. A coding
allocation never counts for reviewing and the reverse.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa

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
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:3].upper()
P1, P2, P3 = (f"L{letter}{_SUFFIX}" for letter in "ABC")  # P3 is granted to nobody
T0 = datetime(2026, 5, 1, 9, 0)  # naive, as the columns are
T1 = datetime(2026, 5, 2, 9, 0)


class LastProjectApiTests(BaseTestCase):
    @classmethod
    def _seed_project(cls, project_id, letter):
        now = datetime.now()
        site_id = f"{letter}{_SUFFIX}"  # site ids are 4 characters
        form_id = f"{project_id}{site_id}01"
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=f"Project {project_id}",
            project_nickname=project_id, coding_intake_mode="pick_and_choose",
            project_status=VaStatuses.active, demo_training_enabled=False,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.add(VaResearchProjects(
            project_id=project_id, project_code=project_id, project_name=f"Project {project_id}",
            project_nickname=project_id, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=site_id, project_id=project_id, site_name=f"Site {site_id}", site_abbr=site_id,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.add(VaForms(
            form_id=form_id, project_id=project_id, site_id=site_id,
            odk_form_id=f"FORM_{project_id}", odk_project_id="11", form_type="WHO VA 2022",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        return form_id

    @classmethod
    def _add_submission(cls, sid, form_id):
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form_id,
            va_submission_date=T0, va_odk_updatedat=T0,
            va_data_collector="Collector", va_odk_reviewstate=None,
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="English",
            va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()

    @classmethod
    def _grant(cls, user, project_id, role):
        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(VaProjectSites.project_id == project_id)
        )
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id, notes="last project test",
            grant_status=VaStatuses.active,
        ))

    @classmethod
    def _allocate(cls, user, sid, allocation_for, created_at, status=VaStatuses.active):
        db.session.add(VaAllocations(
            va_sid=sid, va_allocated_to=user.user_id, va_allocation_for=allocation_for,
            va_allocation_status=status, va_allocation_createdat=created_at,
            va_allocation_updatedat=created_at,
        ))
        db.session.flush()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        forms = {
            P1: cls._seed_project(P1, "A"),
            P2: cls._seed_project(P2, "B"),
            P3: cls._seed_project(P3, "C"),
        }
        for project_id, form_id in forms.items():
            for i in range(5):
                cls._add_submission(f"lp-{project_id}-{i}", form_id)

        def sid(project_id, i):
            return f"lp-{project_id}-{i}"

        cls.coder_two = cls._make_user(f"lp.coder2.{_SUFFIX}@test.local", "LastProject123")
        cls._grant(cls.coder_two, P1, VaAccessRoles.coder)
        cls._grant(cls.coder_two, P2, VaAccessRoles.coder)
        # One active allocation per user and kind: the older one was released.
        cls._allocate(cls.coder_two, sid(P1, 0), VaAllocation.coding, T0, VaStatuses.deactive)
        cls._allocate(cls.coder_two, sid(P2, 0), VaAllocation.coding, T1)

        # Newest coding allocation is in P3, which this coder holds no grant on.
        cls.coder_gone = cls._make_user(f"lp.codergone.{_SUFFIX}@test.local", "LastProject123")
        cls._grant(cls.coder_gone, P1, VaAccessRoles.coder)
        cls._allocate(cls.coder_gone, sid(P1, 1), VaAllocation.coding, T0, VaStatuses.deactive)
        cls._allocate(cls.coder_gone, sid(P3, 0), VaAllocation.coding, T1)

        cls.coder_none = cls._make_user(f"lp.codernone.{_SUFFIX}@test.local", "LastProject123")
        cls._grant(cls.coder_none, P1, VaAccessRoles.coder)

        # Coding allocation in P1 (older), reviewing allocation in P2 (newer).
        cls.dual = cls._make_user(f"lp.dual.{_SUFFIX}@test.local", "LastProject123")
        for project_id in (P1, P2):
            cls._grant(cls.dual, project_id, VaAccessRoles.coder)
            cls._grant(cls.dual, project_id, VaAccessRoles.reviewer)
        cls._allocate(cls.dual, sid(P1, 2), VaAllocation.coding, T0)
        cls._allocate(cls.dual, sid(P2, 1), VaAllocation.reviewing, T1)

        # Newest reviewing allocation is deactivated: any status still counts.
        cls.rev_only = cls._make_user(f"lp.revonly.{_SUFFIX}@test.local", "LastProject123")
        for project_id in (P1, P2):
            cls._grant(cls.rev_only, project_id, VaAccessRoles.reviewer)
        cls._allocate(cls.rev_only, sid(P1, 3), VaAllocation.reviewing, T0)
        cls._allocate(cls.rev_only, sid(P2, 2), VaAllocation.reviewing, T1, VaStatuses.deactive)

        cls.rev_gone = cls._make_user(f"lp.revgone.{_SUFFIX}@test.local", "LastProject123")
        cls._grant(cls.rev_gone, P1, VaAccessRoles.reviewer)
        cls._allocate(cls.rev_gone, sid(P1, 4), VaAllocation.reviewing, T0, VaStatuses.deactive)
        cls._allocate(cls.rev_gone, sid(P3, 1), VaAllocation.reviewing, T1)

        cls.rev_none = cls._make_user(f"lp.revnone.{_SUFFIX}@test.local", "LastProject123")
        cls._grant(cls.rev_none, P1, VaAccessRoles.reviewer)
        db.session.commit()

    def _get(self, user, path):
        self._login(str(user.user_id))
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def _option_ids(self, body):
        return [option["project_id"] for option in body["project_options"]]

    def test_coder_gets_project_of_most_recent_coding_allocation(self):
        body = self._get(self.coder_two, "/api/v1/coding/projects")
        self.assertEqual(self._option_ids(body), [P1, P2])
        self.assertEqual(body["last_project_id"], P2)

    def test_coder_whose_last_project_is_out_of_reach_gets_null(self):
        body = self._get(self.coder_gone, "/api/v1/coding/projects")
        self.assertEqual(self._option_ids(body), [P1])
        self.assertIsNone(body["last_project_id"])

    def test_coder_without_allocation_gets_null(self):
        body = self._get(self.coder_none, "/api/v1/coding/projects")
        self.assertEqual(self._option_ids(body), [P1])
        self.assertIsNone(body["last_project_id"])

    def test_reviewing_allocation_does_not_count_for_coding(self):
        body = self._get(self.dual, "/api/v1/coding/projects")
        self.assertEqual(body["last_project_id"], P1)

    def test_coding_allocation_does_not_count_for_reviewing(self):
        body = self._get(self.dual, "/api/v1/reviewing/projects")
        self.assertEqual(body["last_project_id"], P2)

    def test_reviewer_gets_project_of_most_recent_reviewing_allocation_any_status(self):
        body = self._get(self.rev_only, "/api/v1/reviewing/projects")
        self.assertEqual(self._option_ids(body), [P1, P2])
        self.assertEqual(body["last_project_id"], P2)

    def test_reviewer_whose_last_project_is_out_of_reach_gets_null(self):
        body = self._get(self.rev_gone, "/api/v1/reviewing/projects")
        self.assertEqual(self._option_ids(body), [P1])
        self.assertIsNone(body["last_project_id"])

    def test_reviewer_without_allocation_gets_null(self):
        body = self._get(self.rev_none, "/api/v1/reviewing/projects")
        self.assertEqual(self._option_ids(body), [P1])
        self.assertIsNone(body["last_project_id"])
