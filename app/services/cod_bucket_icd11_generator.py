"""Generate a scheme's native ICD-11 bucket table from the WHO VA cause list.

Policy: docs/policy/icd11-cod-bucket-schemes.md ("Native method", owner
decisions 2026-09-21). Each cause's ICD-11 ranges are expanded against the
active catalogue categories of one release; a code claimed by several causes
goes to the most specific range (the one covering the fewest codes); the two
ranges the cause list shares between causes are split per code; every result
is cross-checked against the owner's curated ICD-10 scheme through WHO's
11-to-10 crosswalk. Nothing here writes to the database unless `apply` is
called, and `apply` replaces only the scheme's ICD-11 rows.
"""

from __future__ import annotations

import bisect
import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa
from openpyxl import load_workbook

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd11Mms
from app.services.cod_bucket_mapping_service import (
    ICD_CLASSIFICATION_ICD10,
    ICD_CLASSIFICATION_ICD11,
    NODE_TYPE_FIELD,
    SCHEME_CODE_WHO_2022_VA,
    _slugify,
)

log = logging.getLogger(__name__)

CAUSE_LIST_PATH = (
    "docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv"
)
CROSSWALK_PATH = (
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd11-icd10-mapping-tables-2025-01-base-2026-09-16/11To10MapToOneCategory.txt"
)
CHANGE_LIST_PATH = (
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd11-mms-changes-2026-01-vs-2025-01-2026-09-16/changes_MMS_2026-01_2025-01-main.xlsx"
)
DEFAULT_REPORT_DIR = (
    "docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd11-native-2026-09-21"
)
CURATED_ICD10_SCHEME_CODE = SCHEME_CODE_WHO_2022_VA

MATCH_TYPE_RANGE = "range"
MATCH_TYPE_SPLIT = "split"
SOURCE_SHEET = Path(CAUSE_LIST_PATH).name

ROAD_TRAFFIC = "VAs-12.01"
OTHER_TRANSPORT = "VAs-12.02"
ASSAULT = "VAs-12.09"
OTHER_EXTERNAL = "VAs-12.99"


@dataclass
class Icd11Generation:
    """Everything one generator run decided, for the report and for `apply`."""

    scheme_code: str
    release: str
    mappings: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    unmapped: list[dict] = field(default_factory=list)
    cause_counts: dict[str, int] = field(default_factory=dict)
    cause_titles: dict[str, str] = field(default_factory=dict)
    catalogue_size: int = 0

    def review_count(self, review_type: str) -> int:
        return sum(1 for row in self.review if row["review_type"] == review_type)


