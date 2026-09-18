from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcd10LegacyReportingAlias,
    MasIcd1020192,
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasOrgLevel,
    MasOrgUnit,
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
    build_dm_mv_filter_conditions,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
    build_submission_cod_snapshot_mv_sql,
    get_dm_kpi_from_mv,
    get_dm_org_unit_stats_from_mv,
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

        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
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
        sync_issue_code: str | None = None,
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
                va_sync_issue_code=sync_issue_code,
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

    def _add_project_site_mapping(self, project_id, *, project_status, mapping_status):
        now = datetime.now(timezone.utc)
        for model in (VaResearchProjects, VaProjectMaster):
            if db.session.get(model, project_id) is None:
                db.session.add(model(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Analytics MV {project_id}",
                    project_nickname=project_id,
                    project_status=project_status,
                    project_registered_at=now,
                    project_updated_at=now,
                ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=project_id,
            site_id=self.SITE_ID,
            project_site_status=mapping_status,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.flush()

    def _core_rows(self, sid):
        return db.session.execute(
            sa.text(f"SELECT project_id FROM {CORE_MV_NAME} WHERE va_sid = :sid"),
            {"sid": sid},
        ).scalars().all()

    def test_core_mv_attributes_to_the_forms_own_project_when_site_is_shared(self):
        """A site with several active project-site rows must not fan out.

        Regression for the production refresh failure: site MH01 carried
        active rows for a deactivated demo project and for the live project
        while the form's own project mapping was deactivated, so the site-only
        join emitted two rows per submission and the unique va_sid index
        rejected REFRESH. A submission belongs to its form's own project.
        """
        sid = "uuid:mv-site-shared"
        self._add_submission(sid, {"age_group": "adult", "ageInYears": "40"})

        own = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.PROJECT_ID,
            VaProjectSites.site_id == self.SITE_ID,
        ))
        own.project_site_status = VaStatuses.deactive
        self._add_project_site_mapping(
            "ANMVDM", project_status=VaStatuses.deactive, mapping_status=VaStatuses.active
        )
        self._add_project_site_mapping(
            "ANMV02", project_status=VaStatuses.active, mapping_status=VaStatuses.active
        )
        db.session.commit()

        refresh_submission_analytics_mv()

        self.assertEqual(self._core_rows(sid), [self.PROJECT_ID])

    def test_core_mv_ignores_other_active_projects_sharing_the_site(self):
        """A demo project sharing a live site does not steal attribution."""
        sid = "uuid:mv-site-own"
        self._add_submission(sid, {"age_group": "adult", "ageInYears": "40"})
        self._add_project_site_mapping(
            "ANMV03", project_status=VaStatuses.active, mapping_status=VaStatuses.active
        )
        db.session.commit()

        refresh_submission_analytics_mv()

        self.assertEqual(self._core_rows(sid), [self.PROJECT_ID])

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
                "unique_id": "UNIQUE-MV-COD-SNAPSHOT",
                "survey_block": "SURVEY-BLOCK-A",
                "ageInYears": "52",
                "ageInYears2": "52",
                "finalAgeInYears": "52",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
                "sa01": "1",
                "sa06": "2",
                "sa06_a": "Visited local healer first",
                "sa14": "1",
                "sa_tu14": "Transport strike delayed referral",
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
                    unique_id,
                    survey_block,
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
                    nqa_length,
                    nqa_pos_symptoms,
                    nqa_neg_symptoms,
                    nqa_chronology,
                    nqa_doc_review,
                    nqa_comorbidity,
                    nqa_score,
                    nqa_rating,
                    social_autopsy_remark,
                    social_autopsy_option_pairs,
                    sa01,
                    sa06,
                    sa06_a,
                    sa14,
                    sa_tu14
                FROM {COD_SNAPSHOT_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(row["unique_id"], "UNIQUE-MV-COD-SNAPSHOT")
        self.assertEqual(row["survey_block"], "SURVEY-BLOCK-A")
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
        self.assertEqual(row["nqa_length"], 3)
        self.assertEqual(row["nqa_pos_symptoms"], 3)
        self.assertEqual(row["nqa_neg_symptoms"], 1)
        self.assertEqual(row["nqa_chronology"], 1)
        self.assertEqual(row["nqa_doc_review"], 1)
        self.assertEqual(row["nqa_comorbidity"], 1)
        self.assertEqual(row["nqa_score"], 10)
        self.assertEqual(row["nqa_rating"], "Good")
        self.assertEqual(row["social_autopsy_remark"], "Social autopsy remark")
        self.assertIn("delay_1_decision::recognition", row["social_autopsy_option_pairs"])
        self.assertIn("delay_2_reaching::transport_logistics", row["social_autopsy_option_pairs"])
        self.assertEqual(row["sa01"], "1")
        self.assertEqual(row["sa06"], "2")
        self.assertEqual(row["sa06_a"], "Visited local healer first")
        self.assertEqual(row["sa14"], "1")
        self.assertEqual(row["sa_tu14"], "Transport strike delayed referral")

    def test_cod_snapshot_mv_emits_one_row_per_submission_for_who_bucket(self):
        """Commit 5580394 deduped map_icd_cod_buckets and added the unique
        index ux_map_icd_cod_buckets_scheme_scope_icd_norm, so the duplicate
        mapping rows this test used to insert are now rejected by the database
        (docs/policy/cod-bucket-reporting.md rules 31-32). Duplicate handling at
        the import boundary is covered by
        tests/services/test_cod_bucket_mapping_service.py; what stays here is
        the MV's one-row-per-submission guarantee.
        """
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
        db.session.add(
            MapIcdCodBucket(
                scheme_id=scheme.scheme_id,
                age_scope=None,
                icd_code="R57",
                node_id=leaf.node_id,
                is_active=True,
            )
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

    def test_cod_snapshot_mv_uses_legacy_reporting_alias_for_bucket_assignment(self):
        sid = "uuid:mv-snapshot-legacy-alias-bucket"
        self._add_submission(
            sid,
            {
                "Id10476": "Legacy ICD alias narrative",
                "ageInYears": "44",
                "ageInYears2": "44",
                "finalAgeInYears": "44",
                "age_group": "adult",
                "isNeonatal": "0",
                "isChild": "0",
                "isAdult": "1",
            },
            gender="female",
            normalized_days=Decimal("44") * Decimal("365.25"),
            normalized_years=Decimal("44"),
            normalized_source="ageInYears",
            workflow_state="coder_finalized",
        )
        coder_final = VaFinalAssessments(
            va_sid=sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="A90-Dengue fever",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.flush()
        upsert_final_cod_authority(
            sid,
            coder_final,
            reason="snapshot_alias_authority",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
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
        parent = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="category",
            node_code="SEC_DENGUE",
            node_label="Vector-borne infections",
            sort_order=1,
            is_active=True,
        )
        leaf = MasCodBucketNode(
            scheme_id=scheme.scheme_id,
            age_scope=None,
            node_type="field",
            parent=parent,
            node_code="BUCKET_DENGUE",
            node_label="Dengue",
            sort_order=1,
            is_active=True,
        )
        db.session.add_all([parent, leaf])
        db.session.flush()
        db.session.add(
            MapIcdCodBucket(
                scheme_id=scheme.scheme_id,
                age_scope=None,
                icd_code="A97",
                node_id=leaf.node_id,
                is_active=True,
            )
        )
        # map_icd10_legacy_reporting_aliases.reporting_code is FK-constrained to
        # mas_icd10_2019_2.code (migration f6b7c8d9e0f1), and the test schema is
        # built by db.create_all() with no ICD-10 catalog seed.
        if db.session.get(MasIcd1020192, "A97") is None:
            db.session.add(
                MasIcd1020192(
                    code="A97",
                    title="Dengue",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=1,
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    source_version="2019-test",
                    source_path="tests",
                    is_active=True,
                )
            )
            db.session.flush()
        db.session.add(
            MapIcd10LegacyReportingAlias(
                legacy_code="A90",
                reporting_code="A97",
                note="Legacy dengue code normalized for reporting.",
            )
        )
        db.session.commit()

        refresh_submission_analytics_mv(concurrently=False)

        row = db.session.execute(
            sa.text(
                f"""
                SELECT
                    coder_final_icd,
                    coder_final_who_bucket_section,
                    coder_final_who_bucket,
                    authoritative_icd,
                    authoritative_who_bucket_section,
                    authoritative_who_bucket
                FROM {COD_SNAPSHOT_MV_NAME}
                WHERE va_sid = :sid
                """
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(row["coder_final_icd"], "A90")
        self.assertEqual(row["coder_final_who_bucket_section"], "Vector-borne infections")
        self.assertEqual(row["coder_final_who_bucket"], "Dengue")
        self.assertEqual(row["authoritative_icd"], "A90")
        self.assertEqual(row["authoritative_who_bucket_section"], "Vector-borne infections")
        self.assertEqual(row["authoritative_who_bucket"], "Dengue")

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

    # ------------------------------------------------------------------
    # Retired-from-ODK submissions (docs/policy/odk-retired-submissions.md)
    # ------------------------------------------------------------------

    def _odk_missing_flags(self) -> dict[str, bool]:
        rows = db.session.execute(
            sa.text(f"SELECT va_sid, odk_missing FROM {CORE_MV_NAME}")
        ).all()
        return {row.va_sid: row.odk_missing for row in rows}

    def _seed_live_and_retired(self, suffix: str) -> tuple[str, str]:
        live_sid = f"uuid:odk-live-{suffix}"
        retired_sid = f"uuid:odk-retired-{suffix}"
        payload = {"ageInYears": 40, "isAdult": "1"}
        self._add_submission(live_sid, payload, workflow_state="coder_finalized")
        self._add_submission(
            retired_sid,
            payload,
            workflow_state="coder_finalized",
            sync_issue_code="missing_in_odk",
        )
        db.session.commit()
        refresh_submission_analytics_mv(concurrently=False)
        return live_sid, retired_sid

    def test_core_mv_flags_retired_submissions_with_odk_missing(self):
        live_sid, retired_sid = self._seed_live_and_retired("flag")

        flags = self._odk_missing_flags()

        self.assertIs(flags[retired_sid], True)
        # A submission with no sync issue at all must be False, not NULL,
        # so that `odk_missing = false` keeps it.
        self.assertIs(flags[live_sid], False)

    def test_dm_kpi_excludes_retired_submissions_by_default(self):
        live_sid, retired_sid = self._seed_live_and_retired("kpi")
        scope = [(self.PROJECT_ID, self.SITE_ID)]

        kpi = get_dm_kpi_from_mv([], scope)

        self.assertNotIn(retired_sid, self._sids_in_scope(kpi_filter=""))
        self.assertIn(live_sid, self._sids_in_scope(kpi_filter=""))
        self.assertEqual(kpi["total_submissions"], 1)
        self.assertEqual(kpi["coded_submissions"], 1)
        # The retired row stays in the MV and is still named explicitly.
        self.assertEqual(kpi["missing_in_odk_submissions"], 1)

    def test_dm_kpi_includes_retired_submissions_on_request(self):
        self._seed_live_and_retired("include")
        scope = [(self.PROJECT_ID, self.SITE_ID)]

        all_kpi = get_dm_kpi_from_mv([], scope, odk_sync="all")
        missing_kpi = get_dm_kpi_from_mv([], scope, odk_sync="missing_in_odk")

        self.assertEqual(all_kpi["total_submissions"], 2)
        self.assertEqual(missing_kpi["total_submissions"], 1)
        self.assertEqual(missing_kpi["coded_submissions"], 1)

    def test_project_site_stats_exclude_retired_submissions_by_default(self):
        self._seed_live_and_retired("stats")

        stats = get_dm_project_site_stats_from_mv(
            project_ids=[],
            project_site_pairs=[(self.PROJECT_ID, self.SITE_ID)],
            timezone_name="UTC",
        )
        all_stats = get_dm_project_site_stats_from_mv(
            project_ids=[],
            project_site_pairs=[(self.PROJECT_ID, self.SITE_ID)],
            timezone_name="UTC",
            odk_sync="all",
        )

        self.assertEqual(stats[0]["total_submissions"], 1)
        self.assertEqual(all_stats[0]["total_submissions"], 2)

    def _sids_in_scope(self, *, kpi_filter: str) -> set[str]:
        """Return the va_sids the MV filter conditions keep for this scope."""
        core = sa.table(
            CORE_MV_NAME,
            sa.column("va_sid"),
            sa.column("project_id"),
            sa.column("site_id"),
            sa.column("submission_date"),
            sa.column("workflow_state"),
            sa.column("odk_review_state"),
            sa.column("odk_sync_issue_code"),
            sa.column("odk_missing"),
        )
        demo = sa.table(
            DEMOGRAPHICS_MV_NAME,
            sa.column("va_sid"),
            sa.column("analytics_age_band"),
            sa.column("sex"),
            sa.column("has_smartva"),
        )
        conditions = build_dm_mv_filter_conditions(
            core,
            demo,
            project_ids=[],
            project_site_pairs=[(self.PROJECT_ID, self.SITE_ID)],
            odk_sync=kpi_filter,
        )
        rows = db.session.execute(
            sa.select(core.c.va_sid)
            .select_from(core.join(demo, core.c.va_sid == demo.c.va_sid))
            .where(sa.and_(*conditions))
        ).scalars().all()
        return set(rows)

    def test_filter_conditions_honour_each_odk_sync_choice(self):
        live_sid, retired_sid = self._seed_live_and_retired("conditions")

        self.assertEqual(self._sids_in_scope(kpi_filter="in_sync"), {live_sid})
        self.assertEqual(self._sids_in_scope(kpi_filter="missing_in_odk"), {retired_sid})
        self.assertEqual(
            self._sids_in_scope(kpi_filter="all"), {live_sid, retired_sid}
        )

    # -- phase 5: organization unit reporting columns -----------------------

    def _make_org_tree(self, project_id: str, *, prefix: str):
        """Create a two-level tree (district > phc) for project_id and
        return (district, phc) MasOrgUnit rows. Mirrors the shape a
        health-system project uses: docs/policy/organization-model.md.
        """
        code_prefix = prefix.upper()
        district_level = MasOrgLevel(
            project_id=project_id,
            level_code=f"{prefix}district",
            level_name="District",
            depth=1,
        )
        phc_level = MasOrgLevel(
            project_id=project_id,
            level_code=f"{prefix}phc",
            level_name="PHC",
            depth=2,
        )
        db.session.add_all([district_level, phc_level])
        db.session.flush()

        district = MasOrgUnit(
            project_id=project_id,
            org_level_id=district_level.org_level_id,
            unit_code=f"{code_prefix}D01",
            unit_name="District One",
            path=f"{code_prefix}D01",
        )
        db.session.add(district)
        db.session.flush()

        phc = MasOrgUnit(
            project_id=project_id,
            org_level_id=phc_level.org_level_id,
            parent_org_unit_id=district.org_unit_id,
            unit_code=f"{code_prefix}P01",
            unit_name="PHC One",
            path=f"{code_prefix}D01.{code_prefix}P01",
        )
        db.session.add(phc)
        db.session.flush()
        return district, phc

    def test_core_mv_carries_org_unit_columns_after_refresh(self):
        district, _phc = self._make_org_tree(self.PROJECT_ID, prefix="orgcol")
        sid = "uuid:mv-org-unit-columns"
        self._add_submission(sid, {"age_group": "adult", "ageInYears": "40"})
        db.session.flush()
        db.session.get(VaSubmissions, sid).org_unit_id = district.org_unit_id
        db.session.get(VaSubmissions, sid).org_unit_resolution = "manual"
        db.session.commit()

        refresh_submission_analytics_mv()

        row = db.session.execute(
            sa.text(
                f"SELECT org_unit_id, org_unit_code, org_unit_path "
                f"FROM {CORE_MV_NAME} WHERE va_sid = :sid"
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertEqual(row["org_unit_id"], district.org_unit_id)
        self.assertEqual(row["org_unit_code"], "ORGCOLD01")
        self.assertEqual(str(row["org_unit_path"]), "ORGCOLD01")

    def test_core_mv_org_unit_columns_are_null_for_unrouted_submission(self):
        """A submission with no unit (no tree, or unrouted) stays NULL."""
        sid = "uuid:mv-org-unit-null"
        self._add_submission(sid, {"age_group": "adult", "ageInYears": "40"})
        db.session.commit()

        refresh_submission_analytics_mv()

        row = db.session.execute(
            sa.text(
                f"SELECT org_unit_id, org_unit_code FROM {CORE_MV_NAME} "
                f"WHERE va_sid = :sid"
            ),
            {"sid": sid},
        ).mappings().one()

        self.assertIsNone(row["org_unit_id"])
        self.assertIsNone(row["org_unit_code"])

    def test_org_unit_subtree_rollup_counts_descendants_once(self):
        """A district's total includes its PHC's submissions exactly once,
        and the PHC's own total is not inflated by its parent's rows."""
        district, phc = self._make_org_tree(self.PROJECT_ID, prefix="rollup")

        district_sid = "uuid:mv-rollup-district"
        phc_sid = "uuid:mv-rollup-phc"
        self._add_submission(district_sid, {"age_group": "adult", "ageInYears": "40"})
        self._add_submission(phc_sid, {"age_group": "adult", "ageInYears": "40"})
        db.session.flush()
        db.session.get(VaSubmissions, district_sid).org_unit_id = district.org_unit_id
        db.session.get(VaSubmissions, district_sid).org_unit_resolution = "manual"
        db.session.get(VaSubmissions, phc_sid).org_unit_id = phc.org_unit_id
        db.session.get(VaSubmissions, phc_sid).org_unit_resolution = "manual"
        db.session.commit()

        refresh_submission_analytics_mv()

        stats = get_dm_org_unit_stats_from_mv(
            project_id=self.PROJECT_ID,
            project_ids=[],
            project_site_pairs=[(self.PROJECT_ID, self.SITE_ID)],
        )
        by_code = {row["org_unit_code"]: row["total_submissions"] for row in stats}

        self.assertEqual(by_code["ROLLUPD01"], 2)
        self.assertEqual(by_code["ROLLUPP01"], 1)

    def test_no_tree_project_kpi_and_site_stats_unchanged(self):
        """A project with no organization tree is untouched by the new
        columns: KPI counts and site-grouped stats behave exactly as before.
        """
        sid = "uuid:mv-no-tree"
        self._add_submission(sid, {"age_group": "adult", "ageInYears": "40"})
        db.session.commit()

        refresh_submission_analytics_mv()

        scope = [(self.PROJECT_ID, self.SITE_ID)]
        kpi = get_dm_kpi_from_mv([], scope)
        stats = get_dm_project_site_stats_from_mv(
            project_ids=[], project_site_pairs=scope, timezone_name="UTC"
        )

        self.assertGreaterEqual(kpi["total_submissions"], 1)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["project_id"], self.PROJECT_ID)
        self.assertEqual(stats[0]["site_id"], self.SITE_ID)
