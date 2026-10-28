import json
from pathlib import Path
from types import SimpleNamespace

from app.services.case_content_service import smartva_summary
from tests.base import BaseTestCase


class TestSmartVaEngineCheckGolden(BaseTestCase):
    def test_host_rust_goldens_match_server_workspace_projection(self):
        golden_path = (
            Path(__file__).parents[1]
            / "../mobile/digitva-collect/src/smartva/engine-check-golden.json"
        ).resolve()
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        self.assertEqual(golden["source"]["engine_version"], "SmartVA-Analyze 3.0.1-rust (smartva-rust 3.0.2)")
        self.assertEqual([case["id"] for case in golden["cases"]], ["adult", "child", "neonate"])

        for case in golden["cases"]:
            expected = case["expected"]
            with self.subTest(case=case["id"]):
                values = {
                    "va_smartva_age": expected["age"],
                    "va_smartva_gender": expected["gender"],
                    "va_smartva_allsymptoms": "; ".join(expected["symptoms"]),
                }
                for cause in expected["causes"]:
                    rank = cause["rank"]
                    values[f"va_smartva_cause{rank}"] = cause["cause"]
                    values[f"va_smartva_cause{rank}icd"] = cause["icd10"]
                    values[f"va_smartva_likelihood{rank}"] = cause["likelihood"]
                    values[f"va_smartva_keysymptom{rank}"] = expected["key_symptoms"][rank - 1]

                actual = smartva_summary(SimpleNamespace(**values))
                self.assertIsNotNone(actual)
                self.assertEqual(actual["age"], expected["age"])
                self.assertEqual(actual["gender"], expected["gender"])
                self.assertEqual(actual["key_symptoms"], expected["key_symptoms"])
                self.assertEqual(actual["symptoms"], expected["symptoms"])
                self.assertEqual(
                    [
                        {
                            key: cause[key]
                            for key in (
                                "rank", "cause", "icd10", "icd11", "likelihood"
                            )
                        }
                        for cause in actual["causes"]
                    ],
                    [{key: value for key, value in cause.items() if key != "icd11_label"}
                     for cause in expected["causes"]],
                )
                # The server intentionally shows the code alone while WHO is unavailable.
                for actual_cause, expected_cause in zip(actual["causes"], expected["causes"]):
                    self.assertIn(actual_cause["icd11_label"], (
                        expected_cause["icd11"], expected_cause["icd11_label"],
                    ))
