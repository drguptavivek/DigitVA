import uuid
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaResearchProjects,
    VaSites,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.final_cod_authority_service import upsert_final_cod_authority
from app.services.submission_analytics_mv import (
    build_submission_analytics_mv_sql,
    get_dm_kpi_from_mv,
    get_dm_project_site_stats_from_mv,
    refresh_submission_analytics_mv,
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
        db.session.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_mv_sql()))
        db.session.execute(
            sa.text(
                "CREATE UNIQUE INDEX ix_va_submission_analytics_mv_va_sid "
                "ON va_submission_analytics_mv (va_sid)"
            )
        )
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            db.session.execute(
                sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE")
            )
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
                va_data=payload,
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
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

        rows = db.session.execute(
            sa.text(
                """
                SELECT
                    va_sid,
                    normalized_age_hours,
                    normalized_age_days,
                    normalized_age_months,
                    normalized_age_years,
                    normalized_age_source,
                    age_precision,
                    analytics_age_band,
                    final_cod_text,
                    final_icd,
                    initial_immediate_icd,
                    smartva_cause1_icd
                FROM va_submission_analytics_mv
                WHERE
                    va_sid = :neonate_sid
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

        row_by_sid = {row["va_sid"]: row for row in rows}

        neonate = row_by_sid[neonate_sid]
        self.assertEqual(neonate["normalized_age_source"], "age_neonate_hours")
        self.assertEqual(neonate["age_precision"], "hours")
        self.assertEqual(neonate["analytics_age_band"], "neonate")
        self.assertEqual(neonate["normalized_age_hours"], Decimal("4"))
        self.assertEqual(neonate["normalized_age_days"], Decimal("0"))
        self.assertEqual(neonate["normalized_age_years"], Decimal("0"))

        child = row_by_sid[child_sid]
        self.assertEqual(child["normalized_age_source"], "ageInDays")
        self.assertEqual(child["age_precision"], "days")
        self.assertEqual(child["analytics_age_band"], "child")
        self.assertEqual(child["normalized_age_days"], Decimal("45"))
        self.assertAlmostEqual(float(child["normalized_age_months"]), 45 / 30.4375, places=4)

        adult = row_by_sid[adult_sid]
        self.assertEqual(adult["normalized_age_source"], "ageInYears2")
        self.assertEqual(adult["age_precision"], "years")
        self.assertEqual(adult["analytics_age_band"], "15_49y")
        self.assertEqual(adult["final_cod_text"], "I21-Acute myocardial infarction")
        self.assertEqual(adult["final_icd"], "I21")
        self.assertEqual(adult["initial_immediate_icd"], "I21")
        self.assertEqual(adult["smartva_cause1_icd"], "I21")

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
            workflow="revoked_va_data_changed",
        )
        self.assertEqual(nonmatching_kpi["total_submissions"], 0)
