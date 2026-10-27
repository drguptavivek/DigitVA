"""The served form definition's shared vector (offline-api-contract.md 14).

``tests/fixtures/served_definition_vectors.json`` lists project
``enabled_extensions`` sets with the composed version, the slice's
``extensions`` and the SHA-256 ``served_form_service`` serves for them. The
Rust station (``desktop/crates/digitva-db``, ``served_definition_vectors``
test) embeds the same composed file and must produce the same bytes, so the
same SHA-256. Python is the authority: after rebuilding
``app/data/who-va-2022.composed.json`` rewrite the file with
``python -m tests.test_served_definition_vectors --write`` and rerun both.
Pure: no database.
"""
import json
import sys
from pathlib import Path
from unittest import TestCase

from app.services import served_form_service

FIXTURE = Path(__file__).parent / "fixtures" / "served_definition_vectors.json"

#: form-options ``enabled_extensions`` lists: names outside the composed
#: file's tags (digitva_core, intake_screen, ...) are ignored by the server.
CASES = {
    "none": ["digitva_core", "intake_screen"],
    "single_module": ["social_autopsy"],
    "typical_project": [
        "digitva_core", "doris_support_whova_2022", "intake_screen", "death_summary",
        "medical_records", "geography", "narration_language", "abha",
    ],
    "all": [
        "abha", "death_summary", "digitva_core", "doris_support_whova_2022", "geography",
        "equity", "intake_screen", "medical_records", "narration_language", "social_autopsy",
    ],
}


def generate() -> dict:
    cases = []
    for name, enabled in CASES.items():
        served = served_form_service.served_definition(enabled)
        cases.append({
            "name": name,
            "enabled_extensions": enabled,
            "extensions": json.loads(served.body)["extensions"],
            "sha256": served.sha256,
            "bytes": len(served.body),
        })
    return {
        "rule": "app/services/served_form_service.py served_definition: filter_definition over the enabled "
                "extensions that are composed-file tags, top-level extensions sorted, then json.dumps("
                "ensure_ascii=False, separators=(',', ':'), sort_keys=True) UTF-8; sha256 of those bytes.",
        "version": served_form_service.composed_version(),
        "cases": cases,
    }


class ServedDefinitionVectorTests(TestCase):
    def test_the_fixture_matches_the_server(self):
        self.assertEqual(json.loads(FIXTURE.read_text(encoding="utf-8")), generate())

    def test_the_sets_give_distinct_slices(self):
        cases = generate()["cases"]
        self.assertEqual(len({case["sha256"] for case in cases}), len(cases))
        none = next(case for case in cases if case["name"] == "none")
        self.assertEqual(none["extensions"], [])


if __name__ == "__main__" and "--write" in sys.argv:
    FIXTURE.write_text(json.dumps(generate(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
