"""Public read-only /help/cod-bucket-schemes page, JSON and CSV (digitva-yds.3).

Anonymous, GET only; public fields only; active schemes only.
"""

import csv
import io
import uuid
from unittest import mock

import sqlalchemy as sa
from cachelib import NullCache, SimpleCache

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasCodBucketSchemeAgeBand,
)
from app.services import cod_bucket_mapping_service as service
from tests.base import BaseTestCase

# Values that exist only in internal columns; none may reach a public reader.
INTERNAL_SHEET = "INTERNAL_SHEET_XYZ"
INTERNAL_NOTE = "internal-note-xyz"
INTERNAL_CATEGORY = "internal-category-xyz"
DROPPED_KEYS = (
    "mapping_id", "source_sheet", "source_row_number", "source_category",
    "mapping_note", "is_active", "node_id", "parent_node_id", "scheme_id",
    "created_at", "updated_at", "exported_at",
)


def _scheme(code, name, *, active=True):
    scheme = MasCodBucketScheme(
        scheme_code=code, scheme_name=name, mapping_version=1, is_active=active,
    )
    db.session.add(scheme)
    db.session.flush()
    return scheme


def _band(scheme, scope, label, order, *, active=True):
    db.session.add(
        MasCodBucketSchemeAgeBand(
            scheme_id=scheme.scheme_id, age_scope=scope, age_label=label,
            min_age_value=0, min_age_unit="years", max_age_value=99,
            max_age_unit="years", sort_order=order, is_active=active,
        )
    )


def _node(scheme, scope, code, label, order, parent=None, *, active=True):
    node = MasCodBucketNode(
        scheme_id=scheme.scheme_id, age_scope=scope, node_type="field",
        node_code=code, node_label=label, sort_order=order,
        parent_node_id=parent.node_id if parent else None, is_active=active,
    )
    db.session.add(node)
    db.session.flush()
    return node


def _map(scheme, scope, node, classification, code, *, active=True):
    db.session.add(
        MapIcdCodBucket(
            scheme_id=scheme.scheme_id, age_scope=scope, icd_classification=classification,
            icd_code=code, node_id=node.node_id, match_type="exact",
            source_sheet=INTERNAL_SHEET, source_row_number=7,
            source_category=INTERNAL_CATEGORY, mapping_note=INTERNAL_NOTE,
            is_active=active,
        )
    )


class HelpCodBucketSchemesTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tag = uuid.uuid4().hex[:6].upper()
        cls.active_code = f"PUB_{tag}"
        cls.inactive_code = f"OFF_{tag}"
        scheme = _scheme(cls.active_code, "Public bucket scheme")
        _band(scheme, "adult", "Adult", 1)
        _band(scheme, "child", "Child", 2, active=False)
        parent = _node(scheme, "adult", "infect", "Infectious", 1)
        child = _node(scheme, "adult", "tb", "Tuberculosis", 1, parent)
        gone = _node(scheme, "adult", "gone", "Retired bucket", 2, active=False)
        _node(scheme, "child", "kid", "Child bucket", 1)
        _map(scheme, "adult", child, "icd10", "A15.0")
        _map(scheme, "adult", child, "icd11", "1B10")
        _map(scheme, "adult", child, "icd10", "A15.1", active=False)
        _map(scheme, "adult", gone, "icd10", "Z99")
        cls.scheme = scheme
        off = _scheme(cls.inactive_code, "Inactive scheme", active=False)
        _band(off, None, "All ages", 1)
        _map(off, None, _node(off, None, "x", "Hidden", 1), "icd10", "B00")
        db.session.commit()

    def setUp(self):
        super().setUp()
        # Redis would carry the projection across tests; a null cache keeps them
        # independent. test_projection_is_cached swaps in a real one.
        patch = mock.patch.object(service, "cache", NullCache())
        patch.start()
        self.addCleanup(patch.stop)

    def _json(self, code=None):
        response = self.client.get(f"/help/cod-bucket-schemes/{code or self.active_code}.json")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_anonymous_page_lists_active_schemes_only(self):
        response = self.client.get(f"/help/cod-bucket-schemes?scheme={self.active_code}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Public bucket scheme", body)
        self.assertIn(f"/help/cod-bucket-schemes/{self.active_code}.json", body)
        self.assertNotIn(self.inactive_code, body)
        for edit_control in ("btn-danger", "Delete", "Save"):
            self.assertNotIn(edit_control, body.split('id="bucket-view"', 1)[-1])

    def test_json_has_known_bucket_and_codes_from_both_classifications(self):
        data = self._json()
        self.assertEqual(data["scheme"], {
            "scheme_code": self.active_code, "scheme_name": "Public bucket scheme",
        })
        self.assertEqual(data["age_bands"], [{"age_scope": "adult", "age_band": "Adult"}])
        paths = {b["bucket_path"] for b in data["buckets"]}
        self.assertIn("Infectious > Tuberculosis", paths)
        by_id = {b["id"]: b for b in data["buckets"]}
        tb = next(b for b in data["buckets"] if b["bucket_label"] == "Tuberculosis")
        self.assertEqual(by_id[tb["parent"]]["bucket_label"], "Infectious")
        self.assertIsNone(by_id[tb["parent"]]["parent"])
        mapped = {
            (m["classification"], m["code"], by_id[m["bucket"]]["bucket_path"])
            for m in data["mappings"]
        }
        self.assertIn(("icd10", "A15.0", "Infectious > Tuberculosis"), mapped)
        self.assertIn(("icd11", "1B10", "Infectious > Tuberculosis"), mapped)

    def test_inactive_rows_are_excluded(self):
        data = self._json()
        self.assertNotIn("A15.1", {m["code"] for m in data["mappings"]})
        self.assertNotIn("Z99", {m["code"] for m in data["mappings"]})
        self.assertNotIn("Retired bucket", {b["bucket_label"] for b in data["buckets"]})
        self.assertNotIn("child", {b["age_scope"] for b in data["buckets"]})

    def test_json_and_csv_drop_internal_fields(self):
        data = self._json()
        self.assertTrue(data["mappings"][0]["code"])  # kept field present first
        text = self.client.get(
            f"/help/cod-bucket-schemes/{self.active_code}.json"
        ).get_data(as_text=True)
        for key in DROPPED_KEYS:
            self.assertNotIn(f'"{key}"', text)
        for value in (INTERNAL_SHEET, INTERNAL_NOTE, INTERNAL_CATEGORY):
            self.assertNotIn(value, text)

        response = self.client.get(f"/help/cod-bucket-schemes/{self.active_code}.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        body = response.get_data(as_text=True)
        rows = list(csv.reader(io.StringIO(body)))
        self.assertEqual(rows[0][:3], ["scheme_code", "scheme_name", "age_band"])
        self.assertIn(
            [self.active_code, "Public bucket scheme", "Adult", "Infectious > Tuberculosis",
             "icd10", "A15.0", rows[1][6], "exact"],
            rows[1:],
        )
        for value in (INTERNAL_SHEET, INTERNAL_NOTE, INTERNAL_CATEGORY, "mapping_id", "A15.1", "Z99"):
            self.assertNotIn(value, body)

    def test_unknown_and_inactive_schemes_are_404(self):
        for code in ("NO_SUCH_SCHEME", self.inactive_code):
            self.assertEqual(self.client.get(f"/help/cod-bucket-schemes/{code}.json").status_code, 404)
            self.assertEqual(self.client.get(f"/help/cod-bucket-schemes/{code}.csv").status_code, 404)

    def test_unknown_scheme_query_falls_back_to_an_active_scheme(self):
        response = self.client.get("/help/cod-bucket-schemes?scheme=<script>")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>", response.get_data(as_text=True).split('id="bucket-view"')[0])

    def test_projection_is_cached_and_shared_by_json_and_csv(self):
        with mock.patch.object(service, "cache", SimpleCache()):
            self._json()
            statements = []

            def record(conn, cursor, statement, parameters, ctx, executemany):
                statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                self.assertEqual(self._json()["scheme"]["scheme_code"], self.active_code)
                self.assertEqual(
                    self.client.get(f"/help/cod-bucket-schemes/{self.active_code}.csv").status_code, 200
                )
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            self.assertEqual(statements, [])
            # Failures are not cached: an inactive scheme stays 404.
            self.assertEqual(
                self.client.get(f"/help/cod-bucket-schemes/{self.inactive_code}.json").status_code, 404
            )

    def test_query_count_does_not_grow_with_rows(self):
        def count():
            statements = []

            def record(conn, cursor, statement, parameters, ctx, executemany):
                statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                self.assertEqual(
                    self.client.get(f"/help/cod-bucket-schemes/{self.active_code}.json").status_code, 200
                )
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            return len(statements)

        before = count()
        node = db.session.scalar(
            sa.select(MasCodBucketNode).where(
                MasCodBucketNode.scheme_id == self.scheme.scheme_id,
                MasCodBucketNode.node_code == "tb",
            )
        )
        for n in range(40):
            _node(self.scheme, "adult", f"extra{n}", f"Extra {n}", 10 + n, node)
        for n in range(40):
            _map(self.scheme, "adult", node, "icd10", f"C{n:02d}.0")
        db.session.commit()
        self.assertEqual(count(), before)
        self.assertLessEqual(before, 12)