def parse_icd11_ranges(text: str | None) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Split a cause-list cell into `(token, start, end)` ranges.

    Separators are ';' and ','; a token is one code or `A-B`. Returns the
    ranges and the tokens that are not a code or a two-ended range (a
    malformed token is reported, never guessed at).
    """
    ranges: list[tuple[str, str, str]] = []
    bad_tokens: list[str] = []
    for raw in (text or "").replace(",", ";").split(";"):
        token = raw.strip().upper()
        if not token:
            continue
        parts = [part.strip() for part in token.split("-")]
        if len(parts) == 1 and parts[0]:
            ranges.append((token, parts[0], parts[0]))
        elif len(parts) == 2 and all(parts):
            ranges.append((token, parts[0], parts[1]))
        else:
            bad_tokens.append(token)
    return ranges, bad_tokens


def load_catalogue(release: str) -> dict[str, dict]:
    """Active coded categories of `release` outside chapter X (extensions).

    Returns `{code: {"title", "parent"}}`, where `parent` is the parent
    category's code along the catalogue's parent chain (None under a block).
    Outside chapter X, plain string order of codes is WHO's order (0-9, then
    A-Z) and a child's code extends its parent's; checked on 2026-01.
    """
    rows = db.session.execute(
        sa.select(
            MasIcd11Mms.code,
            MasIcd11Mms.title,
            MasIcd11Mms.linearization_uri,
            MasIcd11Mms.parent_linearization_uri,
        ).where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.is_active.is_(True),
            MasIcd11Mms.class_kind == "category",
            MasIcd11Mms.code.is_not(None),
            MasIcd11Mms.chapter_no != "X",
        )
    ).all()
    code_by_uri = {row.linearization_uri: row.code for row in rows}
    return {
        row.code: {"title": row.title, "parent": code_by_uri.get(row.parent_linearization_uri)}
        for row in rows
    }


def expand_range(start: str, end: str, sorted_codes: list[str], catalogue: dict) -> tuple[list[str], list[str]]:
    """Codes a range covers: lexically `start`..`end` plus their descendants.

    Descendance follows the catalogue parent chain. Returns `(covered,
    past_end)`, `past_end` being codes that sort after `end` and descend from
    a covered ancestor of `end` rather than from `end` itself (e.g. `2B56.3`
    for `2B00-2B56.2`, which covers `2B56`), so the report can show where a
    range reaches beyond what it wrote.
    """
    covered: list[str] = []
    covered_set: set[str] = set()
    past_end: list[str] = []
    for code in sorted_codes[bisect.bisect_left(sorted_codes, start):]:
        if code <= end:
            covered.append(code)
            covered_set.add(code)
            continue
        if catalogue[code]["parent"] not in covered_set:
            # Descendants sort directly after their ancestor, so the first
            # code past `end` that is not one ends the range.
            break
        covered.append(code)
        covered_set.add(code)
        ancestor = catalogue[code]["parent"]
        while ancestor is not None and ancestor != end:
            ancestor = catalogue[ancestor]["parent"]
        if ancestor is None:
            past_end.append(code)
    return covered, past_end


def _load_cause_list(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            {**row, "row_number": row_number}
            for row_number, row in enumerate(csv.DictReader(handle), start=2)
        ]


def _load_crosswalk(path: str, change_list_path: str) -> tuple[dict[str, str], dict[str, str]]:
    """WHO 11To10 `{icd11_code: icd10_target}` and `{2026-01 code: 2025-01 code}`."""
    crosswalk: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) > 4 and row[1].strip() and row[4].strip():
                crosswalk[row[1].strip()] = row[4].strip()

    moved_from: dict[str, str] = {}
    workbook = load_workbook(change_list_path, read_only=True)
    for row in workbook.active.iter_rows(min_row=2, values_only=True):
        if len(row) > 6 and row[6] == "MovedTo" and row[4] and "->" in row[4]:
            old_code, new_code = (part.strip() for part in row[4].split("->"))
            moved_from[new_code] = old_code
    workbook.close()
    return crosswalk, moved_from


def _icd10_buckets(scheme_code: str) -> dict[str, str]:
    """`{icd10_code: node_code}` of a scheme's ICD-10 rows (all-ages rows)."""
    rows = db.session.execute(
        sa.select(MapIcdCodBucket.icd_code, MasCodBucketNode.node_code)
        .join(MasCodBucketNode, MasCodBucketNode.node_id == MapIcdCodBucket.node_id)
        .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MapIcdCodBucket.scheme_id)
        .where(
            MasCodBucketScheme.scheme_code == scheme_code,
            MapIcdCodBucket.icd_classification == ICD_CLASSIFICATION_ICD10,
            MapIcdCodBucket.is_active.is_(True),
            MapIcdCodBucket.age_scope.is_(None),
        )
    ).all()
    return {row.icd_code.upper(): row.node_code for row in rows}


def _icd10_bucket_for(target: str | None, buckets: dict[str, str]) -> str:
    """Bucket of an ICD-10 crosswalk target: a code, its 3-character parent,
    or a block whose codes all share one bucket. '' when none; 'multiple:...'
    when a block spans several buckets (never guessed)."""
    if not target:
        return ""
    if "-" in target:
        first, last = (part.strip()[:3] for part in target.split("-", 1))
        found = sorted({node for code, node in buckets.items() if first <= code[:3] <= last})
        if len(found) > 1:
            return "multiple:" + "|".join(found)
        return found[0] if found else ""
    return buckets.get(target) or buckets.get(target[:3]) or ""


def _pa_split(code: str, title: str) -> tuple[str, bool, str]:
    """Road traffic (PA0x) versus other transport (PA1x-PA5x), with a title check."""
    lowered = title.lower()
    if code.startswith("PA0"):
        fits = "traffic" in lowered and "nontraffic" not in lowered
        return ROAD_TRAFFIC, fits, "PA0x land transport traffic event"
    fits = "traffic" not in lowered or (
        "nontraffic" in lowered and "unknown whether" not in lowered
    )
    return OTHER_TRANSPORT, fits, "PA1x-PA5x nontraffic, rail, water, air or other transport"


