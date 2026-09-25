"""Coding-search telemetry: recording, choice linkage, export (digitva-zpe.3).

Policy: docs/policy/coding-search-telemetry.md — the search response must be
identical with telemetry on or off, the X-Search-Id header closes the loop to
the COD save, and a telemetry failure never breaks a search.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/routes/test_coding_search_telemetry.py -q
"""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    CodSearchTelemetry,
    MasIcd11Mms,
    MasIcd1020192,
    MasIcdSearchTerms,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import coding_search_telemetry_service
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODING_IN_PROGRESS
from tests.base import BaseTestCase

ACTION = "?action=vacode&actiontype=vademo_start_coding"
ICD10_DISPLAY = "I24 Other acute ischaemic heart diseases"


class TestCodingSearchTelemetry(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"CT{_RUN_SUFFIX}"
    BASE_SITE_ID = f"C{_RUN_SUFFIX[:3]}"
    SID = f"uuid:test-coding-telemetry-{_RUN_SUFFIX.lower()}"
    FORM_ID = f"{BASE_PROJECT_ID}{BASE_SITE_ID}01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Project + site master + project-site mapping, get-or-created under
        # this class's unique ids (tests/base.py rule 5).
        cls._ensure_base_research_project_and_site()
        now = datetime.now(UTC)
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="TELEMETRY_FORM",
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
            va_instance_name="TELEMETRY-1",
            va_uniqueid_real="TELEMETRY-1",
            va_uniqueid_masked="TELEMETRY-1",
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
        cls._merge_icd10(now, "I24", "Other acute ischaemic heart diseases")
        db.session.merge(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="http://id.who.int/icd/test/BA41",
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

    @classmethod
    def _merge_icd10(cls, now, code, title):
        db.session.merge(
            MasIcd1020192(
                code=code,
                title=title,
                node_type="category",
                semantic_level="three_character",
                sort_order=1,
                chapter_code="IX",
                chapter_title="Diseases of the circulatory system",
                block_code="I20-I25",
                block_title="Ischaemic heart diseases",
                three_character_code=code,
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

    def _search(self, query, search_id=None):
        url = f"/api/v1/icd10/2019-2/coding-search/{self.sid}?q={query}"
        if search_id is not None:
            url += f"&search_id={search_id}"
        return self.client.get(url)

    def _rows_for(self, query_text):
        return db.session.scalars(
            sa.select(CodSearchTelemetry).where(CodSearchTelemetry.query_text == query_text)
        ).all()

    # ── Query-side recording ───────────────────────────────────────────────

    def test_search_records_the_client_search_id_and_flags(self):
        search_id = uuid.uuid4()
        response = self._search("ischaemic", search_id=search_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Search-Id"], str(search_id))
        body = response.get_json()
        self.assertEqual([row["icd_code"] for row in body], ["I24"])

        rows = self._rows_for("ischaemic")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.search_id, search_id)
        self.assertEqual(row.surface, "icd10_coding")
        self.assertEqual(row.result_count, 1)
        self.assertFalse(row.zero_results)
        self.assertFalse(row.vocabulary_hit)
        self.assertIsNotNone(row.latency_ms)
        self.assertEqual(row.role, "admin")

    def test_search_body_is_identical_with_and_without_telemetry_fields(self):
        with_field = self._search("ischaemic", search_id=uuid.uuid4())
        without_field = self._search("ischaemic")
        self.assertEqual(with_field.status_code, 200)
        self.assertEqual(without_field.status_code, 200)
        self.assertEqual(with_field.get_json(), without_field.get_json())

    def test_absent_search_id_is_generated_and_echoed(self):
        response = self._search("ischaemic")

        self.assertEqual(response.status_code, 200)
        echoed = uuid.UUID(response.headers["X-Search-Id"])
        rows = db.session.scalars(
            sa.select(CodSearchTelemetry).where(CodSearchTelemetry.search_id == echoed)
        ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].query_text, "ischaemic")

    def test_an_invalid_search_id_never_breaks_the_search(self):
        response = self._search("ischaemic", search_id="not-a-uuid")

        self.assertEqual(response.status_code, 200)
        echoed = uuid.UUID(response.headers["X-Search-Id"])
        self.assertEqual(echoed.version, 4)

    def test_zero_results_flags_the_row(self):
        response = self._search("zzznothing")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        rows = self._rows_for("zzznothing")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].result_count, 0)
        self.assertTrue(rows[0].zero_results)

    def test_a_vocabulary_hit_flags_the_row(self):
        db.session.add(
            MasIcdSearchTerms(
                term="heartattack",
                term_normalized="heartattack",
                icd_classification="icd10",
                icd_code="I24",
                source="admin",
            )
        )
        db.session.commit()

        response = self._search("heartattack")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(any(item.get("vocabulary") for item in body))
        rows = self._rows_for("heartattack")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].vocabulary_hit)
        self.assertFalse(rows[0].zero_results)

    def test_icd11_search_records_the_icd11_surface(self):
        db.session.get(VaProjectMaster, self.BASE_PROJECT_ID).icd_classification = "icd11"
        db.session.commit()

        search_id = uuid.uuid4()
        response = self.client.get(
            f"/api/v1/icd11/coding-search/{self.sid}?q=myocardial&search_id={search_id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Search-Id"], str(search_id))
        self.assertEqual([r["icd_code"] for r in response.get_json()], ["BA41"])
        rows = self._rows_for("myocardial")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].search_id, search_id)
        self.assertEqual(rows[0].surface, "icd11_coding")

    def test_a_telemetry_failure_never_breaks_the_search(self):
        def exploding(**kwargs):
            raise RuntimeError("telemetry store unavailable")

        original = coding_search_telemetry_service.record_query
        coding_search_telemetry_service.record_query = exploding
        try:
            response = self._search("ischaemic")
        finally:
            coding_search_telemetry_service.record_query = original

        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["icd_code"] for r in response.get_json()], ["I24"])
        self.assertEqual(self._rows_for("ischaemic"), [])

    # ── Selection linkage on the conclusive COD save ───────────────────────

    def _post_final(self, extra_fields):
        data = {"va_conclusive_cod": ICD10_DISPLAY, "va_finassess_remark": "telemetry"}
        data.update(extra_fields)
        return self.client.post(
            f"/vaform/{self.sid}/vafinalasses{ACTION}",
            data={**data, "va_save_assessment": "1"},
            headers={**self._csrf_headers(), "HX-Request": "true"},
        )

    def test_final_cod_save_forwards_the_choice_to_its_search(self):
        search_id = uuid.uuid4()
        self.assertEqual(self._search("ischaemic", search_id=search_id).status_code, 200)

        response = self._post_final(
            {
                "cod_search_id": str(search_id),
                "cod_chosen_code": "I24",
                "cod_chosen_rank": "0",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        db.session.expire_all()
        row = db.session.scalar(
            sa.select(CodSearchTelemetry).where(CodSearchTelemetry.search_id == search_id)
        )
        self.assertEqual(row.chosen_code, "I24")
        self.assertEqual(row.chosen_rank, 0)
        self.assertIsNotNone(row.chosen_at)
        self.assertEqual(row.role, "admin")

    def test_final_cod_save_without_search_fields_is_unlinked_but_unharmed(self):
        response = self._post_final({})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count(CodSearchTelemetry.id))), 0
        )

    def test_final_cod_save_with_an_unknown_search_id_still_saves(self):
        response = self._post_final(
            {
                "cod_search_id": str(uuid.uuid4()),
                "cod_chosen_code": "I24",
                "cod_chosen_rank": "0",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    # ── Admin CSV export ───────────────────────────────────────────────────

    def test_export_requires_admin(self):
        self._login(self.base_coder_id)
        response = self.client.get("/admin/api/coding-search-telemetry/export.csv")
        self.assertEqual(response.status_code, 403)

    def test_export_streams_rows_newest_first_with_neutralised_cells(self):
        base_time = datetime.now(UTC).replace(microsecond=0)
        newer = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface="icd10_coding",
            query_text="=cmd|' /c calc'!A0",
            result_count=2,
            created_at=base_time,
        )
        older = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface="icd11_coding",
            query_text="stroke",
            result_count=0,
            zero_results=True,
            created_at=base_time - timedelta(hours=2),
        )
        db.session.add_all([newer, older])
        db.session.commit()

        response = self.client.get("/admin/api/coding-search-telemetry/export.csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual(rows[0], list(coding_search_telemetry_service.CSV_HEADERS))
        self.assertEqual(len(rows), 3)
        # Newest first; the formula-shaped query text carries the leading
        # apostrophe that neutralises it.
        self.assertEqual(
            [row[2] for row in rows[1:]],
            ["'=cmd|' /c calc'!A0", "stroke"],
        )
        self.assertEqual(rows[1][1], "icd10_coding")
        self.assertEqual(rows[2][1], "icd11_coding")

    # ── Two-stage picker rendering (digitva-zpe.3, part 2) ─────────────────

    def test_coding_screens_render_the_grouping_logic_and_degradation(self):
        for partial in ("vafinalasses", "vainitialasses"):
            with self.subTest(partial=partial):
                body = self.client.get(f"/vaform/{self.sid}/{partial}{ACTION}").data
                self.assertIn(b"IcdCodingSearch", body)
                self.assertIn(b"Focused matches", body)
                self.assertIn(b"Expanded matches", body)
                self.assertIn(b"Show more results", body)
                self.assertIn(b"search_id", body)
                # Degradation: unknown/missing tier lands in the expanded
                # group, so a stale cached page still renders the flat list.
                self.assertIn(b"else expanded.push(option)", body)

    def test_final_screen_carries_the_choice_forwarding_inputs(self):
        body = self.client.get(f"/vaform/{self.sid}/vafinalasses{ACTION}").data
        self.assertIn(b'name="cod_search_id"', body)
        self.assertIn(b'name="cod_chosen_code"', body)
        self.assertIn(b'name="cod_chosen_rank"', body)
