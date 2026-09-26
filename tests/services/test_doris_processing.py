"""Focused contract tests for bounded DORIS and CoDEdit processing."""

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from urllib3.exceptions import ProtocolError, ReadTimeoutError

from app.services.doris_certificate import (
    DorisCertificateError,
    normalize_certificate,
)
from app.services.doris_processing import process_certificate
from app.services.who_icd_api import (
    WhoIcdApiTimeout,
    WhoIcdApiUnavailable,
    post_mortality_processor,
)
from tests.base import BaseTestCase

_URI = "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified"


def _payload():
    return {
        "schema_version": 1,
        "client_revision": 3,
        "certificate": {
            "ICDVersion": "ICD11",
            "AdministrativeData": {"Sex": 1, "EstimatedAge": "P44Y"},
            "Part1": [
                {
                    "Conditions": [
                        {
                            "Text": "Respiratory tuberculosis",
                            "Code": "1B10.Z",
                            "LinearizationURI": _URI,
                            "Interval": "P14D",
                        }
                    ]
                }
            ],
        },
    }


def _codeinfo(code, release="2026-01"):
    assert release == "2026-01"
    uris = {
        "1B10.Z": _URI,
        "1B12.2": "http://id.who.int/icd/release/11/2026-01/mms/883140666",
        "XA0G74": "http://id.who.int/icd/release/11/2026-01/mms/1902897114",
    }
    return {"code": code, "stemId": uris[code]}


def _processor(name, certificate, release="2026-01"):
    if certificate:
        assert certificate["ICDMinorVersion"] == release
    if name == "doris":
        result = {
            "code": "1B10.Z",
            "stemCode": "1B10.Z",
            "uri": _URI,
            "stemURI": _URI,
            "report": "Selected cause",
            "tabularReport": "table",
            "reject": False,
            "error": None,
            "warning": None,
        }
    else:
        result = {"report": "check", "tabularReport": "table", "issueIds": "A|B"}
    return 200, json.dumps(result).encode()


