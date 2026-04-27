import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app import db
from app.models import (
    MasIcd1020192,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODING_IN_PROGRESS,
)
from tests.base import BaseTestCase


class TestDemoFinalCodRoute(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"DF{_RUN_SUFFIX}"
    BASE_SITE_ID = f"F{_RUN_SUFFIX[:3]}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Demo Final COD Project",
                project_nickname="DemoFinal",
                project_status=VaStatuses.active,
                project_registered_at=datetime.now(UTC),
                project_updated_at=datetime.now(UTC),
            )
        )
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Demo Final COD Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=datetime.now(UTC),
                site_updated_at=datetime.now(UTC),
            )
        )
        db.session.flush()

        form = VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="DEMO_FINAL_FORM",
            odk_project_id="1",
            form_type="WHO_2022_VA",
            form_status=VaStatuses.active,
            form_registered_at=datetime.now(UTC),
            form_updated_at=datetime.now(UTC),
        )
        db.session.add(form)

        submission = VaSubmissions(
            va_sid=f"uuid:test-demo-final-{cls.BASE_PROJECT_ID.lower()}",
            va_form_id=form.form_id,
            va_submission_date=datetime.now(UTC),
            va_odk_updatedat=datetime.now(UTC),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="DEMO-FINAL-1",
            va_uniqueid_real="DEMO-FINAL-1",
            va_uniqueid_masked="DEMO-FINAL-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=60,
            va_deceased_gender="Male",
            va_summary=[],
            va_catcount={},
            va_category_list=["vademographicdetails", "vacodassessment"],
        )
        db.session.add(submission)
        db.session.commit()
        ensure_active_payload_version(
            submission,
            payload_data={},
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.commit()
        now = datetime.now(UTC)
        for code, title, sex, age_group in (
            ("I24", "Other acute ischaemic heart diseases", "both", "all"),
            ("O71.1", "Rupture of uterus during labour", "female", "adult"),
        ):
            db.session.merge(
                MasIcd1020192(
                    code=code,
                    title=title,
                    node_type="category",
                    semantic_level="detailed_code" if "." in code else "three_character",
                    sort_order=1,
                    parent_code=code.split(".")[0] if "." in code else None,
                    chapter_code="IX" if code.startswith("I") else "XV",
                    chapter_title=(
                        "Diseases of the circulatory system"
                        if code.startswith("I")
                        else "Pregnancy, childbirth and the puerperium"
                    ),
                    block_code="I20-I25" if code.startswith("I") else "O60-O75",
                    block_title=(
                        "Ischaemic heart diseases"
                        if code.startswith("I")
                        else "Complications of labour and delivery"
                    ),
                    three_character_code=code.split(".")[0],
                    three_character_title=title,
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code="." not in code,
                    is_detailed_code="." in code,
                    is_coding_selectable=True,
                    sex_selectable=sex,
                    age_group_selectable=age_group,
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.session.commit()
        cls.sid = submission.va_sid

    def setUp(self):
        super().setUp()
        db.session.execute(
            db.update(VaFinalAssessments)
            .where(VaFinalAssessments.va_sid == self.sid)
            .values(va_finassess_status=VaStatuses.deactive)
        )
        db.session.execute(
            db.update(VaInitialAssessments)
            .where(VaInitialAssessments.va_sid == self.sid)
            .values(va_iniassess_status=VaStatuses.deactive)
        )
        db.session.execute(
            db.update(VaAllocations)
            .where(VaAllocations.va_sid == self.sid)
            .values(va_allocation_status=VaStatuses.deactive)
        )
        db.session.execute(
            db.delete(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == self.sid)
        )
        db.session.commit()

    def _activate_coding_session(self, *, with_initial: bool = True):
        db.session.add(
            VaAllocations(
                va_allocation_id=uuid.uuid4(),
                va_sid=self.sid,
                va_allocated_to=self.base_admin_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        if with_initial:
            db.session.add(
                VaInitialAssessments(
                    va_sid=self.sid,
                    va_iniassess_by=self.base_admin_user.user_id,
                    va_immediate_cod="I24",
                    va_antecedent_cod="I24",
                    va_other_conditions=None,
                    va_iniassess_status=VaStatuses.active,
                )
            )
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == self.sid)
        )
        if workflow is None:
            db.session.add(
                VaSubmissionWorkflow(
                    va_sid=self.sid,
                    workflow_state=WORKFLOW_CODING_IN_PROGRESS,
                )
            )
        else:
            workflow.workflow_state = WORKFLOW_CODING_IN_PROGRESS
        db.session.commit()

    def test_demo_final_cod_save_keeps_new_final_active(self):
        self._login(self.base_admin_id)
        self._activate_coding_session()

        with patch("app.routes.va_form.bust_coder_dashboard_cache") as mock_bust:
            response = self.client.post(
                (
                    f"/vaform/{self.sid}/vafinalasses"
                    "?action=vacode&actiontype=vademo_start_coding"
                ),
                data={
                    "va_conclusive_cod": "I24-Other acute ischaemic heart diseases",
                    "va_finassess_remark": "demo final cod",
                    "va_save_assessment": "1",
                },
                headers={
                    **self._csrf_headers(),
                    "HX-Request": "true",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        mock_bust.assert_called_once_with(self.base_admin_user.user_id)

        final_row = db.session.scalar(
            db.select(VaFinalAssessments).where(
                VaFinalAssessments.va_sid == self.sid,
                VaFinalAssessments.va_finassess_by == self.base_admin_user.user_id,
            )
        )
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == self.sid
            )
        )
        allocation = db.session.scalar(
            db.select(VaAllocations).where(
                VaAllocations.va_sid == self.sid,
                VaAllocations.va_allocated_to == self.base_admin_user.user_id,
            )
        )

        self.assertIsNotNone(final_row)
        self.assertEqual(final_row.va_finassess_status, VaStatuses.active)
        self.assertIsNotNone(final_row.demo_expires_at)
        self.assertEqual(workflow.workflow_state, WORKFLOW_CODER_FINALIZED)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.deactive)

    def test_initial_cod_save_rejects_icd_outside_submission_age_sex_policy(self):
        self._login(self.base_admin_id)
        self._activate_coding_session(with_initial=False)

        response = self.client.post(
            (
                f"/vaform/{self.sid}/vainitialasses"
                "?action=vacode&actiontype=vademo_start_coding"
            ),
            data={
                "va_immediate_cod": "O71.1 Rupture of uterus during labour",
                "va_antecedent_cod": "I24 Other acute ischaemic heart diseases",
                "va_save_assessment": "1",
            },
            headers={
                **self._csrf_headers(),
                "HX-Request": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not selectable for this submission", response.data)
        saved = db.session.scalar(
            db.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == self.sid,
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
        )
        self.assertIsNone(saved)

    def test_final_cod_save_rejects_icd_outside_submission_age_sex_policy(self):
        self._login(self.base_admin_id)
        self._activate_coding_session()

        response = self.client.post(
            (
                f"/vaform/{self.sid}/vafinalasses"
                "?action=vacode&actiontype=vademo_start_coding"
            ),
            data={
                "va_conclusive_cod": "O71.1 Rupture of uterus during labour",
                "va_finassess_remark": "demo final cod",
                "va_save_assessment": "1",
            },
            headers={
                **self._csrf_headers(),
                "HX-Request": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not selectable for this submission", response.data)
        final_row = db.session.scalar(
            db.select(VaFinalAssessments).where(
                VaFinalAssessments.va_sid == self.sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
            )
        )
        self.assertIsNone(final_row)
