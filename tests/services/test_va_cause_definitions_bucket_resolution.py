"""One rule for the VA cause bucket of an ICD-11 code (docs/policy/va-cause-definitions.md).

The COD snapshot's CTEs, the shared helper (seeded and unseeded), the server lookup and the offline pack must give a
code the same bucket: its nearest mapped node, whether or not that node has a definition, from all-ages
(``age_scope IS NULL``) rows only.
"""

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasIcd11Mms,
    MasVaCauseDefinition,
)
from app.services import va_cause_definition_service as svc
from app.services.submission_analytics_mv import (
    _who_2026_bucket_sql,
    resolve_who_2026_icd11_buckets,
)
from scripts.export_offline_va_definitions import build_pack
from tests.base import BaseTestCase
from tests.services.test_va_cause_definition_service import seed_icd_lookup_fixtures

SCHEME = "WHO_2022_VA_2026"
# code -> parent code. 1A00 maps to vas_01_04 (has a definition); 1A00.2 to vas_98 (none) under it.
CHAIN = {
    "1A00.2": "1A00",
    "1A00.2A": "1A00.2",
    "1A00.3": "1A00",  # mapped to a node that is not a vas_* cause
    "1A00.4": "1A00",  # also has an age-scoped row, which must be ignored
    "9Z99": None,  # in the catalogue, nothing mapped on its chain
}


def seed_bucket_chain_fixtures():
    """Extend seed_icd_lookup_fixtures: a section parent, vas_98 (no definition row), and the CHAIN codes."""
    scheme = db.session.scalar(sa.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == SCHEME))
    nodes = {
        node.node_code: node
        for node in db.session.scalars(sa.select(MasCodBucketNode).where(MasCodBucketNode.scheme_id == scheme.scheme_id))
    }
    section = MasCodBucketNode(
        scheme_id=scheme.scheme_id, node_type="section", node_code="infectious", node_label="Infectious",
        age_scope="vadef_test",
    )
    vas_98 = MasCodBucketNode(
        scheme_id=scheme.scheme_id, node_type="field", node_code="vas_98", node_label="Other NCD",
        age_scope="vadef_test",
    )
    db.session.add_all([section, vas_98])
    db.session.flush()
    for code in ("vas_01_04", "other_gastrointestinal_diseases"):
        nodes[code].parent_node_id = section.node_id
    vas_98.parent_node_id = section.node_id

    def _map(node, code, age_scope=None):
        db.session.add(MapIcdCodBucket(
            scheme_id=scheme.scheme_id, node_id=node.node_id, icd_code=code,
            icd_classification="icd11", age_scope=age_scope,
        ))

    _map(vas_98, "1A00.2")
    _map(nodes["other_gastrointestinal_diseases"], "1A00.3")
    _map(vas_98, "1A00.4", age_scope="neonate")
    release = svc.DEFAULT_ICD11_RELEASE
    for code, parent in CHAIN.items():
        db.session.add(MasIcd11Mms(
            release=release, linearization_uri=f"vadef-test/{code}", code=code, title=code,
            class_kind="category", source_version="test",
            parent_linearization_uri=f"vadef-test/{parent}" if parent else None,
        ))
    db.session.commit()


def _snapshot_buckets() -> dict:
    """code -> (label, section) from the CTEs the COD snapshot MV is built from."""
    rows = db.session.execute(sa.text(
        f"WITH RECURSIVE {_who_2026_bucket_sql()[0]} SELECT icd_code, bucket_label, bucket_section FROM icd11_buckets"
    )).all()
    return {code: (label, section) for code, label, section in rows}


class BucketResolutionTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed_icd_lookup_fixtures()
        seed_bucket_chain_fixtures()

    def _catalogue(self) -> list[str]:
        return list(db.session.scalars(
            sa.select(sa.func.upper(MasIcd11Mms.code)).where(
                MasIcd11Mms.release == svc.DEFAULT_ICD11_RELEASE, MasIcd11Mms.code.is_not(None)
            )
        ))

    def test_seeded_and_unseeded_helper_agree(self):
        whole = {row.icd_code: tuple(row) for row in resolve_who_2026_icd11_buckets()}
        codes = self._catalogue()
        seeded = {row.icd_code: tuple(row) for row in resolve_who_2026_icd11_buckets(codes)}
        self.assertTrue({"1A00", "1A00.1", "1A00.2A"} <= set(whole))
        for code in codes:
            self.assertEqual(seeded.get(code), whole.get(code), code)
        self.assertEqual(resolve_who_2026_icd11_buckets(["9Z99"]), [])
        self.assertEqual(resolve_who_2026_icd11_buckets([]), [])

    def test_lookup_snapshot_and_pack_agree_for_every_catalogue_code(self):
        snapshot = _snapshot_buckets()
        pack = build_pack()
        mapped = 0
        for code in self._catalogue():
            found = svc.find_va_definition_for_icd(code, "icd11")
            if code not in snapshot:
                self.assertIsNone(found, code)
                self.assertNotIn(code, pack["codes"], code)
                continue
            mapped += 1
            bucket = pack["buckets"][pack["codes"][code]]
            self.assertEqual((found["bucket_label"], found["bucket_section"]), snapshot[code], code)
            self.assertEqual((bucket["label"], bucket["section"]), snapshot[code], code)
        self.assertGreaterEqual(mapped, 5)

    def test_nearest_mapped_node_without_a_definition_is_shown_not_the_ancestors(self):
        found = svc.find_va_definition_for_icd("1A00.2A", "icd11")
        self.assertEqual(
            {k: v for k, v in found.items()},
            {
                "icd_code": "1A00.2A",
                "classification": "icd11",
                "va_code": "VAs-98",
                "title": "Other NCD",
                "definition_html": "",
                "source": "digitva",
                "bucket_code": "vas_98",
                "bucket_label": "Other NCD",
                "bucket_section": "Infectious",
                "has_definition": False,
            },
        )

    def test_a_node_with_a_definition_carries_it(self):
        found = svc.find_va_definition_for_icd("1A00.1", "icd11")
        self.assertEqual((found["va_code"], found["bucket_code"], found["has_definition"]), ("VAs-01.04", "vas_01_04", True))
        self.assertEqual(found["title"], "Diarrhoeal diseases")  # the WHO title; bucket_label is the node's own
        self.assertEqual(found["bucket_label"], "vas_01_04")
        self.assertIn("<", found["definition_html"])

    def test_a_node_that_is_not_a_va_cause_shows_its_node_code(self):
        found = svc.find_va_definition_for_icd("1A00.3", "icd11")
        self.assertEqual((found["va_code"], found["bucket_code"], found["has_definition"]), (
            "other_gastrointestinal_diseases", "other_gastrointestinal_diseases", False,
        ))
        self.assertEqual((found["title"], found["definition_html"]), ("other_gastrointestinal_diseases", ""))

    def test_age_scoped_rows_are_ignored_like_the_snapshot(self):
        self.assertEqual(svc.find_va_definition_for_icd("1A00.4", "icd11")["bucket_code"], "vas_01_04")
        self.assertEqual(_snapshot_buckets()["1A00.4"], _snapshot_buckets()["1A00"])

    def test_unmapped_code_has_no_result(self):
        self.assertIsNone(svc.find_va_definition_for_icd("9Z99", "icd11"))
        self.assertIsNone(svc.find_va_definition_for_icd("QQ99", "icd11"))  # not in the catalogue

    def test_inactive_definition_leaves_the_bucket_but_drops_the_text(self):
        row = db.session.scalar(sa.select(MasVaCauseDefinition).where(MasVaCauseDefinition.va_code == "VAs-01.04"))
        svc.update_va_definition(row.id, {"is_active": False}, user_id=self.base_admin_id)
        found = svc.find_va_definition_for_icd("1A00", "icd11")
        self.assertEqual((found["va_code"], found["bucket_code"], found["has_definition"]), ("VAs-01.04", "vas_01_04", False))
        self.assertEqual((found["title"], found["definition_html"]), ("vas_01_04", ""))

    def test_inactive_node_is_skipped_to_the_next_mapped_ancestor_like_the_snapshot(self):
        node = db.session.scalar(sa.select(MasCodBucketNode).where(MasCodBucketNode.node_code == "vas_98"))
        node.is_active = False
        db.session.flush()
        found = svc.find_va_definition_for_icd("1A00.2A", "icd11")
        self.assertEqual(found["bucket_code"], "vas_01_04")
        self.assertEqual((found["bucket_label"], found["bucket_section"]), _snapshot_buckets()["1A00.2A"])
