"""The offline VA cause pack (scripts/export_offline_va_definitions.py) and its drift guards.

Collect Plus shows the bucket of a selected ICD-11 code from the committed pack. These tests fail when the pack, the
server lookup (``find_va_definition_for_icd``) and the COD snapshot's CTEs can diverge, or when the committed pack no
longer equals what the database at head produces.
"""

import json

import sqlalchemy as sa

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd11Mms
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.va_cause_definition_service import find_va_definition_for_icd
from scripts.export_offline_va_definitions import (
    HASHED_FIELDS,
    OUTPUT,
    SCHEMA,
    build_pack,
    compact_sha256,
)
from tests.base import BaseTestCase
from tests.services.test_va_cause_definition_service import seed_icd_lookup_fixtures
from tests.services.test_va_cause_definitions_bucket_resolution import seed_bucket_chain_fixtures


def _committed() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_content_digest_matches_mobile_canonical_unicode_vector():
    fixture = {
        "schema": 2,
        "scheme": "WHO_2022_VA_2026",
        "release": "2026-01",
        "count": 1,
        "buckets": {
            "vas_01_01": {"label": "Café", "section": "Infections", "section_code": "infections", "va_code": "VAs-01.01"}
        },
        "definitions": {"VAs-01.01": {"title": "Café", "definition_html": "<p>Fever &amp; pain</p>"}},
        "codes": {"1A00": "vas_01_01"},
    }
    assert compact_sha256(fixture) == "2462b07dc977002c761b238a3e95e98ac3c613176cabd0b7e78ec99721920a04"


class OfflineVaPackParityTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed_icd_lookup_fixtures()
        seed_bucket_chain_fixtures()

    def test_pack_shape_and_lookup_parity(self):
        pack = build_pack()
        self.assertEqual((pack["schema"], pack["scheme"], pack["release"]), (SCHEMA, "WHO_2022_VA_2026", "2026-01"))
        self.assertEqual(pack["count"], len(pack["codes"]))
        self.assertEqual(pack["codes"]["1A00"], "vas_01_04")
        self.assertEqual(pack["codes"]["1A00.1"], "vas_01_04")
        self.assertEqual(pack["codes"]["1A00.2A"], "vas_98")
        self.assertNotIn("9Z99", pack["codes"])
        self.assertEqual(pack["buckets"]["vas_98"]["va_code"], "VAs-98")
        self.assertNotIn("VAs-98", pack["definitions"])  # the node has no definition: label only
        self.assertEqual(pack["buckets"]["vas_01_04"]["section"], "Infectious")
        self.assertEqual(pack["buckets"]["other_gastrointestinal_diseases"]["va_code"], None)
        for code, node_code in pack["codes"].items():
            server = find_va_definition_for_icd(code, "icd11")
            bucket = pack["buckets"][node_code]
            self.assertEqual(server["bucket_code"], node_code, code)
            self.assertEqual(server["va_code"], bucket["va_code"] or node_code, code)
            self.assertEqual((server["bucket_label"], server["bucket_section"]), (bucket["label"], bucket["section"]), code)
            self.assertEqual(server["has_definition"], bucket["va_code"] in pack["definitions"], code)

    def test_pack_hash_is_over_the_documented_fields_without_the_revision(self):
        pack = build_pack()
        self.assertEqual(HASHED_FIELDS, ("schema", "scheme", "release", "count", "buckets", "definitions", "codes"))
        self.assertEqual(pack["content_sha256"], compact_sha256({key: pack[key] for key in HASHED_FIELDS}))
        self.assertIn("db_revision", pack)
        self.assertNotIn("source_digest", pack)

    def test_inactive_scheme_and_node_are_excluded(self):
        scheme = db.session.scalar(sa.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == "WHO_2022_VA_2026"))
        scheme.is_active = False
        db.session.flush()  # the shared helper is raw SQL: no autoflush
        self.assertNotIn("1A00", build_pack()["codes"])
        self.assertIsNone(find_va_definition_for_icd("1A00", "icd11"))
        scheme.is_active = True
        db.session.flush()

        node = MasCodBucketNode(
            scheme_id=scheme.scheme_id, node_type="field", node_code="vas_01_04",
            node_label="inactive test", age_scope="inactive_pack_test", is_active=False,
        )
        db.session.add(node)
        db.session.add(MasIcd11Mms(
            release=DEFAULT_ICD11_RELEASE, linearization_uri="offline-test/9Z98", code="9Z98",
            title="test", class_kind="category", source_version="test",
        ))
        db.session.flush()
        db.session.add(MapIcdCodBucket(
            scheme_id=scheme.scheme_id, node_id=node.node_id, icd_code="9Z98",
            icd_classification="icd11", age_scope=None, is_active=True,
        ))
        db.session.flush()
        self.assertNotIn("9Z98", build_pack()["codes"])
        self.assertIsNone(find_va_definition_for_icd("9Z98", "icd11"))


class CommittedVaPackTests(BaseTestCase):
    def test_committed_pack_is_internally_consistent(self):
        pack = _committed()
        self.assertEqual(pack["schema"], SCHEMA)
        self.assertEqual(pack["content_sha256"], compact_sha256({key: pack[key] for key in HASHED_FIELDS}))
        self.assertEqual(pack["count"], len(pack["codes"]))
        self.assertTrue(set(pack["codes"].values()) <= set(pack["buckets"]))
        va_codes = {bucket["va_code"] for bucket in pack["buckets"].values() if bucket["va_code"]}
        self.assertTrue(set(pack["definitions"]) <= va_codes)
        self.assertFalse([code for code in pack["codes"] if code.isdecimal()])

    def test_committed_pack_equals_the_database_when_the_catalogue_is_loaded(self):
        """Fails after a mapping, definition, scheme or catalogue change until the pack is regenerated:
        docker compose exec -T minerva_app_service uv run --no-sync python -m scripts.export_offline_va_definitions"""
        loaded = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasIcd11Mms).where(MasIcd11Mms.release == DEFAULT_ICD11_RELEASE)
        )
        mapped = db.session.scalar(
            sa.select(sa.func.count()).select_from(MapIcdCodBucket).where(MapIcdCodBucket.icd_classification == "icd11")
        )
        if not loaded or not mapped:
            self.skipTest("The ICD-11 catalogue and its VA mapping are not loaded in this database.")
        built = build_pack()
        committed = _committed()
        # The revision differs by checkout; the content hash is what ties the pack to the data.
        built.pop("db_revision"), committed.pop("db_revision")
        self.assertEqual(committed, built)
