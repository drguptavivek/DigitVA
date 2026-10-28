import json
from pathlib import Path
from unittest import TestCase


class TestSmartVaInputGoldenFixtures(TestCase):
    def test_fixtures_match_server_cleaner(self):
        from app.utils.va_smartva.va_smartva_02_prepdata import _clean_payload_for_smartva

        fixture_path = Path(__file__).parents[1] / "fixtures/local_smartva/input-parity.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 4)
        for case in cases:
            with self.subTest(case=case["name"]):
                actual = _clean_payload_for_smartva(case["payload"], va_sid=case["sid"])
                self.assertEqual(actual, case["expected"])
