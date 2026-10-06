#!/usr/bin/env python3
"""Rebuild the shipped instrument JSON from the curated V2.0 reference workbook.

Run inside the app container (needs the project's pandas/openpyxl):

    docker compose exec -T minerva_app_service uv run --no-sync python \\
        tooling/who-va-2022/build-instrument-from-xlsform.py

Why a script instead of hand-editing the JSON
----------------------------------------------
A raw conversion of the workbook is not the whole story: the shipped
instrument has always carried a handful of deliberate departures from
whatever workbook it was built from, most already documented in
vendor/who-va-2022/README.md's "Deliberate departures from the WHO XLSForm"
section. Keeping every one of them in ``resource/who_va_2022_deviations.json``
(with the reason for each) means a rebuild reapplies them instead of a
hand-edited JSON silently losing them the next time someone regenerates it,
and the same file drives the ODK form.

``digitva-13x`` (docs/policy/va-form-project-configuration.md, "The curated
reference form moves to V2.0, English only") adds two more: ``Id10304_a``
keeps V1.1's relevance (V2.0's own rule is unsatisfiable -- see
docs/kb/WHO_VA_2022_Docs/id10304a-v2-relevance-defect.md) and ``Id10230``
keeps agegroup ``C_A`` (V2.0 narrows it to adult-only ``a``, which the owner
rejected; see the policy doc for the reasoning).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.services.xlsform_instrument_builder import build_instrument_from_xlsform  # noqa: E402

WORKBOOK = REPO_ROOT / "vendor/who-va-2022/2022whova_xls_form_for_odk_multilingual.xlsx"
OUTPUT = REPO_ROOT / "vendor/who-va-2022/src/generated/who-va-2022.instrument.json"

# The deliberate departures from the workbook live in one data file that the
# ODK form generator (app/services/xlsform_service.py) applies too, so web and
# ODK cannot drift: question name -> field overrides applied after conversion,
# and section name -> field overrides.
_DEVIATIONS = json.loads((REPO_ROOT / "resource/who_va_2022_deviations.json").read_text(encoding="utf-8"))
DEVIATIONS = _DEVIATIONS["questions"]
SECTION_DEVIATIONS = _DEVIATIONS["sections"]


def _apply(target: dict, overrides: dict) -> None:
    """Set each override field, or drop it when the override value is None --
    matching how the builder omits a field entirely rather than nulling it."""
    for field, value in overrides.items():
        if value is None:
            target.pop(field, None)
        else:
            target[field] = value


def main() -> None:
    instrument = build_instrument_from_xlsform(WORKBOOK, locales={"en"})

    questions_by_name = {question["name"]: question for question in instrument["questions"]}
    for name, overrides in DEVIATIONS.items():
        question = questions_by_name[name]
        _apply(question, overrides)
        # A "choices" override must keep validation.choiceValues in step --
        # the builder's own invariant (see build_instrument_from_xlsform).
        if "choices" in overrides and question.get("choices") is not None:
            question["validation"]["choiceValues"] = [
                choice["value"] for choice in question["choices"]
            ]

    sections_by_name = {section["name"]: section for section in instrument["sections"]}
    for name, overrides in SECTION_DEVIATIONS.items():
        _apply(sections_by_name[name], overrides)

    OUTPUT.write_text(json.dumps(instrument, indent=2, ensure_ascii=False) + "\n")
    print(
        f"wrote {OUTPUT.relative_to(REPO_ROOT)}: "
        f"{len(instrument['questions'])} questions, {len(instrument['sections'])} sections"
    )


if __name__ == "__main__":
    main()
