"""The coding screen follows the project's ICD classification.

digitva-dus.2, digitva-0n3. Policy:
docs/policy/va-form-project-configuration.md ("5. ICD classification"). The
'selectable' classification is retired: every project is fixed to one
catalogue, which refuses the other catalogue on save and in search.

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
        # ICD-11 means DORIS at the DB level (CHECK
        # cod_entry_mode_classification, digitva-0n3): keep cod_entry_mode in
        # sync with the classification being tested.
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.icd_classification = value
        project.cod_entry_mode = "doris" if value == "icd11" else "simple"
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

    def _save_doris_step1(self, underlying):
        # A masked ICD-11 project's Step 1 is the DORIS certificate
        # (digitva-0n3 phase 2); the coder's underlying cause is still
        # checked against the project's catalogue.
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = "sha256:pinned-image"
        certificate = {"ICDVersion": "ICD11", "Part1": [{"Conditions": [{"Text": "Acute myocardial infarction", "Code": "BA41"}]}]}
        with patch(
            "app.routes.va_form.verify_process_submission",
            return_value={"certificate": certificate, "doris": {}, "codedit": {}},
        ):
            return self._post(
                "vainitialasses",
                {"va_antecedent_cod": underlying, "doris_certificate": "{}", "doris_process_token": "signed"},
            )

    def _active_initial(self):
        return db.session.scalar(
            db.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == self.sid,
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
        )

    # ── Save round trip ────────────────────────────────────────────────────

    def test_fixed_projects_refuse_the_other_catalogue(self):
        self._set_project("icd10")
        response = self._save_step1(ICD11_VALUE, ICD11_VALUE)
        self.assertIn(b"Select a valid ICD-10 code.", response.data)
        self.assertIsNone(self._active_initial())

        self._set_project("icd11")
        response = self._save_doris_step1(ICD10_VALUE)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Select a valid ICD-11 code.", response.data)
        self.assertIsNone(self._active_initial())

        response = self._save_doris_step1(ICD11_VALUE)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNotNone(self._active_initial())

    # ── Screen ─────────────────────────────────────────────────────────────

    def test_switch_never_renders(self):
        url = f"/vaform/{self.sid}/vainitialasses{ACTION}"

        # Masked ICD-11 Step 1 is the DORIS certificate, not a catalogue search.
        self._set_project("icd11")
        body = self.client.get(url).data
        self.assertIn(b"data-doris-editor", body)
        self.assertNotIn(b"data-icd-classification", body)
        self.assertNotIn(b"Code this death in", body)

        self._set_project("icd10")
        body = self.client.get(url).data
        self.assertIn(b'data-icd-classification="icd10"', body)
        self.assertNotIn(b"Code this death in", body)

    def test_screen_follows_the_project_not_a_stored_value(self):
        # A Step 1 saved in ICD-11, then the project fixed to ICD-10 (as the
        # digitva-0n3 migration does to a former 'selectable' project): Step 2
        # presets the ICD-11 value but must search ICD-10, because the ICD-11
        # APIs refuse an ICD-10 project.
        self._set_project("icd11")
        self._save_doris_step1(ICD11_VALUE)
        self.assertIsNotNone(self._active_initial())
        self._set_project("icd10")

        body = self.client.get(f"/vaform/{self.sid}/vafinalasses{ACTION}").data
        self.assertIn(ICD11_VALUE.split()[0].encode(), body)
        self.assertIn(b'data-icd-classification="icd10"', body)
        self.assertNotIn(b'data-icd-classification="icd11"', body)

    # ── Search ─────────────────────────────────────────────────────────────

    def test_search_follows_the_project_setting(self):
        icd10_url = f"/api/v1/icd10/2019-2/coding-search/{self.sid}?q=ischaemic"
        icd11_url = f"/api/v1/icd11/coding-search/{self.sid}?q=myocardial"

        self._set_project("icd11")
        icd11 = self.client.get(icd11_url)
        self.assertEqual(icd11.status_code, 200)
        self.assertEqual([r["icd_code"] for r in icd11.get_json()], ["BA41"])

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
