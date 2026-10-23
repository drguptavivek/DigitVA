"""Memory-bounded ODK sync (digitva-lj7u): paged fetch + upsert, chunked
upsert lookups, set-based sync-issue marking, and a repair map that reads only
the payload keys it needs.

Behaviour is unchanged by all of it: the counts, ``upserted_map``,
``amended_sids``, audit rows and workflow routing are what they were; only the
number of queries and the amount held in memory change.
"""

import gc
import re
import uuid
import weakref
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import requests
import sqlalchemy as sa

from app import db
from app.models import (
    MasCategoryDisplayConfig,
    MasCategoryOrder,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasSubcategoryOrder,
    VaForms,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionUpstreamChange,
    VaSubmissionWorkflow,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.va_data_sync import va_data_sync_01_odkcentral as sync_module
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    SYNC_ISSUE_MISSING_IN_ODK,
    _finalize_enriched_submissions_for_form,
    _mark_form_sync_issues,
    _upsert_form_submissions,
    va_data_sync_odkcentral,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
)
from app.services.workflow.state_store import set_submission_workflow_state
from app.tasks.sync_tasks import _build_repair_map_for_form
from app.utils import va_preprocess_categoriestodisplay
from app.utils.va_odk import va_odk_06_fetchsubmissions as fetch_module
from tests.base import BaseTestCase
from tests.services.test_national_id_sync_rerun import create_form

UPDATED_AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
SYNC_MODULE = "app.services.va_data_sync.va_data_sync_01_odkcentral"


def _record(form_id: str, instance_id: str, **overrides) -> dict:
    """An ODK record as the fetch normalizes it."""
    return {
        "KEY": instance_id,
        "sid": f"{instance_id}-{form_id.lower()}",
        "form_def": form_id,
        "SubmissionDate": UPDATED_AT.isoformat(),
        "updatedAt": UPDATED_AT.isoformat(),
        "SubmitterName": "Collector",
        "ReviewState": None,
        "instanceName": instance_id,
        "unique_id": instance_id,
        "unique_id2": f"{instance_id}-masked",
        "Id10013": "yes",
        "language": "English",
        "finalAgeInYears": "52",
        "Id10019": "female",
        **overrides,
    }


class _StatementCounter:
    """Counts the SQL statements the session's connection runs."""

    def __init__(self):
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, *args):
        self.statements.append(statement)

    def __enter__(self):
        self._connection = db.session.connection()
        self._listener = self._record  # one object, so remove() finds it
        sa.event.listen(self._connection, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *exc):
        sa.event.remove(self._connection, "before_cursor_execute", self._listener)