class TestDorisProcessing(BaseTestCase):
    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    def test_body_read_timeout_does_not_skip_codedit(self, _codeinfo_mock):
        class TimedOutBody:
            def read(self, _size):
                raise ReadTimeoutError(None, None, "body stalled")

        _, codedit_content = _processor("codedit", {})
        responses = [
            SimpleNamespace(headers={}, raw=TimedOutBody(), status_code=200, close=lambda: None),
            SimpleNamespace(headers={}, raw=BytesIO(codedit_content), status_code=200, close=lambda: None),
        ]
        with patch("app.services.who_icd_api.requests.post", side_effect=responses) as post:
            result = process_certificate(_payload())

        self.assertEqual(result["doris"]["status"], "timeout")
        self.assertEqual(result["codedit"]["status"], "completed")
        self.assertEqual(post.call_count, 2)

    def test_body_protocol_error_is_reported_unavailable(self):
        class BrokenBody:
            def read(self, _size):
                raise ProtocolError("connection closed")

        response = SimpleNamespace(
            headers={}, raw=BrokenBody(), status_code=200, close=lambda: None
        )
        with patch("app.services.who_icd_api.requests.post", return_value=response):
            with self.assertRaises(WhoIcdApiUnavailable):
                post_mortality_processor("doris", _payload()["certificate"])

    def test_processor_response_is_bounded_to_512_kib(self):
        response = SimpleNamespace(
            headers={},
            raw=BytesIO(b"x" * (512 * 1024 + 1)),
            status_code=200,
            close=lambda: None,
        )
        with patch("app.services.who_icd_api.requests.post", return_value=response):
            with self.assertRaisesRegex(WhoIcdApiUnavailable, "too large"):
                post_mortality_processor("doris", _payload()["certificate"])

    def test_normalizes_release_and_omits_unknown_fetal_measurements(self):
        certificate = _payload()["certificate"]
        certificate["FetalOrInfantDeath"] = {
            "Stillborn": 9,
            "BirthWeight": None,
            "PregnancyWeeks": "",
            "AgeMother": None,
        }

        normalized = normalize_certificate(certificate)

        self.assertEqual(normalized["ICDMinorVersion"], "2026-01")
        self.assertEqual(
            normalized["FetalOrInfantDeath"], {"Stillborn": 9}
        )
        self.assertIn("BirthWeight", certificate["FetalOrInfantDeath"])

    def test_accepts_who_nested_certificate_fixture(self):
        certificate = _payload()["certificate"]
        certificate.update(
            {
                "AdministrativeData": {
                    "DateBirth": "1980-01-02",
                    "DateDeath": "2020-06-03T12:30:00Z",
                    "Sex": 1,
                    "EstimatedAge": "P40Y",
                },
                "Surgery": {
                    "WasPerformed": 1,
                    "Date": "2020-05-25",
                    "Reason": "Emergency operation",
                },
                "Autopsy": {"WasRequested": 9, "Findings": 0},
                "MannerOfDeath": {
                    "MannerOfDeath": 1,
                    "DateOfExternalCauseOrPoisoning": "2020-06-02",
                    "DescriptionExternalCause": "Road traffic injury",
                    "PlaceOfOccuranceExternalCause": 4,
                },
                "FetalOrInfantDeath": {
                    "MultiplePregnancy": 0,
                    "Stillborn": 0,
                    "DeathWithin24h": 12,
                    "BirthWeight": 1700,
                    "PregnancyWeeks": 32,
                    "AgeMother": 27,
                    "PerinatalDescription": "Prematurity",
                },
                "MaternalDeath": {
                    "WasPregnant": 0,
                    "TimeFromPregnancy": 1,
                    "PregnancyContribute": 1,
                },
            }
        )

        normalized = normalize_certificate(certificate)

        self.assertEqual(normalized["AdministrativeData"]["Sex"], 1)
        self.assertEqual(normalized["Surgery"]["Date"], "2020-05-25")
        self.assertEqual(normalized["Autopsy"]["Findings"], 0)
        self.assertEqual(
            normalized["MannerOfDeath"]["PlaceOfOccuranceExternalCause"], 4
        )
        self.assertEqual(normalized["FetalOrInfantDeath"]["BirthWeight"], 1700)
        self.assertEqual(normalized["MaternalDeath"]["TimeFromPregnancy"], 1)

    def test_normalizes_all_help_certificate_fixtures(self):
        fixture_path = Path(__file__).parents[2] / "resource" / "doris_help_examples.json"
        examples = json.loads(fixture_path.read_text(encoding="utf-8"))["examples"]

        for example in examples:
            with self.subTest(example=example["id"]):
                normalized = normalize_certificate(example["certificate"])
                self.assertEqual(normalized["ICDMinorVersion"], "2026-01")

    def test_rejects_unknown_nested_certificate_fields(self):
        nested_fields = {
            "AdministrativeData": {"Sex": 1},
            "Surgery": {"WasPerformed": 1},
            "Autopsy": {"WasRequested": 1},
            "MannerOfDeath": {"MannerOfDeath": 0},
            "FetalOrInfantDeath": {"Stillborn": 0},
            "MaternalDeath": {"WasPregnant": 0},
        }
        for name, value in nested_fields.items():
            with self.subTest(name=name):
                certificate = _payload()["certificate"]
                value["UnexpectedField"] = 1
                certificate[name] = value

                with self.assertRaises(DorisCertificateError) as caught:
                    normalize_certificate(certificate)

                self.assertEqual(caught.exception.fields[0].path, f"certificate.{name}")

    def test_rejects_malformed_nested_certificate_values(self):
        invalid_values = [
            ("AdministrativeData", {"Sex": "1"}),
            ("AdministrativeData", {"Sex": 3}),
            ("AdministrativeData", {"EstimatedAge": "40 years"}),
            ("AdministrativeData", {"DateBirth": "2020-02-30"}),
            ("Surgery", {"WasPerformed": 2}),
            ("Surgery", {"Date": "not-a-date"}),
            ("Autopsy", {"Findings": True}),
            ("MannerOfDeath", {"MannerOfDeath": 8}),
            ("MannerOfDeath", {"PlaceOfOccuranceExternalCause": 10}),
            ("FetalOrInfantDeath", {"DeathWithin24h": 25}),
            ("FetalOrInfantDeath", {"BirthWeight": 10000}),
            ("FetalOrInfantDeath", {"PregnancyWeeks": 51}),
            ("FetalOrInfantDeath", {"AgeMother": 9}),
            ("MaternalDeath", {"TimeFromPregnancy": 4}),
        ]
        for name, value in invalid_values:
            with self.subTest(name=name, value=value):
                certificate = _payload()["certificate"]
                certificate[name] = value

                with self.assertRaises(DorisCertificateError):
                    normalize_certificate(certificate)

    def test_rejects_different_intervals_on_one_line(self):
        certificate = _payload()["certificate"]
        certificate["Part1"][0]["Conditions"].append(
            {
                "Text": "Tuberculous otitis media",
                "Code": "1B12.2&XA0G74",
                "LinearizationURI": (
                    "http://id.who.int/icd/release/11/2026-01/mms/883140666 & "
                    "http://id.who.int/icd/release/11/2026-01/mms/1902897114"
                ),
                "Interval": "P60D",
            }
        )

        with self.assertRaises(DorisCertificateError) as caught:
            normalize_certificate(certificate)

        self.assertIn("same interval", caught.exception.fields[0].message)

    def test_rejects_invalid_condition_interval_but_preserves_unknown(self):
        certificate = _payload()["certificate"]
        condition = certificate["Part1"][0]["Conditions"][0]
        for interval in ("14 days", "P1.D", "P.5D", "P1Y2Q"):
            with self.subTest(interval=interval):
                condition["Interval"] = interval
                with self.assertRaises(DorisCertificateError) as caught:
                    normalize_certificate(certificate)
                self.assertEqual(
                    caught.exception.fields[0].path,
                    "certificate.Part1[0].Conditions[0].Interval",
                )
        for interval in ("", "P", "PT", "P1Y2M", "PT0.5H"):
            with self.subTest(interval=interval):
                condition["Interval"] = interval
                normalized = normalize_certificate(certificate)
                self.assertEqual(
                    normalized["Part1"][0]["Conditions"][0]["Interval"], interval
                )

    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    def test_verifies_each_component_of_complete_expression(self, codeinfo):
        payload = _payload()
        payload["certificate"]["Part1"][0]["Conditions"][0].update(
            {
                "Text": "Tuberculous otitis media",
                "Code": "1B12.2&XA0G74",
                "LinearizationURI": (
                    "http://id.who.int/icd/release/11/2026-01/mms/883140666 & "
                    "http://id.who.int/icd/release/11/2026-01/mms/1902897114"
                ),
            }
        )
        complete = {
            "code": "1B12.2&XA0G74",
            "stemId": "http://id.who.int/icd/release/11/2026-01/mms/883140666",
        }
        codeinfo.side_effect = [complete, _codeinfo("1B12.2"), _codeinfo("XA0G74")]

        with patch(
            "app.services.doris_processing.post_mortality_processor",
            side_effect=_processor,
        ):
            process_certificate(payload)

        self.assertEqual(codeinfo.call_count, 3)

    def test_rejects_bounds_before_calling_processors(self):
        payload = _payload()
        payload["certificate"]["Part1"] *= 6
        with patch("app.services.doris_processing.post_mortality_processor") as processor:
            with self.assertRaises(DorisCertificateError):
                process_certificate(payload)
        processor.assert_not_called()

    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    @patch("app.services.doris_processing.post_mortality_processor", side_effect=_processor)
    def test_processes_both_engines_and_returns_stable_digests(self, processor, codeinfo):
        first = process_certificate(_payload(), who_image_digest="sha256:image")
        second = process_certificate(_payload(), who_image_digest="sha256:image")

        self.assertEqual(first["certificate_digest"], second["certificate_digest"])
        self.assertEqual(first["result_digest"], second["result_digest"])
        self.assertEqual(first["doris"]["status"], "completed")
        self.assertEqual(first["codedit"]["status"], "completed")
        self.assertEqual(first["codedit"]["result"]["issueIds"], "A|B")
        self.assertEqual(processor.call_count, 4)
        self.assertEqual(codeinfo.call_count, 2)

    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    @patch("app.services.doris_processing.post_mortality_processor")
    def test_processor_statuses_are_independent(self, processor, codeinfo):
        processor.side_effect = [WhoIcdApiTimeout("late"), _processor("codedit", {})]

        result = process_certificate(_payload())

        self.assertEqual(result["doris"], {"status": "timeout", "result": None})
        self.assertEqual(result["codedit"]["status"], "completed")
        self.assertTrue(codeinfo.called)

    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    @patch("app.services.doris_processing.post_mortality_processor", side_effect=_processor)
    def test_rejects_mismatched_code_uri_before_processing(self, processor, codeinfo):
        payload = _payload()
        payload["certificate"]["Part1"][0]["Conditions"][0]["LinearizationURI"] = (
            "http://id.who.int/icd/release/11/2026-01/mms/wrong"
        )

        with self.assertRaises(DorisCertificateError):
            process_certificate(payload)

        processor.assert_not_called()
        self.assertTrue(codeinfo.called)

    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    @patch("app.services.doris_processing.post_mortality_processor")
    def test_marks_reject_true_as_rejected(self, processor, codeinfo):
        _, content = _processor("doris", {})
        result = json.loads(content)
        result["reject"] = True
        processor.side_effect = [
            (200, json.dumps(result).encode()),
            _processor("codedit", {}),
        ]

        response = process_certificate(_payload())

        self.assertEqual(response["doris"]["status"], "rejected")
        self.assertEqual(response["codedit"]["status"], "completed")
        self.assertTrue(codeinfo.called)

    @patch("app.services.doris_certificate.get_icd11_codeinfo", side_effect=_codeinfo)
    @patch("app.services.doris_processing.post_mortality_processor")
    def test_malformed_response_does_not_hide_other_result(self, processor, codeinfo):
        processor.side_effect = [(200, b"not-json"), _processor("codedit", {})]

        response = process_certificate(_payload())

        self.assertEqual(response["doris"]["status"], "malformed_response")
        self.assertEqual(response["codedit"]["status"], "completed")
        self.assertTrue(codeinfo.called)
