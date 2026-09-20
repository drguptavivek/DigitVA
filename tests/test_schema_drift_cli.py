"""Tests for `flask schema drift-check` (digitva-88e).

The full command builds a throwaway migration-chain database and diffs it
against a live target -- too heavy to exercise on every test run. What is
tested here is the part that decides whether the command is trustworthy:
that ``_normalize_sql`` treats Postgres's alternate spellings of the same
CHECK/DEFAULT as equal (so a healthy database stays silent) while a real
content difference still shows up (so drift is not normalized away too),
and that ``_check_constraints`` + ``_diff_mapping`` together detect a
deliberately introduced difference and report nothing on a clean database.
"""

import sqlalchemy as sa

from app import db
from app.commands.schema_drift import _check_constraints, _diff_mapping, _normalize_sql
from tests.base import BaseTestCase


class NormalizeSqlTests(BaseTestCase):
    """Pure-function tests, no database needed."""

    def test_collapses_element_wise_vs_whole_array_cast_spellings(self):
        # digitva-88e's own example: the same CHECK rendered two ways
        # depending on whether Postgres cast each array element or the
        # whole array.
        element_wise = "ARRAY[('success'::varchar)::text, ('failure'::varchar)::text]"
        whole_array = "ARRAY['success'::varchar, 'failure'::varchar]::text[]"
        self.assertEqual(_normalize_sql(element_wise), _normalize_sql(whole_array))

    def test_collapses_redundant_doubled_parens(self):
        # Seen on the real dev database: a whole-array cast strip leaves an
        # extra ANY((...)) wrap that a single-cast version never had.
        doubled = "CHECK ((outcome= ANY ((ARRAY['success', 'partial', 'failed']))))"
        single = "CHECK ((outcome= ANY (ARRAY['success', 'partial', 'failed'])))"
        self.assertEqual(_normalize_sql(doubled), _normalize_sql(single))

    def test_preserves_a_real_content_difference(self):
        # Normalization must not paper over an actual missing role -- the
        # defect digitva-88e is about.
        with_role = (
            "CHECK ((role = ANY (ARRAY['collaborator', 'collaborator_pii', 'coder'])))"
        )
        without_role = "CHECK ((role = ANY (ARRAY['collaborator', 'coder'])))"
        self.assertNotEqual(_normalize_sql(with_role), _normalize_sql(without_role))

    def test_none_stays_none(self):
        self.assertIsNone(_normalize_sql(None))


class DriftDetectionTests(BaseTestCase):
    """`_check_constraints` + `_diff_mapping` against the real test database.

    Runs inside the test harness's per-test SAVEPOINT (tests/base.py), so the
    deliberate ALTER TABLE below is rolled back at tearDown like any other
    test write.
    """

    PROBE_TABLE = "va_smartva_form_runs"
    PROBE_CONSTRAINT = "ck_va_smartva_form_runs_outcome"

    def _conn(self):
        return db.session.connection()

    def test_silent_on_a_clean_database(self):
        conn = self._conn()
        reference = _check_constraints(conn)
        target = _check_constraints(conn)
        self.assertEqual(_diff_mapping(reference, target, str), [])

    def test_detects_a_deliberately_introduced_difference(self):
        conn = self._conn()
        reference = _check_constraints(conn)

        # Narrow the same constraint's allowed values -- semantically a real
        # drift, not just a re-spelling that _normalize_sql should absorb.
        conn.execute(
            sa.text(
                f'ALTER TABLE {self.PROBE_TABLE} '
                f'DROP CONSTRAINT "{self.PROBE_CONSTRAINT}"'
            )
        )
        conn.execute(
            sa.text(
                f"ALTER TABLE {self.PROBE_TABLE} ADD CONSTRAINT "
                f'"{self.PROBE_CONSTRAINT}" '
                "CHECK (outcome IN ('success', 'failed'))"
            )
        )

        target = _check_constraints(conn)
        key = (self.PROBE_TABLE, self.PROBE_CONSTRAINT)
        self.assertNotEqual(reference[key], target[key])

        diffs = _diff_mapping(reference, target, lambda k: f"CHECK {k[0]}.{k[1]}")
        self.assertEqual(
            diffs,
            [
                f"CHECK {self.PROBE_TABLE}.{self.PROBE_CONSTRAINT}: differs\n"
                f"    reference: {reference[key]!r}\n"
                f"    target:    {target[key]!r}"
            ],
        )
