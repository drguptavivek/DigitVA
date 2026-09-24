"""Public list of WHO_2022_VA_2026 ICD-to-VA-cause mappings with their origin.

Policy: docs/policy/icd10-to-icd11-transition.md section 7. Every active
ICD-10 and ICD-11 row of the scheme is compared with WHO's 2026 annex (the
cause list and its footnote f) at read time; the origin is never stored:

- ``who``: the annex gives the code to the row's VA cause and to no other.
- ``who_resolved``: the annex gives the code to two or more causes, the row's
  among them; DigitVA picked one by a rule (see ``_resolution_rule``).
- ``digitva``: the annex does not give the code to the row's cause (a code in
  no annex range, a bucket that is not a ``vas_*`` VA cause, or an override).

docs/ is not shipped in the image, so the annex files are read from copies in
resource/ (kept equal to the docs copies by a test). The derived table is
built once per process and rebuilt when the scheme's rows, nodes or version
change, or when an annex file changes.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd1020192
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
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEME_CODE = "WHO_2022_VA_2026"
ICD11_RELEASE = DEFAULT_ICD11_RELEASE
ANNEX_FILE_NAME = "who_2022_va_cause_list_icd10_icd11.csv"
ANNEX_PATH = _REPO_ROOT / "resource" / ANNEX_FILE_NAME
FOOTNOTES_PATH = _REPO_ROOT / "resource" / "who_2022_va_cause_list_footnotes.csv"

ORIGIN_WHO = "who"
ORIGIN_WHO_RESOLVED = "who_resolved"
ORIGIN_DIGITVA = "digitva"
ORIGIN_LABELS = {
    ORIGIN_WHO: "WHO",
    ORIGIN_WHO_RESOLVED: "WHO, resolved by DigitVA rule",
    ORIGIN_DIGITVA: "DigitVA decision",
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


def _resolution_rule(code: str, node: str, claims: dict, match_type: str | None) -> str:
    """The DigitVA rule that picked `node` among several annex claims, or ''."""
    code = code.upper()
    if match_type == "split" and code.startswith("PA"):
        return "Transport split: PA0x traffic events to road traffic, PA1x-PA5x to other transport"
    if code.startswith("PJ2"):
        return "Owner decision: maltreatment by others to Assault"
    size, token = claims[node]
    others = [claim for other, claim in claims.items() if other != node]
    if all(other_token == token for _, other_token in others):
        return "WHO lists the same code for more than one cause; DigitVA chose this one"
    if "-" not in token and all("-" in other_token for _, other_token in others):
        return "Specific code beats range"
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
    return "Narrowest range wins" if narrowest else ""


def derive_origin(code: str, node: str, claims: dict, match_type: str | None = None) -> tuple[str, str]:
    """`(origin, rule)` of one row, given the annex claims on its code."""
    if node not in claims:
        return ORIGIN_DIGITVA, ""
    if len(claims) == 1:
        return ORIGIN_WHO, ""
    return ORIGIN_WHO_RESOLVED, _resolution_rule(code, node, claims, match_type)


def _cache_key(scheme_code: str, annex_path: Path, footnotes_path: Path, release: str):
    """Changes whenever a row or node is added, removed or edited, the scheme
    version moves, or an annex file changes. One aggregate query."""
    node_updated = (
        sa.select(sa.func.max(MasCodBucketNode.updated_at))
        .where(MasCodBucketNode.scheme_id == MasCodBucketScheme.scheme_id)
        .scalar_subquery()
    )
    row = db.session.execute(
        sa.select(
            MasCodBucketScheme.scheme_id,
            MasCodBucketScheme.mapping_version,
            sa.func.count(MapIcdCodBucket.mapping_id),
            sa.func.max(MapIcdCodBucket.updated_at),
            node_updated,
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
        origin, rule = derive_origin(code, m.node_code, claims, m.match_type)
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
        }
        row["_search"] = " ".join((m.icd_code, title, va_code, m.node_label)).lower()
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
        and (not origin or row["origin"] == origin)
        and (not va_code or row["va_code"] == va_code)
        and (not q or q in row["_search"])
    ]


def csv_cell(value: str) -> str:
    """Neutralise spreadsheet formulas in a CSV cell (notes are admin-written)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value