class UpsertChunkingTests(BaseTestCase):
    PROJECT_ID = "LJ7U1"
    SITE_ID = "LJ01"
    FORM_ID = "LJ7U1LJ0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _form(self):
        return db.session.get(VaForms, self.FORM_ID)

    def _rec(self, instance_id, **overrides):
        return _record(self.FORM_ID, instance_id, **overrides)

    def _sid(self, instance_id):
        return f"{instance_id}-{self.FORM_ID.lower()}"

    def _upsert(self, records, amended=None, upserted=None, **kwargs):
        amended = set() if amended is None else amended
        upserted = {} if upserted is None else upserted
        counts = _upsert_form_submissions(
            self._form(), records, amended, upserted, enrich_payloads=False, **kwargs
        )
        db.session.flush()
        return counts, amended, upserted

    def _actions(self, instance_id):
        return sorted(
            db.session.scalars(
                sa.select(VaSubmissionsAuditlog.va_audit_action).where(
                    VaSubmissionsAuditlog.va_sid == self._sid(instance_id)
                )
            )
        )

    def _versions(self, instance_id):
        return db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.va_sid == self._sid(instance_id))
        )

    def _signature(self, instance_id):
        """Everything observable about a sid's end state, minus the sid itself."""
        sid = self._sid(instance_id)
        submission = db.session.get(VaSubmissions, sid)
        active = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion.payload_data).where(
                VaSubmissionPayloadVersion.va_sid == sid,
                VaSubmissionPayloadVersion.version_status == "active",
            )
        )
        return {
            "versions": self._versions(instance_id),
            "active_gender": active["Id10019"],
            "gender": submission.va_deceased_gender,
            "audit": self._actions(instance_id),
            "workflow": db.session.scalar(
                sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid == sid)
            ),
        }

    # -- query count -----------------------------------------------------------

    def test_unchanged_records_cost_queries_per_chunk_not_per_record(self):
        records = [self._rec(f"uuid:lj7u-count-{i:02d}") for i in range(30)]

        def lookups(counter):
            # The submission and payload-version lookups this change batches.
            # (The projection's form-type/category reads are counted in
            # ProjectionMasterDataTests.)
            return [
                s for s in counter.statements
                if "FROM va_submissions " in s or "FROM va_submission_payload_versions " in s
            ]

        with patch.object(sync_module, "_UPSERT_CHUNK_SIZE", 10):
            self._upsert(records)  # seed: 30 added

            with _StatementCounter() as ten:
                counts, amended, _ = self._upsert(records[:10])
            with _StatementCounter() as thirty:
                counts30, amended30, _ = self._upsert(records)

        self.assertEqual(counts, (0, 0, 0, 0))
        self.assertEqual(counts30, (0, 0, 0, 0))
        self.assertEqual((amended, amended30), (set(), set()))
        # One chunk: one VaSubmissions and one active-version query; three chunks: three of each.
        self.assertEqual(len(lookups(ten)), 2)
        self.assertEqual(len(lookups(thirty)), 6)

    # -- same results as per-record processing ---------------------------------

    def test_mixed_batch_results_across_chunks(self):
        ids = {name: f"uuid:lj7u-mix-{name}" for name in "ABCDE"}
        self._upsert([self._rec(ids[name]) for name in "ABCD"])
        # D is finalised: a changed payload must take the protected path.
        set_submission_workflow_state(self._sid(ids["D"]), WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        # C: same payload but ODK's updatedAt moved on -> metadata refresh only.
        db.session.get(VaSubmissions, self._sid(ids["C"])).va_odk_updatedat = (
            UPDATED_AT - timedelta(days=3)
        ).replace(tzinfo=None)
        db.session.flush()

        incoming = [
            self._rec(ids["A"]),
            self._rec(ids["B"], Id10019="male"),
            self._rec(ids["C"]),
            self._rec(ids["D"], Id10019="male"),
            self._rec(ids["E"]),
        ]
        with patch.object(sync_module, "_UPSERT_CHUNK_SIZE", 2):
            counts, amended, upserted = self._upsert(incoming)

        self.assertEqual(counts, (1, 3, 0, 0))
        changed = {ids[name] for name in "BCDE"}
        self.assertEqual(amended, {self._sid(i) for i in changed})
        self.assertEqual(upserted, {self._sid(i): i for i in changed})
        created = "va_submission_creation_during_datasync"
        self.assertEqual(self._actions(ids["A"]), [created])
        self.assertEqual(
            self._actions(ids["B"]), sorted([created, "va_submission_updation_during_datasync"])
        )
        self.assertEqual(
            self._actions(ids["C"]), sorted([created, "va_submission_metadata_refresh_during_datasync"])
        )
        self.assertEqual(
            self._actions(ids["D"]),
            sorted([created, "upstream_odk_data_changed_on_protected_submission"]),
        )
        self.assertEqual(self._actions(ids["E"]), [created])
        self.assertEqual(
            [self._versions(ids[name]) for name in "ABCDE"], [1, 2, 1, 2, 1]  # D: active + pending upstream
        )
        self.assertEqual(
            db.session.get(VaSubmissions, self._sid(ids["C"])).va_odk_updatedat,
            UPDATED_AT.replace(tzinfo=None),
        )
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count()).select_from(VaSubmissionUpstreamChange).where(
                    VaSubmissionUpstreamChange.va_sid == self._sid(ids["D"])
                )
            ),
            1,
        )
        self.assertEqual(
            db.session.scalar(
                sa.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == self._sid(ids["D"])
                )
            ),
            WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
        )

    # -- a sid twice in one call -----------------------------------------------

    def test_a_new_sid_twice_in_one_call_ends_as_two_sequential_calls(self):
        together, sequential = "uuid:lj7u-dup-new-together", "uuid:lj7u-dup-new-seq"
        self._upsert([self._rec(together), self._rec(together, Id10019="male")])
        self._upsert([self._rec(sequential)])
        self._upsert([self._rec(sequential, Id10019="male")])

        self.assertEqual(self._signature(together), self._signature(sequential))
        self.assertEqual(self._signature(together)["versions"], 2)
        self.assertEqual(self._signature(together)["active_gender"], "male")

    def test_an_existing_sid_twice_in_one_call_ends_as_two_sequential_calls(self):
        together, sequential = "uuid:lj7u-dup-old-together", "uuid:lj7u-dup-old-seq"
        self._upsert([self._rec(together), self._rec(sequential)])

        self._upsert([self._rec(together, Id10019="male"), self._rec(together, Id10019="other")])
        self._upsert([self._rec(sequential, Id10019="male")])
        self._upsert([self._rec(sequential, Id10019="other")])

        self.assertEqual(self._signature(together), self._signature(sequential))
        self.assertEqual(self._signature(together)["versions"], 3)
        self.assertEqual(self._signature(together)["active_gender"], "other")


