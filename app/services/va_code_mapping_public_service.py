"""Public list of WHO_2022_VA_2026 ICD-to-VA-cause mappings with their origin.

Policy: docs/policy/icd10-to-icd11-transition.md section 7. Every active
ICD-10 and ICD-11 row of the scheme is compared with WHO's 2026 annex (the
cause list and its footnote f) at read time; the origin is never stored:

- ``who``: the annex gives the code to the row's VA cause and to no other.
- ``who_resolved``: the annex gives the code to two or more causes, the row's
  among them; DigitVA picked one by a rule (see ``_resolution_rule``).
- ``not_in_who``: a selectable code is not listed for this cause.
- ``differs``: WHO lists the code for a different cause.
- ``not_cod``: an ICD-11 decision-5b fallback that is never selectable.
  ``digitva`` remains an inbound filter alias for these three origins.

docs/ is not shipped in the image, so the annex files are read from copies in
resource/ (kept equal to the docs copies by a test). The derived table is
built once per process and rebuilt when the scheme's rows, nodes or version
change, when an ICD-10 catalogue row changes, or when an annex file changes.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasIcd11Mms,
    MasIcd1020192,
)
from app.services.cod_bucket_icd11_generator import (
    expand_range,
    load_catalogue,
    parse_icd11_ranges,
    va_code_for_node,
)
from app.services.cod_bucket_mapping_service import (
    ICD_CLASSIFICATION_ICD10,
    ICD_CLASSIFICATION_ICD11,
    NODE_TYPE_FIELD,
    _slugify,
)
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE, POLICY_STATUS_OPTIONS

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEME_CODE = "WHO_2022_VA_2026"
ICD11_RELEASE = DEFAULT_ICD11_RELEASE
ANNEX_FILE_NAME = "who_2022_va_cause_list_icd10_icd11.csv"
ANNEX_PATH = _REPO_ROOT / "resource" / ANNEX_FILE_NAME
FOOTNOTES_PATH = _REPO_ROOT / "resource" / "who_2022_va_cause_list_footnotes.csv"

ORIGIN_WHO = "who"
ORIGIN_WHO_RESOLVED = "who_resolved"
ORIGIN_DIGITVA = "digitva"
ORIGIN_NOT_IN_WHO = "not_in_who"
ORIGIN_DIFFERS = "differs"
ORIGIN_NOT_COD = "not_cod"
ORIGIN_DIGITVA_GROUP = frozenset((ORIGIN_NOT_IN_WHO, ORIGIN_DIFFERS, ORIGIN_NOT_COD))
ORIGIN_LABELS = {
    ORIGIN_WHO: "WHO",
    ORIGIN_WHO_RESOLVED: "WHO (overlap resolved)",
    ORIGIN_NOT_IN_WHO: "Not in WHO's list",
    ORIGIN_DIFFERS: "Differs from WHO",
    ORIGIN_NOT_COD: "Not a cause of death",
}
ORIGIN_TONES = {
    ORIGIN_WHO: "success",
    ORIGIN_WHO_RESOLVED: "info",
    ORIGIN_NOT_IN_WHO: "warning",
    ORIGIN_DIFFERS: "danger",
    ORIGIN_NOT_COD: "secondary",
}
CLASSIFICATION_LABELS = {ICD_CLASSIFICATION_ICD10: "ICD-10", ICD_CLASSIFICATION_ICD11: "ICD-11"}
CSV_HEADERS = (
    "classification", "code", "code_title", "va_code", "va_title",
    "origin", "rule", "also_claimed_by", "note",
)

ROAD_TRAFFIC = "VAs-12.01"
OTHER_TRANSPORT = "VAs-12.02"
_ICD10_TOKEN_RE = re.compile(r"^[A-Z]\d{2}(\.\d)?(-[A-Z]\d{2}(\.\d)?)?$")

# ponytail: one table per process, rebuilt on a key change; a multi-worker
# server builds it once per worker. Move to the shared cache if that hurts.
_cache: dict = {"key": None, "rows": [], "va_causes": []}
_icd11_cache: dict = {"key": None, "codes": {}}
_icd11_browser_cache: dict = {
    "key": None,
    "nodes": {},
    "children": {},
    "uri_by_code": {},
}
_icd10_cache: dict = {"key": None, "codes": {}}

SELECTABLE_FILTERS = {"yes": True, "no": False}
# Origin filter values for the ICD-11 state view; "unmapped" has no row (empty origin).
ICD11_ORIGIN_FILTERS = {
    ORIGIN_WHO: ORIGIN_WHO,
    ORIGIN_WHO_RESOLVED: ORIGIN_WHO_RESOLVED,
    ORIGIN_NOT_IN_WHO: ORIGIN_NOT_IN_WHO,
    ORIGIN_DIFFERS: ORIGIN_DIFFERS,
    ORIGIN_NOT_COD: ORIGIN_NOT_COD,
    ORIGIN_DIGITVA: ORIGIN_DIGITVA,
    "unmapped": "",
}
ICD11_ORIGIN_FILTER_LABELS = {
    **ORIGIN_LABELS,
    "unmapped": "Unmapped",
}
POLICY_REVIEW_FILTERS = set(POLICY_STATUS_OPTIONS)
ICD11_CSV_HEADERS = (
    "code", "code_title", "chapter", "block", "selectable", "policy_status",
    "va_code", "va_title", "origin", "sex", "age_group",
)
ICD10_CSV_HEADERS = (
    "classification", "code", "title", "semantic_level", "chapter", "block",
    "selectable", "sex", "age_group", "policy_status", "restriction_note",
    "va_code", "va_title", "origin", "rule",
)


def parse_icd10_ranges(text: str | None) -> list[tuple[str, str, str]]:
    """`(token, start, end)` for each ICD-10 code or range in an annex cell.

    Splits on ';', ',' and whitespace, so the annex's missing separator in
    "K70-K93 L00-L99" (VAs-98) still gives two ranges. Anything that is not
    an ICD-10 code or range (footnote prose) is dropped.
    """
    ranges = []
    for token in re.split(r"[;,\s]+", (text or "").upper()):
        if _ICD10_TOKEN_RE.match(token):
            start, _, end = token.partition("-")
            ranges.append((token, start, end or start))
    return ranges


def icd10_in_range(code: str, start: str, end: str) -> bool:
    """ICD-10 codes are prefix-ordered: `A40-A41` covers A40, A40.x, A41, A41.x;
    `K70.2` covers only itself and its children."""
    return start <= code <= end or code.startswith(end + ".")


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_annex_claims(
    annex_rows: list[dict],
    footnote_rows: list[dict],
    node_labels: dict[str, str],
    catalogue: dict[str, dict],
) -> dict:
    """What the annex says, keyed by bucket node code.

    Annex causes are matched to the scheme's nodes as the ICD-11 generator
    does: by slug (VAs-01.02 -> vas_01_02), else by title (the annex prints
    "VAs-09.0" for Ruptured uterus, node vas_09_08). Returns
    `{"icd10": [(node, token, start, end)], "road": [(start, end)],
    "road_node", "other_transport_node", "icd11": {code: {node: (size, token)}}}`.
    """
    nodes_by_label = {label.strip().lower(): code for code, label in node_labels.items()}
    icd10: list[tuple[str, str, str, str]] = []
    icd11: dict[str, dict[str, tuple[int, str]]] = {}
    node_for_va: dict[str, str] = {}
    sorted_codes = sorted(catalogue)
    for row in annex_rows:
        va_code = row["va_code"].strip()
        node = _slugify(va_code, fallback_prefix="")
        if node not in node_labels:
            node = nodes_by_label.get(row["va_title"].strip().lower())
        if node is None:
            continue
        node_for_va[va_code] = node
        for token, start, end in parse_icd10_ranges(row["icd10_codes"]):
            icd10.append((node, token, start, end))
        ranges, _malformed = parse_icd11_ranges(row["icd11_codes"])
        for token, start, end in ranges:
            covered, _past_end = expand_range(start, end, sorted_codes, catalogue)
            for code in covered:
                current = icd11.setdefault(code, {}).get(node)
                if current is None or len(covered) < current[0]:
                    icd11[code][node] = (len(covered), token)

    # Footnote f is WHO's road-traffic code list, but its tail ("V90-V99;
    # Y85.9") is water/air/other transport and its sequelae, which the scheme
    # buckets as Other transport, as WHO's own ICD-11 PA split does. Only the
    # land transport codes (V01-V89) and Y85.0 count as road traffic.
    footnote_f = next((r["text"] for r in footnote_rows if r["footnote"].strip() == "f"), "")
    road = [
        (start, end) for token, start, end in parse_icd10_ranges(footnote_f)
        if start < "V90" or token == "Y85.0"
    ]
    return {
        "icd10": icd10,
        "road": road,
        "road_node": node_for_va.get(ROAD_TRAFFIC),
        "other_transport_node": node_for_va.get(OTHER_TRANSPORT),
        "icd11": icd11,
    }


def icd10_claims(code: str, annex: dict) -> dict[str, tuple[int | None, str]]:
    """`{node: (None, token)}` for every annex cause that claims an ICD-10 code.

    The transport causes print no ICD-10 range: a V01-V99 or Y85 code is road
    traffic when footnote f lists it and other transport otherwise.
    """
    code = code.upper()
    if code[:1] == "V" or code[:3] == "Y85":
        is_road = any(icd10_in_range(code, start, end) for start, end in annex["road"])
        node = annex["road_node"] if is_road else annex["other_transport_node"]
        return {node: (None, "footnote f")} if node else {}
    claims: dict[str, tuple[int | None, str]] = {}
    for node, token, start, end in annex["icd10"]:
        if icd10_in_range(code, start, end):
            claims.setdefault(node, (None, token))
    return claims


def _review_reason(mapping_note: str) -> str:
    """Plain-language explanation for known reviewed mapping decisions."""
    note = mapping_note or ""
    lower = note.lower()
    decision = re.search(r"owner decision ([^ ]+) \(\d{4}-\d{2}-\d{2}\):", note, re.IGNORECASE)
    number = decision.group(1).lower() if decision else ""

    if number == "5b":
        if "no usable single-bucket crosswalk suggestion" in lower:
            return (
                "Never selectable — WHO's cause list does not include it. "
                "Mapped to Unknown only so no record can go unreported."
            )
        equivalent = re.search(r"crosswalk\s+(.+?)\s+suggests\b", note, re.IGNORECASE)
        if equivalent:
            return f"Not in WHO's list; follows its ICD-10 equivalent {equivalent.group(1).strip()}"
    elif number == "5a":
        topic = note.split(":", 1)[1].strip() if ":" in note else ""
        topic = re.sub(r",\s*in no annex range\s*$", "", topic, flags=re.IGNORECASE)
        if topic:
            return f"Not in WHO's list; placed by clinical review ({topic})"
    elif number == "4":
        return "WHO's range has a typo here; read as intended"
    elif number == "9":
        return "Time of fetal death unknown; counted as Macerated stillbirth, like ICD-10 P95"
    elif number == "10":
        if "heart failure" in lower:
            return "Heart failure counts as Acute cardiac disease in ICD-10 and ICD-11"
        equivalent = re.search(r"mirrors ICD-10 ([A-Z]\d{2}(?:\.\d+)?) override", note, re.IGNORECASE)
        if equivalent:
            return f"Reported the same way as its ICD-10 equivalent {equivalent.group(1).upper()}"
    elif number == "11":
        return (
            "Viral infections of the brain and spinal cord count as "
            "Meningitis/encephalitis, as in ICD-11"
        )
    elif number == "12":
        return (
            "Injured boarding or alighting a vehicle counts as Road traffic, "
            "as in WHO's ICD-10 to ICD-11 table"
        )
    elif number in {"16", "17"}:
        return "Traffic not stated; counted as road traffic, following WHO's ICD-10 rule"

    if "carried forward" in lower and "icd-10" in lower:
        return "Kept from DigitVA's earlier ICD-10 mapping for older records"
    return ""


def _review_tooltip(mapping_note: str) -> str:
    """Expose only the decision number and date, never the internal audit note."""
    match = re.search(
        r"owner decision ([^ ]+) \((\d{4}-\d{2}-\d{2})\)",
        mapping_note or "",
        re.IGNORECASE,
    )
    if not match:
        return ""
    return f"Expert review decision {match.group(1)} ({match.group(2)})"


def _mapping_reason(origin: str, mapping_note: str) -> str:
    reason = _review_reason(mapping_note)
    if reason:
        return reason
    if origin == ORIGIN_DIFFERS:
        return "WHO lists this code for another cause; expert review chose this cause."
    if origin == ORIGIN_NOT_IN_WHO:
        return "Not in WHO's list; placed after expert review."
    if origin == ORIGIN_NOT_COD:
        return (
            "Never selectable — WHO's cause list does not include it. "
            "Mapped to Unknown only so no record can go unreported."
        )
    return ""


def _resolution_rule(
    code: str,
    node: str,
    claims: dict,
    match_type: str | None,
    mapping_note: str = "",
) -> str:
    """Plain-language explanation for a code claimed by multiple WHO causes."""
    code = code.upper()
    if match_type in {"owner_decision", "owner_fallback"}:
        reviewed_reason = _review_reason(mapping_note)
        if reviewed_reason:
            return reviewed_reason
    if match_type == "split" and code.startswith("PA"):
        return "Traffic events count as road traffic, others as other transport"
    if code.startswith("PJ2"):
        return "Maltreatment by others counts as Assault"
    size, token = claims[node]
    others = [claim for other, claim in claims.items() if other != node]
    if all(other_token == token for _, other_token in others):
        return "WHO lists it for two causes and the code cannot tell them apart"
    if "-" not in token and all("-" in other_token for _, other_token in others):
        return "WHO names this code directly for this cause"
    if size is None:
        # ICD-10 claims carry no code count: narrower means inside every other range.
        start, _, end = token.partition("-")
        end = end or start

        def inside(other_token: str) -> bool:
            other_start, _, other_end = other_token.partition("-")
            other_end = other_end or other_start
            return other_token != token and other_start <= start and icd10_in_range(end, other_start, other_end)

        narrowest = all(inside(other_token) for _, other_token in others)
    else:
        narrowest = all(other_size is not None and size < other_size for other_size, _ in others)
    if narrowest:
        return "WHO's more specific range"
    return "WHO lists this code for overlapping causes; this cause was selected after expert review."


def derive_origin(
    code: str,
    node: str,
    claims: dict,
    match_type: str | None = None,
    mapping_note: str = "",
) -> tuple[str, str]:
    """`(origin, public reason)` of one row, given the annex claims on its code."""
    if node in claims:
        if len(claims) == 1:
            return ORIGIN_WHO, "WHO lists this code for this cause."
        return ORIGIN_WHO_RESOLVED, _resolution_rule(code, node, claims, match_type, mapping_note)

    reviewed_reason = _review_reason(mapping_note)
    if (
        match_type == "owner_fallback"
        and "owner decision 5b" in (mapping_note or "").lower()
        and "no usable single-bucket crosswalk suggestion" in (mapping_note or "").lower()
    ):
        return ORIGIN_NOT_COD, reviewed_reason or _mapping_reason(ORIGIN_NOT_COD, mapping_note)
    origin = ORIGIN_DIFFERS if claims else ORIGIN_NOT_IN_WHO
    return origin, _mapping_reason(origin, mapping_note)


def _cache_key(scheme_code: str, annex_path: Path, footnotes_path: Path, release: str):
    """Changes whenever a row or node is added, removed or edited, the scheme
    version moves, an ICD-10 catalogue row (title, chapter or block) is added
    or edited, an ICD-11 catalogue row of the release is added or edited, or
    an annex file changes. One aggregate query."""
    node_updated = (
        sa.select(sa.func.max(MasCodBucketNode.updated_at))
        .where(MasCodBucketNode.scheme_id == MasCodBucketScheme.scheme_id)
        .scalar_subquery()
    )
    icd10_count = sa.select(sa.func.count()).select_from(MasIcd1020192).scalar_subquery()
    icd10_updated = sa.select(sa.func.max(MasIcd1020192.updated_at)).scalar_subquery()
    icd11_count = (
        sa.select(sa.func.count())
        .select_from(MasIcd11Mms)
        .where(MasIcd11Mms.release == release)
        .scalar_subquery()
    )
    icd11_updated = (
        sa.select(sa.func.max(MasIcd11Mms.updated_at))
        .where(MasIcd11Mms.release == release)
        .scalar_subquery()
    )
    row = db.session.execute(
        sa.select(
            MasCodBucketScheme.scheme_id,
            MasCodBucketScheme.mapping_version,
            sa.func.count(MapIcdCodBucket.mapping_id),
            sa.func.max(MapIcdCodBucket.updated_at),
            node_updated,
            icd10_count,
            icd10_updated,
            icd11_count,
            icd11_updated,
        )
        .outerjoin(MapIcdCodBucket, MapIcdCodBucket.scheme_id == MasCodBucketScheme.scheme_id)
        .where(MasCodBucketScheme.scheme_code == scheme_code)
        .group_by(MasCodBucketScheme.scheme_id)
    ).first()
    return (
        scheme_code, release, tuple(row) if row else None,
        annex_path.stat().st_mtime_ns, footnotes_path.stat().st_mtime_ns,
    )


def _build_rows(scheme_code: str, annex_path: Path, footnotes_path: Path, release: str) -> list[dict]:
    node_labels = dict(
        db.session.execute(
            sa.select(MasCodBucketNode.node_code, MasCodBucketNode.node_label)
            .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MasCodBucketNode.scheme_id)
            .where(
                MasCodBucketScheme.scheme_code == scheme_code,
                MasCodBucketNode.node_type == NODE_TYPE_FIELD,
                MasCodBucketNode.node_code.like("vas\\_%", escape="\\"),
            )
        ).all()
    )
    catalogue = load_catalogue(release)
    annex = build_annex_claims(_read_csv(annex_path), _read_csv(footnotes_path), node_labels, catalogue)

    mappings = db.session.execute(
        sa.select(
            MapIcdCodBucket.icd_classification,
            MapIcdCodBucket.icd_code,
            MapIcdCodBucket.match_type,
            MapIcdCodBucket.mapping_note,
            MasCodBucketNode.node_code,
            MasCodBucketNode.node_label,
            MasIcd1020192.title.label("icd10_title"),
            MasIcd1020192.chapter_code,
            MasIcd1020192.chapter_title,
            MasIcd1020192.block_code,
            MasIcd1020192.block_title,
        )
        .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MapIcdCodBucket.scheme_id)
        .join(MasCodBucketNode, MasCodBucketNode.node_id == MapIcdCodBucket.node_id)
        .outerjoin(
            MasIcd1020192,
            sa.and_(
                MapIcdCodBucket.icd_classification == ICD_CLASSIFICATION_ICD10,
                MasIcd1020192.code == sa.func.upper(MapIcdCodBucket.icd_code),
            ),
        )
        .where(MasCodBucketScheme.scheme_code == scheme_code, MapIcdCodBucket.is_active.is_(True))
        .order_by(MapIcdCodBucket.icd_classification, MapIcdCodBucket.icd_code)
    ).all()

    rows = []
    for m in mappings:
        code = m.icd_code.upper()
        if m.icd_classification == ICD_CLASSIFICATION_ICD10:
            claims = icd10_claims(code, annex)
            title = m.icd10_title or ""
        else:
            claims = annex["icd11"].get(code, {})
            title = (catalogue.get(code) or {}).get("title", "")
        origin, rule = derive_origin(code, m.node_code, claims, m.match_type, m.mapping_note or "")
        va_code = va_code_for_node(m.node_code)
        row = {
            "classification": m.icd_classification,
            "code": m.icd_code,
            "code_title": title,
            "va_code": va_code,
            "va_title": m.node_label,
            "origin": origin,
            "rule": rule,
            "also_claimed_by": "; ".join(
                sorted(va_code_for_node(node) for node in claims if node != m.node_code)
            ),
            "note": m.mapping_note or "",
            "origin_tooltip": _review_tooltip(m.mapping_note or ""),
        }
        row["_search"] = " ".join((m.icd_code, title, va_code, m.node_label)).lower()
        if m.icd_classification == ICD_CLASSIFICATION_ICD10:
            # Hierarchy for the compare view; ICD-11 rows get theirs from
            # get_icd11_catalogue(). Underscored keys never reach the CSV.
            row["_chapter"] = (m.chapter_code or "", m.chapter_title or "")
            row["_block"] = (m.block_code or "", m.block_title or "")
        rows.append(row)
    return rows


def get_public_mappings(
    scheme_code: str | None = None,
    annex_path: Path | None = None,
    footnotes_path: Path | None = None,
    release: str | None = None,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """All derived rows (cached) and the `(va_code, va_title)` filter options.

    Defaults are read at call time so tests can point them elsewhere.
    """
    scheme_code = scheme_code or SCHEME_CODE
    annex_path = annex_path or ANNEX_PATH
    footnotes_path = footnotes_path or FOOTNOTES_PATH
    release = release or ICD11_RELEASE
    key = _cache_key(scheme_code, annex_path, footnotes_path, release)
    if _cache["key"] != key:
        rows = _build_rows(scheme_code, annex_path, footnotes_path, release) if key[2] else []
        va_causes = sorted({(r["va_code"], r["va_title"]) for r in rows if r["va_code"]})
        _cache.update(key=key, rows=rows, va_causes=va_causes)
    return _cache["rows"], _cache["va_causes"]


def filter_mappings(
    rows: list[dict],
    *,
    q: str = "",
    classification: str = "",
    origin: str = "",
    va_code: str = "",
) -> list[dict]:
    """Rows matching every given filter; `q` is a case-insensitive substring of
    code, code title, VA code or VA title. Empty values do not filter."""
    q = q.lower()
    return [
        row for row in rows
        if (not classification or row["classification"] == classification)
        and (
            not origin
            or (row["origin"] in ORIGIN_DIGITVA_GROUP if origin == ORIGIN_DIGITVA else row["origin"] == origin)
        )
        and (not va_code or row["va_code"] == va_code)
        and (not q or q in row["_search"])
    ]


def csv_cell(value: str) -> str:
    """Neutralise spreadsheet formulas in a CSV cell (notes are admin-written)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value



