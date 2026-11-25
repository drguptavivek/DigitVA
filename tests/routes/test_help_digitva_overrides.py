"""Public read-only /help/digitva-overrides page (digitva-j5n2)."""

import csv
import re
from datetime import UTC, datetime
from unittest import mock

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd1020192
from app.services.cod_bucket_icd11_generator import DECISIONS_PATH
from app.services.cod_bucket_mapping_service import (
    DEFAULT_WHO_2022_VA_2026_OWNER_DECISIONS_PATH,
    SCHEME_CODE_WHO_2022_VA_2026,
)
from tests.base import BaseTestCase

URL = "/help/digitva-overrides"


def _row(code, family, **values):
    """A catalogue row, created if absent, with `values` set."""
    row = db.session.get(MasIcd1020192, code)
    if row is None:
        now = datetime.now(UTC)
        row = MasIcd1020192(
            code=code, title=f"Title of {code}", node_type="category",
            semantic_level="three_character", sort_order=1, three_character_code=family,
            has_children=False, is_leaf=True, is_three_character_code=code == family,
            is_detailed_code=code != family, policy_status="unreviewed",
            source_version="ICD-10-2019", source_path="test", is_active=True,
            created_at=now, updated_at=now,
        )
        db.session.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    db.session.commit()
    return row


def _r10(selectable):
    """The R10 test row, with the given selectability."""
    _row("R10", "R10", title="Abdominal and pelvic pain", is_coding_selectable=selectable)


def _applied(client, code):
    """True/False for the 'Applied' badge of the table row of `code`; None if no row."""
    body = client.get(URL).get_data(as_text=True)
    match = re.search(rf"<tr><td>{re.escape(code)}</td>[^\n]*", body)
    if match is None:
        return None
    return "text-bg-success" in match.group(0)


def _a80(node_code):
    """WHO_2022_VA_2026 with VA nodes and the A80 ICD-10 mapping pointing at `node_code`."""
    scheme = db.session.scalar(
        db.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026)
    )
    if scheme is None:
        scheme = MasCodBucketScheme(
            scheme_code=SCHEME_CODE_WHO_2022_VA_2026, scheme_name="WHO 2022 VA 2026",
            mapping_version=1, is_active=True,
        )
        db.session.add(scheme)
        db.session.flush()
    nodes = {}
    for code in ("vas_01_07", "vas_99"):
        node = db.session.scalar(db.select(MasCodBucketNode).where(
            MasCodBucketNode.scheme_id == scheme.scheme_id, MasCodBucketNode.node_code == code,
            MasCodBucketNode.age_scope.is_(None),
        ))
        if node is None:
            node = MasCodBucketNode(
                scheme_id=scheme.scheme_id, age_scope=None, node_type="field",
                node_code=code, node_label=f"Label {code}", sort_order=1, is_active=True,
            )
            db.session.add(node)
            db.session.flush()
        nodes[code] = node
    mapping = db.session.scalar(db.select(MapIcdCodBucket).where(
        MapIcdCodBucket.scheme_id == scheme.scheme_id, MapIcdCodBucket.icd_classification == "icd10",
        MapIcdCodBucket.icd_code == "A80", MapIcdCodBucket.age_scope.is_(None),
    ))
    if mapping is None:
        mapping = MapIcdCodBucket(
            scheme_id=scheme.scheme_id, age_scope=None, icd_classification="icd10",
            icd_code="A80", node_id=nodes[node_code].node_id, match_type="exact", is_active=True,
        )
        db.session.add(mapping)
    mapping.node_id = nodes[node_code].node_id
    mapping.is_active = True
    db.session.commit()


class HelpDigitvaOverridesTests(BaseTestCase):
    def test_anonymous_page_shows_sections_counts_and_known_rows(self):
        _r10(False)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        with open(DEFAULT_WHO_2022_VA_2026_OWNER_DECISIONS_PATH, newline="", encoding="utf-8") as handle:
            icd10_rows = len(list(csv.DictReader(handle)))
        with open(DECISIONS_PATH, newline="", encoding="utf-8") as handle:
            layers = [r["layer"] for r in csv.DictReader(handle)]
        digitva, who_fix = layers.count("digitva"), layers.count("who_fix")
        self.assertIn("ICD-10 coding allowability (260)", body)
        self.assertIn(f"ICD-10 owner decisions ({icd10_rows})", body)
        self.assertIn(f"ICD-11 decisions ({digitva})", body)
        self.assertIn(f"Corrections needed to read WHO's annex ({who_fix})", body)
        self.assertIn("Abdominal and pelvic pain", body)
        self.assertIn("not selectable", body)
        self.assertIn("VAs-01.07", body)
        self.assertIn("A80", body)

    def test_applied_column_follows_the_catalogue(self):
        _r10(False)
        row = "<td>R10</td><td>Abdominal and pelvic pain</td><td>whole family</td><td>not selectable</td>"
        yes = f'{row}<td><span class="badge text-bg-success">yes</span></td>'
        no = f'{row}<td><span class="badge text-bg-warning">no</span></td>'
        body = self.client.get(URL).get_data(as_text=True)
        self.assertIn(yes, body)
        self.assertNotIn(no, body)
        _r10(True)
        body = self.client.get(URL).get_data(as_text=True)
        self.assertIn(no, body)
        self.assertNotIn(yes, body)

    def test_help_index_lists_page(self):
        from app.services.help_registry import HELP_PAGES

        self.assertIn(("digitva-overrides", "DigitVA Overrides"), [(p[0], p[1]) for p in HELP_PAGES])

    def test_code_row_applied_follows_age_group(self):
        _row("Q00", "Q00", age_group_selectable="all")
        self.assertIs(_applied(self.client, "Q00"), True)
        _row("Q00", "Q00", age_group_selectable="neonate")
        self.assertIs(_applied(self.client, "Q00"), False)

    def test_family_applied_needs_every_active_subcode(self):
        _r10(False)
        _row("R10.4", "R10", is_coding_selectable=True)
        self.assertIs(_applied(self.client, "R10"), False)
        _row("R10.4", "R10", is_coding_selectable=False)
        self.assertIs(_applied(self.client, "R10"), True)

    def test_owner_decision_applied_follows_live_mapping(self):
        _a80("vas_01_07")
        self.assertIs(_applied(self.client, "A80"), True)
        _a80("vas_99")
        self.assertIs(_applied(self.client, "A80"), False)

    def test_bucket_shows_its_explicit_va_code(self):
        # digitva-0o3z: an explicit va_code wins over the code node_code derives.
        # VAs-01.06 is no override row's bucket, so it appears only via the node.
        _a80("vas_01_07")
        body = self.client.get(URL).get_data(as_text=True)
        self.assertIn("VAs-01.07", body)
        self.assertNotIn("VAs-01.06", body)
        node = db.session.scalar(
            db.select(MasCodBucketNode)
            .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MasCodBucketNode.scheme_id)
            .where(
                MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026,
                MasCodBucketNode.node_code == "vas_01_07",
                MasCodBucketNode.age_scope.is_(None),
            )
        )
        node.va_code = "VAs-01.06"
        db.session.commit()
        body = self.client.get(URL).get_data(as_text=True)
        self.assertIn("VAs-01.06", body)

    def test_unreadable_csv_only_drops_its_section(self):
        _r10(False)
        with mock.patch(
            "app.services.digitva_overrides_public_service._who_2022_va_2026_owner_decisions",
            side_effect=FileNotFoundError("/secret/path.csv"),
        ):
            response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Abdominal and pelvic pain", body)
        self.assertIn("Not available on this server", body)
        self.assertNotIn("/secret/path.csv", body)