class ProjectionMasterDataTests(BaseTestCase):
    """digitva-tn21: the projection's form-type and category config are read
    once per upsert/finalize call, not once per record."""

    PROJECT_ID = "TN21A"
    SITE_ID = "TN01"
    FORM_ID = "TN21ATN0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)
        # A form type with one always-included category and one that depends on
        # the record's data, so the category query runs and the list is non-trivial.
        form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="TN21_FT",
            form_type_name="TN21 form type",
            is_active=True,
        )
        db.session.add(form_type)
        db.session.flush()
        ft_id = form_type.form_type_id
        for order, (code, always) in enumerate((("tn21cataa", False), ("tn21catbb", True)), 1):
            db.session.add(MasCategoryOrder(
                form_type_id=ft_id, category_code=code, category_name=code,
                display_order=order, is_active=True,
            ))
            db.session.add(MasCategoryDisplayConfig(
                form_type_id=ft_id, category_code=code, display_label=code, nav_label=code,
                display_order=order, render_mode="table_sections",
                show_to_coder=True, show_to_reviewer=True, show_to_site_pi_datamanager=True,
                always_include=always, is_active=True,
            ))
        db.session.add(MasSubcategoryOrder(
            form_type_id=ft_id, category_code="tn21cataa", subcategory_code="general",
            subcategory_name="General", display_order=1, is_active=True,
        ))
        db.session.add(MasFieldDisplayConfig(
            form_type_id=ft_id, field_id="tn21_field", category_code="tn21cataa",
            subcategory_code="general", short_label="TN21 field", display_order=1, is_active=True,
        ))
        db.session.get(VaForms, cls.FORM_ID).form_type_id = ft_id
        db.session.commit()

    def _form(self):
        return db.session.get(VaForms, self.FORM_ID)

    def _records(self, prefix, count=30):
        return [_record(self.FORM_ID, f"uuid:tn21-{prefix}-{i:02d}", tn21_field="present") for i in range(count)]

    def _upsert(self, records):
        counts = _upsert_form_submissions(
            self._form(), records, set(), {}, enrich_payloads=False
        )
        db.session.flush()
        return counts

    @staticmethod
    def _master_reads(counter):
        form_types = [s for s in counter.statements if "FROM mas_form_types" in s]
        categories = [s for s in counter.statements if "FROM mas_category_display_config" in s]
        return len(form_types), len(categories)

    def test_steady_state_master_data_reads_do_not_grow_with_the_batch(self):
        records = self._records("upsert")
        with patch.object(sync_module, "_UPSERT_CHUNK_SIZE", 10):
            self._upsert(records)  # seed: 30 added
            # The first rerun also pays the payload-PII side-table probe, which
            # is cached for the process; warm it so both counted calls are alike.
            self._upsert(records[:10])

            with _StatementCounter() as ten:
                counts10 = self._upsert(records[:10])
            with _StatementCounter() as thirty:
                counts30 = self._upsert(records)

        self.assertEqual((counts10, counts30), ((0, 0, 0, 0), (0, 0, 0, 0)))
        # Assert the reads happen before asserting they are bounded.
        form_types10, categories10 = self._master_reads(ten)
        form_types30, categories30 = self._master_reads(thirty)
        self.assertEqual(categories10, 1)
        self.assertGreaterEqual(form_types10, 1)
        self.assertLessEqual(form_types10, 2)
        self.assertEqual((form_types30, categories30), (form_types10, categories10))
        # Beyond one call's master-data reads, 2 more chunks cost only their
        # batched VaSubmissions + active-version lookups (2 each).
        self.assertEqual(len(thirty.statements) - len(ten.statements), 4)

    def test_stored_category_list_is_what_the_per_record_call_produces(self):
        records = self._records("cats", count=3)
        self._upsert(records)

        for record in records:
            stored = db.session.get(VaSubmissions, record["sid"]).va_category_list
            self.assertEqual(
                stored, va_preprocess_categoriestodisplay(record, self.FORM_ID)
            )
        self.assertEqual(stored, ["tn21cataa", "tn21catbb"])  # not trivially empty

    def test_finalize_reads_master_data_once_per_call(self):
        records = self._records("final")
        self._upsert(records)
        db.session.commit()

        def finalize(subset):
            with patch.object(
                sync_module,
                "_enrich_submission_payload_for_storage",
                side_effect=lambda va_form, record, client=None: record,
            ), _StatementCounter() as counter:
                finalized = _finalize_enriched_submissions_for_form(
                    self._form(),
                    subset,
                    {r["sid"]: r["KEY"] for r in subset},
                    set(),
                    client=None,
                )
            return finalized, self._master_reads(counter)

        finalized10, reads10 = finalize(records[:10])
        finalized30, reads30 = finalize(records)

        self.assertEqual((finalized10, finalized30), (10, 30))
        self.assertEqual(reads10[1], 1)
        self.assertLessEqual(reads10[0], 2)
        self.assertEqual(reads30, reads10)