def get_icd11_catalogue(release: str | None = None) -> dict[str, dict]:
    """ICD-11 categories in the generator's scope, with hierarchy and coding policy.

    Scope is `load_catalogue`'s: active, coded, outside chapter X. Chapter X's
    extension codes are never bucketed and none is selectable. Returns
    `{code: {"title", "chapter": (no, title), "block": (block_id, title),
    "selectable", "policy_status", "_search"}}` in WHO order. The block is the
    outermost block (depth 1), the level an ICD-10 block sits at. Built from
    the table the admin ICD-11 browser reads, cached per process, and rebuilt
    when any row of the release is added or edited (one aggregate query per call).
    """
    release = release or ICD11_RELEASE
    key = (release, *db.session.execute(
        sa.select(sa.func.count(MasIcd11Mms.id), sa.func.max(MasIcd11Mms.updated_at))
        .where(MasIcd11Mms.release == release)
    ).one())
    if _icd11_cache["key"] != key:
        _icd11_cache.update(key=key, codes=_build_icd11_catalogue(release))
    return _icd11_cache["codes"]


def _build_icd11_catalogue(release: str) -> dict[str, dict]:
    rows = db.session.execute(
        sa.select(
            MasIcd11Mms.linearization_uri,
            MasIcd11Mms.parent_linearization_uri,
            MasIcd11Mms.class_kind,
            MasIcd11Mms.chapter_no,
            MasIcd11Mms.block_id,
            MasIcd11Mms.code,
            MasIcd11Mms.title,
            MasIcd11Mms.is_coding_selectable,
            MasIcd11Mms.sex_selectable,
            MasIcd11Mms.age_group_selectable,
            MasIcd11Mms.restriction_note,
            MasIcd11Mms.policy_status,
        )
        .where(MasIcd11Mms.release == release, MasIcd11Mms.is_active.is_(True))
        .order_by(MasIcd11Mms.sort_order)
    ).all()
    by_uri = {row.linearization_uri: row for row in rows}
    chapter_titles = {row.chapter_no: row.title for row in rows if row.class_kind == "chapter"}
    outer_block: dict[str, tuple[str, str]] = {}

    def block_of(uri: str) -> tuple[str, str]:
        # Walk up to a known ancestor, then back down: the first block met
        # from the top is the outermost one. Memoised, so each row is walked once.
        chain = []
        while uri in by_uri and uri not in outer_block:
            chain.append(uri)
            uri = by_uri[uri].parent_linearization_uri
        found = outer_block.get(uri, ("", ""))
        for step in reversed(chain):
            row = by_uri[step]
            if not found[1] and row.class_kind == "block":
                found = (row.block_id or "", row.title)
            outer_block[step] = found
        return found

    catalogue = {}
    for row in rows:
        if row.class_kind != "category" or not row.code or row.chapter_no == "X":
            continue
        chapter = (row.chapter_no or "", chapter_titles.get(row.chapter_no, ""))
        block = block_of(row.linearization_uri)
        catalogue[row.code] = {
            "title": row.title,
            "chapter": chapter,
            "block": block,
            "selectable": bool(row.is_coding_selectable),
            "sex_selectable": row.sex_selectable or "",
            "age_group_selectable": row.age_group_selectable or "",
            "restriction_note": row.restriction_note or "",
            "policy_status": row.policy_status,
            "_search": " ".join((row.code, row.title, chapter[1], block[1])).lower(),
        }
    return catalogue


