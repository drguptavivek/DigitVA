"""Public, read-only view of every DigitVA override layer (digitva-j5n2).

Reads the three override CSVs and compares each row with the live catalogue
or bucket scheme, so anyone can see what DigitVA decided on top of WHO's
releases and whether this server has applied it. No PII; four queries.
"Applied" looks only at active catalogue rows and active mappings: coders
never see inactive ones. A missing or malformed CSV makes only its own
section unavailable (None), never a 500.
Policy: docs/policy/who-2022-icd10-coding-allowability.md and
docs/policy/icd11-cod-bucket-schemes.md.
"""

import csv
import logging

import sqlalchemy as sa

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd1020192
from app.services.cod_bucket_icd11_generator import (
    DECISIONS_PATH,
    LAYER_DIGITVA,
    LAYER_WHO_FIX,
    va_code_for_node,
)
from app.services.cod_bucket_mapping_service import (
    ICD_CLASSIFICATION_ICD10,
    SCHEME_CODE_WHO_2022_VA_2026,
    _who_2022_va_2026_owner_decisions,
)
from app.services.icd10_2019_2_service import _OVERRIDE_FIELDS, read_allowability_overrides

log = logging.getLogger(__name__)
_SECTION_ERRORS = (OSError, ValueError, KeyError)


def _sets(override):
    """Plain-language list of what an allowability row sets."""
    parts = []
    if override["is_coding_selectable"] is not None:
        parts.append("selectable" if override["is_coding_selectable"] else "not selectable")
    if override["sex_selectable"]:
        parts.append(f"sex: {override['sex_selectable']}")
    if override["age_group_selectable"]:
        age = override["age_group_selectable"]
        parts.append("all ages" if age == "all" else f"age: {age}")
    return ", ".join(parts)


def _va_cause(node_code, labels):
    """`VAs-01.07 Label` for a bucket node code."""
    return {"va_code": va_code_for_node(node_code) or node_code, "label": labels.get(node_code, "")}


def _read_section(name, reader):
    """`reader()`, or None when its CSV is missing or malformed (logged without paths)."""
    try:
        return reader()
    except _SECTION_ERRORS as exc:
        log.warning("DigitVA overrides section %s unavailable: %s", name, type(exc).__name__)
        return None


def _read_icd11_rows():
    with open(DECISIONS_PATH, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:  # fail here, not mid-render, on a file missing a column
        for key in ("code", "node_code", "decision", "decided_on", "note"):
            row[key]
    return rows


def build_digitva_overrides():
    """The three layers with titles and applied flags, ready to render."""
    allow = _read_section("allowability", read_allowability_overrides)
    bucket10 = _read_section("icd10_decisions", lambda: list(_who_2022_va_2026_owner_decisions().items()))
    rows11 = _read_section("icd11_decisions", _read_icd11_rows)
    allow_rows, bucket_rows = allow or [], bucket10 or []

    exact = {o["code"] for o in allow_rows if o["match"] == "code"}
    families = {o["code"] for o in allow_rows if o["match"] == "family"}
    bucket_codes = {code for code, _ in bucket_rows}
    catalogue = db.session.execute(
        sa.select(
            MasIcd1020192.code,
            MasIcd1020192.three_character_code,
            MasIcd1020192.title,
            MasIcd1020192.is_active,
            *(getattr(MasIcd1020192, f) for f in _OVERRIDE_FIELDS),
        ).where(
            sa.or_(
                MasIcd1020192.code.in_(exact | bucket_codes | families),
                MasIcd1020192.three_character_code.in_(families),
            )
        )
    ).all()
    by_code = {row.code: row for row in catalogue}
    by_family = {}
    for row in catalogue:
        if row.is_active:
            by_family.setdefault(row.three_character_code, []).append(row)

    groups = {}
    for o in allow_rows:
        if o["match"] == "code":
            targets = [by_code[o["code"]]] if o["code"] in by_code and by_code[o["code"]].is_active else []
        else:
            targets = by_family.get(o["code"], [])
        applied = bool(targets) and all(
            getattr(t, f) == o[f] for t in targets for f in _OVERRIDE_FIELDS if o[f] is not None
        )
        title = by_code[o["code"]].title if o["code"] in by_code else ""
        key = (o["decision"], o["decided_on"], o["bead"], o["note"])
        groups.setdefault(key, []).append({
            "code": o["code"],
            "title": title,
            "match": "whole family" if o["match"] == "family" else "code",
            "sets": _sets(o),
            "applied": applied,
        })
    allowability = [
        {"decision": k[0], "decided_on": k[1], "bead": k[2], "note": k[3], "rows": rows}
        for k, rows in groups.items()
    ]

    scheme_id = db.session.scalar(
        sa.select(MasCodBucketScheme.scheme_id).where(
            MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026
        )
    )
    labels, node_code_by_id, live = {}, {}, {}
    if scheme_id is not None:
        for node in db.session.execute(
            sa.select(MasCodBucketNode.node_id, MasCodBucketNode.node_code, MasCodBucketNode.node_label).where(
                MasCodBucketNode.scheme_id == scheme_id, MasCodBucketNode.age_scope.is_(None)
            )
        ):
            labels[node.node_code] = node.node_label
            node_code_by_id[node.node_id] = node.node_code
        live = {
            code.upper(): node_id
            for code, node_id in db.session.execute(
                sa.select(MapIcdCodBucket.icd_code, MapIcdCodBucket.node_id).where(
                    MapIcdCodBucket.scheme_id == scheme_id,
                    MapIcdCodBucket.icd_classification == ICD_CLASSIFICATION_ICD10,
                    # Matches ux_map_icd_cod_buckets_scheme_class_scope_icd_norm.
                    sa.func.coalesce(MapIcdCodBucket.age_scope, "") == "",
                    MapIcdCodBucket.is_active.is_(True),
                    sa.func.upper(MapIcdCodBucket.icd_code).in_(bucket_codes),
                )
            )
        }
    icd10_decisions = [
        {
            "code": code,
            "title": by_code[code].title if code in by_code else "",
            **_va_cause(d["node_code"], labels),
            "note": d["mapping_note"] or "",
            "applied": node_code_by_id.get(live.get(code)) == d["node_code"],
        }
        for code, d in bucket_rows
    ]

    def icd11(layer):
        return [
            {
                "code": r["code"], **_va_cause(r["node_code"], labels), "decision": r["decision"],
                "decided_on": r["decided_on"], "note": r["note"],
            }
            for r in rows11 or []
            if (r.get("layer") or LAYER_DIGITVA).strip() == layer
        ]

    return {
        "allowability": allowability if allow is not None else None,
        "allowability_count": len(allow_rows),
        "icd10_decisions": icd10_decisions if bucket10 is not None else None,
        "icd11_digitva": icd11(LAYER_DIGITVA) if rows11 is not None else None,
        "icd11_who_fix": icd11(LAYER_WHO_FIX) if rows11 is not None else None,
        "scheme_code": SCHEME_CODE_WHO_2022_VA_2026,
    }
