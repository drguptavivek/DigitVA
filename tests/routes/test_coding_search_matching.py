"""Spelling-fold and hyphen-insensitive matching on the coding-search routes.

digitva-zpe.3. Grounded on real catalogue entries: ICD-10 2019 titles are
UK-spelled (Anaemia, Gastro-oesophageal, Cat-scratch), ICD-11 MMS 2026-01 is
mixed (Refractory anaemia UK, Hereditary angioedema US, Non-ulcerative).

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/routes/test_coding_search_matching.py -q
"""

import uuid
from datetime import UTC, datetime

from app import db
from app.models import (
    MasIcd11Mms,
    MasIcd1020192,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.icd_search_vocabulary_service import create_term, set_active
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODING_IN_PROGRESS
from tests.base import BaseTestCase

ACTION = "?action=vacode&actiontype=vademo_start_coding"


class TestCodingSearchMatching(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"CM{_RUN_SUFFIX}"
    BASE_SITE_ID = f"C{_RUN_SUFFIX[:3]}"
    SID = f"uuid:test-coding-matching-{_RUN_SUFFIX.lower()}"
    FORM_ID = f"{BASE_PROJECT_ID}{BASE_SITE_ID}01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        now = datetime.now(UTC)
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="MATCHING_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        submission = VaSubmissions(
            va_sid=cls.SID,
            va_form_id=cls.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="MATCHING-1",
            va_uniqueid_real="MATCHING-1",
            va_uniqueid_masked="MATCHING-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=45,
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
        cls._merge_icd10(now, "A25", "Rat-bite fevers", 1)
        cls._merge_icd10(now, "A28.1", "Cat-scratch disease", 2)
        cls._merge_icd10(now, "A41.9", "Sepsis, unspecified", 3)
        cls._merge_icd10(now, "D50", "Nutritional anaemia", 4)
        cls._merge_icd10(now, "K21", "Gastro-oesophageal reflux disease", 5)
        cls._merge_icd10(now, "X60", "Intentional self-harm", 6)
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/1A81",
                code="1A81",
                title="Non-ulcerative sexually transmitted chlamydial infection",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/2A30",
                code="2A30",
                title="Refractory anaemia",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/4A00.14",
                code="4A00.14",
                title="Hereditary angioedema",
                class_kind="category",
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
                source_version="test",
            )
        )
        db.session.commit()
        cls.sid = submission.va_sid

    @classmethod
    def _merge_icd10(cls, now, code, title, sort_order):
        db.session.merge(
            MasIcd1020192(
                code=code,
                title=title,
                node_type="category",
                semantic_level="three_character",
                sort_order=sort_order,
                chapter_code="I",
                chapter_title="Certain infectious and parasitic diseases",
                block_code="A00-B34",
                block_title="Infectious and parasitic disease test block",
                three_character_code=code.split(".")[0],
                three_character_title=title,
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

    def setUp(self):
        super().setUp()
        self._login(self.base_admin_id)
        db.session.add(
            VaAllocations(
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

    def _icd10(self, query):
        return self.client.get(f"/api/v1/icd10/2019-2/coding-search/{self.sid}?q={query}")

    def _icd11(self, query):
        db.session.get(VaProjectMaster, self.BASE_PROJECT_ID).icd_classification = "icd11"
        db.session.commit()
        return self.client.get(f"/api/v1/icd11/coding-search/{self.sid}?q={query}")

    def test_hyphen_placement_is_irrelevant_on_both_sides(self):
        for query in ("cat scratch", "cat-scratch", "catscratch"):
            with self.subTest(query=query):
                response = self._icd10(query)
                self.assertEqual(response.status_code, 200)
                self.assertIn("A28.1", [r["icd_code"] for r in response.get_json()])

    def test_gastro_oesophageal_reaches_its_codes_in_every_typing(self):
        for query in ("gastrooesophageal", "gastro oesophageal", "gastro-oesophageal"):
            with self.subTest(query=query):
                response = self._icd10(query)
                self.assertEqual(response.status_code, 200)
                self.assertIn("K21", [r["icd_code"] for r in response.get_json()])

    def test_us_spelled_query_finds_uk_titled_icd10_code(self):
        for query in ("anaemia", "anemia"):
            with self.subTest(query=query):
                response = self._icd10(query)
                self.assertEqual(response.status_code, 200)
                self.assertIn("D50", [r["icd_code"] for r in response.get_json()])

    def test_icd11_mixed_spellings_match(self):
        cases = (
            ("non ulcerative", "1A81"),
            ("non-ulcerative", "1A81"),
            ("refractory anemia", "2A30"),
            ("refractory anaemia", "2A30"),
            ("hereditary angio-oedema", "4A00.14"),
            ("hereditary angioedema", "4A00.14"),
        )
        for query, expected_code in cases:
            with self.subTest(query=query):
                response = self._icd11(query)
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    expected_code, [r["icd_code"] for r in response.get_json()]
                )

    def test_folded_matches_rank_as_focused_like_the_typed_form(self):
        response = self._icd11("refractory anemia")
        rows = {r["icd_code"]: r for r in response.get_json()}
        self.assertEqual(rows["2A30"]["tier"], "focused")

    def test_vocabulary_hit_through_spelling_and_hyphen_variants(self):
        create_term(
            term="self-harm",
            icd_classification="icd10",
            icd_code="X60",
            note="intentional self harm",
        )
        for query in ("self harm", "self-harm", "selfharm"):
            with self.subTest(query=query):
                response = self._icd10(query)
                self.assertEqual(response.status_code, 200)
                body = response.get_json()
                self.assertTrue(any(item.get("vocabulary") for item in body))

    def test_deactivating_one_spelling_row_leaves_the_other_reachable(self):
        first = create_term(
            term="septicaemia", icd_classification="icd10", icd_code="A41.9"
        )
        create_term(term="septicemia", icd_classification="icd10", icd_code="A41.9")
        set_active(str(first.term_id), False)

        response = self._icd10("septicaemia")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(any(item.get("vocabulary") for item in body))
        self.assertIn("A41.9", [item["icd_code"] for item in body])