def get_icd11_browser_hierarchy(release: str | None = None) -> dict:
    """Active public hierarchy nodes and URI relationships outside chapter X."""
    release = release or ICD11_RELEASE
    key = (release, *db.session.execute(
        sa.select(sa.func.count(MasIcd11Mms.id), sa.func.max(MasIcd11Mms.updated_at))
        .where(MasIcd11Mms.release == release)
    ).one())
    if _icd11_browser_cache["key"] != key:
        rows = db.session.execute(
            sa.select(
                MasIcd11Mms.linearization_uri,
                MasIcd11Mms.parent_linearization_uri,
                MasIcd11Mms.class_kind,
                MasIcd11Mms.code,
                MasIcd11Mms.title,
                MasIcd11Mms.chapter_no,
                MasIcd11Mms.block_id,
                MasIcd11Mms.is_residual,
                MasIcd11Mms.is_leaf,
                MasIcd11Mms.coding_note,
                MasIcd11Mms.is_coding_selectable,
                MasIcd11Mms.sex_selectable,
                MasIcd11Mms.age_group_selectable,
                MasIcd11Mms.policy_status,
                MasIcd11Mms.restriction_note,
                MasIcd11Mms.sort_order,
            )
            .where(
                MasIcd11Mms.release == release,
                MasIcd11Mms.is_active.is_(True),
                sa.or_(MasIcd11Mms.chapter_no.is_(None), MasIcd11Mms.chapter_no != "X"),
            )
            .order_by(MasIcd11Mms.sort_order, MasIcd11Mms.linearization_uri)
        ).mappings().all()
        nodes = {
            row["linearization_uri"]: {
                "linearization_uri": row["linearization_uri"],
                "parent_linearization_uri": row["parent_linearization_uri"],
                "class_kind": row["class_kind"],
                "code": row["code"],
                "title": row["title"],
                "chapter_no": row["chapter_no"],
                "block_id": row["block_id"],
                "is_residual": bool(row["is_residual"]),
                "is_leaf": bool(row["is_leaf"]),
                "coding_note": row["coding_note"] or "",
                "is_coding_selectable": bool(row["is_coding_selectable"]),
                "sex_selectable": row["sex_selectable"] or "",
                "age_group_selectable": row["age_group_selectable"] or "",
                "policy_status": row["policy_status"] or "unreviewed",
                "restriction_note": row["restriction_note"] or "",
            }
            for row in rows
        }
        children = {}
        uri_by_code = {}
        for uri, node in nodes.items():
            children.setdefault(node["parent_linearization_uri"], []).append(uri)
            if node["class_kind"] == "category" and node["code"]:
                uri_by_code[node["code"]] = uri
        _icd11_browser_cache.update(
            key=key, nodes=nodes, children=children, uri_by_code=uri_by_code
        )
    return _icd11_browser_cache


