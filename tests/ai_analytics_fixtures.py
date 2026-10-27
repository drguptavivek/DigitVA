"""Shared fixtures for the AI analytics questions tests (digitva-qwvt).

One project with two active sites, a submission in site A and two in site B,
the analytics MVs built over them, the reader role and ``digitva_ai_run``,
and a data manager granted site A only. Site B also holds a submission
retired from ODK (``RETIRED_SID``) and one whose web case is a confirmed
duplicate (``DUPLICATE_SID``); a second project, ``TRAINING_PROJECT_ID``,
holds one submission for the training-exclusion test. None of the three may
reach the cube, so site B still counts 2. ``sandbox_on_session_connection``
points the sandbox at the session's connection, where these uncommitted
fixtures live (the real one opens a pooled connection of its own).
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
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
from app.models.va_allocations import VaAllocations
from app.models.va_coder_review import VaCoderReview
from app.models.va_final_assessments import VaFinalAssessments
from app.models.va_reviewer_final_assessments import VaReviewerFinalAssessments
from app.models.va_selectives import VaAllocation
from app.models.va_smartva_results import VaSmartvaResults
from app.services.ai_analytics_sandbox import READER_SETUP_SQL
from app.services.submission_analytics_mv import (
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_snapshot_mv_sql,
)

PROJECT_ID = "AIQ001"
SITE_A = "AQ01"
SITE_B = "AQ02"
TRAINING_PROJECT_ID = "AIQTRN"
SITE_T = "AQ03"
RETIRED_SID = "uuid:ai-questions-retired"
DUPLICATE_SID = "uuid:ai-questions-duplicate"
TRAINING_SID = "uuid:ai-questions-training"
SID_A = "uuid:ai-questions-0"
SID_B = "uuid:ai-questions-1"
DISTRICT_ONE = "AI District One"
DISTRICT_TWO = "AI District Two"
SUBCENTRE_ONE = "AI Sub-centre One"
SUBCENTRE_TWO = "AI Sub-centre Two"
# Coder A's final on SID_A, 2 minutes after the allocation; coder B's on
# SID_B, 10 minutes after.
FINAL_AT = datetime(2026, 9, 15, 10, 0, 0)


@contextmanager
def _session_connection():
    yield db.session.connection()


def sandbox_on_session_connection():
    return mock.patch(
        "app.services.ai_analytics_sandbox._sandbox_connection", _session_connection
    )


class AiAnalyticsFixtures:
    """Mixin for a ``BaseTestCase``: call ``_seed_ai_fixtures`` in setUpClass."""

    @classmethod
    def _seed_ai_fixtures(cls, *, with_staff=False):
        # The role is cluster-wide: create it committed, as the migration does,
        # so parallel workers never wait on one another's open transaction.
        with db.engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                sa.text(READER_SETUP_SQL)
            )

        now = datetime.now(UTC)
        for project_id in (PROJECT_ID, TRAINING_PROJECT_ID):
            for model in (VaResearchProjects, VaProjectMaster):
                db.session.add(model(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"AI Questions Project {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ))
        db.session.flush()
        cls.forms = {}
        for project_id, site_id in ((PROJECT_ID, SITE_A), (PROJECT_ID, SITE_B), (TRAINING_PROJECT_ID, SITE_T)):
            db.session.add(VaSites(
                site_id=site_id, project_id=project_id, site_name=f"AI site {site_id}",
                site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=f"AI site {site_id}", site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.flush()
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            form_id = f"{project_id}{site_id}01"
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=site_id,
                odk_form_id=f"AIQ_{site_id}", odk_project_id="31", form_type="WHO VA 2022",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
            cls.forms[site_id] = form_id
        db.session.flush()
        sids = [(f"uuid:ai-questions-{i}", site) for i, site in enumerate((SITE_A, SITE_B, SITE_B))]
        sids += [(RETIRED_SID, SITE_B), (DUPLICATE_SID, SITE_B), (TRAINING_SID, SITE_T)]
        for sid, site_id in sids:
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=cls.forms[site_id], va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="ai", va_odk_reviewstate="approved",
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English", va_deceased_age=40,
                va_deceased_gender="male", va_summary=[], va_catcount={}, va_category_list=[],
                va_sync_issue_code="missing_in_odk" if sid == RETIRED_SID else None,
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state="ready_for_coding", workflow_reason="test",
                workflow_updated_by_role="vasystem",
            ))
        db.session.flush()
        db.session.add(VaDeathRegister(
            project_id=PROJECT_ID, site_id=SITE_B, death_number=990001,
            unique_id=f"{SITE_B}-990001", va_sid=DUPLICATE_SID,
            registered_by=cls.base_admin_user.user_id, source="register", status="duplicate",
            deceased_name="Duplicate Case", deceased_sex="male", date_of_death=now.date(),
        ))
        db.session.flush()

        cls.dm_user = cls._make_user(f"ai.dm.{uuid.uuid4().hex[:8]}@test.local", "AiDm12345")
        cls.other_dm_user = cls._make_user(f"ai.dm2.{uuid.uuid4().hex[:8]}@test.local", "AiDm12345")
        for user in (cls.dm_user, cls.other_dm_user):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id,
                role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=db.session.scalar(
                    sa.select(VaProjectSites.project_site_id).where(
                        VaProjectSites.project_id == PROJECT_ID,
                        VaProjectSites.site_id == SITE_A,
                    )
                ),
                notes="ai questions test",
                grant_status=VaStatuses.active,
            ))
        db.session.flush()
        if with_staff:
            cls._seed_ai_staff(now)

        for mv in (COD_SNAPSHOT_MV_NAME, DEMOGRAPHICS_MV_NAME, CORE_MV_NAME):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(sa.text(build_submission_cod_snapshot_mv_sql(icd11_buckets=True)))
        db.session.commit()

    @classmethod
    def _grant(cls, user, role, *, site_id=None, org_unit_id=None):
        project_site_id = None
        if site_id is not None:
            project_site_id = db.session.scalar(
                sa.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == PROJECT_ID, VaProjectSites.site_id == site_id,
                )
            )
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.org_unit if org_unit_id else VaAccessScopeTypes.project_site,
            project_site_id=project_site_id,
            org_unit_id=org_unit_id,
            notes="ai questions test",
            grant_status=VaStatuses.active,
        ))

    @classmethod
    def _seed_ai_staff(cls, now):
        """A two-level tree (district, sub-centre), the site A and B cases
        routed to sub-centres One and Two, interviewers granted at each
        sub-centre, a unit data manager over district One, and a coder per
        site with one final each (coder A's with DORIS flags, a reviewer
        change, a matching SmartVA ICD at low likelihood and a not-codeable
        mark)."""
        levels = {}
        for depth, name in ((1, "District"), (2, "Sub-centre")):
            level = MasOrgLevel(project_id=PROJECT_ID, level_code=f"L{depth}", level_name=name, depth=depth)
            db.session.add(level)
            levels[depth] = level
        db.session.flush()
        cls.units = {}
        for code, name, parent, depth in (
            ("D1", DISTRICT_ONE, None, 1), ("D1.S1", SUBCENTRE_ONE, "D1", 2),
            ("D2", DISTRICT_TWO, None, 1), ("D2.S2", SUBCENTRE_TWO, "D2", 2),
        ):
            unit = MasOrgUnit(
                project_id=PROJECT_ID, org_level_id=levels[depth].org_level_id,
                parent_org_unit_id=cls.units[parent].org_unit_id if parent else None,
                unit_code=code.split(".")[-1], unit_name=name, path=code,
                created_at=now, updated_at=now,
            )
            db.session.add(unit)
            db.session.flush()
            cls.units[code] = unit
        for sid, code in ((SID_A, "D1.S1"), (SID_B, "D2.S2")):
            submission = db.session.get(VaSubmissions, sid)
            submission.org_unit_id = cls.units[code].org_unit_id
            submission.org_unit_resolution = "form_field"

        def user(prefix, languages=("english",)):
            made = cls._make_user(f"ai.{prefix}.{uuid.uuid4().hex[:8]}@test.local", "AiStaff12345")
            made.name = f"AI {prefix}"
            made.vacode_language = list(languages)
            return made

        cls.coder_a = user("coder-a")
        cls.coder_b = user("coder-b", ("English", "hindi"))
        cls.reviewer = user("reviewer")
        cls.interviewer_one = user("interviewer-one")
        cls.interviewer_two = user("interviewer-two")
        cls.interviewer_two.email_verified = False
        cls.unit_dm = user("unit-dm")
        cls._grant(cls.coder_a, VaAccessRoles.coder, site_id=SITE_A)
        cls._grant(cls.coder_b, VaAccessRoles.coder, site_id=SITE_B)
        cls._grant(cls.interviewer_one, VaAccessRoles.interviewer, org_unit_id=cls.units["D1.S1"].org_unit_id)
        cls._grant(cls.interviewer_two, VaAccessRoles.interviewer, org_unit_id=cls.units["D2.S2"].org_unit_id)
        cls._grant(cls.unit_dm, VaAccessRoles.data_manager, org_unit_id=cls.units["D1"].org_unit_id)
        db.session.flush()

        for sid, coder, minutes, extra in (
            (SID_A, cls.coder_a, 2, {
                "doris_result": {"status": "rejected", "result": {"warning": "Check age", "code": "1A00"}},
                "icd11_provenance": {"conclusive": {"code": "1A01", "causing_condition_unknown": True,
                                                    "age_restriction_confirmation": {"code": "1A01"}}},
            }),
            (SID_B, cls.coder_b, 10, {}),
        ):
            db.session.add(VaAllocations(
                va_sid=sid, va_allocated_to=coder.user_id, va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.deactive,
                va_allocation_createdat=FINAL_AT - timedelta(minutes=minutes),
                va_allocation_updatedat=FINAL_AT,
            ))
            db.session.add(VaFinalAssessments(
                va_sid=sid, va_finassess_by=coder.user_id, va_conclusive_cod="A09",
                va_finassess_status=VaStatuses.active,
                va_finassess_createdat=FINAL_AT, va_finassess_updatedat=FINAL_AT, **extra,
            ))
        db.session.add(VaSmartvaResults(
            va_sid=SID_A, va_smartva_cause1="Diarrhoea", va_smartva_cause1icd="A09",
            va_smartva_likelihood1="Possible", va_smartva_status=VaStatuses.active,
        ))
        db.session.add(VaReviewerFinalAssessments(
            va_sid=SID_A, va_rfinassess_by=cls.reviewer.user_id, va_conclusive_cod="B54",
            va_rfinassess_status=VaStatuses.active,
            va_rfinassess_createdat=FINAL_AT + timedelta(days=1),
            va_rfinassess_updatedat=FINAL_AT + timedelta(days=1),
        ))
        db.session.add(VaCoderReview(
            va_sid=SID_A, va_creview_by=cls.coder_a.user_id, va_creview_reason="test",
            va_creview_status=VaStatuses.deactive,
            va_creview_createdat=FINAL_AT, va_creview_updatedat=FINAL_AT,
        ))
        db.session.flush()
