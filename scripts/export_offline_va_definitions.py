"""Export the active ICD-11 to VA definition lookup for Collect Plus.

Run in minerva_app_service against the approved reference catalog. This reads
only ICD-11 hierarchy, VA scheme/mapping, and VA definition tables.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import sqlalchemy as sa

from app import create_app, db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd11Mms
from app.models.mas_va_cause_definitions import MasVaCauseDefinition
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.va_cause_definition_service import VA_DEFINITION_SCHEMES

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "mobile/digitva-collect/assets/va-definitions-WHO_2022_VA_2026.json"
SCHEMA = 1
SCHEME = VA_DEFINITION_SCHEMES["icd11"]


def compact_sha256(value: object) -> str:
    canonical = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_codes(hierarchy_rows, direct: dict[str, str]) -> dict[str, str]:
    """Expand direct mappings to WHO descendants using nearest ancestor first."""
    by_uri = {uri: (code.upper(), parent_uri) for code, uri, parent_uri in hierarchy_rows}
    codes: dict[str, str] = dict(direct)
    for code, _uri, parent_uri in hierarchy_rows:
        candidate, parent = code.upper(), parent_uri
        seen: set[str] = set()
        while candidate not in seen:
            seen.add(candidate)
            if candidate in direct:
                codes[code.upper()] = direct[candidate]
                break
            if not parent or parent not in by_uri:
                break
            candidate, parent = by_uri[parent]
    return codes


def build_pack() -> dict:
    """Build definitions and nearest active VA ancestor lookup in bulk."""
    mapping_rows = db.session.execute(
        sa.select(
            sa.func.upper(MapIcdCodBucket.icd_code),
            MasCodBucketNode.node_code,
            MasVaCauseDefinition.va_code,
            MasVaCauseDefinition.title,
            MasVaCauseDefinition.definition_html,
            MapIcdCodBucket.age_scope,
        )
        .join(MasCodBucketScheme, MasCodBucketScheme.scheme_id == MapIcdCodBucket.scheme_id)
        .join(MasCodBucketNode, MasCodBucketNode.node_id == MapIcdCodBucket.node_id)
        .join(
            MasVaCauseDefinition,
            MasVaCauseDefinition.va_code
            == (sa.literal("VAs-") + sa.func.replace(sa.func.substr(MasCodBucketNode.node_code, 5), "_", ".")),
        )
        .where(
            MasCodBucketScheme.scheme_code == SCHEME,
            MasCodBucketScheme.is_active.is_(True),
            MapIcdCodBucket.icd_classification == "icd11",
            MapIcdCodBucket.is_active.is_(True),
            MasCodBucketNode.is_active.is_(True),
            MasCodBucketNode.node_code.like("vas\\_%", escape="\\"),
            MasVaCauseDefinition.is_active.is_(True),
        )
        .order_by(sa.func.upper(MapIcdCodBucket.icd_code), MapIcdCodBucket.age_scope.nullsfirst(), MasVaCauseDefinition.va_code)
    ).all()

    definition_rows = db.session.execute(
        sa.select(
            MasVaCauseDefinition.va_code,
            MasVaCauseDefinition.title,
            MasVaCauseDefinition.definition_html,
        )
        .where(MasVaCauseDefinition.is_active.is_(True))
        .order_by(MasVaCauseDefinition.va_code)
    ).all()
    definitions = {
        va_code: {"title": title, "definition_html": definition_html or ""}
        for va_code, title, definition_html in definition_rows
    }
    direct: dict[str, str] = {}
    for code, _node_code, va_code, _title, _definition_html, _age_scope in mapping_rows:
        # The server ignores age_scope; keep a deterministic row if reference
        # data has parallel age-scoped copies of one mapping.
        direct.setdefault(code, va_code)

    hierarchy_rows = db.session.execute(
        sa.select(MasIcd11Mms.code, MasIcd11Mms.linearization_uri, MasIcd11Mms.parent_linearization_uri)
        .where(MasIcd11Mms.release == DEFAULT_ICD11_RELEASE, MasIcd11Mms.code.is_not(None))
        .order_by(MasIcd11Mms.code)
    ).all()
    # Exact mapping rows stay queryable even if a WHO hierarchy row is absent.
    codes = resolve_codes(hierarchy_rows, direct)

    ordered_sources = {
        "mappings": [list(row) for row in mapping_rows],
        "hierarchy": [list(row) for row in hierarchy_rows],
        "definitions": [[code, *value.values()] for code, value in sorted(definitions.items())],
    }
    pack = {
        "schema": SCHEMA,
        "scheme": SCHEME,
        "release": DEFAULT_ICD11_RELEASE,
        "source_digest": compact_sha256(ordered_sources),
        "count": len(codes),
        "definitions": dict(sorted(definitions.items())),
        "codes": dict(sorted(codes.items())),
    }
    content_fields = ("schema", "scheme", "release", "source_digest", "count", "definitions", "codes")
    pack["content_sha256"] = compact_sha256({key: pack[key] for key in content_fields})
    return pack


def main() -> int:
    app = create_app()
    with app.app_context():
        pack = build_pack()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(pack, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {pack['count']} mapped ICD-11 codes, {OUTPUT.stat().st_size} bytes, {pack['content_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