def get_icd10_catalogue() -> dict[str, dict]:
    """Active ICD-10 coding rows with hierarchy and public policy fields."""
    semantic_levels = ("three_character", "detailed_code")
    key = tuple(db.session.execute(
        sa.select(sa.func.count(MasIcd1020192.code), sa.func.max(MasIcd1020192.updated_at))
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level.in_(semantic_levels),
        )
    ).one())
    if _icd10_cache["key"] != key:
        rows = db.session.scalars(
            sa.select(MasIcd1020192)
            .where(
                MasIcd1020192.is_active.is_(True),
                MasIcd1020192.semantic_level.in_(semantic_levels),
            )
            .order_by(MasIcd1020192.sort_order, MasIcd1020192.code)
        ).all()
        codes = {}
        for row in rows:
            chapter = (row.chapter_code or "", row.chapter_title or "")
            block = (row.block_code or "", row.block_title or "")
            codes[row.code] = {
                "title": row.title,
                "semantic_level": row.semantic_level,
                "parent_code": row.parent_code,
                "chapter": chapter,
                "block": block,
                "selectable": bool(row.is_coding_selectable),
                "sex_selectable": row.sex_selectable or "",
                "age_group_selectable": row.age_group_selectable or "",
                "policy_status": row.policy_status or "unreviewed",
                "restriction_note": row.restriction_note or "",
                "_search": " ".join((row.code, row.title, chapter[1], block[1])).lower(),
            }
        _icd10_cache.update(key=key, codes=codes)
    return _icd10_cache["codes"]


