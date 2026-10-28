#!/usr/bin/env python3
"""Export the canonical SmartVA ICD-10 crosswalk and server WHO labels.

Run inside the app container so the configured WHO ICD API and its cache are available:
    docker compose exec -T minerva_app_service uv run --no-sync python mobile/digitva-collect/scripts/export_smartva_icd11_reference.py

This is a build-time/reference export; it does not initialize the mobile DORIS engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.services.icd11_policy_draft_service import (  # noqa: E402
    CHANGE_LIST_PATH,
    CROSSWALK_PATH,
    TEN_TO_ELEVEN_PATH,
    load_icd10_to_icd11,
)
from app.services.icd11_titles import icd11_alternatives_label  # noqa: E402
from app.services.who_icd_api import DEFAULT_ICD11_RELEASE  # noqa: E402
from app.utils.va_smartva.va_smartva_01_icdcodes import VA_SMARTVA_ICDS  # noqa: E402

OUTPUT = ROOT / "mobile/digitva-collect/src/smartva/va-icd11.json"
SOURCE_FILES = {
    "app/utils/va_smartva/va_smartva_01_icdcodes.py": ROOT / "app/utils/va_smartva/va_smartva_01_icdcodes.py",
    "ten_to_eleven": ROOT / TEN_TO_ELEVEN_PATH,
    "change_list": ROOT / CHANGE_LIST_PATH,
    "crosswalk": ROOT / CROSSWALK_PATH,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate() -> str:
    icd10_codes = sorted({code for table in VA_SMARTVA_ICDS.values() for code in table.values()})
    targets = load_icd10_to_icd11(
        path=str(ROOT / TEN_TO_ELEVEN_PATH),
        change_list_path=str(ROOT / CHANGE_LIST_PATH),
        crosswalk_path=str(ROOT / CROSSWALK_PATH),
    )
    mappings = {code: targets[code] for code in icd10_codes if targets.get(code)}
    expressions = sorted(set(mappings.values()))

    app = create_app()
    with app.app_context():
        labels = {expression: icd11_alternatives_label(expression) for expression in expressions}

    content = {
        "source": {
            "release": DEFAULT_ICD11_RELEASE,
            "files_sha256": {name: sha256(path) for name, path in SOURCE_FILES.items()},
        },
        "by_icd10": {
            code: {"icd11": expression, "icd11_label": labels.get(expression)}
            for code, expression in sorted(mappings.items())
        },
    }
    return json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the committed export without rewriting it")
    args = parser.parse_args()
    expected = generate()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            parser.error("generated reference is stale; rerun this exporter in minerva_app_service")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
