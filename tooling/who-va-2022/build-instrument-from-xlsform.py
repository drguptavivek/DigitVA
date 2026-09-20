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
section. Baking every one of them into ``DEVIATIONS`` below, next to the
workbook path, means a rebuild reapplies them instead of a hand-edited JSON
silently losing them the next time someone regenerates it.

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

# question name -> field overrides applied after conversion. Each predates
# this script (see vendor/who-va-2022/README.md, "Deliberate departures from
# the WHO XLSForm") except the two named digitva-13x, and none are resolved
# by the move to V2.0 -- the raw V2.0 workbook still carries the same issue
# each one works around.
DEVIATIONS = {
    # The source constraint rejects a valid normal birth-weight combination.
    # `None` drops the key entirely, matching how the builder omits
    # `constraint` for a question that has none.
    "Id10365": {
        "constraint": None,
        "constraintMessage": {},
        "validation": {
            "required": True,
            "dataType": "string",
            "choiceValues": ["yes", "no", "dk", "ref"],
            "constraintMessage": {},
        },
    },
    # Matches the interviewer guidance that 99 means "don't know" and a
    # true 88-hour estimate should be entered as 87 -- a clearer app-supplied
    # message than the workbook's own.
    "Id10382": {
        "constraint": {"source": "(.>=0 and .<=98) or .=99"},
        "constraintMessage": {
            "en": "Enter a whole number of hours from 0 to 98. Use 0 for less than "
            "1 hour; use 23 or 25 when only the less-than or more-than-24-hour "
            "estimate is known; use 88 for refused; and use 99 for don't know. If "
            "the actual duration was 88 hours, enter 87."
        },
        "validation": {
            "required": False,
            "dataType": "number",
            "constraint": {"source": "(.>=0 and .<=98) or .=99"},
            "constraintMessage": {
                "en": "Enter a whole number of hours from 0 to 98. Use 0 for less "
                "than 1 hour; use 23 or 25 when only the less-than or "
                "more-than-24-hour estimate is known; use 88 for refused; and use "
                "99 for don't know. If the actual duration was 88 hours, enter 87."
            },
        },
    },
    # Clearer app-supplied English constraint message than the workbook's own.
    "Id10023_a": {
        "constraintMessage": {
            "en": "Date of death must be on or after the date of birth and cannot be in the future."
        },
        "validation": {
            "required": True,
            "dataType": "date",
            "constraint": {"source": ".>=${Id10021} and . <= today()"},
            "constraintMessage": {
                "en": "Date of death must be on or after the date of birth and "
                "cannot be in the future."
            },
        },
    },
    "Id10023_b": {
        "constraintMessage": {"en": "Date of death cannot be in the future."},
        "validation": {
            "required": True,
            "dataType": "date",
            "constraint": {"source": ". <= today()"},
            "constraintMessage": {"en": "Date of death cannot be in the future."},
        },
    },
    # Shown under consented > injuries_accidents so the mid-form guidance
    # appears with the injury section instead of as a detached
    # completion-screen item.
    "nmh": {"sectionPath": ["consented", "injuries_accidents"]},
    # The app ships English only; the workbook's placeholder "Language 2" /
    # "Language 3" choices must never reach an interviewer (see
    # docs/policy/va-form-project-configuration.md).
    "language": {
        "choices": [{"value": "en", "label": {"en": "English"}, "sourceRow": 3}],
        "validation": {
            "required": True,
            "dataType": "string",
            "choiceValues": ["en"],
            "constraintMessage": {},
        },
    },
    # App-added name validation; the workbook carries none.
    "Id10007": {
        "constraint": {"source": "regex(., '^[A-Za-z ]+$')"},
        "constraintMessage": {"en": "Respondent name can contain letters and spaces only"},
        "validation": {
            "required": False,
            "dataType": "string",
            "constraintMessage": {"en": "Respondent name can contain letters and spaces only"},
            "constraint": {"source": "regex(., '^[A-Za-z ]+$')"},
        },
    },
    "Id10010": {
        "constraint": {"source": "regex(., '^[A-Za-z ]+$')"},
        "constraintMessage": {"en": "Interviewer name can contain letters and spaces only"},
        "validation": {
            "required": True,
            "dataType": "string",
            "constraint": {"source": "regex(., '^[A-Za-z ]+$')"},
            "constraintMessage": {"en": "Interviewer name can contain letters and spaces only"},
        },
    },
    # The package's own curated symptom checklist, narrower than the
    # workbook's select_510/511/512 lists.
    "Id10477": {
        "choices": [
            {
                "value": "Chronic_kidney_disease",
                "label": {"en": "Chronic kidney disease"},
                "sourceRow": 253,
            },
            {"value": "Dialysis", "label": {"en": "Dialysis"}, "sourceRow": 254},
            {"value": "Fever", "label": {"en": "Fever"}, "sourceRow": 255},
            {"value": "Heart_attack", "label": {"en": "Heart attack"}, "sourceRow": 256},
            {"value": "Heart_problem", "label": {"en": "Heart problem"}, "sourceRow": 257},
            {"value": "Jaundice", "label": {"en": "Jaundice"}, "sourceRow": 258},
            {"value": "Liver_failure", "label": {"en": "Liver failure"}, "sourceRow": 259},
            {"value": "Malaria", "label": {"en": "Malaria"}, "sourceRow": 260},
            {"value": "Pneumonia", "label": {"en": "Pneumonia"}, "sourceRow": 261},
            {
                "value": "Renal_kidney_failure",
                "label": {"en": "Renal (kidney) failure"},
                "sourceRow": 262,
            },
            {"value": "Suicide", "label": {"en": "Suicide"}, "sourceRow": 263},
            {
                "value": "None",
                "label": {"en": "None of the above words were mentioned"},
                "sourceRow": 264,
            },
        ],
    },
    "Id10478": {
        "choices": [
            {"value": "abdomen", "label": {"en": "Abdomen"}, "sourceRow": 274},
            {"value": "cancer", "label": {"en": "Cancer"}, "sourceRow": 275},
            {"value": "dehydration", "label": {"en": "Dehydration"}, "sourceRow": 276},
            {"value": "dengue", "label": {"en": "Dengue fever"}, "sourceRow": 277},
            {"value": "diarrhea", "label": {"en": "Diarrhoea"}, "sourceRow": 278},
            {"value": "fever", "label": {"en": "Fever"}, "sourceRow": 279},
            {"value": "heart_problem", "label": {"en": "Heart problems"}, "sourceRow": 280},
            {
                "value": "jaundice",
                "label": {"en": "Jaundice (yellow skin or eyes)"},
                "sourceRow": 281,
            },
            {"value": "pneumonia", "label": {"en": "Pneumonia"}, "sourceRow": 282},
            {"value": "rash", "label": {"en": "Rash"}, "sourceRow": 283},
            {
                "value": "None",
                "label": {"en": "None of the above words were mentioned"},
                "sourceRow": 284,
            },
        ],
    },
    "Id10479": {
        "choices": [
            {"value": "asphyxia", "label": {"en": "Asphyxia"}, "sourceRow": 266},
            {"value": "incubator", "label": {"en": "Incubator"}, "sourceRow": 267},
            {"value": "lung_problem", "label": {"en": "Lung problem"}, "sourceRow": 268},
            {"value": "pneumonia", "label": {"en": "Pneumonia"}, "sourceRow": 269},
            {"value": "preterm_delivery", "label": {"en": "Preterm delivery"}, "sourceRow": 270},
            {
                "value": "respiratory_distress",
                "label": {"en": "Respiratory distress"},
                "sourceRow": 271,
            },
            {
                "value": "None",
                "label": {"en": "None of the above words were mentioned"},
                "sourceRow": 272,
            },
        ],
    },
    # digitva-13x: V2.0's relevant is unsatisfiable
    # (docs/kb/WHO_VA_2022_Docs/id10304a-v2-relevance-defect.md).
    "Id10304_a": {"relevant": {"source": "selected(${Id10304},'yes')"}},
    # digitva-13x: V2.0 narrows this to adult-only 'a'; kept wider
    # deliberately (docs/policy/va-form-project-configuration.md).
    "Id10230": {"ageGroup": "C_A"},
}

# section name -> field overrides.
SECTION_DEVIATIONS = {
    # Relabelled from the workbook's "Skip to end if not consented".
    "consented": {"label": {"en": "Interview completion"}},
}


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
