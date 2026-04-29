from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaSiteMaster,
    VaSites,
    VaSmartvaResults,
    VaSocialAutopsyAnalysis,
    VaSocialAutopsyAnalysisOption,
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
    build_submission_cod_snapshot_mv_sql,
    get_dm_kpi_from_mv,
    get_dm_project_site_stats_from_mv,
    refresh_submission_analytics_mv,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    COD_MV_NAME,
    COD_SNAPSHOT_MV_NAME,
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
            VaProjectMaster(
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
            VaSiteMaster(
                site_id=cls.SITE_ID,
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
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.commit()

        # Drop any old/existing MVs and create the three new ones
        for mv in (
            COD_MV_NAME,
            DEMOGRAPHICS_MV_NAME,
            CORE_MV_NAME,
            COD_SNAPSHOT_MV_NAME,
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

        db.session.execute(sa.text(build_submission_cod_snapshot_mv_sql()))
        db.session.execute(
            sa.text(
                f"CREATE UNIQUE INDEX ix_test_cod_snapshot_va_sid ON {COD_SNAPSHOT_MV_NAME} (va_sid)"
            )
        )

        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            for mv in (
                COD_MV_NAME,
                DEMOGRAPHICS_MV_NAME,
                CORE_MV_NAME,
                COD_SNAPSHOT_MV_NAME,
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
        project_id = "RVMV01"
        site_id = "RV01"
        form_id = "RVMV01RV0101"
        sid = "uuid:mv-reviewer-final"
        now = datetime.now(timezone.utc)

        db.session.add(
            VaResearchProjects(
                project_id=project_id,
                project_code=project_id,
                project_name="Reviewer MV Project",
                project_nickname="ReviewerMV",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name="Reviewer MV Project",
                project_nickname="ReviewerMV",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=site_id,
                project_id=project_id,
                site_name="Reviewer MV Site",
                site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSiteMaster(
                site_id=site_id,
                site_name="Reviewer MV Site",
                site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=form_id,
                project_id=project_id,
                site_id=site_id,
                odk_form_id="REVIEWER_MV_FORM",
                odk_project_id="55",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaProjectSites(
                project_id=project_id,
                site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.commit()

        submitted_at = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=form_id,
                va_submission_date=submitted_at,
                va_odk_updatedat=submitted_at,
                va_data_collector="analytics",
                va_odk_reviewstate="reviewed",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=0,
                va_deceased_age_normalized_days=Decimal("52") * Decimal("365.25"),
                va_deceased_age_normalized_years=Decimal("52"),
                va_deceased_age_source="ageInYears",
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        submission = db.session.get(VaSubmissions, sid)
        ensure_active_payload_version(
            submission,
            payload_data={
                "ageInYears": "52",
                "ageInYears2": "52",
                "finalAgeInYears": "52",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            source_updated_at=None,
            created_by_role="vasystem",
        )
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state="reviewer_finalized",
                workflow_reason="test",
                workflow_updated_by_role="vasystem",
            )
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

        kpi = get_dm_kpi_from_mv([project_id], [], workflow="reviewer_finalized")
        self.assertEqual(kpi["total_submissions"], 1)
        self.assertEqual(kpi["coded_submissions"], 1)

    def test_cod_snapshot_mv_preserves_coder_reviewer_authoritative_and_bucket_data(self):
        sid = "uuid:mv-cod-snapshot"

        self._add_submission(
            sid,
            {
                "Id10476": "Free text narrative for export",
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
        reviewer_user = self._make_user(
            "snapshot.reviewer@test.local",
            "SnapshotReviewer123",
        )
        db.session.add(
            VaInitialAssessments(
                va_sid=sid,
                va_iniassess_by=self.base_coder_user.user_id,
                va_immediate_cod="I21-Acute myocardial infarction",
                va_antecedent_cod="I10-Essential hypertension",
                va_other_conditions="E11-Type 2 diabetes mellitus",
                va_iniassess_status=VaStatuses.active,
            )
        )
        coder_final = VaFinalAssessments(
            va_sid=sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21-Acute myocardial infarction",
            va_finassess_remark="Coder final remark",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.flush()
        upsert_final_cod_authority(
            sid,
            coder_final,
            reason="snapshot_coder_authority",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        reviewer_final = VaReviewerFinalAssessments(
            va_sid=sid,
            va_rfinassess_by=reviewer_user.user_id,
            va_conclusive_cod="J18-Pneumonia, unspecified organism",
            va_rfinassess_remark="Reviewer final remark",
            supersedes_coder_final_assessment_id=coder_final.va_finassess_id,
            va_rfinassess_status=VaStatuses.active,
        )
        db.session.add(reviewer_final)
        db.session.flush()
        upsert_reviewer_final_cod_authority(
            sid,
            reviewer_final,
            reason="snapshot_reviewer_authority",
            updated_by=reviewer_user.user_id,
        )
        db.session.add(
            VaSmartvaResults(
                va_sid=sid,
                va_smartva_age="52",
                va_smartva_gender="male",
                va_smartva_resultfor="adult",
                va_smartva_cause1="Sepsis",
                va_smartva_cause1icd="A41",
                va_smartva_cause2="HIV disease",
                va_smartva_cause2icd="B20",
                va_smartva_cause3="Lung cancer",
                va_smartva_cause3icd="C34",
                va_smartva_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaNarrativeAssessment(
                va_sid=sid,
                va_nqa_by=self.base_coder_user.user_id,
                payload_version_id=db.session.get(VaSubmissions, sid).active_payload_version_id,
                va_nqa_length=3,
                va_nqa_pos_symptoms=3,
                va_nqa_neg_symptoms=1,
                va_nqa_chronology=1,
                va_nqa_doc_review=1,
                va_nqa_comorbidity=1,
                va_nqa_score=10,
                va_nqa_cannot_grade=False,
                va_nqa_status=VaStatuses.active,
            )
        )
        social = VaSocialAutopsyAnalysis(
            va_sid=sid,
            va_saa_by=self.base_coder_user.user_id,
            payload_version_id=db.session.get(VaSubmissions, sid).active_payload_version_id,
            va_saa_remark="Social autopsy remark",
            va_saa_status=VaStatuses.active,
        )
        db.session.add(social)
        db.session.flush()
        db.session.add_all(
            [
                VaSocialAutopsyAnalysisOption(
                    va_saa_id=social.va_saa_id,
                    delay_level="delay_1_decision",
                    option_code="recognition",
                ),
                VaSocialAutopsyAnalysisOption(
                    va_saa_id=social.va_saa_id,
                    delay_level="delay_2_reaching",
                    option_code="transport_logistics",
                ),
            ]
        )
        scheme = db.session.scalar(
            sa.select(MasCodBucketScheme).where(
                MasCodBucketScheme.scheme_code == "WHO_2022_VA"
            )
        )
        if scheme is None:
            scheme = MasCodBucketScheme(
                scheme_code="WHO_2022_VA",
                scheme_name="WHO 2022 VA",
                is_active=True,
            )
            db.session.add(scheme)
            db.session.flush()
        parent_heart = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            parent_node_id=None,
            node_code="SEC1",
            node_label="Cardiovascular diseases",
            sort_order=1,
            is_active=True,
        )
        leaf_heart = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent_heart,
            node_code="BUCKET1",
            node_label="Acute myocardial infarction",
            sort_order=1,
            is_active=True,
        )
        parent_resp = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            parent_node_id=None,
            node_code="SEC2",
            node_label="Respiratory infections",
            sort_order=2,
            is_active=True,
        )
        leaf_resp = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent_resp,
            node_code="BUCKET2",
            node_label="Pneumonia",
            sort_order=1,
            is_active=True,
        )
        parent_inf = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            parent_node_id=None,
            node_code="SEC3",
            node_label="Systemic infections",
            sort_order=3,
            is_active=True,
        )
        leaf_inf = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent_inf,
            node_code="BUCKET3",
            node_label="Sepsis",
            sort_order=1,
            is_active=True,
        )
        parent_hiv = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            parent_node_id=None,
            node_code="SEC4",
            node_label="HIV and related",
            sort_order=4,
            is_active=True,
        )
        leaf_hiv = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent_hiv,
            node_code="BUCKET4",
            node_label="HIV disease",
            sort_order=1,
            is_active=True,
        )
        parent_cancer = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            parent_node_id=None,
            node_code="SEC5",
            node_label="Cancers",
            sort_order=5,
            is_active=True,
        )
        leaf_cancer = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent_cancer,
            node_code="BUCKET5",
            node_label="Lung cancer",
            sort_order=1,
            is_active=True,
        )
        db.session.add_all(
            [
                parent_heart,
                leaf_heart,
                parent_resp,
                leaf_resp,
                parent_inf,
                leaf_inf,
                parent_hiv,
                leaf_hiv,
                parent_cancer,
                leaf_cancer,
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                MapIcdCodBucket(scheme_id=scheme.scheme_id, age_scope=None, icd_code="I21", node_id=leaf_heart.node_id, is_active=True),
                MapIcdCodBucket(scheme_id=scheme.scheme_id, age_scope=None, icd_code="J18", node_id=leaf_resp.node_id, is_active=True),
                MapIcdCodBucket(scheme_id=scheme.scheme_id, age_scope=None, icd_code="A41", node_id=leaf_inf.node_id, is_active=True),
                MapIcdCodBucket(scheme_id=scheme.scheme_id, age_scope=None, icd_code="B20", node_id=leaf_hiv.node_id, is_active=True),
                MapIcdCodBucket(scheme_id=scheme.scheme_id, age_scope=None, icd_code="C34", node_id=leaf_cancer.node_id, is_active=True),
            ]
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        row = db.session.execute(
            sa.text(
                f"""
                SELECT
                    narrative_text,
                    coder_name,
                    coder_final_cod_text,
                    coder_final_who_bucket_section,
                    coder_final_who_bucket,
                    reviewer_name,
                    reviewer_final_cod_text,
                    reviewer_final_who_bucket_section,
                    reviewer_final_who_bucket,
                    authoritative_source,
                    authoritative_cod_text,
                    authoritative_icd,
                    authoritative_who_bucket_section,
                    authoritative_who_bucket,
                    smartva_cause1_icd,
                    smartva_cause1_who_bucket,
                    smartva_cause2_icd,
                    smartva_cause2_who_bucket,
                    smartva_cause3_icd,
                    smartva_cause3_who_bucket,
                    nqa_score,
                    nqa_rating,
                    social_autopsy_remark,
                    social_autopsy_option_pairs
                FROM {COD_SNAPSHOT_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(row["narrative_text"], "Free text narrative for export")
        self.assertEqual(row["coder_name"], "base.coder@test.local")
        self.assertEqual(row["coder_final_cod_text"], "I21-Acute myocardial infarction")
        self.assertEqual(row["coder_final_who_bucket_section"], "Cardiovascular diseases")
        self.assertEqual(row["coder_final_who_bucket"], "Acute myocardial infarction")
        self.assertEqual(row["reviewer_name"], "snapshot.reviewer@test.local")
        self.assertEqual(row["reviewer_final_cod_text"], "J18-Pneumonia, unspecified organism")
        self.assertEqual(row["reviewer_final_who_bucket"], "Pneumonia")
        self.assertEqual(row["authoritative_source"], "reviewer")
        self.assertEqual(row["authoritative_cod_text"], "J18-Pneumonia, unspecified organism")
        self.assertEqual(row["authoritative_icd"], "J18")
        self.assertEqual(row["authoritative_who_bucket"], "Pneumonia")
        self.assertEqual(row["smartva_cause1_icd"], "A41")
        self.assertEqual(row["smartva_cause1_who_bucket"], "Sepsis")
        self.assertEqual(row["smartva_cause2_icd"], "B20")
        self.assertEqual(row["smartva_cause2_who_bucket"], "HIV disease")
        self.assertEqual(row["smartva_cause3_icd"], "C34")
        self.assertEqual(row["smartva_cause3_who_bucket"], "Lung cancer")
        self.assertEqual(row["nqa_score"], 10)
        self.assertEqual(row["nqa_rating"], "Good")
        self.assertEqual(row["social_autopsy_remark"], "Social autopsy remark")
        self.assertIn("delay_1_decision::recognition", row["social_autopsy_option_pairs"])
        self.assertIn("delay_2_reaching::transport_logistics", row["social_autopsy_option_pairs"])

    def test_cod_snapshot_mv_tolerates_duplicate_who_bucket_mapping_rows(self):
        sid = "uuid:mv-snapshot-duplicate-bucket"
        self._add_submission(
            sid,
            {
                "Id10476": "Duplicate bucket test narrative",
                "ageInYears": "63",
                "ageInYears2": "63",
                "finalAgeInYears": "63",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            gender="male",
            normalized_days=Decimal("63") * Decimal("365.25"),
            normalized_years=Decimal("63"),
            normalized_source="ageInYears",
            workflow_state="reviewer_finalized",
        )
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                va_finassess_by=self.base_coder_user.user_id,
                va_conclusive_cod="R57-Shock, not elsewhere classified",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.flush()
        scheme = db.session.scalar(
            sa.select(MasCodBucketScheme).where(
                MasCodBucketScheme.scheme_code == "WHO_2022_VA"
            )
        )
        if scheme is None:
            scheme = MasCodBucketScheme(
                scheme_code="WHO_2022_VA",
                scheme_name="WHO 2022 VA",
                is_active=True,
            )
            db.session.add(scheme)
            db.session.flush()
        parent = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            node_code="SEC_UNKNOWN",
            node_label="Cause of death unknown",
            sort_order=1,
            is_active=True,
        )
        leaf = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent,
            node_code="BUCKET_UNKNOWN",
            node_label="Cause of death unknown",
            sort_order=1,
            is_active=True,
        )
        db.session.add_all([parent, leaf])
        db.session.flush()
        db.session.add_all(
            [
                MapIcdCodBucket(
                    scheme_id=scheme.scheme_id,
                    age_scope=None,
                    icd_code="R57",
                    node_id=leaf.node_id,
                    is_active=True,
                ),
                MapIcdCodBucket(
                    scheme_id=scheme.scheme_id,
                    age_scope=None,
                    icd_code="R57",
                    node_id=leaf.node_id,
                    is_active=True,
                ),
            ]
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        row_count = db.session.execute(
            sa.text(f"SELECT COUNT(*) FROM {COD_SNAPSHOT_MV_NAME} WHERE va_sid = :sid"),
            {"sid": sid},
        ).scalar_one()
        row = db.session.execute(
            sa.text(
                f"""
                SELECT authoritative_icd, authoritative_who_bucket
                FROM {COD_SNAPSHOT_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(row_count, 1)
        self.assertEqual(row["authoritative_icd"], "R57")
        self.assertEqual(row["authoritative_who_bucket"], "Cause of death unknown")

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
            VaProjectMaster(
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
            VaSiteMaster(
                site_id=kpi_site,
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
        db.session.add(
            VaProjectSites(
                project_id=kpi_project,
                site_id=kpi_site,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
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

    def test_smartva_missing_includes_consent_refused_workflow(self):
        project_id = "SMMV01"
        site_id = "SM01"
        form_id = "SMMV01SM0101"
        sid_missing = "uuid:mv-kpi-smartva-missing"
        sid_consent_refused = "uuid:mv-kpi-consent-refused"
        now = datetime.now(timezone.utc)

        db.session.add(
            VaResearchProjects(
                project_id=project_id,
                project_code=project_id,
                project_name="SmartVA Missing Project",
                project_nickname="SmartVAMissing",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name="SmartVA Missing Project",
                project_nickname="SmartVAMissing",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=site_id,
                project_id=project_id,
                site_name="SmartVA Missing Site",
                site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSiteMaster(
                site_id=site_id,
                site_name="SmartVA Missing Site",
                site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=form_id,
                project_id=project_id,
                site_id=site_id,
                odk_form_id="SMARTVA_MISSING_FORM",
                odk_project_id="88",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaProjectSites(
                project_id=project_id,
                site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.commit()

        for sid, years, gender, workflow_state in (
            (sid_missing, "41", "female", "ready_for_coding"),
            (sid_consent_refused, "39", "male", "consent_refused"),
        ):
            submitted_at = datetime.now(timezone.utc)
            db.session.add(
                VaSubmissions(
                    va_sid=sid,
                    va_form_id=form_id,
                    va_submission_date=submitted_at,
                    va_odk_updatedat=submitted_at,
                    va_data_collector="analytics",
                    va_odk_reviewstate="reviewed",
                    va_instance_name=sid,
                    va_uniqueid_real=sid,
                    va_uniqueid_masked=sid,
                    va_consent="yes",
                    va_narration_language="English",
                    va_deceased_age=0,
                    va_deceased_age_normalized_days=Decimal(years) * Decimal("365.25"),
                    va_deceased_age_normalized_years=Decimal(years),
                    va_deceased_age_source="ageInYears",
                    va_deceased_gender=gender,
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                )
            )
            db.session.flush()
            submission = db.session.get(VaSubmissions, sid)
            ensure_active_payload_version(
                submission,
                payload_data={
                    "ageInYears": years,
                    "ageInYears2": years,
                    "finalAgeInYears": years,
                    "age_group": "adult",
                    "isNeonatal": "0",
                    "isChild": "0",
                    "isAdult": "1",
                },
                source_updated_at=None,
                created_by_role="vasystem",
            )
            db.session.add(
                VaSubmissionWorkflow(
                    va_sid=sid,
                    workflow_state=workflow_state,
                    workflow_reason="test",
                    workflow_updated_by_role="vasystem",
                )
            )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        kpi = get_dm_kpi_from_mv([], [(project_id, site_id)])
        self.assertEqual(kpi["smartva_missing_submissions"], 2)
        self.assertEqual(kpi["consent_refused_submissions"], 1)

        missing_filter_kpi = get_dm_kpi_from_mv(
            [],
            [(project_id, site_id)],
            smartva="missing",
        )
        self.assertEqual(missing_filter_kpi["total_submissions"], 2)
        self.assertEqual(missing_filter_kpi["smartva_missing_submissions"], 2)
        self.assertEqual(missing_filter_kpi["consent_refused_submissions"], 1)
