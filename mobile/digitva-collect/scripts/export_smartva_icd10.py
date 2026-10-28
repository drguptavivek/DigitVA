#!/usr/bin/env python3
"""Export the canonical server SmartVA cause-to-ICD-10 map for the offline app.

Run from any directory with:
    python mobile/digitva-collect/scripts/export_smartva_icd10.py
Use --check in validation to fail when the committed asset is stale.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "app/utils/va_smartva/va_smartva_01_icdcodes.py"
OUTPUT = ROOT / "mobile/digitva-collect/src/smartva/va-icd10.json"


def export_content() -> str:
    source_bytes = SOURCE.read_bytes()
    module = ast.parse(source_bytes.decode("utf-8"), filename=str(SOURCE))
    mapping = None
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "VA_SMARTVA_ICDS"
            for target in statement.targets
        ):
            mapping = ast.literal_eval(statement.value)
            break
    if not isinstance(mapping, dict):
        raise ValueError(f"VA_SMARTVA_ICDS was not found in {SOURCE}")
    normalized = {str(module_name).lower(): values for module_name, values in mapping.items()}
    if set(normalized) != {"adult", "child", "neonate"}:
        raise ValueError("Expected the adult, child, and neonate SmartVA maps.")
    if any(not isinstance(values, dict) for values in normalized.values()):
        raise ValueError("Each SmartVA module map must be an object.")
    content = {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "by_module": normalized,
    }
    return json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the committed export without rewriting it")
    args = parser.parse_args()
    expected = export_content()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            parser.error(f"generated map is stale; regenerate with {Path(__file__).relative_to(ROOT)}")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