def filter_icd11_catalogue(
    catalogue: dict[str, dict],
    rows: list[dict] = (),
    *,
    q: str = "",
    selectable: str = "",
    origin: str = "",
    policy_status: str = "",
    sex_filter: str = "",
    age_filter: str = "",
) -> list[str]:
    """Codes matching every given filter, in WHO order. `q` is a case-insensitive
    substring of code, title, chapter or block title; `selectable` is a key of
    SELECTABLE_FILTERS, `origin` a key of ICD11_ORIGIN_FILTERS and
    `policy_status` a value in POLICY_REVIEW_FILTERS; each empty string means
    'all'. `origin` needs `rows` (the mapping rows) to know each code's mapped
    origin; omit it when not filtering by origin."""
    q = q.lower()
    wanted_selectable = SELECTABLE_FILTERS.get(selectable)
    wanted_origin = ICD11_ORIGIN_FILTERS.get(origin)
    mapped = _mapped_icd11(rows) if origin else {}
    def origin_matches(code: str) -> bool:
        actual = mapped.get(code.upper(), {}).get("origin", "")
        if origin == ORIGIN_DIGITVA:
            return actual in ORIGIN_DIGITVA_GROUP
        return actual == wanted_origin

    return [
        code for code, entry in catalogue.items()
        if (wanted_selectable is None or entry["selectable"] is wanted_selectable)
        and (not q or q in entry["_search"])
        and (not policy_status or entry["policy_status"] == policy_status)
        and (not sex_filter or entry["sex_selectable"] == sex_filter)
        and (not age_filter or entry["age_group_selectable"] == age_filter)
        and (not origin or origin_matches(code))
    ]


