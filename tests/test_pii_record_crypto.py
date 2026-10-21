"""app/utils/pii_crypto.py record API: one DEK per record, DEK cache, HKDF
class subkeys (PII slice 1b part I).

Policy: docs/policy/pii-encryption-at-rest.md, "Keys and blind indexes" and
"Tests". No database: a throwaway Flask app per test carries the keyring.
"""
import hashlib
import hmac
import logging
import uuid
from unittest import mock

from flask import g

from app.utils import pii_crypto as pc
from tests.test_pii_crypto import KeyringCase, _CaptureHandler, _config

TABLE = "map_payload_version_pii"
FIELDS = {"Id10017": '"Asha"', "Id10018": '"Devi"', "Id10073": '"XXXXXXXXX123"'}
BLIND = "ab" * 32

# Pinned with BLIND as the master key; recomputed independently below too.
SUBKEY_KAT = {
    "phone": (
        "e5a8bab5bbc8e2611254c565af3a7c2559173c4957b0680a9b4b744eb9df85cc"
        "9bdf177bdbb45d46bafca4f459a6e77fe38e063f17a6bb588f6362b4f2f224cc"
    ),
}


def _hkdf_sha256(ikm: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 by hand (salt absent = HashLen zero bytes)."""
    prk = hmac.new(b"\x00" * 32, ikm, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


class RecordCase(KeyringCase):
    def setUp(self):
        super().setUp()
        self.use_pair("k1", blind=BLIND)
        self.row_id = uuid.uuid4().bytes

    def seal(self, fields=FIELDS, row_id=None):
        return pc.seal_record(dict(fields), table=TABLE, row_id=row_id or self.row_id)

    def open(self, sealed, wrapped, row_id=None, table=TABLE, **kwargs):
        return pc.open_record(
            sealed, wrapped, table=table, row_id=row_id or self.row_id, row_ref="v-1", **kwargs
        )


class RecordRoundTripTests(RecordCase):
    def test_round_trip_and_stored_forms(self):
        sealed, wrapped, key_id = self.seal()
        self.assertEqual(key_id, "k1")
        self.assertEqual(set(sealed), set(FIELDS))
        for value in sealed.values():
            self.assertTrue(value.startswith("v1:aes256gcm:"))
        self.assertTrue(wrapped.startswith("v1:aes256gcm+mlkem768x25519:k1:"))
        blob = "".join(sealed.values()) + wrapped
        for plain in ("Asha", "Devi", "XXXXXXXXX123"):
            self.assertNotIn(plain, blob)
        self.assertEqual(self.open(sealed, wrapped), FIELDS)

    def test_open_only_named_fields(self):
        sealed, wrapped, _ = self.seal()
        self.assertEqual(self.open(sealed, wrapped, only=["Id10018", "absent"]), {"Id10018": '"Devi"'})
        self.assertEqual(self.open(sealed, wrapped, only=[]), {})

    def test_empty_record_seals_and_opens(self):
        sealed, wrapped, _ = self.seal({})
        self.assertEqual(sealed, {})
        self.assertTrue(wrapped.startswith("v1:aes256gcm+mlkem768x25519:k1:"))
        self.assertEqual(self.open(sealed, wrapped), {})

    def test_one_dek_per_record_one_wrap(self):
        with mock.patch.object(pc, "wrap_dek", wraps=pc.wrap_dek) as spy:
            sealed, wrapped, _ = self.seal()
        self.assertEqual(spy.call_count, 1)
        # Every field opens under the single wrapped DEK, each with its own nonce.
        self.assertEqual(self.open(sealed, wrapped), FIELDS)
        nonces = {pc._b64d(value.rpartition(":")[2])[:12] for value in sealed.values()}
        self.assertEqual(len(nonces), len(FIELDS))
        # A second record draws a fresh DEK.
        _, wrapped_2, _ = self.seal()
        self.assertNotEqual(wrapped, wrapped_2)

    def test_field_moved_to_another_record_or_field_fails(self):
        sealed, wrapped, _ = self.seal()
        other_row = uuid.uuid4().bytes
        # The same record opens (the failure below is the AAD).
        self.assertEqual(self.open(sealed, wrapped)["Id10017"], '"Asha"')
        cases = {
            "another record": dict(row_id=other_row),
            "another table": dict(table="va_death_register"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(pc.PiiCryptoError):
                self.open(sealed, wrapped, **kwargs)
        swapped = dict(sealed, Id10017=sealed["Id10018"])  # column swapped
        with self.assertRaises(pc.PiiCryptoError):
            self.open(swapped, wrapped, only=["Id10017"])
        # A field from another record under this record's DEK.
        sealed_2, _, _ = self.seal(row_id=other_row)
        with self.assertRaises(pc.PiiCryptoError):
            self.open(dict(sealed, Id10017=sealed_2["Id10017"]), wrapped, only=["Id10017"])

    def test_tamper_and_unknown_versions_raise_generic_error(self):
        sealed, wrapped, _ = self.seal()
        value = sealed["Id10017"]
        head, _, tail = value.rpartition(":")
        flipped = head + ":" + ("A" if tail[10] != "A" else "B").join([tail[:10], tail[11:]])
        cases = {
            "tampered field": (dict(sealed, Id10017=flipped), wrapped),
            "unknown field version": (dict(sealed, Id10017=value.replace("v1:", "v9:", 1)), wrapped),
            "unknown field alg": (dict(sealed, Id10017=value.replace("aes256gcm", "chacha", 1)), wrapped),
            "unknown wrap version": (sealed, wrapped.replace("v1:", "v9:", 1)),
            "unknown key id": (sealed, wrapped.replace(":k1:", ":zz:", 1)),
            "garbage": ({"Id10017": "nonsense"}, "nonsense"),
        }
        for name, (blob, dek) in cases.items():
            g.pop(pc._DEK_CACHE_ATTR, None)
            with self.subTest(name), self.assertRaises(pc.PiiCryptoError) as caught:
                self.open(blob, dek, only=["Id10017"])
            message = str(caught.exception)
            self.assertIn("v-1", message)
            for secret in ("Asha", value, tail, wrapped.rpartition(":")[2]):
                self.assertNotIn(secret, message)

    def test_failures_log_nothing_sensitive(self):
        public, private, _ = self.pairs["k1"]
        sealed, wrapped, _ = self.seal()
        handler = _CaptureHandler()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.setLevel, previous_level)
        self.addCleanup(root.removeHandler, handler)
        with self.assertRaises(pc.PiiCryptoError):
            self.open(sealed, wrapped, row_id=uuid.uuid4().bytes)
        logging.getLogger("app.probe").debug("capture-sentinel")
        text = "\n".join(handler.lines)
        self.assertIn("capture-sentinel", text)
        for secret in (
            "Asha", "Devi", wrapped.rpartition(":")[2], sealed["Id10017"].rpartition(":")[2],
            public.to_config()[:40], private.to_file_text().split(":")[1][:40], BLIND,
        ):
            self.assertNotIn(secret, text)


class DekCacheTests(RecordCase):
    def test_second_open_of_a_record_does_not_unwrap_again(self):
        sealed, wrapped, _ = self.seal()
        with mock.patch.object(pc, "unwrap_dek", wraps=pc.unwrap_dek) as spy:
            self.open(sealed, wrapped, only=["Id10017"])
            self.open(sealed, wrapped, only=["Id10018"])
            self.assertEqual(spy.call_count, 1)
            pc.clear_dek_cache()
            self.open(sealed, wrapped)
            self.assertEqual(spy.call_count, 2)

    def test_cache_is_per_app_context(self):
        sealed, wrapped, _ = self.seal()
        self.open(sealed, wrapped)
        self.assertIn(wrapped, g.get(pc._DEK_CACHE_ATTR))
        self.use_pair("k1", blind=BLIND)  # a new app context: a new request
        self.assertIsNone(g.get(pc._DEK_CACHE_ATTR))

    def test_cache_is_bounded(self):
        records = [self.seal({"f": '"x"'}) for _ in range(4)]
        with mock.patch.object(pc, "DEK_CACHE_MAX", 3):
            for sealed, wrapped, _ in records:
                self.open(sealed, wrapped)
            cache = g.get(pc._DEK_CACHE_ATTR)
            self.assertEqual(len(cache), 3)
            self.assertNotIn(records[0][1], cache)  # the oldest went first
            self.assertIn(records[3][1], cache)

    def test_failed_unwrap_is_not_cached(self):
        sealed, wrapped, _ = self.seal()
        with self.assertRaises(pc.PiiCryptoError):
            self.open(sealed, wrapped.replace(":k1:", ":zz:", 1))
        self.assertEqual(g.get(pc._DEK_CACHE_ATTR), {})

    def test_private_key_objects_built_once(self):
        sealed, wrapped, _ = self.seal()
        private = pc._keyring().private["k1"]
        self.assertIs(private.kem_objects, private.kem_objects)
        with mock.patch.object(pc.mlkem.MLKEM768PrivateKey, "from_seed_bytes") as built:
            pc.unwrap_dek(wrapped, row_ref="v-1")
            pc.unwrap_dek(wrapped, row_ref="v-1")
        built.assert_not_called()


class RecordKeyTests(RecordCase):
    def test_public_key_only_process_seals_but_cannot_open(self):
        public, _, _ = self.pairs["k1"]
        self.use(_config(public, "", blind=BLIND), testing=True)  # no private key file
        sealed, wrapped, key_id = self.seal()
        self.assertEqual(key_id, "k1")
        with self.assertRaises(pc.PiiCryptoError):
            self.open(sealed, wrapped)
        self.use_pair("k1", blind=BLIND)
        self.assertEqual(self.open(sealed, wrapped), FIELDS)

    def test_rewrap_leaves_field_ciphertexts_byte_identical(self):
        sealed, wrapped, _ = self.seal()
        before = dict(sealed)
        self.use_pair("k2", previous=("k1",), blind=BLIND)
        new_wrapped, new_key = pc.rewrap_dek(wrapped, row_ref="v-1")
        self.assertEqual(new_key, "k2")
        self.assertTrue(new_wrapped.startswith("v1:aes256gcm+mlkem768x25519:k2:"))
        self.use_pair("k2", blind=BLIND)  # the old private key is gone
        self.assertEqual(sealed, before)
        self.assertEqual(self.open(sealed, new_wrapped), FIELDS)
        with self.assertRaises(pc.PiiCryptoError):
            self.open(sealed, wrapped)


class ClassSubkeyTests(RecordCase):
    def test_hkdf_subkey_known_answer_per_class(self):
        for label in sorted(pc.BLIND_INDEX_CLASSES):
            with self.subTest(label):
                expected = _hkdf_sha256(bytes.fromhex(BLIND), b"digitva-pii-bidx/v1/" + label.encode(), 64)
                self.assertEqual(pc.subkey(label), expected)
                self.assertEqual(
                    pc.class_index(label, "9876543210"),
                    hmac.new(expected, b"9876543210", hashlib.sha512).hexdigest(),
                )
        self.assertEqual(pc.subkey("phone").hex(), SUBKEY_KAT["phone"])

    def test_classes_separate_and_identifier_index_unchanged(self):
        value = "12345678901234"
        indexes = {label: pc.class_index(label, value) for label in pc.BLIND_INDEX_CLASSES}
        self.assertEqual(len(set(indexes.values())), len(indexes))
        context = uuid.uuid4().bytes
        legacy = hmac.new(bytes.fromhex(BLIND), context + b"\x00" + value.encode(), hashlib.sha512).hexdigest()
        self.assertEqual(pc.blind_index(context, value), legacy)
        self.assertNotIn(legacy, indexes.values())

    def test_unknown_class_refused(self):
        for label in ("aadhaar", "identifier", "", "Phone"):
            with self.subTest(label), self.assertRaises(ValueError):
                pc.class_index(label, "1")

    def test_blind_key_id(self):
        self.assertEqual(pc.blind_key_id(), hashlib.sha256(bytes.fromhex(BLIND)).hexdigest()[:8])
