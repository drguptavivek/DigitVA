"""Export the ICD-11 to VA cause bucket lookup for Collect Plus (pack schema 2).

Run in minerva_app_service against the approved reference catalog. This reads
only the ICD-11 hierarchy, the VA scheme/mapping and the VA definition tables.

The phone shows the bucket of the selected ICD-11 code from this file in every
mode, with no network call (docs/policy/va-cause-definitions.md, "VA cause
bucket for the selected ICD-11 code"). Buckets come from
``resolve_who_2026_icd11_buckets``, the CTEs the COD snapshot and the server
lookup use, so the three agree; tests/services/test_export_offline_va_definitions.py
checks it, and that the committed pack equals the database at head.

Pack layout (schema 2):
  buckets      node_code -> {label, section, section_code, va_code}; section and
               section_code are null for a node without a parent; va_code is
               ``VAs-NN.NN`` for a ``vas_*`` node (null otherwise), whether or not
               ``definitions`` holds it.
  definitions  va_code -> {title, definition_html}, active ones that buckets name.
  codes        ICD-11 stem -> node_code, every code the shared helper resolves.
  db_revision  alembic version_num the pack was cut at (null without one); not hashed.

``content_sha256`` is the sha256 (hex) of the UTF-8 bytes of the compact JSON
``json.dumps({"schema", "scheme", "release", "count", "buckets", "definitions",
"codes"}, separators=(",", ":"), ensure_ascii=False)``, keys in that order,
nested keys sorted by code point as written in the file. The app recomputes it
from the parsed file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import sqlalchemy as sa

from app import create_app, db
from app.models.mas_va_cause_definitions import MasVaCauseDefinition
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.submission_analytics_mv import resolve_who_2026_icd11_buckets
from app.services.va_cause_definition_service import VA_DEFINITION_SCHEMES, _va_code_of_node

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "mobile/digitva-collect/assets/va-definitions-WHO_2022_VA_2026.json"
SCHEMA = 2
SCHEME = VA_DEFINITION_SCHEMES["icd11"]
HASHED_FIELDS = ("schema", "scheme", "release", "count", "buckets", "definitions", "codes")


def compact_sha256(value: object) -> str:
    canonical = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_pack() -> dict:
    """The pack from the current database (needs an app context)."""
    buckets: dict[str, dict] = {}
    codes: dict[str, str] = {}
    for code, node_code, label, section_code, section in resolve_who_2026_icd11_buckets():
        # JS orders integer-like keys first, which would break the app's hash.
        if code.isdecimal():
            raise ValueError(f"ICD-11 code {code!r} cannot be a JSON object key in the pack.")
        bucket = {"label": label, "section": section, "section_code": section_code, "va_code": _va_code_of_node(node_code)}
        if buckets.setdefault(node_code, bucket) != bucket:
            raise ValueError(f"Bucket node {node_code!r} resolves to different labels or sections.")
        codes[code] = node_code

    va_codes = {bucket["va_code"] for bucket in buckets.values() if bucket["va_code"]}
    definition_rows = db.session.execute(
        sa.select(
            MasVaCauseDefinition.va_code,
            MasVaCauseDefinition.title,
            MasVaCauseDefinition.definition_html,
        )
        .where(MasVaCauseDefinition.is_active.is_(True), MasVaCauseDefinition.va_code.in_(va_codes))
        .order_by(MasVaCauseDefinition.va_code)
    ).all()

    pack = {
        "schema": SCHEMA,
        "scheme": SCHEME,
        "release": DEFAULT_ICD11_RELEASE,
        "count": len(codes),
        "buckets": dict(sorted(buckets.items())),
        # Sorted here, not by SQL ORDER BY, so the key order (and the hash) never depends on the DB collation.
        "definitions": dict(sorted(
            (va_code, {"title": title, "definition_html": definition_html or ""})
            for va_code, title, definition_html in definition_rows
        )),
        "codes": dict(sorted(codes.items())),
    }
    pack["content_sha256"] = compact_sha256({key: pack[key] for key in HASHED_FIELDS})
    # A create_all test database has no alembic_version: no revision to record.
    has_revision_table = db.session.scalar(sa.text("SELECT to_regclass('alembic_version') IS NOT NULL"))
    pack["db_revision"] = (
        db.session.scalar(sa.text("SELECT version_num FROM alembic_version LIMIT 1")) if has_revision_table else None
    )
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