def filter_icd10_catalogue(
    catalogue: dict[str, dict],
    rows: list[dict] = (),
    *,
    q: str = "",
    selectable: str = "",
    origin: str = "",
    policy_status: str = "",
    sex_filter: str = "",
    age_filter: str = "",
) -> list[str]:
    """ICD-10 catalogue codes matching search, coding, policy and origin filters."""
    q = q.lower()
    wanted_selectable = SELECTABLE_FILTERS.get(selectable)
    wanted_origin = "" if origin == "unmapped" else origin
    mapped = _mapped_icd10(rows) if origin else {}

    def origin_matches(code: str) -> bool:
        actual = mapped.get(code.upper(), {}).get("origin", "")
        if origin == ORIGIN_DIGITVA:
            return actual in ORIGIN_DIGITVA_GROUP
        return actual == wanted_origin

    return [
        code for code, entry in catalogue.items()
        if (wanted_selectable is None or entry["selectable"] is wanted_selectable)
        and (not q or q in entry["_search"])
        and (not policy_status or entry["policy_status"] == policy_status)
        and (not sex_filter or entry["sex_selectable"] == sex_filter)
        and (not age_filter or entry["age_group_selectable"] == age_filter)
        and (not origin or origin_matches(code))
    ]


def block_aligned_pages(codes: list[str], catalogue: dict[str, dict], per_page: int) -> list[list[str]]:
    """Split `codes` (in catalogue/WHO order) into pages, filling each with
    whole blocks up to `per_page` before starting the next page. A block
    larger than `per_page` still gets a page of its own rather than being
    split, so a block never straddles two pages. Codes with no block are
    grouped by chapter instead. Returns `[]` for an empty `codes`."""
    pages: list[list[str]] = []
    current: list[str] = []
    current_group = None
    for code in codes:
        entry = catalogue[code]
        group = (entry["chapter"][0], entry["block"][0])
        if group != current_group and len(current) >= per_page:
            pages.append(current)
            current = []
        current_group = group
        current.append(code)
    if current:
        pages.append(current)
    return pages


def icd11_block_pages(codes: list[str], catalogue: dict[str, dict], per_page: int) -> list[list[str]]:
    """Backward-compatible name for the ICD-11 block paging helper."""
    return block_aligned_pages(codes, catalogue, per_page)


def _mapped_icd11(rows: list[dict]) -> dict[str, dict]:
    return {row["code"].upper(): row for row in rows if row["classification"] == ICD_CLASSIFICATION_ICD11}


def _mapped_icd10(rows: list[dict]) -> dict[str, dict]:
    return {row["code"].upper(): row for row in rows if row["classification"] == ICD_CLASSIFICATION_ICD10}


def count_unmapped_icd11(catalogue: dict[str, dict], rows: list[dict]) -> int:
    """Catalogue codes that no active row maps."""
    mapped = _mapped_icd11(rows)
    return sum(1 for code in catalogue if code.upper() not in mapped)


def count_unmapped_icd10(catalogue: dict[str, dict], rows: list[dict]) -> int:
    """ICD-10 catalogue codes that have no active row in the selected scheme."""
    mapped = _mapped_icd10(rows)
    return sum(1 for code in catalogue if code.upper() not in mapped)