class MarkFormSyncIssuesTests(BaseTestCase):
    PROJECT_ID = "LJ7U2"
    SITE_ID = "LJ02"
    FORM_ID = "LJ7U2LJ0201"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _submission(self, instance_id, code=None, detail=None, issue_at=None):
        submission = VaSubmissions(
            va_sid=f"{instance_id}-{self.FORM_ID.lower()}", va_form_id=self.FORM_ID,
            va_submission_date=UPDATED_AT, va_odk_updatedat=UPDATED_AT.replace(tzinfo=None),
            va_data_collector="Collector", va_odk_reviewstate=None, va_consent="yes",
            va_narration_language="English", va_deceased_age=52, va_deceased_gender="female",
            va_uniqueid_masked="masked", va_summary=[], va_catcount={}, va_category_list=[],
            va_sync_issue_code=code, va_sync_issue_detail=detail, va_sync_issue_updated_at=issue_at,
        )
        db.session.add(submission)
        return submission

    def _audit(self, submission):
        return [
            (row.va_audit_byrole, row.va_audit_operation, row.va_audit_action)
            for row in db.session.scalars(
                sa.select(VaSubmissionsAuditlog).where(VaSubmissionsAuditlog.va_sid == submission.va_sid)
            )
        ]

    def test_flags_restores_and_leaves_the_rest_alone(self):
        old = datetime(2023, 5, 5, 5, 5, tzinfo=UTC)
        clean_present = self._submission("uuid:lj7u-mark-ok")
        flagged_present = self._submission(
            "uuid:lj7u-mark-back", SYNC_ISSUE_MISSING_IN_ODK, "old detail", old
        )
        clean_absent = self._submission("uuid:lj7u-mark-gone")
        flagged_absent = self._submission(
            "uuid:lj7u-mark-stillgone", SYNC_ISSUE_MISSING_IN_ODK, "old detail", old
        )
        other_issue_present = self._submission("uuid:lj7u-mark-other", "something_else", "kept", old)
        db.session.flush()  # all five are loaded in the session

        before = datetime.now(UTC)
        _mark_form_sync_issues(
            self._form(), ["uuid:lj7u-mark-ok", "uuid:lj7u-mark-back", "uuid:lj7u-mark-other"]
        )
        db.session.flush()

        # Objects already in the session see the new values.
        self.assertIsNone(flagged_present.va_sync_issue_code)
        self.assertIsNone(flagged_present.va_sync_issue_detail)
        self.assertGreaterEqual(flagged_present.va_sync_issue_updated_at, before)
        self.assertEqual(clean_absent.va_sync_issue_code, SYNC_ISSUE_MISSING_IN_ODK)
        self.assertEqual(
            clean_absent.va_sync_issue_detail,
            "Submission exists locally but is missing from active ODK submissions.",
        )
        self.assertGreaterEqual(clean_absent.va_sync_issue_updated_at, before)

        # Untouched: clean and present, already flagged and still absent, other code and present.
        self.assertIsNone(clean_present.va_sync_issue_code)
        self.assertIsNone(clean_present.va_sync_issue_updated_at)
        self.assertEqual(flagged_absent.va_sync_issue_detail, "old detail")
        self.assertEqual(flagged_absent.va_sync_issue_updated_at, old)
        self.assertEqual(other_issue_present.va_sync_issue_code, "something_else")
        self.assertEqual(other_issue_present.va_sync_issue_updated_at, old)

        # The rows in the database agree with the session objects.
        stored = dict(
            db.session.execute(
                sa.select(VaSubmissions.va_sid, VaSubmissions.va_sync_issue_code).where(
                    VaSubmissions.va_form_id == self.FORM_ID
                )
            ).all()
        )
        self.assertEqual(stored[flagged_present.va_sid], None)
        self.assertEqual(stored[clean_absent.va_sid], SYNC_ISSUE_MISSING_IN_ODK)

        self.assertEqual(
            self._audit(flagged_present),
            [("vaadmin", "u", "submission restored from ODK sync issue")],
        )
        self.assertEqual(
            self._audit(clean_absent),
            [("vaadmin", "u", "submission missing from ODK detected during sync")],
        )
        for untouched in (clean_present, flagged_absent, other_issue_present):
            self.assertEqual(self._audit(untouched), [])

    def test_flagging_runs_in_in_chunks(self):
        submissions = [self._submission(f"uuid:lj7u-chunk-{i}") for i in range(5)]
        db.session.flush()

        with patch.object(sync_module, "_SYNC_IN_CHUNK", 2):
            with _StatementCounter() as counter:
                _mark_form_sync_issues(self._form(), [], by_role="vasystem")
            db.session.flush()

        self.assertTrue(
            all(s.va_sync_issue_code == SYNC_ISSUE_MISSING_IN_ODK for s in submissions)
        )
        updates = [s for s in counter.statements if s.lstrip().upper().startswith("UPDATE")]
        self.assertEqual(len(updates), 3)  # 5 sids, 2 per statement
        self.assertEqual(
            self._audit(submissions[0]),
            [("vasystem", "u", "submission missing from ODK detected during sync")],
        )

    def _form(self):
        return db.session.get(VaForms, self.FORM_ID)


