"""The coding screen follows the project's ICD classification.

digitva-dus.2. Policy: docs/policy/va-form-project-configuration.md
("5. ICD classification"). A selectable project stores whichever
classification the coder picked, recorded by the value's code shape; a fixed
project refuses the other catalogue on save and in search.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/routes/test_icd_classification_coding_screen.py -q
"""
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app import db
from app.models import (
    MasIcd11Mms,
    MasIcd1020192,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODING_IN_PROGRESS
from tests.base import BaseTestCase

ICD10_VALUE = "I24 Other acute ischaemic heart diseases"
ICD11_VALUE = "BA41 Acute myocardial infarction"
ACTION = "?action=vacode&actiontype=vademo_start_coding"


class TestIcdClassificationCodingScreen(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"IC{_RUN_SUFFIX}"
    BASE_SITE_ID = f"C{_RUN_SUFFIX[:3]}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        who_uri = "http://id.who.int/icd/release/11/2026-01/mms/1334938734"
        who_patch = patch(
            "app.services.who_icd_api.get_icd11_codeinfo",
            return_value={
                "@id": "http://id.who.int/icd/release/11/2026-01/mms/codeinfo/BA41",
                "code": "BA41",
                "stemId": who_uri,
            },
        )
        who_patch.start()
        cls.addClassCleanup(who_patch.stop)
        cls._ensure_base_research_project_and_site()
        now = datetime.now(UTC)
        form = VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="ICD_SWITCH_FORM",
            odk_project_id="1",
            form_type="WHO_2022_VA",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        )
        db.session.add(form)
        submission = VaSubmissions(
            va_sid=f"uuid:test-icd-switch-{cls.BASE_PROJECT_ID.lower()}",
            va_form_id=form.form_id,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="ICD-SWITCH-1",
            va_uniqueid_real="ICD-SWITCH-1",
            va_uniqueid_masked="ICD-SWITCH-1",
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
        db.session.merge(
            MasIcd1020192(
                code="I24",
                title="Other acute ischaemic heart diseases",
                node_type="category",
                semantic_level="three_character",
                sort_order=1,
                chapter_code="IX",
                chapter_title="Diseases of the circulatory system",
                block_code="I20-I25",
                block_title="Ischaemic heart diseases",
                three_character_code="I24",
                three_character_title="Other acute ischaemic heart diseases",
                has_children=False,
                is_leaf=True,
                is_three_character_code=True,
                is_detailed_code=False,
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                policy_status="unreviewed",
                source_version="ICD-10-2019",
                source_path="test",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/release/11/mms/1334938734",
                code="BA41",
                title="Acute myocardial infarction",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.commit()
        cls.sid = submission.va_sid

    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)
        db.session.add(
            VaAllocations(
                va_allocation_id=uuid.uuid4(),
                va_sid=self.sid,
                va_allocated_to=self.base_admin_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaSubmissionWorkflow(va_sid=self.sid, workflow_state=WORKFLOW_CODING_IN_PROGRESS)
        )
        db.session.commit()

    def _set_project(self, value):
        db.session.get(VaProjectMaster, self.BASE_PROJECT_ID).icd_classification = value
        db.session.commit()

    def _post(self, partial, data):
        return self.client.post(
            f"/vaform/{self.sid}/{partial}{ACTION}",
            data={**data, "va_save_assessment": "1"},
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

    def _save_step1(self, immediate, antecedent):
        return self._post(
            "vainitialasses",
            {"va_immediate_cod": immediate, "va_antecedent_cod": antecedent},
        )

    def _active_initial(self):
        return db.session.scalar(
            db.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == self.sid,
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
        )

    # ── Save round trip ────────────────────────────────────────────────────

    def test_selectable_project_stores_an_icd11_pick(self):
        self._set_project("selectable")
        response = self._save_step1(ICD11_VALUE, ICD11_VALUE)
        self.assertEqual(response.status_code, 200)
        saved = self._active_initial()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.va_immediate_cod, ICD11_VALUE)
        self.assertEqual(saved.va_antecedent_cod, ICD11_VALUE)
        # The final screen that comes back starts on ICD-11, from Step 1's value.
        self.assertIn(b'data-icd-classification="icd11"', response.data)

        final = self._post(
            "vafinalasses",
            {"va_conclusive_cod": ICD11_VALUE, "va_finassess_remark": "icd11"},
        )
        self.assertEqual(final.status_code, 200)
        self.assertTrue(final.get_json()["success"])
        final_row = db.session.scalar(
            db.select(VaFinalAssessments).where(
                VaFinalAssessments.va_sid == self.sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(final_row)
        self.assertEqual(final_row.va_conclusive_cod, ICD11_VALUE)

    def test_selectable_project_stores_an_icd10_pick(self):
        self._set_project("selectable")
        response = self._save_step1(ICD10_VALUE, ICD10_VALUE)
        self.assertEqual(response.status_code, 200)
        saved = self._active_initial()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.va_immediate_cod, ICD10_VALUE)
        self.assertIn(b'data-icd-classification="icd10"', response.data)

    def test_selectable_project_rejects_a_mixed_step1(self):
        self._set_project("selectable")
        response = self._save_step1(ICD10_VALUE, ICD11_VALUE)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"both be ICD-10 or both be ICD-11", response.data)
        self.assertIsNone(self._active_initial())

    def test_fixed_projects_refuse_the_other_catalogue(self):
        self._set_project("icd10")
        response = self._save_step1(ICD11_VALUE, ICD11_VALUE)
        self.assertIn(b"Select a valid ICD-10 code.", response.data)
        self.assertIsNone(self._active_initial())

        self._set_project("icd11")
        response = self._save_step1(ICD10_VALUE, ICD10_VALUE)
        self.assertIn(b"Select a valid ICD-11 code.", response.data)
        self.assertIsNone(self._active_initial())

        response = self._save_step1(ICD11_VALUE, ICD11_VALUE)
        self.assertIsNotNone(self._active_initial())

    # ── Screen ─────────────────────────────────────────────────────────────

    def test_switch_renders_only_for_selectable_projects(self):
        url = f"/vaform/{self.sid}/vainitialasses{ACTION}"
        self._set_project("selectable")
        body = self.client.get(url).data
        self.assertIn(b"Code this death in", body)
        self.assertIn(b'data-icd-classification="icd10"', body)
        self.assertIn(b"/api/v1/icd11/coding-search/", body)

        self._set_project("icd11")
        body = self.client.get(url).data
        self.assertIn(b'data-icd-classification="icd11"', body)
        self.assertNotIn(b"Code this death in", body)

        self._set_project("icd10")
        body = self.client.get(url).data
        self.assertIn(b'data-icd-classification="icd10"', body)
        self.assertNotIn(b"Code this death in", body)

    # ── Search ─────────────────────────────────────────────────────────────

    def test_search_follows_the_project_setting(self):
        icd10_url = f"/api/v1/icd10/2019-2/coding-search/{self.sid}?q=ischaemic"
        icd11_url = f"/api/v1/icd11/coding-search/{self.sid}?q=myocardial"

        self._set_project("selectable")
        icd11 = self.client.get(icd11_url)
        self.assertEqual(icd11.status_code, 200)
        self.assertEqual([r["icd_code"] for r in icd11.get_json()], ["BA41"])
        icd10 = self.client.get(icd10_url)
        self.assertEqual(icd10.status_code, 200)
        self.assertEqual([r["icd_code"] for r in icd10.get_json()], ["I24"])

        self._set_project("icd10")
        self.assertEqual(self.client.get(icd11_url).status_code, 400)
        self.assertEqual(self.client.get(icd10_url).status_code, 200)

        self._set_project("icd11")
        self.assertEqual(self.client.get(icd10_url).status_code, 400)
        self.assertEqual(self.client.get(icd11_url).status_code, 200)

    def test_icd11_search_requires_a_coding_session(self):
        db.session.execute(
            db.update(VaAllocations)
            .where(VaAllocations.va_sid == self.sid)
            .values(va_allocation_status=VaStatuses.deactive)
        )
        db.session.commit()
        self._set_project("icd11")
        response = self.client.get(f"/api/v1/icd11/coding-search/{self.sid}?q=myocardial")
        self.assertIn(response.status_code, (403, 404))
