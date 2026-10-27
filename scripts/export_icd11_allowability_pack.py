"""Export the ICD-11 coding allowability pack that Collect Plus applies offline.

Reads (never writes) the policy columns of ``mas_icd11_mms`` for one release and
writes ``mobile/digitva-collect/assets/icd11-allowability-<release>.json``: every
selectable category, grouped by (sex, age group, restriction note). A code
absent from the pack is not selectable (chapter 22, blocks, residual parents,
admin-disabled rows), so the pack stays small (about 14k codes).

The rules that read it live in mobile/digitva-collect/src/coding/icd11Allowability.ts
and mirror app/services/icd11_mms_service.py (``validate_icd11_mms_coding_value_for_submission``).
``sha256`` is over the compact JSON of ``{"release", "groups"}``; the device records
``<release>+<sha256[:12]>`` in each offline coding's provenance. Regenerate whenever
a migration or an admin edit changes the policy columns; the drift test
tests/services/test_icd11_allowability_pack.py fails until you do.

Run: docker compose exec -T minerva_app_service uv run --no-sync python scripts/export_icd11_allowability_pack.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import sqlalchemy as sa

from app import create_app, db
from app.models import MasIcd11Mms
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE, POLICY_EDITABLE_CLASS_KINDS

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "mobile/digitva-collect/assets"
SCHEMA = 1


def pack_path(release: str) -> Path:
    return ASSETS / f"icd11-allowability-{release}.json"


def groups_digest(release: str, groups: list[dict]) -> str:
    """sha256 of the compact JSON the device recomputes (key order: release, groups)."""
    body = json.dumps({"release": release, "groups": groups}, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_pack(release: str = DEFAULT_ICD11_RELEASE) -> dict:
    """The pack for ``release`` from the current database (needs an app context)."""
    rows = db.session.execute(
        sa.select(
            MasIcd11Mms.code,
            MasIcd11Mms.sex_selectable,
            MasIcd11Mms.age_group_selectable,
            MasIcd11Mms.restriction_note,
        )
        .where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.is_active.is_(True),
            MasIcd11Mms.class_kind.in_(tuple(POLICY_EDITABLE_CLASS_KINDS)),
            MasIcd11Mms.is_coding_selectable.is_(True),
            MasIcd11Mms.code.is_not(None),
        )
    ).all()
    buckets: dict[tuple[str, str, str | None], list[str]] = {}
    for code, sex, age, note in rows:
        # NULL policy columns on a selectable row mean unrestricted, as the server's predicate treats them.
        buckets.setdefault((sex or "both", age or "all", note), []).append(code)
    groups = [
        {"sex": sex, "age": age, "note": note, "codes": sorted(codes)}
        for (sex, age, note), codes in sorted(buckets.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or ""))
    ]
    # A create_all test database has no alembic_version: no revision to record.
    has_revision_table = db.session.scalar(sa.text("SELECT to_regclass('alembic_version') IS NOT NULL"))
    revision = db.session.scalar(sa.text("SELECT version_num FROM alembic_version LIMIT 1")) if has_revision_table else None
    return {
        "schema": SCHEMA,
        "release": release,
        "db_revision": revision,
        "count": len(rows),
        "sha256": groups_digest(release, groups),
        "groups": groups,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        pack = build_pack()
    path = pack_path(pack["release"])
    path.write_text(json.dumps(pack, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path.relative_to(ROOT)}: {pack['count']} codes, {path.stat().st_size} bytes, sha256 {pack['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
