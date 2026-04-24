from datetime import datetime, timezone

from app import db
from app.models import (
    VaFinalAssessments,
    VaInitialAssessments,
    VaStatuses,
    VaSubmissions,
)
from app.routes.va_form import _get_display_initial_assessment, renderpartial
from app.routes.forms.partials import renderpartial as forms_renderpartial
from tests.base import BaseTestCase


class CodingViewCodAssessmentTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}01"
    SID = "sid-view-cod-assessment"

    def setUp(self):
        super().setUp()
        now = datetime.now(timezone.utc)

        self._ensure_project_site_fixture(
            project_id=self.BASE_PROJECT_ID,
            site_id=self.BASE_SITE_ID,
            project_name="Base Test Project",
            project_nickname="BaseTest",
            site_name="Base Test Site",
            create_research_project=True,
            now=now,
        )
        self._ensure_form_fixture(
            form_id=self.FORM_ID,
            project_id=self.BASE_PROJECT_ID,
            site_id=self.BASE_SITE_ID,
            odk_form_id="BASE_FORM",
            odk_project_id="1",
            form_type="WHO VA 2022",
            now=now,
        )

        if db.session.get(VaSubmissions, self.SID) is None:
            db.session.add(
                VaSubmissions(
                    va_sid=self.SID,
                    va_form_id=self.FORM_ID,
                    va_submission_date=now,
                    va_odk_updatedat=now,
                    va_data_collector="Collector",
                    va_odk_reviewstate=None,
                    va_instance_name=self.SID,
                    va_uniqueid_real=self.SID,
                    va_uniqueid_masked=self.SID,
                    va_consent="yes",
                    va_narration_language="English",
                    va_deceased_age=42,
                    va_deceased_gender="male",
                    va_summary=[],
                    va_catcount={},
                    va_category_list=["vacodassessment"],
                )
            )
            db.session.flush()

    def test_display_initial_assessment_prefers_active_row(self):
        now = datetime.now(timezone.utc)
        active_initial = VaInitialAssessments(
            va_sid=self.SID,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="Immediate Active COD",
            va_antecedent_cod="Antecedent Active COD",
            va_other_conditions="Active Condition",
            va_iniassess_status=VaStatuses.active,
            va_iniassess_createdat=now,
            va_iniassess_updatedat=now,
        )
        db.session.add(active_initial)
        db.session.commit()

        resolved = _get_display_initial_assessment(self.SID)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.va_iniassess_id, active_initial.va_iniassess_id)
        self.assertEqual(resolved.va_other_conditions, "Active Condition")

    def test_va_form_compat_module_reexports_renderpartial(self):
        self.assertIs(renderpartial, forms_renderpartial)

    def test_display_initial_assessment_falls_back_to_final_linked_source(self):
        now = datetime.now(timezone.utc)
        initial = VaInitialAssessments(
            va_sid=self.SID,
            va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="Immediate Test COD",
            va_antecedent_cod="Antecedent Test COD",
            va_other_conditions="Condition A | Condition B",
            va_iniassess_status=VaStatuses.deactive,
            va_iniassess_createdat=now,
            va_iniassess_updatedat=now,
        )
        db.session.add(initial)
        db.session.flush()
        db.session.add(
            VaFinalAssessments(
                va_sid=self.SID,
                va_finassess_by=self.base_coder_user.user_id,
                source_initial_assessment_id=initial.va_iniassess_id,
                va_conclusive_cod="Final Test COD",
                va_finassess_remark="Technical note for review",
                va_finassess_status=VaStatuses.active,
                va_finassess_createdat=now,
                va_finassess_updatedat=now,
            )
        )
        db.session.commit()

        resolved = _get_display_initial_assessment(self.SID)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.va_iniassess_id, initial.va_iniassess_id)
        self.assertEqual(resolved.va_immediate_cod, "Immediate Test COD")
        self.assertEqual(resolved.va_antecedent_cod, "Antecedent Test COD")
        self.assertEqual(resolved.va_other_conditions, "Condition A | Condition B")