def icd11_code_states(codes: list[str], catalogue: dict[str, dict], rows: list[dict]) -> list[dict]:
    """The current state of each code: its coding policy and, when an active
    row maps it, the VA cause and origin; unmapped codes get empty ones."""
    mapped = _mapped_icd11(rows)
    states = []
    for code in codes:
        entry = catalogue[code]
        row = mapped.get(code.upper(), {})
        states.append({
            "code": code,
            "code_title": entry["title"],
            "chapter": entry["chapter"],
            "block": entry["block"],
            "selectable": entry["selectable"],
            "sex": entry["sex_selectable"],
            "age_group": entry["age_group_selectable"],
            "policy_status": entry["policy_status"],
            "va_code": row.get("va_code", ""),
            "va_title": row.get("va_title", ""),
            "origin": row.get("origin", ""),
            "rule": row.get("rule", ""),
            "note": row.get("note", ""),
        })
    return states


def icd10_code_states(codes: list[str], catalogue: dict[str, dict], rows: list[dict]) -> list[dict]:
    """Current coding and VA-mapping state for each ICD-10 catalogue code."""
    mapped = _mapped_icd10(rows)
    states = []
    for code in codes:
        entry = catalogue[code]
        mapping = mapped.get(code.upper(), {})
        states.append({
            **entry,
            "code": code,
            "va_code": mapping.get("va_code", ""),
            "va_title": mapping.get("va_title", ""),
            "origin": mapping.get("origin", ""),
            "rule": mapping.get("rule", ""),
            "note": mapping.get("note", ""),
            "also_claimed_by": mapping.get("also_claimed_by", ""),
        })
    return states


def icd11_state_csv_row(state: dict) -> list[str]:
    """One ICD11_CSV_HEADERS row; hierarchy flattened to titles."""
    values = {
        **state,
        "chapter": " ".join(part for part in state["chapter"] if part),
        "block": state["block"][1],
        "selectable": "yes" if state["selectable"] else "no",
    }
    return [csv_cell(values[column] or "") for column in ICD11_CSV_HEADERS]


def icd10_state_csv_row(state: dict) -> list[str]:
    """Public ICD-10 CSV row; internal mapping notes are deliberately omitted."""
    values = {
        "classification": CLASSIFICATION_LABELS[ICD_CLASSIFICATION_ICD10],
        **state,
        "chapter": " ".join(part for part in state["chapter"] if part),
        "block": " ".join(part for part in state["block"] if part),
        "selectable": "yes" if state["selectable"] else "no",
        "origin": state.get("origin", "") or "unmapped",
        "sex": state.get("sex", ""),
        "age_group": state.get("age_group", ""),
    }
    return [csv_cell(str(values.get(column, "") or "")) for column in ICD10_CSV_HEADERS]


def public_data_version() -> str:
    """A short digest of the mapping and ICD-11 cache keys, current after
    get_public_mappings() and get_icd11_catalogue() have run in this request.
    Changes whenever either cache would rebuild."""
    return hashlib.sha256(
        repr((_cache["key"], _icd11_cache["key"], ICD11_CSV_HEADERS)).encode()
    ).hexdigest()[:16]


def cached_icd11_state_csv(root: str, selectable: str, make_states) -> str | None:
    """Path of the ICD-11 state CSV for one `selectable` variant (no search),
    written to `root` on first use from `make_states()` (called only then).

    The file name carries public_data_version(), so a mapping or catalogue edit
    gives a new file; older files of the variant are removed when it is written.
    Written to a temp file in `root` and moved into place with os.replace, so
    concurrent workers never read a partial file. The bytes equal the live CSV
    (same csv.writer dialect, UTF-8). Returns None when `root` is not
    writable, and the caller streams live instead. Only public data is written.
    """
    prefix = f"icd11_states_{selectable or 'all'}_"
    path = os.path.join(root, f"{prefix}{public_data_version()}.csv")
    if os.path.exists(path):
        return path
    try:
        os.makedirs(root, exist_ok=True)
        handle, tmp_path = tempfile.mkstemp(dir=root, prefix=".tmp_", suffix=".csv")
        try:
            with os.fdopen(handle, "w", newline="", encoding="utf-8") as out:
                writer = csv.writer(out)
                writer.writerow(ICD11_CSV_HEADERS)
                writer.writerows(icd11_state_csv_row(state) for state in make_states())
            os.replace(tmp_path, path)
        except BaseException:
            _remove_quietly(tmp_path)
            raise
    except OSError:
        log.warning("ICD-11 state CSV cache not writable at %s; streaming live", root, exc_info=True)
        return None
    for name in os.listdir(root):
        if name.startswith(prefix) and name.endswith(".csv") and os.path.join(root, name) != path:
            _remove_quietly(os.path.join(root, name))
    return path


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _origin_cell(row: dict) -> dict | str:
    if not row.get("origin"):
        return {"badge": "Unmapped", "tone": "secondary", "note": "No VA cause is assigned yet.", "title": ""}
    note = row.get("rule") or ""
    if not note and row["origin"] == ORIGIN_WHO:
        note = "WHO lists this code for this cause."
    elif not note and row["origin"] == ORIGIN_WHO_RESOLVED:
        note = "WHO lists this code for overlapping causes; this cause was selected after expert review."
    elif not note and row["origin"] in ORIGIN_DIGITVA_GROUP:
        note = _mapping_reason(row["origin"], row.get("note", ""))
    if row.get("also_claimed_by"):
        note = "; ".join(filter(None, (note, "WHO also lists: " + row["also_claimed_by"])))
    return {
        "badge": ORIGIN_LABELS[row["origin"]],
        "tone": ORIGIN_TONES[row["origin"]],
        "note": note,
        "title": _review_tooltip(row.get("note", "")),
    }


