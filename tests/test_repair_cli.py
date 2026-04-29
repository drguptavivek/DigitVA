from datetime import datetime, timezone

from app import db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from tests.base import BaseTestCase


class RepairCliTests(BaseTestCase):
    PROJECT_ID = "RPR01"
    SITE_ID = "RP01"
    FORM_ID = "RPR01RP0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = cls.app.test_cli_runner()
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaResearchProjects(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Repair CLI Project",
                    project_nickname="RepairCLI",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaProjectMaster(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Repair CLI Project",
                    project_nickname="RepairCLI",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.SITE_ID,
                    site_name="Repair CLI Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                VaSites(
                    site_id=cls.SITE_ID,
                    project_id=cls.PROJECT_ID,
                    site_name="Repair CLI Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaProjectSites(
                    project_id=cls.PROJECT_ID,
                    site_id=cls.SITE_ID,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                ),
            ]
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="REPAIR_FORM",
                odk_project_id="77",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    def _make_submission(self, sid: str):
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="repair",
                va_odk_reviewstate="reviewed",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=50,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state="coder_finalized",
            )
        )

    def test_reactivate_step1_after_final_dry_run_and_apply(self):
        sid = "uuid:repair-cli-dry-run-apply"
        self._make_submission(sid)
        initial = VaInitialAssessments(
            va_sid=sid,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="I21-Acute myocardial infarction",
            va_antecedent_cod="I10-Essential hypertension",
            va_iniassess_status=VaStatuses.deactive,
        )
        db.session.add(initial)
        db.session.flush()
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                va_finassess_by=self.base_coder_user.user_id,
                source_initial_assessment_id=initial.va_iniassess_id,
                va_conclusive_cod="I21-Acute myocardial infarction",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        dry_run = self.runner.invoke(
            args=["repair", "reactivate-step1-after-final", "--sid", sid]
        )
        self.assertEqual(dry_run.exit_code, 0, dry_run.output)
        self.assertIn("WOULD REPAIR", dry_run.output)
        self.assertIn("mode=dry-run", dry_run.output)

        status_after_dry_run = db.session.scalar(
            db.select(VaInitialAssessments.va_iniassess_status).where(
                VaInitialAssessments.va_iniassess_id == initial.va_iniassess_id
            )
        )
        self.assertEqual(status_after_dry_run, VaStatuses.deactive)

        apply_result = self.runner.invoke(
            args=[
                "repair",
                "reactivate-step1-after-final",
                "--sid",
                sid,
                "--apply",
            ]
        )
        self.assertEqual(apply_result.exit_code, 0, apply_result.output)
        self.assertIn("REPAIR", apply_result.output)
        self.assertIn("mode=apply", apply_result.output)

        repaired = db.session.get(VaInitialAssessments, initial.va_iniassess_id)
        self.assertEqual(repaired.va_iniassess_status, VaStatuses.active)

        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == sid,
                VaSubmissionsAuditlog.va_audit_action
                == "step1 reactivated after final cod repair",
            )
        )
        self.assertIsNotNone(audit)

    def test_reactivate_step1_after_final_skips_conflicting_active_initial(self):
        sid = "uuid:repair-cli-conflict"
        self._make_submission(sid)
        linked_initial = VaInitialAssessments(
            va_sid=sid,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="J18-Pneumonia",
            va_antecedent_cod="R05-Cough",
            va_iniassess_status=VaStatuses.deactive,
        )
        active_initial = VaInitialAssessments(
            va_sid=sid,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="A41-Sepsis",
            va_antecedent_cod="R50-Fever",
            va_iniassess_status=VaStatuses.active,
        )
        db.session.add_all([linked_initial, active_initial])
        db.session.flush()
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                va_finassess_by=self.base_coder_user.user_id,
                source_initial_assessment_id=linked_initial.va_iniassess_id,
                va_conclusive_cod="J18-Pneumonia",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        result = self.runner.invoke(
            args=[
                "repair",
                "reactivate-step1-after-final",
                "--sid",
                sid,
                "--apply",
            ]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("SKIP conflict", result.output)

        stale = db.session.get(VaInitialAssessments, linked_initial.va_iniassess_id)
        self.assertEqual(stale.va_iniassess_status, VaStatuses.deactive)
