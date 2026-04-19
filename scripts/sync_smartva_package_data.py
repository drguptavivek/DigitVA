#!/usr/bin/env python3
"""Copy non-Python SmartVA package assets into the installed package."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SMARTVA_SOURCE_ROOT = REPO_ROOT / "vendor" / "smartva-analyze" / "src" / "smartva"
ASSET_DIRS = ("data", "res")
ASSET_SUFFIXES = {
    ".csv",
    ".json",
    ".html",
    ".ico",
    ".png",
    ".docx",
    ".xml",
    ".thmx",
}


def _installed_smartva_root() -> Path:
    spec = importlib.util.find_spec("smartva")
    if spec is None or spec.origin is None:
        raise RuntimeError("smartva is not installed in the current environment")
    return Path(spec.origin).resolve().parent


def _copy_asset_tree(source_dir: Path, target_dir: Path) -> int:
    copied = 0
    if not source_dir.exists():
        return copied

    for source_path in source_dir.rglob("*"):
        if not source_path.is_file():
            continue
        if source_path.suffix.lower() not in ASSET_SUFFIXES:
            continue

        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied += 1

    return copied


def main() -> int:
    if not SMARTVA_SOURCE_ROOT.exists():
        raise RuntimeError(
            f"SmartVA vendor source not found at {SMARTVA_SOURCE_ROOT}"
        )

    installed_root = _installed_smartva_root()
    copied = 0
    for asset_dir in ASSET_DIRS:
        copied += _copy_asset_tree(
            SMARTVA_SOURCE_ROOT / asset_dir,
            installed_root / asset_dir,
        )

    print(f"Synced {copied} SmartVA asset file(s) into {installed_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"SmartVA asset sync failed: {exc}", file=sys.stderr)
        raise