def public_origin_display(row: dict) -> dict:
    """Safe badge and explanation fields for a public code-detail view."""
    value = _origin_cell(row)
    if isinstance(value, str):
        return {"badge": value, "tone": "secondary", "note": "", "title": ""}
    return value


def tree_nodes(leaves: list[tuple[tuple[str, str], tuple[str, str], str, str, dict]]) -> list[dict]:
    """Flat tree-table nodes (static/js/tree_table.js) grouping leaves by chapter, then block.

    Each leaf is `(chapter, block, code, title, cells)`, chapter and block
    being `(key, label)`; a leaf with no block sits directly under its
    chapter. Group nodes are emitted on first sight, so leaf order is kept.
    """
    nodes, seen = [], set()
    for chapter, block, code, title, cells in leaves:
        chapter_id = "c:" + chapter[0]
        if chapter_id not in seen:
            seen.add(chapter_id)
            nodes.append({
                "id": chapter_id, "parent_id": None, "expanded": True,
                "title": chapter[1] or "Not in the catalogue",
            })
        parent_id = chapter_id
        if block[1]:
            parent_id = "b:" + chapter[0] + ":" + (block[0] or block[1])
            if parent_id not in seen:
                seen.add(parent_id)
                nodes.append({
                    "id": parent_id, "parent_id": chapter_id, "expanded": True,
                    "title": block[1],
                })
        nodes.append({"id": code, "parent_id": parent_id, "title": f"{code} {title}".strip(), "cells": cells})
    return nodes


def _chapter(key: str, title: str) -> tuple[str, str]:
    return (key, f"Chapter {key}: {title}") if key else ("", "")


def compare_trees(rows: list[dict], va_code: str, catalogue: dict[str, dict]) -> dict[str, list[dict]]:
    """ICD-10 and ICD-11 tree nodes for the codes mapped to one VA cause.

    ICD-10 rows keep their code order (chapters follow it); ICD-11 rows follow
    WHO's catalogue order. A code missing from its catalogue is grouped under
    "Not in the catalogue" rather than dropped.
    """
    icd10 = [
        (
            _chapter(*row["_chapter"]),
            (row["_block"][0], " ".join(part for part in row["_block"] if part)),
            row["code"], row["code_title"], {"origin": _origin_cell(row)},
        )
        for row in rows
        if row["va_code"] == va_code and row["classification"] == ICD_CLASSIFICATION_ICD10
    ]
    order = {code: index for index, code in enumerate(catalogue)}
    icd11_rows = sorted(
        (row for row in rows if row["va_code"] == va_code and row["classification"] == ICD_CLASSIFICATION_ICD11),
        key=lambda row: order.get(row["code"], len(order)),
    )
    no_entry = {"chapter": ("", ""), "block": ("", "")}
    icd11 = []
    for row in icd11_rows:
        entry = catalogue.get(row["code"], no_entry)
        icd11.append((
            _chapter(*entry["chapter"]), entry["block"],
            row["code"], row["code_title"], {"origin": _origin_cell(row)},
        ))
    return {"icd10": tree_nodes(icd10), "icd11": tree_nodes(icd11)}


def icd11_state_nodes(states: list[dict]) -> list[dict]:
    """Tree nodes for the ICD-11 state view: one leaf per state, grouped by chapter and block."""
    return tree_nodes([
        (
            _chapter(*state["chapter"]), state["block"], state["code"], state["code_title"],
            {
                "va_cause": " ".join(part for part in (state["va_code"], state["va_title"]) if part),
                "origin": _origin_cell(state),
                "selectable": "Selectable" if state["selectable"] else "Not selectable",
                "policy_status": state["policy_status"].capitalize(),
            },
        )
        for state in states
    ])


def icd10_state_nodes(
    states: list[dict], catalogue: dict[str, dict], rows: list[dict]
) -> list[dict]:
    """Tree-table leaves plus any code ancestors needed for their paths."""
    state_by_code = {state["code"]: state for state in states}
    included = set(state_by_code)
    for code in tuple(included):
        current = catalogue.get(code, {}).get("parent_code")
        while current and current not in included:
            included.add(current)
            current = catalogue.get(current, {}).get("parent_code")
    ordered_codes = [code for code in catalogue if code in included]
    complete_states = [
        state_by_code.get(code) or icd10_code_states([code], catalogue, rows)[0]
        for code in ordered_codes
    ]
    nodes = []
    seen = set()
    for state in complete_states:
        chapter = _chapter(*state["chapter"])
        chapter_id = "c:" + chapter[0]
        if chapter_id not in seen:
            seen.add(chapter_id)
            nodes.append({
                "id": chapter_id,
                "parent_id": None,
                "expanded": True,
                "title": chapter[1] or "Not in the catalogue",
            })
        parent_id = chapter_id
        block = state["block"]
        if block[1]:
            parent_id = "b:" + chapter[0] + ":" + (block[0] or block[1])
            if parent_id not in seen:
                seen.add(parent_id)
                nodes.append({"id": parent_id, "parent_id": chapter_id, "expanded": True, "title": block[1]})
        if state["semantic_level"] == "detailed_code" and state.get("parent_code"):
            parent_id = state["parent_code"]
        cells = {
            "coding": "Selectable" if state["selectable"] else "Not selectable",
            "sex": (state["sex_selectable"] or "—").replace("_", " ").title(),
            "age_group": (state["age_group_selectable"] or "—").replace("_", " ").title(),
            "policy_status": state["policy_status"].capitalize(),
            "restriction_note": state["restriction_note"],
            "va_cause": " ".join(part for part in (state["va_code"], state["va_title"]) if part),
            "origin": _origin_cell(state),
        }
        nodes.append({
            "id": state["code"],
            "parent_id": parent_id,
            "title": f"{state['code']} {state['title']}".strip(),
            "cells": cells,
        })
    return nodes
