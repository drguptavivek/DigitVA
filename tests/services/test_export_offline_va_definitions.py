import sqlalchemy as sa

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd11Mms
from app.services.va_cause_definition_service import find_va_definition_for_icd
from scripts.export_offline_va_definitions import build_pack, compact_sha256, resolve_codes
from tests.base import BaseTestCase
from tests.services.test_va_cause_definition_service import seed_icd_lookup_fixtures


def test_lookup_expansion_prefers_exact_then_nearest_parent_and_skips_unmapped():
    hierarchy = [
        ("1A00", "urn:1A00", None),
        ("1A00.1", "urn:1A00.1", "urn:1A00"),
        ("1A00.1.1", "urn:1A00.1.1", "urn:1A00.1"),
        ("9Z99", "urn:2B00", None),
    ]
    direct = {"1A00": "VAs-01.01", "1A00.1": "VAs-02.01", "3C00": "VAs-03.01"}

    assert resolve_codes(hierarchy, direct) == {
        "1A00": "VAs-01.01",
        "1A00.1": "VAs-02.01",
        "1A00.1.1": "VAs-02.01",
        "3C00": "VAs-03.01",
    }


def test_content_digest_matches_mobile_canonical_unicode_vector():
    fixture = {
        "schema": 1,
        "scheme": "WHO_2022_VA_2026",
        "release": "2026-01",
        "source_digest": "b" * 64,
        "count": 1,
        "definitions": {"VAs-01.01": {"title": "Café", "definition_html": "<p>Fever &amp; pain</p>"}},
        "codes": {"1A00": "VAs-01.01"},
    }
    assert compact_sha256(fixture) == "b1a705617815902c8ca9d91c70de0f1b4a20e965acb91aa2124f9d2418864429"


class OfflineVaPackParityTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed_icd_lookup_fixtures()

    def test_pack_uses_exact_then_parent_mapping_like_server(self):
        pack = build_pack()
        self.assertEqual(pack["scheme"], "WHO_2022_VA_2026")
        self.assertEqual(pack["release"], "2026-01")
        self.assertEqual(pack["codes"]["1A00"], "VAs-01.04")
        self.assertEqual(pack["codes"]["1A00.1"], "VAs-01.04")
        server = find_va_definition_for_icd("1A00.1 child", "icd11")
        self.assertEqual(pack["codes"]["1A00.1"], server["va_code"])
        self.assertNotIn("9Z99", pack["codes"])

    def test_inactive_scheme_and_node_are_excluded(self):
        scheme = db.session.scalar(sa.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == "WHO_2022_VA_2026"))
        scheme.is_active = False
        self.assertNotIn("1A00", build_pack()["codes"])
        self.assertIsNone(find_va_definition_for_icd("1A00", "icd11"))
        scheme.is_active = True

        node = MasCodBucketNode(
            scheme_id=scheme.scheme_id, node_type="field", node_code="vas_01_04",
            node_label="inactive test", age_scope="inactive_pack_test", is_active=False,
        )
        db.session.add(node)
        db.session.add(MasIcd11Mms(
            release="2026-01", linearization_uri="offline-test/9Z99", code="9Z99",
            title="test", class_kind="category", source_version="test",
        ))
        db.session.flush()
        db.session.add(MapIcdCodBucket(
            scheme_id=scheme.scheme_id, node_id=node.node_id, icd_code="9Z99",
            icd_classification="icd11", age_scope="inactive_pack_test", is_active=True,
        ))
        self.assertNotIn("9Z99", build_pack()["codes"])
        self.assertIsNone(find_va_definition_for_icd("9Z99", "icd11"))
