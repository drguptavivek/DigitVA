#!/usr/bin/env python3
"""Generate synthetic SmartVA device-check goldens from the host Rust C ABI.

Usage from the repository root:
    python3 mobile/digitva-collect/scripts/generate_smartva_engine_check.py
    python3 mobile/digitva-collect/scripts/generate_smartva_engine_check.py --check

If no host library exists yet, build `vendor/smartva-analyze/rust` for this host first.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "tests/fixtures/local_smartva/engine-check-cases.json"
WHO_MAPPING = ROOT / "vendor/smartva-analyze/rust/src/data/who_data.rs"
ICD10_MAP = ROOT / "mobile/digitva-collect/src/smartva/va-icd10.json"
ICD11_MAP = ROOT / "mobile/digitva-collect/src/smartva/va-icd11.json"
OUTPUT = ROOT / "mobile/digitva-collect/src/smartva/engine-check-golden.json"
LIBRARIES = (
    ROOT / "vendor/smartva-analyze/rust/target/release/deps/libsmartva_rust.dylib",
    ROOT / "vendor/smartva-analyze/rust/target/debug/deps/libsmartva_rust.dylib",
    ROOT / "vendor/smartva-analyze/rust/target/release/deps/libsmartva_rust.so",
    ROOT / "vendor/smartva-analyze/rust/target/debug/deps/libsmartva_rust.so",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_library(explicit: str | None) -> tuple[ctypes.CDLL, Path]:
    candidates = [Path(explicit).expanduser()] if explicit else []
    target_dir = os.environ.get("CARGO_TARGET_DIR")
    if target_dir:
        for suffix in ("release", "debug"):
            for name in ("libsmartva_rust.dylib", "libsmartva_rust.so"):
                candidates.append(Path(target_dir) / suffix / "deps" / name)
    candidates.extend(LIBRARIES)
    for candidate in candidates:
        if candidate.is_file():
            return ctypes.CDLL(str(candidate)), candidate
    raise FileNotFoundError(
        "Host libsmartva_rust was not found; build vendor/smartva-analyze/rust "
        "or pass --library /path/to/libsmartva_rust.dylib."
    )


def score(lib: ctypes.CDLL, payload: dict[str, str], options: dict[str, Any]) -> dict[str, Any]:
    lib.smartva_score_json.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.smartva_score_json.restype = ctypes.c_int
    lib.smartva_free_string.argtypes = [ctypes.c_void_p]
    lib.smartva_free_string.restype = None

    result_ptr = ctypes.c_void_p()
    error_ptr = ctypes.c_void_p()
    encoded = json.dumps([payload], separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    country = options["country"].encode("utf-8")
    flags = [int(options[key]) for key in ("hiv", "malaria", "hce", "freetext")]
    code = lib.smartva_score_json(
        encoded,
        country,
        *flags,
        0,
        ctypes.byref(result_ptr),
        ctypes.byref(error_ptr),
    )
    try:
        if code != 0:
            message = ctypes.string_at(error_ptr).decode("utf-8", errors="replace") if error_ptr.value else "engine_error"
            raise RuntimeError(f"Synthetic C ABI scoring failed: {message}")
        if not result_ptr.value:
            raise RuntimeError("Synthetic C ABI returned no result.")
        return json.loads(ctypes.string_at(result_ptr).decode("utf-8"))
    finally:
        if result_ptr.value:
            lib.smartva_free_string(result_ptr)
        if error_ptr.value:
            lib.smartva_free_string(error_ptr)


def nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" or text.lower() == "nan" else text


def projected(
    prediction: dict[str, Any],
    by_module: dict[str, dict[str, str]],
    by_icd10: dict[str, dict[str, str | None]],
) -> dict[str, Any]:
    module = nullable_text(prediction.get("module"))
    icd_map = by_module.get(module or "", {})
    causes = []
    key_symptoms = []
    for rank in (1, 2, 3):
        cause = nullable_text(prediction.get(f"cause{rank}"))
        icd10 = icd_map.get(cause) if cause else None
        icd11 = by_icd10.get(icd10 or "")
        causes.append({
            "rank": rank,
            "cause": cause,
            "icd10": icd10,
            "icd11": icd11.get("icd11") if icd11 else None,
            "icd11_label": icd11.get("icd11_label") if icd11 else None,
            "likelihood": nullable_text(prediction.get(f"likelihood{rank}")),
        })
        key_symptoms.append(nullable_text(prediction.get(f"key_symptom{rank}")))
    all_symptoms = nullable_text(prediction.get("all_symptoms"))
    return {
        "age": nullable_text(prediction.get("age")),
        "gender": nullable_text(prediction.get("sex")),
        "key_symptoms": key_symptoms,
        "causes": causes,
        "symptoms": [item.strip() for item in (all_symptoms or "").split(";") if item.strip()],
        "module": module,
        "cause34": nullable_text(prediction.get("cause34")),
        "icd10": nullable_text(prediction.get("icd10")),
    }


def generate(lib: ctypes.CDLL, library_path: Path) -> dict[str, Any]:
    fixtures = json.loads(CASES.read_text(encoding="utf-8"))
    icd_asset = json.loads(ICD10_MAP.read_text(encoding="utf-8"))
    icd11_asset = json.loads(ICD11_MAP.read_text(encoding="utf-8"))
    by_module = icd_asset["by_module"]
    by_icd10 = icd11_asset["by_icd10"]
    lib.smartva_version.argtypes = []
    lib.smartva_version.restype = ctypes.c_char_p
    engine_version = lib.smartva_version().decode("utf-8")

    cases = []
    for fixture in fixtures["cases"]:
        result = score(lib, fixture["input"], fixtures["options"])
        predictions = result.get("predictions")
        if result.get("total_vas") != 1 or not isinstance(predictions, list) or len(predictions) != 1:
            raise RuntimeError(f"Expected one synthetic prediction for {fixture['id']}.")
        prediction = predictions[0]
        if (not nullable_text(prediction.get("cause34")) or prediction["cause34"] == "Undetermined"
                or not nullable_text(prediction.get("all_symptoms"))
                or not any(nullable_text(prediction.get(f"key_symptom{rank}")) for rank in (1, 2, 3))):
            raise RuntimeError(f"Synthetic fixture {fixture['id']} did not exercise a determined cause and symptoms.")
        cases.append({
            "id": fixture["id"],
            "input": fixture["input"],
            "expected": projected(predictions[0], by_module, by_icd10),
            "all_symptoms": predictions[0].get("all_symptoms"),
        })

    return {
        "schema_version": fixtures["schema_version"],
        "source": {
            "source_mapping": fixtures["source_mapping"],
            "source_mapping_sha256": sha256(WHO_MAPPING),
            "cases_sha256": sha256(CASES),
            "icd10_map_sha256": sha256(ICD10_MAP),
            "icd11_map_sha256": sha256(ICD11_MAP),
            "host_library_sha256": sha256(library_path),
            "engine_version": engine_version,
        },
        "options": fixtures["options"],
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", help="host libsmartva_rust path; defaults to the local Cargo target")
    parser.add_argument("--check", action="store_true", help="check the committed golden without rewriting it")
    args = parser.parse_args()
    lib, library_path = load_library(args.library)
    expected = json.dumps(generate(lib, library_path), ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            parser.error("golden is stale; regenerate with mobile/digitva-collect/scripts/generate_smartva_engine_check.py")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} from {library_path.relative_to(ROOT) if library_path.is_relative_to(ROOT) else library_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