def generate_icd11_buckets(
    *,
    scheme_code: str,
    release: str,
    cause_list_path: str = CAUSE_LIST_PATH,
    crosswalk_path: str = CROSSWALK_PATH,
    change_list_path: str = CHANGE_LIST_PATH,
    curated_scheme_code: str = CURATED_ICD10_SCHEME_CODE,
) -> Icd11Generation:
    """Decide the scheme's ICD-11 table without writing anything.

    Raises LookupError for an unknown scheme and ValueError when the release
    has no catalogue rows.
    """
    scheme = db.session.scalar(
        sa.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == scheme_code)
    )
    if scheme is None:
        raise LookupError(f"Unknown COD bucket scheme: {scheme_code}")
    catalogue = load_catalogue(release)
    if not catalogue:
        raise ValueError(f"No active ICD-11 catalogue categories for release {release}.")
    sorted_codes = sorted(catalogue)
    result = Icd11Generation(scheme_code=scheme_code, release=release, catalogue_size=len(catalogue))

    field_nodes = list(
        db.session.scalars(
            sa.select(MasCodBucketNode).where(
                MasCodBucketNode.scheme_id == scheme.scheme_id,
                MasCodBucketNode.node_type == NODE_TYPE_FIELD,
            )
        )
    )

    def review(review_type: str, **values) -> None:
        result.review.append({"review_type": review_type, **values})

    # 1. Expand every cause's ranges; remember each cause's narrowest cover.
    causes: dict[str, dict] = {}
    claims: dict[str, dict[str, tuple[int, str]]] = {}
    for row in _load_cause_list(cause_list_path):
        va_code = row["va_code"].strip()
        va_title = row["va_title"].strip()
        nodes = [node for node in field_nodes if node.node_code == _slugify(va_code, fallback_prefix="")]
        if not nodes:
            nodes = [node for node in field_nodes if node.node_label.strip().lower() == va_title.lower()]
            if nodes:
                review("node_matched_by_label", va_code=va_code, detail=f"{va_title} -> {nodes[0].node_code}")
        if not nodes:
            review("cause_without_node", va_code=va_code, detail=f"{va_title}: codes stay unmapped")
        causes[va_code] = {"title": va_title, "nodes": nodes, "row_number": row["row_number"]}
        result.cause_counts[va_code] = 0
        result.cause_titles[va_code] = va_title

        ranges, bad_tokens = parse_icd11_ranges(row["icd11_codes"])
        for token in bad_tokens:
            review("range_issue", va_code=va_code, token=token, detail="not a code or a two-ended range; skipped")
        for token, start, end in ranges:
            missing = [code for code in {start, end} if code not in catalogue]
            covered, past_end = expand_range(start, end, sorted_codes, catalogue)
            if missing:
                review(
                    "range_issue", va_code=va_code, token=token,
                    detail=f"endpoint not in catalogue: {', '.join(sorted(missing))}; covers {len(covered)} codes lexically",
                )
            if past_end:
                review(
                    "range_past_end", va_code=va_code, token=token,
                    detail=f"covers descendants after its end: {' '.join(past_end)}",
                )
            for code in covered:
                current = claims.setdefault(code, {}).get(va_code)
                if current is None or len(covered) < current[0]:
                    claims[code][va_code] = (len(covered), token)

    # 2. One cause per code: most specific wins; shared ranges split per code.
    crosswalk, moved_from = _load_crosswalk(crosswalk_path, change_list_path)
    curated = _icd10_buckets(curated_scheme_code)
    own_icd10 = _icd10_buckets(scheme_code)
    decided: dict[str, tuple[str, str, str, int]] = {}
    for code in sorted(claims):
        by_cause = claims[code]
        narrowest = min(size for size, _ in by_cause.values())
        winners = sorted(va for va, (size, _) in by_cause.items() if size == narrowest)
        competing = "; ".join(f"{va} {tok} ({size})" for va, (size, tok) in sorted(by_cause.items()))
        title = catalogue[code]["title"]
        if len(winners) == 1:
            va_code = winners[0]
            decided[code] = (va_code, MATCH_TYPE_RANGE, by_cause[va_code][1], narrowest)
            continue
        if set(winners) == {ROAD_TRAFFIC, OTHER_TRANSPORT}:
            va_code, fits, rule = _pa_split(code, title)
            decided[code] = (va_code, MATCH_TYPE_SPLIT, by_cause[va_code][1], narrowest)
            review(
                "pa_split", code=code, title=title, va_code=va_code, token=rule,
                detail="title fits" if fits else "TITLE DOES NOT FIT the traffic/nontraffic rule",
            )
            continue
        if set(winners) == {ASSAULT, OTHER_EXTERNAL} and code.startswith("PJ2"):
            proposal = ASSAULT if "maltreatment" in title.lower() else ""
            if proposal:
                decided[code] = (proposal, MATCH_TYPE_SPLIT, by_cause[proposal][1], narrowest)
            review(
                "pj2x_owner_decision", code=code, title=title, va_code=proposal,
                token=competing, detail="proposed: maltreatment by others -> Assault" if proposal else "no proposal",
            )
            continue
        review("tie", code=code, title=title, va_code="|".join(winners), token=competing, detail="not mapped")

    # 3. Rows per resolved node, with the crosswalk cross-check.
    for code, (va_code, match_type, token, size) in decided.items():
        title = catalogue[code]["title"]
        icd10 = crosswalk.get(code) or crosswalk.get(moved_from.get(code, ""), "")
        curated_bucket = _icd10_bucket_for(icd10, curated)
        own_bucket = _icd10_bucket_for(icd10, own_icd10)
        nodes = causes[va_code]["nodes"]
        for node in nodes:
            result.mappings.append(
                {
                    "code": code,
                    "title": title,
                    "va_code": va_code,
                    "node": node,
                    "node_code": node.node_code,
                    "match_type": match_type,
                    "token": token,
                    "range_size": size,
                    "row_number": causes[va_code]["row_number"],
                    "icd10_crosswalk": icd10,
                    "curated_icd10_bucket": curated_bucket,
                    "own_icd10_bucket": own_bucket,
                }
            )
            if (curated_bucket and curated_bucket != node.node_code) or (
                own_bucket and own_bucket != node.node_code
            ):
                review(
                    "crosswalk_disagreement", code=code, title=title, va_code=va_code,
                    token=icd10,
                    detail=(
                        f"generated {node.node_code}; {curated_scheme_code} {curated_bucket or '-'}; "
                        f"{scheme_code} ICD-10 {own_bucket or '-'}"
                    ),
                )
        if nodes:
            result.cause_counts[va_code] = result.cause_counts.get(va_code, 0) + 1

    # 4. Every catalogue code without a row, with the crosswalk's suggestion.
    for code in sorted_codes:
        if code in decided and causes[decided[code][0]]["nodes"]:
            continue
        reason = "no_node" if code in decided else ("tie" if code in claims else "no_range")
        icd10 = crosswalk.get(code) or crosswalk.get(moved_from.get(code, ""), "")
        result.unmapped.append(
            {
                "code": code,
                "title": catalogue[code]["title"],
                "reason": reason,
                "icd10_crosswalk": icd10,
                "suggested_bucket": _icd10_bucket_for(icd10, curated),
            }
        )
    return result


