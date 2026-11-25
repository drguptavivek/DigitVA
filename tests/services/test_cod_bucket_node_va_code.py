"""A COD bucket's VA cause code (digitva-0o3z).

Policy: docs/policy/cod-bucket-reporting.md, "VA cause code of a bucket". The
effective code is the node's explicit ``va_code``, else the one its
``node_code`` derives; lookups and displays use it, node_code is never renamed.
"""

import unittest
import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasCodBucketSchemeAgeBand,
    MasVaCauseDefinition,
)
from app.models.mas_cod_bucket import derived_va_code, effective_va_code, effective_va_code_sql
from app.services import va_cause_definition_service as svc
from app.services.cod_bucket_mapping_service import (
    export_cod_bucket_scheme_json,
    import_cod_bucket_scheme_json,
    set_cod_bucket_node_va_code,
)
from scripts.export_offline_va_definitions import build_pack
from tests.base import BaseTestCase
from tests.services.test_va_cause_definition_service import seed_icd_lookup_fixtures
from tests.services.test_va_cause_definitions_bucket_resolution import seed_bucket_chain_fixtures


class EffectiveVaCodeTests(unittest.TestCase):
    def test_explicit_code_wins_over_the_derived_one(self):
        self.assertEqual(effective_va_code("vas_01_02", None), "VAs-01.02")
        self.assertEqual(effective_va_code("vas_01_02", "VAs-01.09"), "VAs-01.09")

    def test_node_that_is_not_a_vas_cause(self):
        self.assertEqual(effective_va_code("other_gastrointestinal_diseases", "VAs-06.99"), "VAs-06.99")
        self.assertIsNone(effective_va_code("other_gastrointestinal_diseases", None))
        self.assertIsNone(derived_va_code(None))
        self.assertEqual(derived_va_code("vas_99"), "VAs-99")


class NodeVaCodeTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed_icd_lookup_fixtures()
        seed_bucket_chain_fixtures()

    def _node(self, scheme_code, node_code):
        return db.session.scalar(
            sa.select(MasCodBucketNode)
            .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MasCodBucketNode.scheme_id)
            .where(MasCodBucketScheme.scheme_code == scheme_code, MasCodBucketNode.node_code == node_code)
        )

    def _mappings(self, node):
        return sorted(
            (m.icd_classification, m.icd_code, m.node_id)
            for m in db.session.scalars(sa.select(MapIcdCodBucket).where(MapIcdCodBucket.node_id == node.node_id))
        )

    def test_sql_expression_matches_python(self):
        node = self._node("WHO_2022_VA", "other_gastrointestinal_diseases")
        vas = self._node("WHO_2022_VA", "vas_01_04")
        node.va_code = "VAs-06.02"
        db.session.flush()
        rows = dict(db.session.execute(
            sa.select(MasCodBucketNode.node_code, effective_va_code_sql(MasCodBucketNode))
            .where(MasCodBucketNode.node_id.in_([node.node_id, vas.node_id]))
        ).all())
        self.assertEqual(rows, {"other_gastrointestinal_diseases": "VAs-06.02", "vas_01_04": "VAs-01.04"})
        node.va_code = None
        db.session.flush()
        self.assertIsNone(db.session.scalar(
            sa.select(effective_va_code_sql(MasCodBucketNode)).where(MasCodBucketNode.node_id == node.node_id)
        ))

    def test_set_on_a_non_vas_node_drives_the_icd10_and_icd11_lookups(self):
        self.assertIsNone(svc.find_va_definition_for_icd("Z99"))
        found = svc.find_va_definition_for_icd("1A00.3", "icd11")
        self.assertEqual(found["va_code"], "other_gastrointestinal_diseases")
        for scheme_code in ("WHO_2022_VA", "WHO_2022_VA_2026"):
            node = self._node(scheme_code, "other_gastrointestinal_diseases")
            before = self._mappings(node)
            version = node.scheme.mapping_version
            self.assertTrue(set_cod_bucket_node_va_code(node, " VAs-06.02 "))
            db.session.flush()
            self.assertEqual(node.va_code, "VAs-06.02")
            self.assertEqual(node.node_code, "other_gastrointestinal_diseases")
            self.assertEqual(self._mappings(node), before)
            self.assertTrue(before)
            self.assertEqual(node.scheme.mapping_version, version + 1)

        found = svc.find_va_definition_for_icd("Z99")
        self.assertEqual((found["va_code"], found["title"]), ("VAs-06.02", "Liver cirrhosis"))
        found = svc.find_va_definition_for_icd("1A00.3", "icd11")
        self.assertEqual(
            (found["va_code"], found["bucket_code"], found["has_definition"]),
            ("VAs-06.02", "other_gastrointestinal_diseases", True),
        )
        self.assertEqual(build_pack()["buckets"]["other_gastrointestinal_diseases"]["va_code"], "VAs-06.02")
        # Unchanged value: no write, no version bump.
        self.assertFalse(set_cod_bucket_node_va_code(node, "VAs-06.02"))

    def test_clearing_falls_back_to_the_derived_code(self):
        node = self._node("WHO_2022_VA", "vas_01_04")
        set_cod_bucket_node_va_code(node, "VAs-06.02")
        db.session.flush()
        self.assertEqual(svc.find_va_definition_for_icd("A04")["va_code"], "VAs-06.02")
        self.assertTrue(set_cod_bucket_node_va_code(node, ""))
        db.session.flush()
        self.assertIsNone(node.va_code)
        self.assertEqual(svc.find_va_definition_for_icd("A04")["va_code"], "VAs-01.04")
        self.assertEqual(node.disease_default_va_code, "VAs-01.04")
        self.assertIsNone(self._node("WHO_2022_VA", "other_gastrointestinal_diseases").disease_default_va_code)

    def test_refusals(self):
        node = self._node("WHO_2022_VA", "other_gastrointestinal_diseases")
        cases = {
            "VAs-6.2": "must look like",
            "VAs-98": "must look like",
            "VAs-77.77": "not an active VA definition",
            "VAs-01.04": "bucket 'vas_01_04'",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, message):
                    set_cod_bucket_node_va_code(node, value)
        with self.assertRaisesRegex(ValueError, "must be a string"):
            set_cod_bucket_node_va_code(node, 12)

        definition = db.session.scalar(
            sa.select(MasVaCauseDefinition).where(MasVaCauseDefinition.va_code == "VAs-06.02")
        )
        definition.is_active = False
        db.session.flush()
        with self.assertRaisesRegex(ValueError, "not an active VA definition"):
            set_cod_bucket_node_va_code(node, "VAs-06.02")

        section = self._node("WHO_2022_VA_2026", "infectious")
        self.assertEqual(section.node_type, "section")
        with self.assertRaisesRegex(ValueError, "Only a disease bucket"):
            set_cod_bucket_node_va_code(section, "VAs-01.01")
        self.assertIsNone(node.va_code)

    def test_clearing_is_refused_when_the_derived_code_is_taken(self):
        vas = self._node("WHO_2022_VA", "vas_01_04")
        other = self._node("WHO_2022_VA", "other_gastrointestinal_diseases")
        set_cod_bucket_node_va_code(vas, "VAs-06.02")
        db.session.flush()
        set_cod_bucket_node_va_code(other, "VAs-01.04")
        db.session.flush()
        with self.assertRaisesRegex(ValueError, "bucket 'other_gastrointestinal_diseases'"):
            set_cod_bucket_node_va_code(vas, None)
        self.assertEqual(vas.va_code, "VAs-06.02")

    def _fresh_scheme(self):
        """A scheme of its own: an import replaces every node, and its commit
        outlives the per-test rollback, so the shared fixtures stay untouched."""
        scheme = MasCodBucketScheme(
            scheme_code=f"TEST_VACODE_{uuid.uuid4().hex[:8].upper()}", scheme_name="VA code test",
            mapping_version=1, is_active=True,
        )
        db.session.add(scheme)
        db.session.flush()
        db.session.add(MasCodBucketSchemeAgeBand(
            scheme_id=scheme.scheme_id, age_scope=None, age_label="All ages", min_age_value=0,
            min_age_unit="days", max_age_value=120, max_age_unit="years", level_count=2,
        ))
        group = MasCodBucketNode(
            scheme_id=scheme.scheme_id, node_type="category", node_code="digestive", node_label="Digestive",
        )
        db.session.add(group)
        db.session.flush()
        for node_code in ("vas_01_04", "other_digestive"):
            db.session.add(MasCodBucketNode(
                scheme_id=scheme.scheme_id, node_type="field", parent_node_id=group.node_id,
                node_code=node_code, node_label=node_code,
            ))
        db.session.flush()
        return scheme

    def test_snapshot_json_round_trips_and_old_files_import_null(self):
        scheme = self._fresh_scheme()
        set_cod_bucket_node_va_code(self._node(scheme.scheme_code, "other_digestive"), "VAs-06.02")
        db.session.commit()

        payload = export_cod_bucket_scheme_json(scheme_code=scheme.scheme_code)
        exported = {row["node_code"]: row["va_code"] for row in payload["nodes"]}
        self.assertEqual(exported["other_digestive"], "VAs-06.02")
        self.assertIsNone(exported["vas_01_04"])

        import_cod_bucket_scheme_json(scheme_code=scheme.scheme_code, payload=payload)
        self.assertEqual(self._node(scheme.scheme_code, "other_digestive").va_code, "VAs-06.02")

        for row in payload["nodes"]:
            row.pop("va_code")
        import_cod_bucket_scheme_json(scheme_code=scheme.scheme_code, payload=payload)
        node = self._node(scheme.scheme_code, "other_digestive")
        self.assertIsNotNone(node)
        self.assertIsNone(node.va_code)

    def test_import_refuses_a_malformed_va_code(self):
        scheme = self._fresh_scheme()
        payload = export_cod_bucket_scheme_json(scheme_code=scheme.scheme_code)
        row = next(r for r in payload["nodes"] if r["node_code"] == "other_digestive")
        row["va_code"] = "<b>VAs</b>"
        with self.assertRaisesRegex(ValueError, "va_code must be"):
            import_cod_bucket_scheme_json(scheme_code=scheme.scheme_code, payload=payload)
        group = next(r for r in payload["nodes"] if r["node_code"] == "digestive")
        row["va_code"], group["va_code"] = None, "VAs-06.02"
        with self.assertRaisesRegex(ValueError, "on a disease node"):
            import_cod_bucket_scheme_json(scheme_code=scheme.scheme_code, payload=payload)
