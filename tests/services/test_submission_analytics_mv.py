from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaSites,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.final_cod_authority_service import (
    upsert_final_cod_authority,
    upsert_reviewer_final_cod_authority,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.submission_analytics_mv import (
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
    get_dm_kpi_from_mv,
    get_dm_project_site_stats_from_mv,
    refresh_submission_analytics_mv,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    COD_MV_NAME,
)
from tests.base import BaseTestCase


class SubmissionAnalyticsMaterializedViewTests(BaseTestCase):
    PROJECT_ID = "ANMV01"
    SITE_ID = "AMV1"
    FORM_ID = "ANMV01AMV101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(
            VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Analytics MV Project",
                project_nickname="AnalyticsMV",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Analytics MV Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="ANALYTICS_MV_FORM",
                odk_project_id="22",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

        # Drop any old/existing MVs and create the three new ones
        for mv in (
            COD_MV_NAME,
            DEMOGRAPHICS_MV_NAME,
            CORE_MV_NAME,
            "va_submission_analytics_mv",
        ):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))

        db.session.execute(sa.text(build_submission_analytics_core_mv_sql()))
        db.session.execute(sa.text(
            f"CREATE UNIQUE INDEX ix_test_core_va_sid ON {CORE_MV_NAME} (va_sid)"
        ))

        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(sa.text(
            f"CREATE UNIQUE INDEX ix_test_demo_va_sid ON {DEMOGRAPHICS_MV_NAME} (va_sid)"
        ))

        db.session.execute(sa.text(build_submission_cod_detail_mv_sql()))
        db.session.execute(sa.text(
            f"CREATE UNIQUE INDEX ix_test_cod_va_sid ON {COD_MV_NAME} (va_sid)"
        ))

        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            for mv in (
                COD_MV_NAME,
                DEMOGRAPHICS_MV_NAME,
                CORE_MV_NAME,
                "va_submission_analytics_mv",
            ):
                db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
            db.session.commit()
        finally:
            super().tearDownClass()

    def _add_submission(
        self,
        sid: str,
        payload: dict,
        *,
        gender: str = "female",
        normalized_days: Decimal | None = None,
        normalized_years: Decimal | None = None,
        normalized_source: str | None = None,
        workflow_state: str = "coding_in_progress",
    ):
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="analytics",
                va_odk_reviewstate="reviewed",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=0,
                va_deceased_age_normalized_days=normalized_days,
                va_deceased_age_normalized_years=normalized_years,
                va_deceased_age_source=normalized_source,
                va_deceased_gender=gender,
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        submission = db.session.get(VaSubmissions, sid)
        ensure_active_payload_version(submission, payload_data=payload, source_updated_at=None, created_by_role="vasystem")
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state=workflow_state,
                workflow_reason="test",
                workflow_updated_by_role="vasystem",
            )
        )

    def test_mv_normalizes_age_and_selects_authoritative_final_cod(self):
        neonate_sid = "uuid:mv-neonate"
        child_sid = "uuid:mv-child"
        adult_sid = "uuid:mv-adult"

        self._add_submission(
            neonate_sid,
            {
                "age_neonate_days": "0",
                "age_neonate_hours": "4",
                "ageInDays": "",
                "ageInMonths": "",
                "ageInYears": "",
                "ageInYears2": "",
                "finalAgeInYears": "",
                "age_group": "neonate",
                "isNeonatal": "1",
                "isChild": "0",
                "isAdult": "0",
            },
            gender="male",
            normalized_days=Decimal("0"),
            normalized_years=Decimal("0"),
            normalized_source="age_neonate_hours",
        )
        self._add_submission(
            child_sid,
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "45",
                "ageInMonths": "1",
                "ageInYears": "0",
                "ageInYears2": "0",
                "finalAgeInYears": "0",
                "age_group": "child",
                "isNeonatal": "0",
                "isChild": "1",
                "isAdult": "0",
            },
            gender="female",
            normalized_days=Decimal("45"),
            normalized_years=Decimal("45") / Decimal("365.25"),
            normalized_source="ageInDays",
        )
        self._add_submission(
            adult_sid,
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "16050",
                "ageInMonths": "11",
                "ageInYears": "99",
                "ageInYears2": "43",
                "finalAgeInYears": "43",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            gender="male",
            normalized_days=Decimal("43") * Decimal("365.25"),
            normalized_years=Decimal("43"),
            normalized_source="ageInYears2",
        )
        db.session.flush()

        db.session.add(
            VaInitialAssessments(
                va_sid=adult_sid,
                va_iniassess_by=self.base_coder_user.user_id,
                va_immediate_cod="I21-Acute myocardial infarction",
                va_antecedent_cod="I10-Essential (primary) hypertension",
                va_iniassess_status=VaStatuses.active,
            )
        )
        fallback_final = VaFinalAssessments(
            va_sid=adult_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99-Other ill-defined and unspecified causes of mortality",
            va_finassess_status=VaStatuses.active,
        )
        authoritative_final = VaFinalAssessments(
            va_sid=adult_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21-Acute myocardial infarction",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add_all([fallback_final, authoritative_final])
        db.session.flush()
        upsert_final_cod_authority(
            adult_sid,
            authoritative_final,
            reason="test_mv",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        db.session.add(
            VaSmartvaResults(
                va_sid=adult_sid,
                va_smartva_age="43",
                va_smartva_gender="male",
                va_smartva_resultfor="adult",
                va_smartva_cause1="Acute myocardial infarction",
                va_smartva_cause1icd="I21",
                va_smartva_status=VaStatuses.active,
            )
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        # Check demographics MV: age band
        demo_rows = db.session.execute(
            sa.text(
                f"""
                SELECT va_sid, analytics_age_band, sex
                FROM {DEMOGRAPHICS_MV_NAME}
                WHERE va_sid = :neonate_sid
                   OR va_sid = :child_sid
                   OR va_sid = :adult_sid
                ORDER BY va_sid
                """
            ),
            {
                "neonate_sid": neonate_sid,
                "child_sid": child_sid,
                "adult_sid": adult_sid,
            },
        ).mappings().all()

        demo_by_sid = {row["va_sid"]: row for row in demo_rows}

        self.assertEqual(demo_by_sid[neonate_sid]["analytics_age_band"], "neonate")
        self.assertEqual(demo_by_sid[child_sid]["analytics_age_band"], "child")
        self.assertEqual(demo_by_sid[adult_sid]["analytics_age_band"], "15_49y")

        # Check COD detail MV
        cod_row = db.session.execute(
            sa.text(
                f"""
                SELECT initial_immediate_icd, final_icd, final_cod_text, smartva_cause1_icd
                FROM {COD_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": adult_sid},
        ).mappings().one()

        self.assertEqual(cod_row["final_cod_text"], "I21-Acute myocardial infarction")
        self.assertEqual(cod_row["final_icd"], "I21")
        self.assertEqual(cod_row["initial_immediate_icd"], "I21")
        self.assertEqual(cod_row["smartva_cause1_icd"], "I21")

    def test_mv_helpers_apply_dashboard_filters(self):
        filtered_sid = "uuid:mv-filtered"
        nonmatching_sid = "uuid:mv-nonmatching"

        self._add_submission(
            filtered_sid,
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "",
                "ageInMonths": "",
                "ageInYears": "43",
                "ageInYears2": "43",
                "finalAgeInYears": "43",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            gender="male",
            normalized_days=Decimal("43") * Decimal("365.25"),
            normalized_years=Decimal("43"),
            normalized_source="ageInYears",
            workflow_state="coder_finalized",
        )
        self._add_submission(
            nonmatching_sid,
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "10",
                "ageInMonths": "",
                "ageInYears": "",
                "ageInYears2": "",
                "finalAgeInYears": "0",
                "age_group": "child",
                "isNeonatal": "0",
                "isChild": "1",
                "isAdult": "0",
            },
            gender="female",
            normalized_days=Decimal("10"),
            normalized_years=Decimal("10") / Decimal("365.25"),
            normalized_source="ageInDays",
            workflow_state="ready_for_coding",
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        filtered_kpi = get_dm_kpi_from_mv(
            [self.PROJECT_ID],
            [],
            workflow="coder_finalized",
            gender="male",
        )
        self.assertEqual(filtered_kpi["total_submissions"], 1)
        self.assertEqual(filtered_kpi["coded_submissions"], 1)

        filtered_stats = get_dm_project_site_stats_from_mv(
            project_ids=[self.PROJECT_ID],
            project_site_pairs=[],
            timezone_name="Asia/Kolkata",
            workflow="coder_finalized",
            gender="male",
        )
        self.assertEqual(len(filtered_stats), 1)
        self.assertEqual(filtered_stats[0]["project_id"], self.PROJECT_ID)
        self.assertEqual(filtered_stats[0]["site_id"], self.SITE_ID)

        nonmatching_kpi = get_dm_kpi_from_mv(
            [self.PROJECT_ID],
            [],
            workflow="finalized_upstream_changed",
        )
        self.assertEqual(nonmatching_kpi["total_submissions"], 0)

    def test_mv_prefers_reviewer_authority_and_counts_reviewer_states_as_coded(self):
        sid = "uuid:mv-reviewer-final"

        self._add_submission(
            sid,
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "",
                "ageInMonths": "",
                "ageInYears": "52",
                "ageInYears2": "52",
                "finalAgeInYears": "52",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            gender="male",
            normalized_days=Decimal("52") * Decimal("365.25"),
            normalized_years=Decimal("52"),
            normalized_source="ageInYears",
            workflow_state="reviewer_finalized",
        )
        coder_final = VaFinalAssessments(
            va_sid=sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21-Acute myocardial infarction",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.flush()
        upsert_final_cod_authority(
            sid,
            coder_final,
            reason="test_mv_reviewer_base",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        reviewer_user = self._make_user(
            "base.reviewer.analytics@test.local",
            "BaseReviewerAnalytics123",
        )
        reviewer_final = VaReviewerFinalAssessments(
            va_sid=sid,
            va_rfinassess_by=reviewer_user.user_id,
            va_conclusive_cod="J18-Pneumonia, unspecified organism",
            va_rfinassess_remark="Reviewer override",
            supersedes_coder_final_assessment_id=coder_final.va_finassess_id,
            va_rfinassess_status=VaStatuses.active,
        )
        db.session.add(reviewer_final)
        db.session.flush()
        upsert_reviewer_final_cod_authority(
            sid,
            reviewer_final,
            reason="test_mv_reviewer_override",
            updated_by=reviewer_user.user_id,
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        # Check core MV for workflow_state
        core_row = db.session.execute(
            sa.text(
                f"""
                SELECT workflow_state
                FROM {CORE_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(core_row["workflow_state"], "reviewer_finalized")

        # Check COD detail MV for final cod
        cod_row = db.session.execute(
            sa.text(
                f"""
                SELECT final_cod_text, final_icd
                FROM {COD_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(
            cod_row["final_cod_text"],
            "J18-Pneumonia, unspecified organism",
        )
        self.assertEqual(cod_row["final_icd"], "J18")

        kpi = get_dm_kpi_from_mv([self.PROJECT_ID], [], workflow="reviewer_finalized")
        self.assertEqual(kpi["total_submissions"], 1)
        self.assertEqual(kpi["coded_submissions"], 1)

    def test_pending_coding_kpi_excludes_pre_coding_pipeline_states(self):
        # Use a separate project to avoid data leakage from prior tests
        kpi_project = "KPMV01"
        kpi_site = "KP01"
        kpi_form = "KPMV01KP0101"
        now = datetime.now(timezone.utc)
        db.session.add(
            VaResearchProjects(
                project_id=kpi_project,
                project_code=kpi_project,
                project_name="KPI Isolation Project",
                project_nickname="KPIIsolation",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=kpi_site,
                project_id=kpi_project,
                site_name="KPI Isolation Site",
                site_abbr=kpi_site,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=kpi_form,
                project_id=kpi_project,
                site_id=kpi_site,
                odk_form_id="KPI_MV_FORM",
                odk_project_id="99",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

        original_add = self._add_submission

        def _kpi_add(sid, payload, *, workflow_state="coding_in_progress"):
            now = datetime.now(timezone.utc)
            db.session.add(
                VaSubmissions(
                    va_sid=sid,
                    va_form_id=kpi_form,
                    va_submission_date=now,
                    va_odk_updatedat=now,
                    va_data_collector="analytics",
                    va_odk_reviewstate="reviewed",
                    va_instance_name=sid,
                    va_uniqueid_real=sid,
                    va_uniqueid_masked=sid,
                    va_consent="yes",
                    va_narration_language="English",
                    va_deceased_age=0,
                    va_deceased_gender="female",
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                )
            )
            db.session.flush()
            kpi_submission = db.session.get(VaSubmissions, sid)
            ensure_active_payload_version(kpi_submission, payload_data=payload, source_updated_at=None, created_by_role="vasystem")
            db.session.add(
                VaSubmissionWorkflow(
                    va_sid=sid,
                    workflow_state=workflow_state,
                    workflow_reason="test",
                    workflow_updated_by_role="vasystem",
                )
            )

            db.session.flush()

        _kpi_add(
            "uuid:mv-kpi-pending-ready",
            {
                "ageInYears": "45",
                "ageInYears2": "45",
                "finalAgeInYears": "45",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            workflow_state="ready_for_coding",
        )
        _kpi_add(
            "uuid:mv-kpi-pending-inprogress",
            {
                "ageInYears": "46",
                "ageInYears2": "46",
                "finalAgeInYears": "46",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            workflow_state="coding_in_progress",
        )
        _kpi_add(
            "uuid:mv-kpi-pending-step1",
            {
                "ageInYears": "47",
                "ageInYears2": "47",
                "finalAgeInYears": "47",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            workflow_state="coder_step1_saved",
        )
        _kpi_add(
            "uuid:mv-kpi-pipeline-screening",
            {
                "ageInYears": "48",
                "ageInYears2": "48",
                "finalAgeInYears": "48",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            workflow_state="screening_pending",
        )
        _kpi_add(
            "uuid:mv-kpi-pipeline-attachments",
            {
                "ageInYears": "49",
                "ageInYears2": "49",
                "finalAgeInYears": "49",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            workflow_state="attachment_sync_pending",
        )
        _kpi_add(
            "uuid:mv-kpi-pipeline-smartva",
            {
                "ageInYears": "50",
                "ageInYears2": "50",
                "finalAgeInYears": "50",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            workflow_state="smartva_pending",
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        unfiltered_kpi = get_dm_kpi_from_mv([kpi_project], [])
        self.assertEqual(unfiltered_kpi["smartva_pending_submissions"], 1)

        kpi = get_dm_kpi_from_mv([kpi_project], [], workflow="pending_coding")
        self.assertEqual(kpi["total_submissions"], 3)
        self.assertEqual(kpi["pending_submissions"], 3)
        self.assertEqual(kpi["smartva_pending_submissions"], 0)
