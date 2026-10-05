"""DM KPIs tell an interviewer send-back/reopen from an ODK upstream change.

digitva-jcll. Both reuse workflow state ``finalized_upstream_changed``; the
latest workflow event's reason splits them (docs/policy/kpis.md C-10, C-11,
D-WT-04, D-WF-03). Cases: tests/revision_request_fixtures.py.
"""

import uuid
from datetime import datetime, timezone

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from tests.base import BaseTestCase
from tests.revision_request_fixtures import seed_revision_cases


class DmKpiRevisionRequestTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}22"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        cls._ensure_base_research_project_and_site()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="DM_KPI_REVISION_FORM",
                odk_project_id="73",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()
        cls.sids = seed_revision_cases(cls.FORM_ID, cls.base_coder_user.user_id, now, prefix="dmkpirev")
        db.session.commit()

    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex[:8]
        dm_user = VaUsers(
            user_id=uuid.uuid4(),
            name=f"dmrev.{suffix}",
            email=f"dmrev.{suffix}@example.com",
            vacode_language=["English"],
            permission={},
            landing_page="data_manager",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        dm_user.set_password("DataManager123")
        db.session.add(dm_user)
        db.session.flush()
        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=dm_user.user_id,
                role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="dm kpi revision grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(dm_user.user_id))

    def _kpi(self, path: str) -> dict:
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def test_flowchart_counts_the_two_kinds_apart(self):
        stages = self._kpi("workflow/flowchart")["stages"]

        self.assertEqual(stages["upstream_changed"], 3)  # odk, legacy, odk_after
        self.assertEqual(stages["sent_back"], 2)  # sent_back, reopened
        # Both kinds were coded: coded + 3 + 2 (restarted is back in coding).
        self.assertEqual(stages["coded"], 6)

    def test_stagnation_has_its_own_row_for_sent_back_cases(self):
        alerts = {a["state"]: a for a in self._kpi("workflow/stagnation")["alerts"]}

        self.assertEqual(alerts["finalized_upstream_changed"]["total"], 3)
        sent_back = alerts["sent_back_for_revision"]
        self.assertEqual(sent_back["total"], 2)
        self.assertEqual(sent_back["label"], "Sent Back for Revision")
        self.assertEqual(sent_back["dm_action"], "Wait for the interviewer or cancel the request")

    def test_daily_transitions_map_revision_events_to_the_virtual_state(self):
        days = self._kpi("workflow/daily-transitions?days=7")["days"]
        totals: dict[str, int] = {}
        for day in days:
            for state, count in day["transitions"].items():
                totals[state] = totals.get(state, 0) + count

        # Events into fuc: ODK = odk, odk_after, dm_reopen; revision = sent_back,
        # reopened, odk_after (its earlier send-back), restarted.
        self.assertEqual(totals["finalized_upstream_changed"], 3)
        self.assertEqual(totals["sent_back_for_revision"], 4)

    def test_c10_queue_is_odk_only_and_the_sent_back_count_is_apart(self):
        data = self._kpi("pipeline/upstream-changes")

        self.assertEqual(data["c10_queue_count"], 3)
        self.assertEqual(data["c10_sent_back_count"], 2)

    def test_c11_counts_only_odk_detected_events(self):
        data = self._kpi("pipeline/upstream-changes")

        self.assertEqual(data["c11_total_coded"], 6)
        # odk and odk_after; sent_back, reopened, legacy carry no ODK event, and
        # dm_reopen is no longer in a coded state.
        self.assertEqual(data["c11_with_upstream"], 2)

    def test_d_wt_04_excludes_interviewer_revision_restarts(self):
        data = self._kpi("pipeline/upstream-changes")

        self.assertEqual(data["d_wt_04_reopened_7d"], 1)  # the data manager's accept
        self.assertEqual(data["d_wt_04_revision_restarts_7d"], 1)  # the interviewer's revision
        self.assertEqual(data["d_wt_04_finalized_7d"], 7)
        self.assertEqual(data["d_wt_04_reopen_rate"], round(1 / 7 * 100, 1))

    def test_d_wt_02_resolution_time_is_unchanged(self):
        # No resolved upstream-change rows: send-backs never had one.
        self.assertIsNone(self._kpi("pipeline/upstream-changes")["d_wt_02_resolution_p50_seconds"])

    def test_blocked_forms_split_the_upstream_category(self):
        data = self._kpi("exclusions/blocked")
        by_reason = {b["blockage_reason"]: b for b in data["breakdown"]}

        self.assertEqual(by_reason["finalized_upstream_changed"]["count"], 3)
        self.assertEqual(by_reason["finalized_upstream_changed"]["label"], "Upstream change pending")
        self.assertEqual(by_reason["sent_back_for_revision"]["count"], 2)
        self.assertEqual(by_reason["sent_back_for_revision"]["label"], "Sent back for revision")
        self.assertEqual(
            by_reason["sent_back_for_revision"]["dm_action"],
            "Wait for the interviewer or cancel the request",
        )
        # Five fuc rows plus the one smartva_pending row; the split adds nothing.
        self.assertEqual(data["total_blocked"], 6)
