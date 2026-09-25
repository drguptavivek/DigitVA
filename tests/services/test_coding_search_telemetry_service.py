"""Coding-search telemetry service: normalisation, recording, prune, export.

digitva-zpe.3. Policy: docs/policy/coding-search-telemetry.md — the insert
must be cheap, must never raise into the search path, and must store no PII.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/services/test_coding_search_telemetry_service.py -q
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa

from app import db
from app.models import CodSearchTelemetry
from app.services import coding_search_telemetry_service as service
from tests.base import BaseTestCase


def _row_count() -> int:
    return db.session.scalar(sa.select(sa.func.count(CodSearchTelemetry.id)))


def _only_row() -> CodSearchTelemetry:
    return db.session.scalar(sa.select(CodSearchTelemetry).limit(1))


class NormalizeQueryTextTest(BaseTestCase):
    def test_collapses_whitespace_and_keeps_case(self):
        self.assertEqual(
            service.normalize_query_text("  MI   acute\tinfarct \n "),
            "MI acute infarct",
        )

    def test_hard_truncates_at_128_characters(self):
        self.assertEqual(len(service.normalize_query_text("x" * 500)), 128)
        self.assertEqual(service.normalize_query_text("a" * 128 + "bbb"), "a" * 128)
        self.assertEqual(len(service.normalize_query_text("a" * 128)), 128)

    def test_none_becomes_empty_string(self):
        self.assertEqual(service.normalize_query_text(None), "")


class ResolveSearchIdTest(BaseTestCase):
    def test_parses_a_valid_client_uuid(self):
        given = uuid.uuid4()
        self.assertEqual(service.resolve_search_id(str(given)), given)

    def test_invalid_or_absent_values_become_a_fresh_uuid(self):
        for bad in (None, "", "not-a-uuid", "123", object()):
            resolved = service.resolve_search_id(bad)
            self.assertIsInstance(resolved, uuid.UUID)

    def test_fresh_uuids_differ(self):
        self.assertNotEqual(service.resolve_search_id(None), service.resolve_search_id(None))


class RoleLabelTest(BaseTestCase):
    def test_names_the_first_matching_role(self):
        user = SimpleNamespace(
            is_coder=lambda: False,
            is_coding_tester=lambda: True,
            is_reviewer=lambda: True,
            is_admin=lambda: False,
        )
        self.assertEqual(service.role_label(user), "coding_tester")

    def test_unknown_user_shape_yields_none(self):
        self.assertIsNone(service.role_label(SimpleNamespace()))
        self.assertIsNone(service.role_label(None))


class RecordQueryTest(BaseTestCase):
    def test_records_the_search_fields(self):
        search_id = uuid.uuid4()
        service.record_query(
            search_id=search_id,
            surface=service.SURFACE_ICD10,
            query_text="  MI   acute ",
            result_count=3,
            zero_results=False,
            vocabulary_hit=True,
            latency_ms=42,
            role="coder",
        )

        row = _only_row()
        self.assertIsNotNone(row)
        self.assertEqual(row.search_id, search_id)
        self.assertEqual(row.surface, "icd10_coding")
        self.assertEqual(row.query_text, "MI acute")
        self.assertEqual(row.result_count, 3)
        self.assertFalse(row.zero_results)
        self.assertTrue(row.vocabulary_hit)
        self.assertEqual(row.latency_ms, 42)
        self.assertEqual(row.role, "coder")
        self.assertIsNone(row.chosen_code)
        self.assertIsNone(row.chosen_at)
        self.assertIsNotNone(row.created_at)

    def test_refuses_an_unknown_surface_without_raising(self):
        service.record_query(
            search_id=uuid.uuid4(), surface="icd9_coding", query_text="x"
        )
        self.assertEqual(_row_count(), 0)

    def test_an_insert_failure_is_swallowed(self):
        class ExplodingModel:
            def __init__(self, **kwargs):
                raise RuntimeError("database on fire")

        original = service.CodSearchTelemetry
        service.CodSearchTelemetry = ExplodingModel
        try:
            service.record_query(
                search_id=uuid.uuid4(),
                surface=service.SURFACE_ICD11,
                query_text="cva",
            )
        finally:
            service.CodSearchTelemetry = original
        self.assertEqual(_row_count(), 0)


class RecordChoiceTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.search_id = uuid.uuid4()
        service.record_query(
            search_id=self.search_id,
            surface=service.SURFACE_ICD10,
            query_text="mi",
            result_count=2,
        )
        # record_query commits; make the row visible to the assertions.
        db.session.expire_all()

    def test_attaches_code_rank_and_timestamp(self):
        before = datetime.now(UTC)
        service.record_choice(
            search_id=str(self.search_id), chosen_code="I21.9", chosen_rank="1"
        )
        db.session.expire_all()

        row = _only_row()
        self.assertEqual(row.chosen_code, "I21.9")
        self.assertEqual(row.chosen_rank, 1)
        self.assertIsNotNone(row.chosen_at)
        self.assertGreaterEqual(row.chosen_at, before - timedelta(seconds=1))

    def test_a_malformed_rank_is_dropped_but_the_code_is_kept(self):
        service.record_choice(
            search_id=str(self.search_id), chosen_code="I21.9", chosen_rank="top"
        )
        db.session.expire_all()
        row = _only_row()
        self.assertEqual(row.chosen_code, "I21.9")
        self.assertIsNone(row.chosen_rank)

    def test_unknown_search_id_is_a_silent_no_op(self):
        service.record_choice(
            search_id=str(uuid.uuid4()), chosen_code="I21.9", chosen_rank=0
        )
        db.session.expire_all()
        row = _only_row()
        self.assertIsNone(row.chosen_code)

    def test_an_empty_code_changes_nothing(self):
        service.record_choice(search_id=str(self.search_id), chosen_code="  ")
        db.session.expire_all()
        row = _only_row()
        self.assertIsNone(row.chosen_code)

    def test_truncates_an_oversized_code_to_the_column_limit(self):
        service.record_choice(
            search_id=str(self.search_id), chosen_code="X" * 40, chosen_rank=0
        )
        db.session.expire_all()
        self.assertEqual(len(_only_row().chosen_code), 16)


class PruneExpiredTest(BaseTestCase):
    def test_deletes_only_rows_past_retention(self):
        fresh = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface=service.SURFACE_ICD10,
            query_text="fresh",
            created_at=datetime.now(UTC),
        )
        stale = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface=service.SURFACE_ICD11,
            query_text="stale",
            created_at=datetime.now(UTC) - timedelta(days=91),
        )
        db.session.add_all([fresh, stale])
        db.session.commit()

        pruned = service.prune_expired()
        db.session.expire_all()

        self.assertEqual(pruned, 1)
        remaining = db.session.scalars(sa.select(CodSearchTelemetry)).all()
        self.assertEqual([row.query_text for row in remaining], ["fresh"])

    def test_default_window_is_90_days(self):
        self.assertEqual(service.DEFAULT_RETENTION_DAYS, 90)
        boundary = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface=service.SURFACE_ICD10,
            query_text="boundary",
            created_at=datetime.now(UTC) - timedelta(days=service.DEFAULT_RETENTION_DAYS, minutes=5),
        )
        db.session.add(boundary)
        db.session.commit()
        self.assertEqual(service.prune_expired(), 1)


class ExportCsvRowsTest(BaseTestCase):
    def test_rows_are_newest_first_with_plain_values(self):
        old = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface=service.SURFACE_ICD10,
            query_text="old",
            result_count=1,
            zero_results=False,
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        new = CodSearchTelemetry(
            search_id=uuid.uuid4(),
            surface=service.SURFACE_ICD11,
            query_text="new",
            result_count=0,
            zero_results=True,
            chosen_code="BA41",
            chosen_rank=0,
            chosen_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.session.add_all([old, new])
        db.session.commit()

        rows = service.export_csv_rows()
        self.assertEqual([row["query_text"] for row in rows], ["new", "old"])
        newest = rows[0]
        self.assertEqual(newest["surface"], "icd11_coding")
        self.assertEqual(newest["zero_results"], "true")
        self.assertEqual(newest["chosen_code"], "BA41")
        self.assertEqual(newest["search_id"], str(new.search_id))
        self.assertTrue(newest["created_at"])

    def test_csv_lines_are_formula_neutralised(self):
        db.session.add(
            CodSearchTelemetry(
                search_id=uuid.uuid4(),
                surface=service.SURFACE_ICD10,
                query_text="=HYPERLINK(\"http://evil\")",
            )
        )
        db.session.commit()

        lines = list(service.iter_csv_lines())
        self.assertEqual(lines[0].strip().split(",")[0], "search_id")
        self.assertIn("'=HYPERLINK", lines[1])
