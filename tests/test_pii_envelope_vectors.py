"""Cross-implementation vectors for the PII envelope format.

Spec: docs/policy/pii-envelope-format.md. The committed vectors
(tests/fixtures/pii_envelope_vectors.json) must all behave as stated under
app/utils/pii_crypto.py, the checker must catch a wrong expectation, and the
deterministic section must regenerate byte for byte. No database, no app
configuration: the TEST keys come from the vectors file.
"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_pii_blob, generate_pii_vectors

FIXTURE = Path(__file__).parent / "fixtures" / "pii_envelope_vectors.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
DOC = Path(__file__).parents[1] / "docs" / "policy" / "pii-envelope-format.md"


def _main(path, *extra):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = check_pii_blob.main([str(path), *extra])
    return code, out.getvalue()


class VectorFileTests(unittest.TestCase):
    def test_checker_loads_the_repo_implementation(self):
        pc = check_pii_blob.load_pii_crypto()
        self.assertEqual(Path(pc.__file__).resolve(), check_pii_blob.PII_CRYPTO_PATH)
        self.assertTrue(check_pii_blob.PII_CRYPTO_PATH.samefile(
            Path(__file__).parents[1] / "app" / "utils" / "pii_crypto.py"))

    def test_every_vector_and_deterministic_check_passes(self):
        result = check_pii_blob.run_checks(DATA)
        self.assertEqual(result["failed_ids"], [])
        self.assertEqual(result["failed_checks"], [])
        self.assertEqual(result["vectors_passed"], len(DATA["vectors"]))
        self.assertGreaterEqual(result["deterministic_passed"], 18)

    def test_vectors_cover_positive_and_required_negative_cases(self):
        ids = {v["id"] for v in DATA["vectors"]}
        expects = {v["expect"] for v in DATA["vectors"]}
        self.assertEqual(expects, {"ok", "fail"})
        for required in (
            "value-identifier", "value-unicode", "value-empty", "record-multi", "record-unicode",
            "record-empty-string", "record-long", "record-empty", "record-key-tv2", "record-rewrapped-tv2",
            "fail-value-aad-other-type", "fail-value-ct-flipped", "fail-value-truncated", "fail-value-version",
            "fail-value-non-utf8", "fail-wrap-version", "fail-wrap-unknown-key-id",
            "fail-wrap-relabelled-key-id", "fail-wrap-truncated", "fail-record-other-table",
            "fail-record-other-row", "fail-record-renamed-field", "fail-record-field-from-other-record",
        ):
            self.assertIn(required, ids)

    def test_long_value_is_long_and_unicode_kept_unnormalised(self):
        by_id = {v["id"]: v for v in DATA["vectors"]}
        self.assertEqual(len(by_id["record-long"]["plaintext"]["Id10476"]), 4000)
        self.assertIn("é", by_id["value-unicode"]["plaintext"])
        self.assertEqual(by_id["value-empty"]["plaintext_hex"], "")

    def test_deterministic_section_regenerates_byte_for_byte(self):
        pc = check_pii_blob.load_pii_crypto()
        regenerated = generate_pii_vectors.build_deterministic(pc)
        self.assertEqual(
            generate_pii_vectors.dumps(regenerated), generate_pii_vectors.dumps(DATA["deterministic"])
        )
        self.assertIn("TEST KEYS ONLY", DATA["deterministic"]["test_keys"]["warning"])

    def test_fresh_generation_passes_its_own_checks(self):
        pc = check_pii_blob.load_pii_crypto()
        fresh = generate_pii_vectors.build_all(pc)
        self.assertEqual(fresh["deterministic"], DATA["deterministic"])
        self.assertEqual([v["id"] for v in fresh["vectors"]], [v["id"] for v in DATA["vectors"]])
        result = check_pii_blob.run_checks(fresh)
        self.assertEqual((result["failed_ids"], result["failed_checks"]), ([], []))
        # Sealing is randomised: the fresh blobs differ from the committed ones.
        self.assertNotEqual(fresh["vectors"][0]["value_ciphertext"], DATA["vectors"][0]["value_ciphertext"])


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, data):
        path = Path(self.tmp.name) / "vectors.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_main_exits_zero_on_the_fixture(self):
        code, out = _main(FIXTURE)
        self.assertEqual(code, 0)
        self.assertIn(f"vectors {len(DATA['vectors'])} passed, 0 failed", out)

    def test_wrong_expectations_fail_and_print_no_plaintext(self):
        data = copy.deepcopy(DATA)
        by_id = {v["id"]: v for v in data["vectors"]}
        secret = by_id["value-identifier"]["plaintext"]
        by_id["value-identifier"]["plaintext"] = "WRONG-EXPECTATION"
        by_id["fail-value-ct-flipped"]["expect"] = "ok"
        by_id["fail-value-ct-flipped"]["plaintext"] = secret
        by_id["record-multi"]["intermediate"]["dek_hex"] = "00" * 32
        data["deterministic"]["blind_index"]["blind_key_id"] = "00000000"
        code, out = _main(self.write(data))
        self.assertEqual(code, 1)
        self.assertIn(f"vectors {len(DATA['vectors']) - 3} passed, 3 failed;", out)
        self.assertIn("passed, 1 failed", out)
        for vid in ("value-identifier", "fail-value-ct-flipped", "record-multi", "blind_key_id"):
            self.assertIn(vid, out)
        for leak in (secret, "WRONG-EXPECTATION", "Asha", by_id["value-identifier"]["value_ciphertext"][13:40]):
            self.assertNotIn(leak, out)

    def test_ok_vector_that_raises_unexpected_error_counts_as_failure(self):
        data = {"vectors": [dict(DATA["vectors"][0], kind="unknown")]}
        result = check_pii_blob.run_checks(data, DATA)
        self.assertEqual(result["vectors_failed"], 1)

    def test_rust_style_file_uses_keys_from_the_fixture(self):
        # The shape a Rust writer emits: vectors only, keys taken from --keys.
        ok = [v for v in DATA["vectors"] if v["expect"] == "ok"][:3]
        path = self.write({"format": DATA["format"], "producer": "test", "vectors": ok})
        code, out = _main(path, "--keys", str(FIXTURE))
        self.assertEqual(code, 0)
        self.assertIn("vectors 3 passed, 0 failed; deterministic 0 passed", out)

    def test_unsafe_vector_ids_are_reported_by_position(self):
        bad = dict(DATA["vectors"][0], id="Asha <script>", plaintext="nope")
        result = check_pii_blob.run_checks({"vectors": [bad]}, DATA)
        self.assertEqual(result["failed_ids"], ["#0"])

    def test_empty_or_unreadable_file_exits_one(self):
        self.assertEqual(_main(self.write({"vectors": []}), "--keys", str(FIXTURE))[0], 1)
        missing = Path(self.tmp.name) / "absent.json"
        self.assertEqual(_main(missing)[0], 1)

    def test_mismatched_test_key_entry_is_refused(self):
        data = copy.deepcopy(DATA)
        data["deterministic"]["test_keys"]["kem_keys"][0]["x25519_private_hex"] = "00" * 32
        self.assertEqual(_main(self.write(data))[0], 1)


class SpecDocTests(unittest.TestCase):
    def test_spec_has_front_matter_and_names_the_vectors(self):
        lines = DOC.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "---")
        end = lines.index("---", 1)
        keys = {line.split(":", 1)[0].strip() for line in lines[1:end] if ":" in line}
        self.assertTrue({"title", "doc_type", "status", "owner", "last_updated"} <= keys)
        text = "\n".join(lines)
        for name in ("tests/fixtures/pii_envelope_vectors.json", "scripts/check_pii_blob.py",
                     "digitva pii kem combiner v1", "digitva-pii-bidx/v1/"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
