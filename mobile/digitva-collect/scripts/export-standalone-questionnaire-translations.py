#!/usr/bin/env python3
"""Export the existing Hindi questionnaire pack into the standalone APK.

Reads only the translation catalogue through Flask's read-only export command;
it never translates, imports, or changes server data. The owner explicitly
requested Hindi for standalone while its catalogue lifecycle is in_review.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "standalone-questionnaire-translations.json"
LOCALE = "hi"
INSTRUMENT = "WHO_2022_VA"


def flask_command(*args: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "minerva_app_service",
            "uv",
            "run",
            "--no-sync",
            "flask",
            "instrument-translations",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> None:
    status = flask_command("status", "--instrument-code", INSTRUMENT)
    row = next(
        (line.split(maxsplit=5) for line in status.splitlines() if line.startswith(f"{LOCALE} ")),
        None,
    )
    if not row or len(row) < 6:
        raise SystemExit("Hindi is missing from the WHO_2022_VA translation catalogue.")
    _, active, lifecycle, raw_version, raw_coverage, source_document = row
    if lifecycle not in {"in_review", "approved"}:
        raise SystemExit(f"Refusing Hindi catalogue lifecycle {lifecycle!r}.")

    payload = json.loads(flask_command("export", INSTRUMENT, LOCALE))
    if payload.get("instrument_code") != INSTRUMENT or payload.get("locale") != LOCALE:
        raise SystemExit("The translation export returned an unexpected instrument or locale.")
    if payload.get("version") != int(raw_version):
        raise SystemExit("Hindi changed while exporting; run this exporter again.")
    questions = payload.get("questions")
    choices = payload.get("choices")
    if not isinstance(questions, dict) or not isinstance(choices, dict):
        raise SystemExit("The translation export has an unexpected shape.")

    bundle = {
        "instrument_code": INSTRUMENT,
        "locales": {
            LOCALE: {
                "label": "हिन्दी",
                "version": payload["version"],
                "lifecycle_state": lifecycle,
                "active": active == "yes",
                "source_document": source_document.split()[-1],
                "coverage": float(raw_coverage.rstrip("%")) / 100,
                "label_coverage": float(source_document.split()[1].rstrip("%")) / 100,
                "complete": False,
                "translations": payload,
            }
        },
    }
    OUTPUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {OUTPUT.relative_to(ROOT)}: Hindi v{payload['version']}, "
        f"{len(questions)} question entries, {len(choices)} choice entries, "
        f"lifecycle={lifecycle}, active={active} (partial pack)."
    )


if __name__ == "__main__":
    main()
