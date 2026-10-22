"""Station config conformance fixture (digitva-gb8w.4, contract 14).

``tests/fixtures/station_config/``: a TEST-ONLY server signing key (a seed
derived from a public label), a sample payload, and the signed two-line file
``station_config.signed`` the server code makes from them. This test
regenerates the file byte for byte; the Rust test
``desktop/crates/digitva-bundle/tests/station_config_fixture.rs`` verifies
it with ``VerifiedStationConfig::parse_and_verify``. The Python code is the
authority: after a deliberate format change, rewrite the file with
``python -m tests.test_station_config_fixture --write`` and rerun both.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.services import station_config_service as service

FIXTURE = Path(__file__).parent / "fixtures" / "station_config"
KEY_LABEL = b"digitva station config TEST VECTOR ONLY server signing key"


def _payload() -> dict:
    return json.loads((FIXTURE / "payload.json").read_text(encoding="utf-8"))


def _key():
    return service.parse_signing_key((FIXTURE / "test_server_signing_key").read_text(encoding="ascii"))


def generate() -> str:
    return service.sign_station_config(_payload(), _key())


class StationConfigFixtureTests(unittest.TestCase):

    def test_the_key_is_the_published_test_key(self):
        text = (FIXTURE / "test_server_signing_key").read_text(encoding="ascii").strip()
        self.assertEqual(service.decode_b64url(text), hashlib.sha256(KEY_LABEL).digest())
        self.assertEqual(_payload()["server_signing_key"], service.public_signing_key(_key()))
        # server_signing_key() refuses this key outside TESTING by this id.
        self.assertEqual(service.public_signing_key(_key())["signing_key_id"], service.FIXTURE_SIGNING_KEY_ID)

    def test_the_signed_file_regenerates_byte_for_byte(self):
        self.assertEqual((FIXTURE / "station_config.signed").read_bytes(), generate().encode("utf-8"))

    def test_the_file_is_two_canonical_lines_and_verifies(self):
        raw = (FIXTURE / "station_config.signed").read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertNotIn(b"\r", raw)
        line1, line2 = raw[:-1].split(b"\n")
        self.assertEqual(line1, service.canonical_json(json.loads(line1)))
        signature_line = json.loads(line2)
        self.assertEqual(set(signature_line), {"alg", "sig", "signing_key_id"})
        self.assertEqual(signature_line["alg"], "ed25519")
        public = service.decode_b64url(_payload()["server_signing_key"]["public"])
        # Raises InvalidSignature on any change.
        Ed25519PublicKey.from_public_bytes(public).verify(
            service.decode_b64url(signature_line["sig"]), service.STATION_CONFIG_SIG_DOMAIN + line1)

    def test_text_is_nfc_in_the_signed_line(self):
        self.assertIn("Renée", _payload()["custodian"]["name"])
        line1 = (FIXTURE / "station_config.signed").read_text(encoding="utf-8").split("\n")[0]
        self.assertIn("Renée", line1)
        self.assertNotIn("Renée", line1)

    def test_notice_hashes_hold_after_the_canonical_form(self):
        line1 = json.loads((FIXTURE / "station_config.signed").read_text(encoding="utf-8").split("\n")[0])
        versions = line1["projects"][0]["consent"]["notice_versions"]
        self.assertTrue(versions)
        for version in versions:
            self.assertEqual(hashlib.sha256(version["text"].encode("utf-8")).hexdigest(), version["text_sha256"])

    def test_project_display_maps_cover_the_listed_sites_and_units(self):
        project = json.loads((FIXTURE / "station_config.signed").read_text(encoding="utf-8").split("\n")[0])[
            "projects"][0]
        self.assertEqual(sorted(project["site_names"]), project["sites"])
        self.assertEqual(sorted(project["org_unit_paths"]), project["org_units"])
        self.assertEqual(sorted(project["org_unit_sites"]), project["org_units"])
        self.assertTrue(set(project["org_unit_sites"].values()) <= set(project["sites"]))
        self.assertEqual(project["org_unit_paths"]["3c9e1f2a-5b6d-4e7f-8a9b-0c1d2e3f4a5b"],
                         "Solan, Kandaghat, PHC Chail")

    def test_form_policy_names_the_servers_current_definition(self):
        """The fixture's form_options must be one the station accepts: the
        composed version and the sha the server serves for its modules."""
        from app.services import served_form_service

        project = _payload()["projects"][0]
        options = project["form_options"]
        served = served_form_service.served_definition(options["enabled_extensions"])
        self.assertEqual(options["instrument_version"], served_form_service.composed_version())
        self.assertEqual(options["definition_sha256"], served.sha256)
        self.assertEqual(sorted(project["translations"]),
                         sorted(loc["code"] for loc in options["available_locales"] if loc["code"] != "en"))

    def test_purge_shape(self):
        purge = json.loads((FIXTURE / "station_config.signed").read_text(encoding="utf-8").split("\n")[0])["purge"]
        self.assertEqual(purge, sorted(set(purge)))
        self.assertTrue(all(isinstance(p, str) and len(p) == 36 for p in purge))


class CanonicalJsonTests(unittest.TestCase):

    def test_jcs_cases(self):
        cases = [
            ({"b": 1, "a": [True, False, None], "": "x"}, '{"":"x","a":[true,false,null],"b":1}'),
            ({"k": "q\"\\\n\t\x01\x7f "}, '{"k":"q\\"\\\\\\n\\t\\u0001\x7f "}'),
            # UTF-16 order: U+E000 sorts after the surrogate pair of U+1F600.
            ({"": 1, "\U0001f600": 2}, '{"\U0001f600":2,"":1}'),
            ({"é": "é"}, '{"é":"é"}'),
            ([2**53 - 1, -(2**53 - 1)], "[9007199254740991,-9007199254740991]"),
        ]
        for value, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(service.canonical_json(value), expected.encode("utf-8"))

    def test_jcs_refuses_what_it_cannot_represent(self):
        for value in (1.5, 2**53, {"a": object()}, {1: "x"}, {"é": 1, "é": 2}):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                service.canonical_json(value)


if __name__ == "__main__" and "--write" in sys.argv:
    (FIXTURE / "station_config.signed").write_bytes(generate().encode("utf-8"))
    print(f"wrote {FIXTURE / 'station_config.signed'}")
