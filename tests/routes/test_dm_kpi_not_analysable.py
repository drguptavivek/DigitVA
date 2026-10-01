"""DM KPI "Not analysable": one bucket with a per-reason split.

Policy: docs/policy/kpis.md (C-06). Every ``consent_refused`` row counts;
the reason is the active payload's ``interview_outcome``, and a payload
without one (every ODK submission) is Refused.
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
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED, WORKFLOW_CONSENT_REFUSED
from tests.base import BaseTestCase


class DmKpiNotAnalysableTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}08"
    #: sid -> (workflow state, interview_outcome in the payload or None)
    SEED = {
        "uuid:na-web-refused": (WORKFLOW_CONSENT_REFUSED, "refused"),
        "uuid:na-web-unavailable": (WORKFLOW_CONSENT_REFUSED, "respondent_unavailable"),
        "uuid:na-web-partial-1": (WORKFLOW_CONSENT_REFUSED, "partially_completed"),
        "uuid:na-web-partial-2": (WORKFLOW_CONSENT_REFUSED, "partially_completed"),
        "uuid:na-odk-no-consent": (WORKFLOW_CONSENT_REFUSED, None),
        "uuid:na-coded": (WORKFLOW_CODER_FINALIZED, None),
    }

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
                odk_form_id="DM_KPI_NA_FORM",
                odk_project_id="72",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()
        for sid, (state, outcome) in cls.SEED.items():
            db.session.add(
                VaSubmissions(
                    va_sid=sid,
                    va_form_id=cls.FORM_ID,
                    va_submission_date=now,
                    va_odk_updatedat=now,
                    va_odk_reviewstate="approved",
                    va_data_collector="Collector",
                    va_instance_name=sid,
                    va_uniqueid_real=sid,
                    va_uniqueid_masked=f"masked-{sid[-8:]}",
                    va_consent="no" if state == WORKFLOW_CONSENT_REFUSED else "yes",
                    va_narration_language="English",
                    va_deceased_age=55,
                    va_deceased_gender="female",
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                )
            )
            db.session.flush()
            version = VaSubmissionPayloadVersion(
                va_sid=sid,
                payload_fingerprint=f"fp-{sid}",
                payload_data={"interview_outcome": outcome} if outcome else {},
                version_status="active",
                created_by_role="vasystem",
            )
            db.session.add(version)
            db.session.flush()
            db.session.get(VaSubmissions, sid).active_payload_version_id = version.payload_version_id
            db.session.add(
                VaSubmissionWorkflow(
                    va_sid=sid,
                    workflow_state=state,
                    workflow_reason="test_seed",
                    workflow_updated_by_role="vasystem",
                )
            )
        db.session.commit()

    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex[:8]
        dm_user = VaUsers(
            user_id=uuid.uuid4(),
            name=f"dmkpi.{suffix}",
            email=f"dmkpi.{suffix}@example.com",
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
                notes="dm kpi retired grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(dm_user.user_id))

    def _kpi(self, path: str) -> dict:
        response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def test_rates_bucket_every_not_analysable_interview_with_a_reason_split(self):
        rates = self._kpi("exclusions/rates")
        bucket = rates["not_analysable"]

        self.assertEqual(bucket["count"], 5)
        self.assertEqual(
            bucket["by_reason"],
            {"refused": 2, "respondent_unavailable": 1, "partially_completed": 2},
        )
        # Backward compatibility: the old key still carries the same count.
        self.assertEqual(rates["consent_refused"]["count"], 5)
        self.assertEqual(rates["all_synced"], 6)
