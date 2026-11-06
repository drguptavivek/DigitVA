"""The coder daily cap (digitva-fkec) and the project clock (digitva-apee).

Policy: docs/policy/coding-workflow-state-machine.md ("Coder daily allocation
limit"), docs/policy/project-clock-and-gates.md ("Project clock", "Coding gate").
"""

import uuid
from datetime import UTC, date, datetime
from unittest import mock

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
from app.models.va_allocations import ALLOCATION_KIND_DEMO, ALLOCATION_KIND_RECODE
from app.services.coder_workflow_service import (
    CODER_DAILY_CAP_MESSAGE,
    _get_excluded_sites_for_coding,
    coder_daily_cap_error,
)
from app.services.project_clock import project_day
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:3].upper()
# 19:00 UTC on 6 Nov is 00:30 IST on 7 Nov: the Kolkata day has just turned.
NOW = datetime(2026, 11, 6, 19, 0, tzinfo=UTC)
# 23:30 IST on 6 Nov, still 6 Nov in UTC.
BEFORE_IST_MIDNIGHT = datetime(2026, 11, 6, 18, 0)


class CoderDailyCapAndProjectClockTests(BaseTestCase):
    IST_PROJECT = f"IS{_SUFFIX}"
    UTC_PROJECT = f"UT{_SUFFIX}"
    SITE_ID = f"Q{_SUFFIX}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls.coder = cls._make_user(f"cap.coder.{_SUFFIX.lower()}@test.local", "CapCoder123")
        cls.forms = {}
        cls.sids = {}
        cls.project_sites = {}
        for project_id, zone in ((cls.IST_PROJECT, "Asia/Kolkata"), (cls.UTC_PROJECT, "UTC")):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, timezone=zone,
            ))
            db.session.add(VaResearchProjects(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE_ID) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE_ID, site_name="Cap site", site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE_ID, project_id=cls.IST_PROJECT, site_name="Cap site",
            site_abbr=cls.SITE_ID, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        for project_id in (cls.IST_PROJECT, cls.UTC_PROJECT):
            project_site = VaProjectSites(
                project_id=project_id, site_id=cls.SITE_ID,
                project_site_status=VaStatuses.active, coding_enabled=True,
                daily_coder_limit=1000,
                project_site_registered_at=now, project_site_updated_at=now,
            )
            db.session.add(project_site)
            db.session.flush()
            cls.project_sites[project_id] = project_site
            db.session.add(VaUserAccessGrants(
                user_id=cls.coder.user_id, role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project, project_id=project_id,
                grant_status=VaStatuses.active,
            ))
            form_id = f"F{project_id}{_SUFFIX}"[:12]
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=cls.SITE_ID,
                odk_form_id="TEST_FORM", odk_project_id="1", form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            ))
            db.session.flush()
            sid = f"uuid:cap-{project_id}"
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=form_id, va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="tester", va_odk_reviewstate=None,
                va_instance_name=sid, va_uniqueid_real=None, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English", va_deceased_age=42,
                va_deceased_gender="male", va_summary=[], va_catcount={},
                va_category_list=[],
            ))
            cls.forms[project_id] = form_id
            cls.sids[project_id] = sid
        db.session.commit()

    def setUp(self):
        super().setUp()
        patcher = mock.patch("app.services.project_clock._now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _allocate(
        self, project_id, count, at=BEFORE_IST_MIDNIGHT, user=None, kind=None, training=False
    ):
        """*count* released coding allocations in *project_id* created *at* (naive UTC)."""
        db.session.execute(sa.insert(VaAllocations), [
            {
                "va_allocation_id": uuid.uuid4(),
                "va_sid": self.sids[project_id],
                "va_allocated_to": (user or self.coder).user_id,
                "va_allocation_for": VaAllocation.coding,
                "va_allocation_status": VaStatuses.deactive,
                "va_allocation_training": training,
                "va_allocation_kind": kind,
                "va_allocation_createdat": at,
                "va_allocation_updatedat": at,
            }
            for _ in range(count)
        ])
        db.session.commit()

    def test_project_day_turns_at_the_project_midnight(self):
        self.assertEqual(
            project_day("Asia/Kolkata"),
            (date(2026, 11, 7), datetime(2026, 11, 6, 18, 30)),
        )
        self.assertEqual(project_day("UTC"), (date(2026, 11, 6), datetime(2026, 11, 6)))

    def test_cap_refuses_the_201st_and_counts_projects_separately(self):
        now_utc = NOW.replace(tzinfo=None)
        self._allocate(self.UTC_PROJECT, 199, at=now_utc)
        self.assertIsNone(coder_daily_cap_error(self.coder, self.UTC_PROJECT))

        self._allocate(self.UTC_PROJECT, 1, at=now_utc)
        self.assertEqual(
            coder_daily_cap_error(self.coder, self.UTC_PROJECT), CODER_DAILY_CAP_MESSAGE
        )
        self.assertEqual(
            CODER_DAILY_CAP_MESSAGE,
            "You have reached today's limit of 200 coding allocations in this project.",
        )
        self.assertIsNone(coder_daily_cap_error(self.coder, self.IST_PROJECT))
        excluded = _get_excluded_sites_for_coding(list(self.forms.values()), self.coder)
        self.assertEqual(excluded, {(self.UTC_PROJECT, self.SITE_ID)})

    def test_cap_resets_at_the_project_midnight(self):
        """200 allocations at 23:30 IST yesterday: Kolkata has a new day, UTC does not."""
        self._allocate(self.IST_PROJECT, 200)
        self._allocate(self.UTC_PROJECT, 200)

        self.assertIsNone(coder_daily_cap_error(self.coder, self.IST_PROJECT))
        self.assertEqual(
            coder_daily_cap_error(self.coder, self.UTC_PROJECT), CODER_DAILY_CAP_MESSAGE
        )

    def test_site_gate_dates_and_limit_use_the_project_clock(self):
        for project_site in self.project_sites.values():
            project_site.daily_coder_limit = 1
        db.session.commit()
        self._allocate(self.IST_PROJECT, 1)
        self._allocate(self.UTC_PROJECT, 1)
        form_ids = list(self.forms.values())

        # The limit: yesterday's allocation in Kolkata, today's in UTC.
        self.assertEqual(
            _get_excluded_sites_for_coding(form_ids, self.coder),
            {(self.UTC_PROJECT, self.SITE_ID)},
        )

        # The end date 6 Nov: past in Kolkata (7 Nov), today in UTC.
        for project_site in self.project_sites.values():
            project_site.daily_coder_limit = 1000
            project_site.coding_end_date = date(2026, 11, 6)
        db.session.commit()
        self.assertEqual(
            _get_excluded_sites_for_coding(form_ids, self.coder),
            {(self.IST_PROJECT, self.SITE_ID)},
        )

    def test_tester_allocations_are_not_capped(self):
        tester = self._make_user(f"cap.tester.{_SUFFIX.lower()}@test.local", "CapTester123")
        db.session.add(VaUserAccessGrants(
            user_id=tester.user_id, role=VaAccessRoles.coding_tester,
            scope_type=VaAccessScopeTypes.project, project_id=self.UTC_PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._allocate(self.UTC_PROJECT, 200, at=NOW.replace(tzinfo=None), user=tester)

        self.assertIsNone(coder_daily_cap_error(tester, self.UTC_PROJECT))
        self.assertEqual(_get_excluded_sites_for_coding([self.forms[self.UTC_PROJECT]], tester), set())

    def test_only_new_cases_count_toward_the_cap(self):
        """Recode, demo and practice (training) allocations are not counted."""
        now_utc = NOW.replace(tzinfo=None)
        self._allocate(self.UTC_PROJECT, 199, at=now_utc)
        self._allocate(self.UTC_PROJECT, 5, at=now_utc, kind=ALLOCATION_KIND_RECODE)
        self._allocate(self.UTC_PROJECT, 5, at=now_utc, kind=ALLOCATION_KIND_DEMO)
        self._allocate(self.UTC_PROJECT, 5, at=now_utc, training=True)
        self.assertIsNone(coder_daily_cap_error(self.coder, self.UTC_PROJECT))

        self._allocate(self.UTC_PROJECT, 1, at=now_utc)
        self.assertEqual(
            coder_daily_cap_error(self.coder, self.UTC_PROJECT), CODER_DAILY_CAP_MESSAGE
        )

    def test_site_tester_over_the_cap_still_picks_at_their_tester_site(self):
        """A coder of the project over the cap, coding_tester at this site: the pick
        allocator lets the tester allocation through; a plain coder is refused."""
        from app.services.coder_workflow_service import AllocationError, allocate_pick_form
        from app.services.workflow.definition import WORKFLOW_READY_FOR_CODING
        from app.services.workflow.intake_modes import CODING_INTAKE_PICK
        from app.services.workflow.state_store import set_submission_workflow_state

        project = db.session.get(VaProjectMaster, self.UTC_PROJECT)
        project.coding_intake_mode = CODING_INTAKE_PICK
        sid = self.sids[self.UTC_PROJECT]
        set_submission_workflow_state(sid, WORKFLOW_READY_FOR_CODING, by_role="vasystem")
        tester = self._make_user(f"cap.sitetester.{_SUFFIX.lower()}@test.local", "CapTester123")
        db.session.add_all([
            VaUserAccessGrants(
                user_id=tester.user_id, role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project, project_id=self.UTC_PROJECT,
                grant_status=VaStatuses.active,
            ),
            VaUserAccessGrants(
                user_id=tester.user_id, role=VaAccessRoles.coding_tester,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=self.project_sites[self.UTC_PROJECT].project_site_id,
                grant_status=VaStatuses.active,
            ),
        ])
        db.session.commit()

        # The counting is covered above; here the project is over the cap.
        with mock.patch(
            "app.services.coder_workflow_service._capped_project_ids",
            return_value={self.UTC_PROJECT},
        ):
            with self.assertRaises(AllocationError) as ctx:
                allocate_pick_form(self.coder, sid)
            self.assertEqual(ctx.exception.message, CODER_DAILY_CAP_MESSAGE)

            result = allocate_pick_form(tester, sid)
        self.assertEqual(result.va_sid, sid)