class BuildRepairMapPayloadKeysTests(BaseTestCase):
    PROJECT_ID = "LJ7U3"
    SITE_ID = "LJ03"
    FORM_ID = "LJ7U3LJ0301"

    COMPLETE = {
        "FormVersion": "v1",
        "DeviceID": "dev",
        "SubmitterID": 7,
        "instanceID": "uuid:x",
        "AttachmentsPresent": 0,
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _sid(self, name):
        return f"uuid:lj7u-repair-{name}-{self.FORM_ID.lower()}"

    def _add(self, name, payload):
        submission = VaSubmissions(
            va_sid=self._sid(name), va_form_id=self.FORM_ID,
            va_submission_date=UPDATED_AT, va_odk_updatedat=UPDATED_AT.replace(tzinfo=None),
            va_data_collector="Collector", va_odk_reviewstate=None, va_consent="yes",
            va_narration_language="English", va_deceased_age=52, va_deceased_gender="female",
            va_uniqueid_masked="masked", va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission, payload_data=payload, source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.flush()

    def test_attachments_expected_and_missing_keys_decide_like_the_full_payload(self):
        with_key = {"KEY": "uuid:from-payload", **self.COMPLETE}
        cases = {
            # name: (payload, needs_metadata, needs_attachments)
            "int": ({**with_key, "AttachmentsExpected": 3}, False, True),
            "float": ({**with_key, "AttachmentsExpected": 2.0}, False, True),
            "numstr": ({**with_key, "AttachmentsExpected": "2"}, False, True),
            "empty": ({**with_key, "AttachmentsExpected": ""}, False, False),
            "zero": ({**with_key, "AttachmentsExpected": 0}, False, False),
            "junk": ({**with_key, "AttachmentsExpected": "abc"}, False, False),
            "null": ({**with_key, "AttachmentsExpected": None}, True, False),
            "absent": ({"Id10019": "female"}, True, False),  # no KEY: instance id from the sid
        }
        for name, (payload, _, _) in cases.items():
            self._add(name, payload)

        with _StatementCounter() as counter:
            repair_map, summary = _build_repair_map_for_form(self.FORM_ID, {}, {})

        for name, (_, needs_metadata, needs_attachments) in cases.items():
            with self.subTest(name):
                entry = repair_map[self._sid(name)]
                self.assertEqual(entry["needs_metadata"], needs_metadata)
                self.assertEqual(entry["needs_attachments"], needs_attachments)
                self.assertTrue(entry["needs_smartva"])  # no SmartVA result for any of them
                expected_instance = (
                    "uuid:lj7u-repair-absent" if name == "absent" else "uuid:from-payload"
                )
                self.assertEqual(entry["instance_id"], expected_instance)
        self.assertEqual(
            summary,
            {
                "metadata_missing": 2,
                "attachments_missing": 3,
                "smartva_missing": len(cases),
                "legacy_attachment_rows": 0,
            },
        )

        # The payload column itself is no longer selected, only keys of it.
        selects = [s for s in counter.statements if "va_submission_payload_versions" in s]
        self.assertTrue(selects)
        for statement in selects:
            self.assertNotRegex(statement, r"\.payload_data(?!\s*->)")
            self.assertGreaterEqual(len(re.findall(r"payload_data\s*->", statement)), 7)


class PagedFetchTests(TestCase):
    class _Session:
        def __init__(self, pages):
            self.pages = list(pages)
            self.params = []

        def get(self, url, params=None, timeout=None):
            self.params.append(dict(params))
            value = self.pages.pop(0) if self.pages else []
            return SimpleNamespace(status_code=200, json=lambda: {"value": value}, text="")

    @staticmethod
    def _odata(instance_id):
        return {
            "__id": instance_id,
            "__system": {
                "submissionDate": "2026-03-14T00:00:00.000Z",
                "updatedAt": "2026-03-14T00:00:00.000Z",
                "submitterName": "tester",
                "reviewState": None,
            },
            "meta": {"instanceName": instance_id},
        }

    def _form(self):
        return SimpleNamespace(
            project_id="PROJ01", odk_project_id="11", odk_form_id="FORM_A", form_id="FORM01"
        )

    def _client(self, pages):
        return SimpleNamespace(session=self._Session(pages))

    def test_fetch_all_pages_until_a_short_page_with_unchanged_results(self):
        odata = [self._odata(f"uuid:{i}") for i in range(5)]
        client = self._client([odata[0:2], odata[2:4], odata[4:5]])

        with patch.object(fetch_module, "_PAGE_SIZE", 2):
            rows = fetch_module.va_odk_fetch_submissions(self._form(), client=client)

        self.assertEqual([r["KEY"] for r in rows], [f"uuid:{i}" for i in range(5)])
        self.assertEqual(rows[0]["sid"], "uuid:0-form01")
        self.assertEqual([p["$skip"] for p in client.session.params], [0, 2, 4])
        self.assertEqual({p["$top"] for p in client.session.params}, {2})
        self.assertTrue(all("$filter" not in p for p in client.session.params))

    def test_a_full_last_page_costs_one_more_empty_request(self):
        odata = [self._odata(f"uuid:{i}") for i in range(4)]
        client = self._client([odata[0:2], odata[2:4], []])

        with patch.object(fetch_module, "_PAGE_SIZE", 2):
            rows = fetch_module.va_odk_fetch_submissions(self._form(), client=client)

        self.assertEqual(len(rows), 4)
        self.assertEqual([p["$skip"] for p in client.session.params], [0, 2, 4])

    def test_page_function_fetches_one_page_at_the_given_offset(self):
        client = self._client([[self._odata("uuid:a"), self._odata("uuid:b")]])
        since = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

        with patch.object(fetch_module, "_PAGE_SIZE", 2):
            page = fetch_module.va_odk_fetch_submissions_page(
                self._form(), since=since, skip=6, client=client
            )

        self.assertEqual([r["KEY"] for r in page], ["uuid:a", "uuid:b"])
        (params,) = client.session.params
        self.assertEqual((params["$skip"], params["$top"]), (6, 2))
        self.assertIn("2026-01-02T03:04:05.000Z", params["$filter"])

    def test_page_function_raises_on_http_error_and_naive_since(self):
        failing = SimpleNamespace(
            session=SimpleNamespace(
                get=lambda *a, **k: SimpleNamespace(status_code=500, text="boom", json=lambda: {})
            )
        )
        with self.assertRaisesRegex(Exception, "HTTP 500"):
            fetch_module.va_odk_fetch_submissions_page(self._form(), since=None, skip=0, client=failing)
        with self.assertRaises(ValueError):
            fetch_module.va_odk_fetch_submissions_page(
                self._form(), since=datetime(2026, 1, 1), skip=0, client=failing
            )


class _Record(dict):
    """A record that can be weakly referenced, to see whether a fetched page is retained.

    The records are tracked, not the page list: the page list is rebound each
    loop turn, so it would die even if its records were kept in another list.
    """


class MainSyncPagingTests(BaseTestCase):
    PROJECT_ID = "LJ7U4"
    SITE_ID = "LJ04"
    FORM_ID = "LJ7U4LJ0401"
    TOTAL = 8
    PAGE = 3

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _run(
        self,
        *,
        with_enrichment_dispatcher,
        fail_page_two_once=False,
        on_dispatch=None,
        page_two_error=None,
        real_upsert=False,
        page_counts=None,
    ):
        events: list = []
        pages: list = []  # per fetched page: weakrefs to its records
        progress: list = []
        seen_before_failure: list = []
        failed = []
        form = db.session.get(VaForms, self.FORM_ID)
        mapping = SimpleNamespace(last_synced_at=None, odk_project_id=98)
        client_factory = Mock(return_value=object())
        finalize_seen: list = []
        real_commit = db.session.commit

        def fake_fetch(va_form, *, since, skip, client):
            events.append(("fetch", skip))
            if fail_page_two_once and skip == self.PAGE and not failed:
                failed.append(True)
                raise requests.exceptions.ConnectionError("Central unreachable")
            if page_two_error is not None and skip == self.PAGE:
                # What page 1 left in the session at the moment page 2 fails.
                seen_before_failure.append(self._form_rows())
                raise page_two_error
            page = [
                _Record(_record(self.FORM_ID, f"uuid:lj7u-sync-{i:02d}"))
                for i in range(skip, min(skip + self.PAGE, self.TOTAL))
            ]
            pages.append([weakref.ref(record) for record in page])
            return page

        def fake_upsert(va_form, records, amended_sids, upserted_map=None, **kwargs):
            events.append(("upsert", len(records)))
            self.assertIs(kwargs.get("enrich_payloads"), False)
            self.assertIs(kwargs.get("defer_protected_updates"), True)
            for record in records:
                amended_sids.add(record["sid"])
                upserted_map[record["sid"]] = record["KEY"]
            return page_counts(len(records)) if page_counts else (len(records), 0, 0, 0)

        def dispatch(va_form, upserted_map, progress):
            events.append(("dispatch", len(upserted_map)))
            if on_dispatch:
                on_dispatch(pages)

        def finalize(va_form, raw, upserted_map, amended_sids, **kwargs):
            events.append(("finalize", len(raw)))
            finalize_seen.append(raw)
            return len(upserted_map)

        def counting_commit():
            events.append(("commit",))
            return real_commit()

        with ExitStack() as stack:
            for name, kwargs in (
                ("sync_runtime_forms_from_site_mappings", {"return_value": [form]}),
                ("_resolve_project_connections", {"return_value": {}}),
                ("get_active_mapping_for_form", {"return_value": mapping}),
                ("_get_or_create_sync_odk_client", {"new": client_factory}),
                ("_warn_on_missing_org_fields", {}),
                ("va_odk_fetch_instance_ids", {"return_value": []}),
                ("_mark_form_sync_issues", {}),
                ("va_odk_fetch_submissions_page", {"new": fake_fetch}),
                *(() if real_upsert else (("_upsert_form_submissions", {"new": fake_upsert}),)),
                ("_attach_all_odk_comments", {"new": lambda _f, subs, **_k: subs}),
                ("_finalize_enriched_submissions_for_form", {"new": finalize}),
                ("_ODK_FETCH_PAGE_SIZE", {"new": self.PAGE}),
            ):
                stack.enter_context(patch(f"{SYNC_MODULE}.{name}", **kwargs))
            stack.enter_context(patch.object(sync_module.time, "sleep"))
            stack.enter_context(patch.object(db.session, "commit", side_effect=counting_commit))
            # A failed form ends in rollback() then remove(); remove() would also
            # drop the test harness's connection binding, so only record it.
            session_remove = stack.enter_context(patch.object(db.session, "remove"))
            result = va_data_sync_odkcentral(
                log_progress=progress.append,
                attachment_sync_dispatcher=lambda *a: None,
                enrichment_sync_dispatcher=dispatch if with_enrichment_dispatcher else None,
            )
        return SimpleNamespace(
            result=result, events=events, pages=pages, client_factory=client_factory,
            mapping=mapping, finalize_seen=finalize_seen, progress=progress,
            seen_before_failure=seen_before_failure, session_remove=session_remove,
        )

    def _form_rows(self) -> int:
        return db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissions).where(
                VaSubmissions.va_form_id == self.FORM_ID
            )
        )

    def test_each_page_is_upserted_before_the_next_is_fetched_and_the_form_commits_once(self):
        run = self._run(with_enrichment_dispatcher=True)

        self.assertEqual(
            run.events[:8],
            [
                ("fetch", 0), ("upsert", 3),
                ("fetch", 3), ("upsert", 3),
                ("fetch", 6), ("upsert", 2),
                ("commit",), ("dispatch", self.TOTAL),
            ],
        )
        # The form's commit, then the last_synced_at commit; none between pages.
        self.assertEqual([e for e in run.events if e == ("commit",)], [("commit",)] * 2)
        self.assertEqual(run.result["added"], self.TOTAL)
        self.assertEqual(run.result["failed_forms"], [])
        self.assertEqual(run.result["enrichment_sync_forms_enqueued"], 1)
        self.assertIsNotNone(run.mapping.last_synced_at)

    def test_a_connectivity_failure_on_page_two_retries_page_two_only(self):
        run = self._run(with_enrichment_dispatcher=True, fail_page_two_once=True)

        self.assertEqual(
            run.events[:9],
            [
                ("fetch", 0), ("upsert", 3),
                ("fetch", 3), ("fetch", 3), ("upsert", 3),
                ("fetch", 6), ("upsert", 2),
                ("commit",), ("dispatch", self.TOTAL),
            ],
        )
        self.assertEqual(run.result["added"], self.TOTAL)
        # Page fetches ask for a fresh client only on the retry attempt.
        refresh_flags = [
            call.kwargs["force_refresh"]
            for call in run.client_factory.call_args_list
            if "force_refresh" in call.kwargs
        ]
        self.assertEqual(refresh_flags, [False, False, True, False])

    def test_with_a_dispatcher_no_fetched_page_is_kept(self):
        alive_at_dispatch = []

        def on_dispatch(pages):
            gc.collect()
            alive_at_dispatch.extend(
                [ref() is not None for ref in page_refs] for page_refs in pages
            )

        run = self._run(with_enrichment_dispatcher=True, on_dispatch=on_dispatch)

        self.assertEqual([len(refs) for refs in run.pages], [3, 3, 2])
        # The loop variable still holds the last page; no record of the earlier ones is kept.
        self.assertEqual(alive_at_dispatch[:2], [[False] * 3, [False] * 3])

    def test_all_four_counts_are_summed_across_pages(self):
        run = self._run(
            with_enrichment_dispatcher=True,
            page_counts=lambda n: (n, 1, 2, 3),  # added, updated, discarded, skipped per page
        )

        self.assertEqual(run.result["added"], self.TOTAL)
        self.assertEqual(run.result["updated"], 3)
        self.assertEqual(run.result["discarded"], 6)
        # Skipped is only reported in the per-form progress line.
        self.assertIn(
            f"[{self.FORM_ID}] upsert: complete — +{self.TOTAL} added, 3 updated, 9 skipped",
            run.progress,
        )

    def test_a_failing_later_page_rolls_back_the_whole_form(self):
        self.assertEqual(self._form_rows(), 0)

        run = self._run(
            with_enrichment_dispatcher=True,
            real_upsert=True,
            page_two_error=ValueError("malformed OData page"),
        )

        # Page 1 really was written before page 2 failed...
        self.assertEqual(run.seen_before_failure, [self.PAGE])
        # ...and none of it survives: no commit, form failed, nothing counted.
        run.session_remove.assert_called()  # the failed-form handler ran
        self.assertNotIn(("commit",), run.events)
        self.assertEqual(self._form_rows(), 0)
        self.assertEqual(run.result["failed_forms"], [self.FORM_ID])
        self.assertEqual(
            (run.result["added"], run.result["updated"], run.result["discarded"]), (0, 0, 0)
        )
        self.assertIsNone(run.mapping.last_synced_at)
        self.assertFalse([e for e in run.events if e[0] == "dispatch"])

    def test_without_a_dispatcher_the_full_list_reaches_the_in_process_enrichment(self):
        run = self._run(with_enrichment_dispatcher=False)

        self.assertEqual(run.finalize_seen[0].__class__, list)
        self.assertEqual(
            [r["KEY"] for r in run.finalize_seen[0]],
            [f"uuid:lj7u-sync-{i:02d}" for i in range(self.TOTAL)],
        )
        self.assertEqual(run.result["added"], self.TOTAL)
        self.assertEqual(run.result["enrichment_sync_forms_enqueued"], 0)
