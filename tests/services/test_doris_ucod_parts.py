"""The computed DORIS UCOD split into titled codes for the coder."""

from unittest.mock import patch

from app.services.doris_processing import ucod_parts
from tests.base import BaseTestCase

CERT = {"Part1": [{"Conditions": [{"Text": "Sugar disease", "Code": "5A14"}]}]}
URIS = (
    "http://id.who.int/icd/release/11/mms/1697306310 / "
    "http://id.who.int/icd/release/11/mms/1334938734/unspecified"
)


class TestUcodParts(BaseTestCase):
    def test_certificate_title_first_then_api_for_postcoordinated_code(self):
        with patch(
            "app.services.doris_processing.icd11_title",
            return_value="Acute myocardial infarction, unspecified",
        ) as api:
            parts = ucod_parts({"code": "5A14/BA41.Z", "uri": URIS}, CERT)
        self.assertEqual(
            [(p["code"], p["title"], p["role"]) for p in parts],
            [
                ("5A14", "Sugar disease", "stem"),
                ("BA41.Z", "Acute myocardial infarction, unspecified", "postcoordinated"),
            ],
        )
        api.assert_called_once_with("BA41.Z")
        self.assertTrue(parts[0]["uri"].endswith("/1697306310"))
        self.assertTrue(parts[1]["uri"].endswith("/1334938734/unspecified"))

    def test_extension_codes_and_several_postcoordinated_parts(self):
        with patch("app.services.doris_processing.icd11_title", side_effect=lambda c: f"T-{c}"):
            parts = ucod_parts({"code": "A&X/B/C", "uri": None}, {})
        self.assertEqual(
            [(p["code"], p["role"]) for p in parts],
            [("A", "stem"), ("X", "extension"), ("B", "postcoordinated"), ("C", "postcoordinated")],
        )
        self.assertTrue(all(p["uri"] is None for p in parts))

    def test_api_failure_falls_back_to_empty_title(self):
        with patch("app.services.doris_processing.icd11_title", side_effect=RuntimeError("down")):
            parts = ucod_parts({"code": "5A14/BA41.Z"}, {})
        self.assertEqual([(p["code"], p["title"]) for p in parts], [("5A14", ""), ("BA41.Z", "")])

    def test_no_code_gives_no_parts(self):
        self.assertEqual(ucod_parts({"code": None}, {}), [])
        self.assertEqual(ucod_parts(None, {}), [])
