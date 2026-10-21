"""app/utils/pii_crypto.py: envelope encryption of personal-data columns.

Policy: docs/policy/death-registration-identifiers.md, "Tests for encryption".
No database: a throwaway Flask app per test carries the keyring.
"""
import hashlib
import hmac
import json
import logging
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import mlkem, x25519
from flask import Flask

from app.services.death_identifier_rules import IdentifierRuleError, validate_value
from app.utils import pii_crypto as pc

KAT = json.loads((Path(__file__).parent / "fixtures" / "mlkem768_kat.json").read_text())
SECRET = "S3CRET-MCCD/2026/000123"
AAD = uuid.uuid4().bytes + uuid.uuid4().bytes


def _config(public, private_path="", previous="", blind=None):
    return {
        "SECRET_KEY": "test",
        "PII_KEM_PUBLIC_KEY": public.to_config(),
        "PII_KEM_KEY_ID": public.key_id,
        "PII_KEM_PRIVATE_KEY_FILE": private_path,
        "PII_KEM_PREVIOUS_PRIVATE_KEY_FILES": previous,
        "PII_BLIND_INDEX_KEY": blind or os.urandom(32).hex(),
    }


class _CaptureHandler(logging.Handler):
    """Every record, formatted with any traceback, kept as text."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


class KeyringCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pairs = {}

    def new_pair(self, key_id):
        public, private = pc.generate_keyset(key_id)
        path = os.path.join(self.tmp.name, f"{key_id}.key")
        Path(path).write_text(private.to_file_text())
        self.pairs[key_id] = (public, private, path)
        return public, private, path

    def use(self, config, *, debug=False, testing=False):
        """Push an app context whose keyring is built from *config*."""
        app = Flask("pii-test")
        app.debug, app.testing = debug, testing
        app.config.update(config)
        pc.init_app(app)
        ctx = app.app_context()
        ctx.push()
        self.addCleanup(ctx.pop)
        return app

    def use_pair(self, key_id, previous=(), blind=None):
        public, _, path = self.pairs.get(key_id) or self.new_pair(key_id)
        return self.use(
            _config(public, path, ",".join(self.pairs[k][2] for k in previous), blind),
            testing=True,
        )


class KnownAnswerTests(unittest.TestCase):
    def test_x25519_rfc7748_section_6_1(self):
        alice = x25519.X25519PrivateKey.from_private_bytes(
            bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"))
        bob_public = x25519.X25519PublicKey.from_public_bytes(
            bytes.fromhex("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"))
        self.assertEqual(
            alice.exchange(bob_public).hex(),
            "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742",
        )

    def test_hmac_sha512_rfc4231_cases_1_and_2(self):
        # The blind index is HMAC-SHA-512 (hmac/hashlib); these are the RFC 4231 answers.
        self.assertEqual(
            hmac.new(b"\x0b" * 20, b"Hi There", hashlib.sha512).hexdigest(),
            "87aa7cdea5ef619d4ff0b4241a1d6cb02379f4e2ce4ec2787ad0b30545e17cde"
            "daa833b7d6b8a702038b274eaea3f4e4be9d914eeb61f1702e696c203a126854",
        )
        self.assertEqual(
            hmac.new(b"Jefe", b"what do ya want for nothing?", hashlib.sha512).hexdigest(),
            "164b7a7bfcf819e2e395fbe73b56e0a387bd64222e831fd610270cd7ea250554"
            "9758bf75c05a994a6d034f65f8f0e6fdcaeab1a34d4a6b4b636e070a38bce737",
        )

    def test_mlkem768_pinned_vector(self):
        # Recorded from the library (no deterministic encapsulation is exposed,
        # so FIPS 203 ACVP encapsulation vectors cannot be fed in).
        sk = mlkem.MLKEM768PrivateKey.from_seed_bytes(bytes.fromhex(KAT["seed"]))
        self.assertEqual(
            hashlib.sha256(sk.public_key().public_bytes_raw()).hexdigest(), KAT["public_sha256"])
        self.assertEqual(sk.decapsulate(bytes.fromhex(KAT["ciphertext"])).hex(), KAT["shared_secret"])

    def test_combiner_fixed_input_vector(self):
        ss_m, ss_x = bytes(range(32)), bytes(range(32, 64))
        ct_m, eph = b"\x01" * 1088, b"\x02" * 32
        pub_m, pub_x = b"\x03" * 1184, b"\x04" * 32
        got = pc.combine(ss_m, ss_x, "k1", ct_m, eph, pub_m, pub_x)
        # Independent HKDF-SHA256 (RFC 5869) over the documented info layout.
        def field(raw):
            return len(raw).to_bytes(2, "big") + raw
        info = (b"digitva pii kem combiner v1" + field(pc.WRAP_ALG.encode()) + field(b"k1")
                + field(ct_m) + field(eph) + field(pub_m) + field(pub_x))
        prk = hmac.new(b"\x00" * 32, ss_m + ss_x, hashlib.sha256).digest()
        expected = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
        self.assertEqual(got, expected)
        # Pinned: a change to the info layout fails here.
        self.assertEqual(got.hex(), "57c20aeef040abcf4187948c9617874fb899722f3f8351a83df183596e9e3d11")

    def test_combiner_binds_both_recipient_public_keys(self):
        args = (bytes(32), bytes(32), "k1", b"\x01" * 1088, b"\x02" * 32)
        base = pc.combine(*args, b"\x03" * 1184, b"\x04" * 32)
        self.assertNotEqual(base, pc.combine(*args, b"\x05" * 1184, b"\x04" * 32))
        self.assertNotEqual(base, pc.combine(*args, b"\x03" * 1184, b"\x05" * 32))


class RoundTripTests(KeyringCase):
    def setUp(self):
        super().setUp()
        self.use_pair("k1")

    def test_round_trip_and_stored_forms(self):
        ciphertext, wrapped, key_id = pc.encrypt_value(SECRET, AAD)
        self.assertEqual(key_id, "k1")
        self.assertTrue(ciphertext.startswith("v1:aes256gcm:"))
        self.assertTrue(wrapped.startswith("v1:aes256gcm+mlkem768x25519:k1:"))
        self.assertNotIn(SECRET, ciphertext + wrapped)
        self.assertEqual(pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r1"), SECRET)

    def test_fresh_dek_and_nonce_per_write(self):
        first = pc.encrypt_value(SECRET, AAD)
        second = pc.encrypt_value(SECRET, AAD)
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])
        context = uuid.uuid4().bytes
        self.assertEqual(pc.blind_index(context, SECRET), pc.blind_index(context, SECRET))

    def test_wrong_aad_fails(self):
        ciphertext, wrapped, _ = pc.encrypt_value(SECRET, AAD)
        other = uuid.uuid4().bytes + AAD[16:]
        with self.assertRaises(pc.PiiCryptoError):
            pc.decrypt_value(ciphertext, wrapped, other, row_ref="r1")
        # The subject decrypts under the right AAD (the failure is the AAD).
        self.assertEqual(pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r1"), SECRET)

    def test_wrapped_dek_under_another_key_id_fails(self):
        self.use_pair("k2", previous=("k1",))
        ciphertext, wrapped, _ = pc.encrypt_value(SECRET, AAD)
        self.assertTrue(wrapped.startswith("v1:aes256gcm+mlkem768x25519:k2:"))
        relabelled = wrapped.replace(":k2:", ":k1:", 1)
        with self.assertRaises(pc.PiiCryptoError):
            pc.decrypt_value(ciphertext, relabelled, AAD, row_ref="r1")
        self.assertEqual(pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r1"), SECRET)

    def test_tamper_and_unknown_dispatch_raise_generic_error(self):
        ciphertext, wrapped, _ = pc.encrypt_value(SECRET, AAD)

        def flip(blob):
            head, _, tail = blob.rpartition(":")
            return head + ":" + ("A" if tail[10] != "A" else "B").join([tail[:10], tail[11:]])

        cases = {
            "tampered ciphertext": (flip(ciphertext), wrapped),
            "tampered wrapped dek": (ciphertext, flip(wrapped)),
            "unknown data version": (ciphertext.replace("v1:", "v9:", 1), wrapped),
            "unknown data alg": (ciphertext.replace("aes256gcm", "chacha", 1), wrapped),
            "unknown wrap version": (ciphertext, wrapped.replace("v1:", "v9:", 1)),
            "unknown wrap alg": (ciphertext, wrapped.replace("mlkem768x25519", "mlkem1024", 1)),
            "unknown key id": (ciphertext, wrapped.replace(":k1:", ":zz:", 1)),
            "garbage": ("nonsense", "nonsense"),
        }
        for name, (ct, dek) in cases.items():
            with self.subTest(name), self.assertRaises(pc.PiiCryptoError) as caught:
                pc.decrypt_value(ct, dek, AAD, row_ref="row-42")
            message = str(caught.exception)
            self.assertIn("row-42", message)
            for secret in (SECRET, ciphertext, wrapped, ciphertext.rpartition(":")[2], wrapped.rpartition(":")[2]):
                self.assertNotIn(secret, message)

    def test_failures_log_no_plaintext(self):
        public, private, _ = self.pairs["k1"]
        ciphertext, wrapped, _ = pc.encrypt_value(SECRET, AAD)
        handler = _CaptureHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.setLevel, previous_level)
        self.addCleanup(root.removeHandler, handler)

        with self.assertRaises(pc.PiiCryptoError):  # a decrypt failure
            pc.decrypt_value(ciphertext, wrapped, uuid.uuid4().bytes, row_ref="r1")
        with self.assertRaises(IdentifierRuleError):  # a validation failure
            validate_value(SimpleNamespace(
                label="MCCD number", is_active=True, min_length=1, max_length=64,
                char_type="digits", pattern=None, example=None), SECRET)
        with self.assertRaises(Exception):  # a wrap failure: bytes that are not a key
            pc.wrap_dek(bytes(32), pc.KemPublicKey("k1", b"bad", b"bad"))

        # The capture works: attached, at DEBUG, and a record from a child logger arrives.
        self.assertIn(handler, root.handlers)
        logging.getLogger("app.probe").debug("capture-sentinel")
        text = "\n".join(handler.lines)
        self.assertIn("capture-sentinel", text)
        for secret in (
            SECRET, ciphertext, wrapped, ciphertext.rpartition(":")[2], wrapped.rpartition(":")[2],
            public.to_config()[:40], private.to_file_text().split(":")[1][:40],
        ):
            self.assertNotIn(secret, text)


class BlindIndexTests(KeyringCase):
    def test_blind_index_is_hmac_sha512_bound_to_context(self):
        blind = "ab" * 32
        self.use_pair("k1", blind=blind)
        type_a, type_b = uuid.uuid4().bytes, uuid.uuid4().bytes
        got = pc.blind_index(type_a, "MCCD/1")
        self.assertEqual(len(got), 128)
        self.assertEqual(got, hmac.new(bytes.fromhex(blind), type_a + b"\x00" + b"MCCD/1", hashlib.sha512).hexdigest())
        self.assertEqual(got, pc.blind_index(type_a, "MCCD/1"))
        self.assertNotEqual(got, pc.blind_index(type_b, "MCCD/1"))

    def test_spacing_and_case_normalise_to_one_index(self):
        from app.services.death_identifier_rules import normalise

        self.use_pair("k1")
        context = uuid.uuid4().bytes
        self.assertEqual(
            pc.blind_index(context, normalise("mccd/1")),
            pc.blind_index(context, normalise("  MCCD/1 ")),
        )


class RotationTests(KeyringCase):
    def test_old_rows_read_then_rewrap_leaves_data_ciphertext_untouched(self):
        self.use_pair("k1")
        ciphertext, wrapped, _ = pc.encrypt_value(SECRET, AAD)

        self.use_pair("k2", previous=("k1",))
        # Window: new writes use k2, the old row still reads through the previous key.
        self.assertEqual(pc.encrypt_value("x", AAD)[2], "k2")
        self.assertEqual(pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r1"), SECRET)

        new_wrapped, new_key = pc.rewrap_dek(wrapped, row_ref="r1")
        self.assertEqual(new_key, "k2")
        self.assertTrue(new_wrapped.startswith("v1:aes256gcm+mlkem768x25519:k2:"))
        self.assertNotEqual(new_wrapped, wrapped)

        # The old private key is gone: the row still reads, the data blob is byte-identical.
        self.use_pair("k2")
        self.assertEqual(pc.decrypt_value(ciphertext, new_wrapped, AAD, row_ref="r1"), SECRET)
        with self.assertRaises(pc.PiiCryptoError):
            pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r1")

    def test_public_key_only_writer_writes_but_cannot_read(self):
        public, _, path = self.new_pair("k1")
        self.use_pair("k1")
        ciphertext, wrapped, _ = pc.encrypt_value(SECRET, AAD)

        self.use(_config(public, ""), testing=True)  # beat: no private key file
        writer_ciphertext, writer_wrapped, key_id = pc.encrypt_value("OTHER-1", AAD)
        self.assertEqual(key_id, "k1")
        with self.assertRaises(pc.PiiCryptoError):
            pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r1")
        # What the writer wrote reads in a process that holds the key.
        self.use_pair("k1")
        self.assertEqual(pc.decrypt_value(writer_ciphertext, writer_wrapped, AAD, row_ref="r2"), "OTHER-1")


class StartupTests(KeyringCase):
    def prod(self, config):
        return self.use(config)

    def good(self):
        public, _, path = self.new_pair("k1")
        return _config(public, path)

    def test_production_accepts_a_complete_configuration(self):
        self.prod(self.good())  # subject present: no refusal

    def test_production_refuses_missing_or_malformed_settings(self):
        for name, value in (
            ("PII_KEM_PUBLIC_KEY", ""),
            ("PII_KEM_PUBLIC_KEY", "not-a-key"),
            ("PII_KEM_PUBLIC_KEY", "AAAA.BBBB"),
            ("PII_KEM_KEY_ID", ""),
            ("PII_KEM_KEY_ID", "bad id!"),
            ("PII_BLIND_INDEX_KEY", ""),
            ("PII_BLIND_INDEX_KEY", "abcd"),
            ("PII_BLIND_INDEX_KEY", "zz" * 32),
        ):
            config = {**self.good(), name: value}
            with self.subTest(name=name, value=value[:8]), self.assertRaises(RuntimeError):
                self.prod(config)

    def test_reading_process_refuses_missing_or_mismatched_private_key(self):
        config = self.good()
        with self.assertRaises(RuntimeError):
            self.prod({**config, "PII_KEM_PRIVATE_KEY_FILE": os.path.join(self.tmp.name, "absent.key")})
        other_public, _, other_path = self.new_pair("k9")
        with self.assertRaises(RuntimeError):
            self.prod({**config, "PII_KEM_PRIVATE_KEY_FILE": other_path})  # right file shape, wrong pair
        Path(self.tmp.name, "junk.key").write_text("garbage")
        with self.assertRaises(RuntimeError):
            self.prod({**config, "PII_KEM_PRIVATE_KEY_FILE": os.path.join(self.tmp.name, "junk.key")})

    def test_refusal_message_has_no_key_material(self):
        good = self.good()
        valid = good["PII_KEM_PUBLIC_KEY"]
        mlkem_part = valid.split(".")[0]
        bad_keys = {
            "wrong length": "ZmFrZWtleW1hdGVyaWFs.QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
            "bad base64": "!!!notbase64!!!." + valid.split(".")[1],
            "missing dot": mlkem_part,
            "extra dot": valid + ".AAAA",
        }
        for name, bad in bad_keys.items():
            with self.subTest(name):
                with self.assertRaises(pc.PiiKeyConfigError) as caught:
                    pc.parse_public_key(bad, "k1")
                message = str(caught.exception)
                self.assertIn("PII_KEM_PUBLIC_KEY", message)  # the parser's own message
                for piece in (bad[:16], mlkem_part[:16], valid[-16:]):
                    self.assertNotIn(piece, message)
                with self.assertRaises(RuntimeError) as startup:
                    self.prod({**good, "PII_KEM_PUBLIC_KEY": bad})
                self.assertNotIn(bad[:16], str(startup.exception))
                self.assertNotIn(mlkem_part[:16], str(startup.exception))

    def test_development_and_test_generate_throwaway_keys(self):
        for flags in ({"debug": True}, {"testing": True}):
            self.use({"SECRET_KEY": "dev", "PII_KEM_PUBLIC_KEY": ""}, **flags)
            ciphertext, wrapped, key_id = pc.encrypt_value(SECRET, AAD)
            self.assertEqual(key_id, "dev")
            self.assertEqual(pc.decrypt_value(ciphertext, wrapped, AAD, row_ref="r"), SECRET)

    def test_throwaway_keys_refuse_beside_any_other_pii_setting(self):
        names = ("PII_KEM_KEY_ID", "PII_KEM_PRIVATE_KEY_FILE", "PII_KEM_PREVIOUS_PRIVATE_KEY_FILES",
                 "PII_BLIND_INDEX_KEY")
        for name in names:
            for flags in ({"debug": True}, {"testing": True}):
                with self.subTest(name=name, flags=flags):
                    config = {"SECRET_KEY": "dev", "PII_KEM_PUBLIC_KEY": "", name: "LEAKCHECK"}
                    with self.assertRaises(RuntimeError) as caught:
                        self.use(config, **flags)
                    self.assertIn(name, str(caught.exception))
                    self.assertNotIn("LEAKCHECK", str(caught.exception))
        # All blank (what TestConfig sets) still starts, with usable throwaway keys.
        self.use({"SECRET_KEY": "dev", **{n: "" for n in names}, "PII_KEM_PUBLIC_KEY": ""}, testing=True)
        self.assertEqual(pc.current_key_id(), "dev")

    def test_generated_keyset_files(self):
        private = os.path.join(self.tmp.name, "new.key")
        env = os.path.join(self.tmp.name, "env")
        pc.write_new_keyset(private, env)
        self.assertEqual(os.stat(private).st_mode & 0o777, 0o600)
        values = dict(line.rstrip("\n").split("=", 1) for line in Path(env).read_text().splitlines())
        self.assertEqual(set(values), {"PII_KEM_PUBLIC_KEY", "PII_KEM_KEY_ID", "PII_BLIND_INDEX_KEY"})
        self.prod({"SECRET_KEY": "x", **values, "PII_KEM_PRIVATE_KEY_FILE": private})  # a matching pair
        with self.assertRaises(pc.PiiKeyConfigError):
            pc.write_new_keyset(private, os.path.join(self.tmp.name, "env2"))  # never overwrites

    def test_env_file_without_trailing_newline_keeps_its_last_line(self):
        private = os.path.join(self.tmp.name, "nl.key")
        env = os.path.join(self.tmp.name, "env-nl")
        Path(env).write_text("FOO=bar")  # no trailing newline
        pc.write_new_keyset(private, env)
        values = dict(line.split("=", 1) for line in Path(env).read_text().splitlines())
        self.assertEqual(values["FOO"], "bar")
        self.assertEqual(set(values) - {"FOO"}, {"PII_KEM_PUBLIC_KEY", "PII_KEM_KEY_ID", "PII_BLIND_INDEX_KEY"})
        self.assertTrue(Path(env).read_text().endswith("\n"))

    def test_failed_env_append_removes_the_new_private_file(self):
        private = os.path.join(self.tmp.name, "orphan.key")
        env = os.path.join(self.tmp.name, "env-ro")
        Path(env).write_text("FOO=bar\n")
        real_open = open

        def refuse_append(path, mode="r", *args, **kwargs):
            if path == env and "a" in mode:
                raise PermissionError("denied")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", refuse_append), self.assertRaises(pc.PiiKeyConfigError):
            pc.write_new_keyset(private, env)
        self.assertFalse(os.path.exists(private))
        self.assertEqual(Path(env).read_text(), "FOO=bar\n")
        pc.write_new_keyset(private, env)  # the subject works once the append can succeed
        self.assertTrue(os.path.exists(private))


if __name__ == "__main__":
    unittest.main()


class StrayPrivateKeyTests(unittest.TestCase):
    """Owner decision 13: a process that is not configured to read values
    (beat) must not be able to read a private key file at a default path."""

    def _app(self, root, **config):
        app = Flask("stray-key-probe", root_path=str(Path(root) / "app"))
        app.config.update({"PII_KEM_PRIVATE_KEY_FILE": "", **config})
        app.debug = False  # production; the dev container sets FLASK_DEBUG
        app.testing = False
        return app

    def test_production_refuses_a_readable_key_in_the_checkout(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(pc, "DEFAULT_PRIVATE_KEY_PATHS", ()):
            app = self._app(root)
            self.assertEqual(pc.stray_private_key_files(app), [])
            pc._refuse_stray_private_key(app)  # nothing there: starts
            os.makedirs(Path(root) / "private")
            (Path(root) / "private" / "pii_kem_private_key").write_text("key")
            self.assertEqual(len(pc.stray_private_key_files(app)), 1)
            with self.assertRaises(RuntimeError) as raised:
                pc._refuse_stray_private_key(app)
            self.assertIn("not configured to read", str(raised.exception))
            self.assertNotIn("key\n", str(raised.exception))

    def test_a_reader_and_debug_do_not_refuse(self):
        with tempfile.TemporaryDirectory() as root:
            key = Path(root) / "secret"
            key.write_text("key")
            with mock.patch.object(pc, "DEFAULT_PRIVATE_KEY_PATHS", (str(key),)):
                pc._refuse_stray_private_key(self._app(root, PII_KEM_PRIVATE_KEY_FILE=str(key)))  # a reader
                debug = self._app(root)
                debug.debug = True
                with self.assertLogs(debug.logger, level="WARNING"):
                    pc._refuse_stray_private_key(debug)