def write_icd11_generation_report(result: Icd11Generation, report_dir: str | Path) -> list[Path]:
    """Write the mappings, review and unmapped CSVs plus a README summary."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    def write_csv(name: str, headers: list[str], rows: list[dict]) -> Path:
        path = report_dir / name
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    written = [
        write_csv(
            "icd11_generated_mappings.csv",
            ["code", "title", "va_code", "node_code", "match_type", "token", "range_size",
             "icd10_crosswalk", "curated_icd10_bucket", "own_icd10_bucket"],
            result.mappings,
        ),
        write_csv(
            "icd11_review.csv",
            ["review_type", "code", "title", "va_code", "token", "detail"],
            result.review,
        ),
        write_csv(
            "icd11_unmapped_with_suggestion.csv",
            ["code", "title", "reason", "icd10_crosswalk", "suggested_bucket"],
            result.unmapped,
        ),
    ]

    review_types = sorted({row["review_type"] for row in result.review})
    unmapped_reasons: dict[str, int] = {}
    for row in result.unmapped:
        unmapped_reasons[row["reason"]] = unmapped_reasons.get(row["reason"], 0) + 1
    lines = [
        "---",
        f"title: WHO 2022 VA native ICD-11 buckets, generator report ({result.scheme_code})",
        "doc_type: reference",
        "status: draft",
        "owner: engineering",
        "last_updated: 2026-09-21",
        "---",
        "",
        f"# WHO 2022 VA native ICD-11 buckets: generator report ({result.scheme_code})",
        "",
        "Written by `flask cod-buckets generate-icd11`. Policy: "
        "`docs/policy/icd11-cod-bucket-schemes.md`. Source: "
        f"`{CAUSE_LIST_PATH}`, catalogue release `{result.release}`, crosswalk "
        f"`{CROSSWALK_PATH}` (2025-01, 2026-01 codes translated through the change list).",
        "",
        "## Totals",
        "",
        f"- Catalogue categories (chapter X excluded): {result.catalogue_size}",
        f"- Generated mappings: {len(result.mappings)} "
        f"(range {sum(1 for r in result.mappings if r['match_type'] == MATCH_TYPE_RANGE)}, "
        f"split {sum(1 for r in result.mappings if r['match_type'] == MATCH_TYPE_SPLIT)})",
        f"- Unmapped: {len(result.unmapped)} "
        + ", ".join(f"{reason} {count}" for reason, count in sorted(unmapped_reasons.items())),
        "",
        "## Review items (`icd11_review.csv`)",
        "",
        *[f"- `{review_type}`: {result.review_count(review_type)}" for review_type in review_types],
        "",
        "## Codes per cause",
        "",
        "| VA code | Cause | Codes |",
        "|---|---|---:|",
        *[
            f"| {va_code} | {result.cause_titles[va_code]} | {count} |"
            for va_code, count in result.cause_counts.items()
        ],
        "",
        "## Notes",
        "",
        "- Stillbirths: ICD-11 splits them (KD3B.1 intrapartum fetal death -> VAs-11.01 "
        "Fresh stillbirth, KD3B.0 -> VAs-11.02 Macerated stillbirth). ICD-10 cannot: P95 "
        "stays with Macerated stillbirth in the ICD-10 rows, so the two classifications "
        "count fresh stillbirths differently.",
        "",
        "## Files",
        "",
        "- `icd11_generated_mappings.csv`: one row per generated mapping, with the "
        "crosswalk ICD-10 target and its bucket in the curated `WHO_2022_VA` scheme and "
        "in this scheme's own ICD-10 rows.",
        "- `icd11_review.csv`: ties (not mapped), PJ2x owner decisions, PA split "
        "verification, crosswalk disagreements, range issues and ranges reaching past "
        "their written end.",
        "- `icd11_unmapped_with_suggestion.csv`: catalogue codes without a mapping, "
        "with the crosswalk's suggested bucket (not applied).",
        "",
    ]
    readme = report_dir / "README.md"
    readme.write_text("\n".join(lines), encoding="utf-8")
    written.append(readme)
    return written


def apply_icd11_generation(result: Icd11Generation) -> MasCodBucketScheme:
    """Replace the scheme's ICD-11 rows with `result` in one transaction.

    ICD-10 rows are untouched. Sets `icd11_method='native'` and bumps
    `mapping_version`. Rolls back and re-raises on any failure.
    """
    scheme = db.session.scalar(
        sa.select(MasCodBucketScheme).where(MasCodBucketScheme.scheme_code == result.scheme_code)
    )
    if scheme is None:
        raise LookupError(f"Unknown COD bucket scheme: {result.scheme_code}")
    try:
        deleted = db.session.execute(
            sa.delete(MapIcdCodBucket).where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id,
                MapIcdCodBucket.icd_classification == ICD_CLASSIFICATION_ICD11,
            )
        ).rowcount
        db.session.add_all(
            MapIcdCodBucket(
                scheme_id=scheme.scheme_id,
                age_scope=row["node"].age_scope,
                icd_classification=ICD_CLASSIFICATION_ICD11,
                icd_code=row["code"],
                node_id=row["node"].node_id,
                source_sheet=SOURCE_SHEET,
                source_row_number=row["row_number"],
                source_category=row["va_code"],
                match_type=row["match_type"],
                mapping_note=f"ICD-11 {result.release} range {row['token']}",
                is_active=True,
            )
            for row in result.mappings
        )
        scheme.icd11_method = "native"
        scheme.mapping_version = (scheme.mapping_version or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info(
        "Generated native ICD-11 buckets for %s (release %s): replaced %s rows with %s; "
        "mapping_version=%s",
        scheme.scheme_code, result.release, deleted, len(result.mappings), scheme.mapping_version,
    )
    return scheme
