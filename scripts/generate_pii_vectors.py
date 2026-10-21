"""Generate the PII envelope cross-implementation vectors.

Spec: docs/policy/pii-envelope-format.md. Writes
``tests/fixtures/pii_envelope_vectors.json``:

- ``deterministic``: TEST-ONLY keys derived from fixed labels (SHA-512 /
  SHA-256 of a public string, so anyone can rebuild them and they are useless
  for real data), blind-index answers, the KEM combiner fixed-input vector
  and the X25519 / HMAC-SHA-512 / ML-KEM reference vectors. Byte-identical on
  every run; ``tests/test_pii_envelope_vectors.py`` regenerates and compares.
- ``vectors``: value and record blobs sealed by ``app/utils/pii_crypto.py``
  with those keys, positive (with the expected plaintext and the KEM
  intermediates) and negative (one input changed; must fail). ML-KEM
  encapsulation, the X25519 ephemeral, DEKs and nonces are random, so these
  differ on every run: regenerate only when the format changes, and commit the
  result as the reference other implementations decrypt.

    python scripts/generate_pii_vectors.py [--out tests/fixtures/pii_envelope_vectors.json]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from scripts.check_pii_blob import ROOT, keyring_from_test_keys, load_pii_crypto, use_keyring
except ImportError:  # run as ``python scripts/generate_pii_vectors.py``
    from check_pii_blob import ROOT, keyring_from_test_keys, load_pii_crypto, use_keyring

OUT = ROOT / "tests" / "fixtures" / "pii_envelope_vectors.json"
FORMAT = "digitva-pii-envelope-vectors/v1"
_LABEL = b"digitva pii envelope TEST VECTOR ONLY "
KEY_IDS = ("tv1", "tv2")

DEATH_ID = uuid.UUID("0d1e0000-0000-4000-8000-000000000001")
TYPE_ID = uuid.UUID("7e9e0000-0000-4000-8000-000000000002")
OTHER_TYPE_ID = uuid.UUID("7e9e0000-0000-4000-8000-000000000003")
TABLE = "map_payload_version_pii"
ROW_1 = uuid.UUID("5e1f0000-0000-4000-8000-000000000011")
ROW_2 = uuid.UUID("5e1f0000-0000-4000-8000-000000000012")

# Payload fields are JSON text, as app/services/payload_pii_accessor.put_pii stores them.
RECORD_1 = {"Id10017": '"Asha"', "Id10018": '"Devi"', "Id10073": '"XXXXXXXXX123"'}
RECORD_UNICODE = {
    "Id10017": '"राम कुमार"',
    "Id10018": '"Zoë é 😀"',
    "naam_नाम": '"field id is UTF-8 in the AAD"',
}
RECORD_EMPTY_STRING = {"Id10017": "", "Id10018": '"x"'}
LONG_TEXT = ("long value 0123456789 अआइ " * 160)[:4000]


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hex(text: str) -> str:
    return text.encode("utf-8").hex()


# ---------------------------------------------------------------------------
# Deterministic section
# ---------------------------------------------------------------------------

def test_keys(pc) -> dict:
    """The fixed TEST keys: seeds are hashes of public labels."""
    entries = []
    for key_id in KEY_IDS:
        seed = hashlib.sha512(_LABEL + b"mlkem768 seed " + key_id.encode()).digest()
        x_private = hashlib.sha256(_LABEL + b"x25519 private " + key_id.encode()).digest()
        private = pc.KemPrivateKey(key_id, seed, x_private)
        public = private.public_key()
        entries.append({
            "key_id": key_id,
            "mlkem_seed_hex": seed.hex(),
            "x25519_private_hex": x_private.hex(),
            "mlkem_public_sha256": hashlib.sha256(public.mlkem).hexdigest(),
            "x25519_public_hex": public.x25519.hex(),
            "private_key_file_text": private.to_file_text(),
            "public_key_config": public.to_config(),
        })
    return {
        "warning": "TEST KEYS ONLY. Derived from public labels; never use for real data.",
        "derivation": {
            "mlkem_seed": "SHA-512(b'digitva pii envelope TEST VECTOR ONLY mlkem768 seed ' || key_id)",
            "x25519_private": "SHA-256(b'digitva pii envelope TEST VECTOR ONLY x25519 private ' || key_id)",
            "blind_index_key": "SHA-256(b'digitva pii envelope TEST VECTOR ONLY blind index key')",
        },
        "current_key_id": KEY_IDS[0],
        "kem_keys": entries,
        "blind_index_key_hex": hashlib.sha256(_LABEL + b"blind index key").hexdigest(),
    }


def _blind_section(pc) -> dict:
    identifier = [
        {"context_hex": TYPE_ID.bytes.hex(), "context_uuid": str(TYPE_ID), "normalised": "MCCD/2026/000123"},
        {"context_hex": OTHER_TYPE_ID.bytes.hex(), "context_uuid": str(OTHER_TYPE_ID), "normalised": "MCCD/2026/000123"},
        {"context_hex": TYPE_ID.bytes.hex(), "context_uuid": str(TYPE_ID), "normalised": "राम-१२"},
    ]
    for item in identifier:
        item["index_hex"] = pc.blind_index(bytes.fromhex(item["context_hex"]), item["normalised"])
    classes = [
        {"class": "phone", "normalised": "9876543210"},
        {"class": "phone", "normalised": ""},
        {"class": "abha_number", "normalised": "12345678901234"},
        {"class": "abha_address", "normalised": "asha.devi@abdm"},
        {"class": "payload-fp", "normalised": "12345678901234"},
    ]
    for item in classes:
        item["index_hex"] = pc.class_index(item["class"], item["normalised"])
    return {
        "subkeys": {label: pc.subkey(label).hex() for label in sorted(pc.BLIND_INDEX_CLASSES)},
        "identifier": identifier,
        "class": classes,
        "blind_key_id": pc.blind_key_id(),
    }


def _combiner_section(pc) -> dict:
    inputs = {
        "ss_mlkem_hex": bytes(range(32)).hex(),
        "ss_x25519_hex": bytes(range(32, 64)).hex(),
        "key_id": "k1",
        "mlkem_ct_hex": (b"\x01" * 1088).hex(),
        "eph_pub_hex": (b"\x02" * 32).hex(),
        "mlkem_pub_hex": (b"\x03" * 1184).hex(),
        "x25519_pub_hex": (b"\x04" * 32).hex(),
    }
    args = [bytes.fromhex(v) if k != "key_id" else v for k, v in inputs.items()]
    return {"inputs": inputs, "kek_hex": pc.combine(*args).hex()}


def _reference_section() -> dict:
    kat = json.loads((ROOT / "tests" / "fixtures" / "mlkem768_kat.json").read_text())
    return {
        "x25519_rfc7748_6_1": {
            "alice_private_hex": "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a",
            "bob_public_hex": "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f",
            "shared_hex": "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742",
        },
        "hmac_sha512_rfc4231": [
            {"case": 1, "key_hex": "0b" * 20, "data_hex": b"Hi There".hex(),
             "mac_hex": "87aa7cdea5ef619d4ff0b4241a1d6cb02379f4e2ce4ec2787ad0b30545e17cde"
                        "daa833b7d6b8a702038b274eaea3f4e4be9d914eeb61f1702e696c203a126854"},
            {"case": 2, "key_hex": b"Jefe".hex(), "data_hex": b"what do ya want for nothing?".hex(),
             "mac_hex": "164b7a7bfcf819e2e395fbe73b56e0a387bd64222e831fd610270cd7ea250554"
                        "9758bf75c05a994a6d034f65f8f0e6fdcaeab1a34d4a6b4b636e070a38bce737"},
        ],
        "mlkem768_pinned": {k: kat[k] for k in ("seed", "public_sha256", "ciphertext", "shared_secret")},
    }


def build_deterministic(pc) -> dict:
    keys = test_keys(pc)
    with use_keyring(keyring_from_test_keys(pc, keys)):
        return {
            "test_keys": keys,
            "blind_index": _blind_section(pc),
            "combiner": _combiner_section(pc),
            "reference": _reference_section(),
        }


# ---------------------------------------------------------------------------
# Sealed vectors (random)
# ---------------------------------------------------------------------------

def _intermediate(pc, keyring, dek_wrapped: str) -> dict:
    """The KEM steps of *dek_wrapped*, recomputed from the spec layout and
    checked against ``unwrap_dek``, so a second implementation can test each."""
    _, _, key_id, blob = dek_wrapped.split(":", 3)
    raw = _b64d(blob)
    ct_m, eph, nonce, wrapped = raw[:1088], raw[1088:1120], raw[1120:1132], raw[1132:]
    m_key, x_key, m_pub, x_pub = keyring.private[key_id].kem_objects
    ss_m = m_key.decapsulate(ct_m)
    ss_x = x_key.exchange(x25519.X25519PublicKey.from_public_bytes(eph))
    kek = pc.combine(ss_m, ss_x, key_id, ct_m, eph, m_pub, x_pub)
    dek = AESGCM(kek).decrypt(nonce, wrapped, f"{key_id}|{pc.WRAP_ALG}".encode("ascii"))
    if dek != pc.unwrap_dek(dek_wrapped, row_ref="generator"):
        raise AssertionError("spec layout disagrees with unwrap_dek")
    return {"ss_mlkem_hex": ss_m.hex(), "ss_x25519_hex": ss_x.hex(), "kek_hex": kek.hex(),
            "wrap_nonce_hex": nonce.hex(), "dek_hex": dek.hex()}


def _mutate(blob: str, fn) -> str:
    """*blob* with its base64url payload replaced by ``fn(raw)``."""
    head, _, tail = blob.rpartition(":")
    return head + ":" + _b64e(fn(_b64d(tail)))


def _flip(index: int):
    def fn(raw: bytes) -> bytes:
        out = bytearray(raw)
        out[index] ^= 0x01
        return bytes(out)
    return fn


def _value(vid, description, plaintext, aad, pc, keyring):
    ciphertext, wrapped, key_id = pc.encrypt_value(plaintext, aad)
    return {
        "id": vid, "kind": "value", "description": description, "current_key_id": keyring.public.key_id,
        "key_id": key_id, "aad_hex": aad.hex(), "value_ciphertext": ciphertext, "dek_wrapped": wrapped,
        "row_ref": vid, "expect": "ok", "plaintext": plaintext, "plaintext_hex": _hex(plaintext),
        "intermediate": _intermediate(pc, keyring, wrapped),
    }


def _record(vid, description, fields, row_id, pc, keyring, *, only=None):
    sealed, wrapped, key_id = pc.seal_record(dict(fields), table=TABLE, row_id=row_id.bytes)
    return _record_entry(vid, description, sealed, wrapped, key_id, row_id, fields, pc, keyring, only=only)


def _record_entry(vid, description, sealed, wrapped, key_id, row_id, fields, pc, keyring, *, only=None):
    opened = fields if only is None else {n: fields[n] for n in only if n in fields}
    entry = {
        "id": vid, "kind": "record", "description": description, "current_key_id": keyring.public.key_id,
        "key_id": key_id, "table": TABLE, "row_id_hex": row_id.bytes.hex(), "row_id_uuid": str(row_id),
        "sealed": sealed, "dek_wrapped": wrapped, "only": only, "row_ref": vid, "expect": "ok",
        "plaintext": opened, "plaintext_hex": {n: _hex(t) for n, t in opened.items()},
    }
    if wrapped.startswith(pc.WRAP_PREFIX):
        entry["intermediate"] = _intermediate(pc, keyring, wrapped)
    return entry


def _fail(base: dict, vid: str, mutation: str, **changes) -> dict:
    entry = {k: v for k, v in base.items() if k not in ("plaintext", "plaintext_hex", "intermediate")}
    entry.update(changes, id=vid, description=mutation, row_ref=vid, expect="fail")
    return entry


def build_sealed(pc, keys: dict) -> list[dict]:
    ring_1 = keyring_from_test_keys(pc, keys, "tv1")
    ring_2 = keyring_from_test_keys(pc, keys, "tv2")
    vectors = []
    with use_keyring(ring_1):
        aad = DEATH_ID.bytes + TYPE_ID.bytes
        value = _value("value-identifier", "per-value API, identifier AAD death_id || type_id",
                       "MCCD/2026/000123", aad, pc, ring_1)
        other_value = _value("value-identifier-2", "a second value under the same AAD (fresh DEK)",
                             "MCCD/2026/000999", aad, pc, ring_1)
        vectors += [
            value, other_value,
            _value("value-unicode", "UTF-8, a decomposed e + U+0301 kept as is (no normalisation), emoji",
                   "Zoë é राम 😀", aad, pc, ring_1),
            _value("value-empty", "empty plaintext: the ciphertext is the 16-byte tag only", "", aad, pc, ring_1),
        ]
        rec = _record("record-multi", "three payload fields under one DEK", RECORD_1, ROW_1, pc, ring_1)
        rec_2 = _record("record-other-row", "the same fields sealed for another row", RECORD_1, ROW_2, pc, ring_1)
        vectors += [
            rec, rec_2,
            _record("record-unicode", "UTF-8 values and a non-ASCII field id", RECORD_UNICODE, ROW_1, pc, ring_1),
            _record("record-empty-string", "an empty-string field beside a non-empty one",
                    RECORD_EMPTY_STRING, ROW_1, pc, ring_1),
            _record("record-long", "a 4000-character mixed-script value", {"Id10476": LONG_TEXT}, ROW_1, pc, ring_1),
            _record("record-empty", "no fields: still one wrapped DEK", {}, ROW_1, pc, ring_1),
            _record_entry("record-only", "open only Id10018 (and an absent name, skipped)", rec["sealed"],
                          rec["dek_wrapped"], "tv1", ROW_1, RECORD_1, pc, ring_1, only=["Id10018", "absent"]),
        ]
        # Python opens nothing, and so unwraps nothing, when no field is asked for.
        vectors.append(dict(
            _record_entry("record-only-none-bogus-wrap", "only=[] never unwraps: a garbage dek_wrapped passes",
                          rec["sealed"], "nonsense", "tv1", ROW_1, RECORD_1, pc, ring_1, only=[]),
            conformance="implementation-defined"))
        # Hand-built: authentic AES-GCM over bytes that are not UTF-8.
        dek, nonce = os.urandom(32), os.urandom(12)
        bad_utf8 = "v1:aes256gcm:" + _b64e(nonce + AESGCM(dek).encrypt(nonce, b"\xff\xfe\xfd", aad))
        non_utf8 = dict(value, value_ciphertext=bad_utf8, dek_wrapped=pc.wrap_dek(dek, ring_1.public))
    with use_keyring(ring_2):
        vectors.append(_record("record-key-tv2", "sealed while tv2 is the current key", RECORD_1, ROW_1, pc, ring_2))
        rewrapped, key_id = pc.rewrap_dek(rec["dek_wrapped"], row_ref="generator")
        vectors.append(_record_entry("record-rewrapped-tv2", "record-multi's fields, DEK re-wrapped to tv2",
                                     rec["sealed"], rewrapped, key_id, ROW_1, RECORD_1, pc, ring_2))

    v_ct, v_w = value["value_ciphertext"], value["dek_wrapped"]
    tag_end = len(_b64d(v_ct.rpartition(":")[2])) - 1
    vectors += [
        _fail(value, "fail-value-aad-other-type", "AAD with another identifier type id",
              aad_hex=(DEATH_ID.bytes + OTHER_TYPE_ID.bytes).hex()),
        _fail(value, "fail-value-aad-reversed", "AAD halves swapped: type_id || death_id",
              aad_hex=(TYPE_ID.bytes + DEATH_ID.bytes).hex()),
        _fail(value, "fail-value-aad-empty", "empty AAD", aad_hex=""),
        _fail(value, "fail-value-nonce-flipped", "one bit of the data nonce flipped",
              value_ciphertext=_mutate(v_ct, _flip(0))),
        _fail(value, "fail-value-ct-flipped", "one bit of the data ciphertext flipped",
              value_ciphertext=_mutate(v_ct, _flip(12))),
        _fail(value, "fail-value-tag-flipped", "one bit of the GCM tag flipped",
              value_ciphertext=_mutate(v_ct, _flip(tag_end))),
        _fail(value, "fail-value-truncated", "nonce || ciphertext cut to 27 bytes (shorter than nonce + tag)",
              value_ciphertext=_mutate(v_ct, lambda raw: raw[:27])),
        _fail(value, "fail-value-empty-payload", "nothing after the prefix", value_ciphertext="v1:aes256gcm:"),
        _fail(value, "fail-value-version", "unknown data version v2",
              value_ciphertext=v_ct.replace("v1:", "v2:", 1)),
        _fail(value, "fail-value-alg", "unknown data algorithm",
              value_ciphertext=v_ct.replace("aes256gcm", "chacha20poly1305", 1)),
        _fail(value, "fail-value-prefix-case", "prefix in upper case", value_ciphertext=v_ct.replace("v1:", "V1:", 1)),
        _fail(value, "fail-value-non-utf8", "authentic AES-GCM over bytes that are not UTF-8",
              value_ciphertext=non_utf8["value_ciphertext"], dek_wrapped=non_utf8["dek_wrapped"]),
        _fail(value, "fail-value-dek-of-other-value", "the wrapped DEK of another value",
              dek_wrapped=other_value["dek_wrapped"]),
        _fail(value, "fail-wrap-version", "unknown wrap version v2", dek_wrapped=v_w.replace("v1:", "v2:", 1)),
        _fail(value, "fail-wrap-alg", "unknown wrap algorithm (ML-KEM-1024)",
              dek_wrapped=v_w.replace("mlkem768x25519", "mlkem1024x25519", 1)),
        _fail(value, "fail-wrap-unknown-key-id", "key id no private key is held for",
              dek_wrapped=v_w.replace(":tv1:", ":tvx:", 1)),
        _fail(value, "fail-wrap-relabelled-key-id", "tv1 blob labelled tv2 (a held key: the combiner and wrap AAD bind the id)",
              dek_wrapped=v_w.replace(":tv1:", ":tv2:", 1)),
        _fail(value, "fail-wrap-mlkem-ct-flipped", "one bit of the ML-KEM ciphertext flipped (implicit rejection)",
              dek_wrapped=_mutate(v_w, _flip(0))),
        _fail(value, "fail-wrap-eph-flipped", "one bit of the X25519 ephemeral public key flipped",
              dek_wrapped=_mutate(v_w, _flip(1088))),
        _fail(value, "fail-wrap-eph-low-order", "X25519 ephemeral public key all zero (low order)",
              dek_wrapped=_mutate(v_w, lambda raw: raw[:1088] + bytes(32) + raw[1120:])),
        _fail(value, "fail-wrap-nonce-flipped", "one bit of the wrap nonce flipped",
              dek_wrapped=_mutate(v_w, _flip(1120))),
        _fail(value, "fail-wrap-dek-flipped", "one bit of the wrapped DEK flipped",
              dek_wrapped=_mutate(v_w, _flip(1132))),
        _fail(value, "fail-wrap-truncated", "wrap blob one byte short (1179)",
              dek_wrapped=_mutate(v_w, lambda raw: raw[:-1])),
        _fail(value, "fail-wrap-extended", "wrap blob one byte long (1181)",
              dek_wrapped=_mutate(v_w, lambda raw: raw + b"\x00")),
        _fail(value, "fail-wrap-garbage", "not a blob at all", value_ciphertext="nonsense", dek_wrapped="nonsense"),
    ]
    sealed = rec["sealed"]
    other = rec_2["sealed"]
    vectors += [
        _fail(rec, "fail-record-other-table", "opened as another table", table="va_death_register"),
        _fail(rec, "fail-record-other-row", "opened with another row id", row_id_hex=ROW_2.bytes.hex()),
        _fail(rec, "fail-record-renamed-field", "a field ciphertext stored under another field id",
              sealed={**sealed, "Id10099": sealed["Id10017"]}, only=["Id10099"]),
        _fail(rec, "fail-record-swapped-fields", "two field ciphertexts swapped",
              sealed={**sealed, "Id10017": sealed["Id10018"], "Id10018": sealed["Id10017"]}),
        _fail(rec, "fail-record-field-from-other-record", "Id10017 taken from the same fields sealed for another row",
              sealed={**sealed, "Id10017": other["Id10017"]}),
        _fail(rec, "fail-record-field-flipped", "one bit of one field ciphertext flipped",
              sealed={**sealed, "Id10018": _mutate(sealed["Id10018"], _flip(14))}),
        _fail(rec, "fail-record-field-version", "one field with an unknown version",
              sealed={**sealed, "Id10073": sealed["Id10073"].replace("v1:", "v2:", 1)}),
        _fail(rec, "fail-record-other-records-dek", "the fields under another record's wrapped DEK",
              dek_wrapped=rec_2["dek_wrapped"]),
        _fail(rec, "fail-record-unknown-key-id", "wrapped DEK with an unknown key id",
              dek_wrapped=rec["dek_wrapped"].replace(":tv1:", ":tvx:", 1)),
    ]
    return vectors


RUST_TO_PYTHON = {
    "description": (
        "A second implementation proves its writer by emitting a file with this file's shape: "
        "{\"format\": \"" + FORMAT + "\", \"producer\": \"<name and version>\", \"vectors\": [...]}, "
        "each vector sealed with the test keys of deterministic.test_keys (current_key_id names the "
        "wrapping key), kind value or record, expect ok with the plaintext it sealed, plus any negative "
        "vectors with expect fail. Then run: python scripts/check_pii_blob.py <file> "
        "--keys tests/fixtures/pii_envelope_vectors.json. Exit 0 means every blob opened in Python as "
        "expected; the output is counts and failing ids only."
    ),
    "value_vector_fields": ["id", "kind=value", "current_key_id", "aad_hex", "value_ciphertext",
                            "dek_wrapped", "row_ref", "expect", "plaintext", "plaintext_hex (optional)",
                            "intermediate.dek_hex (optional)"],
    "record_vector_fields": ["id", "kind=record", "current_key_id", "table", "row_id_hex", "sealed",
                             "dek_wrapped", "only (null or list)", "row_ref", "expect", "plaintext",
                             "plaintext_hex (optional)", "intermediate.dek_hex (optional)"],
    "id_rule": "^[a-z0-9][a-z0-9-]{0,63}$ (other ids are reported by position)",
    "skip_rule": "a reader MAY skip vectors with conformance = implementation-defined",
}


def build_all(pc) -> dict:
    deterministic = build_deterministic(pc)
    return {
        "format": FORMAT,
        "warning": "TEST KEYS AND FICTIONAL DATA ONLY. Never put real keys or real personal data here.",
        "spec": "docs/policy/pii-envelope-format.md",
        "generator": "scripts/generate_pii_vectors.py",
        "checker": "scripts/check_pii_blob.py",
        "producer": "app/utils/pii_crypto.py (Python, cryptography)",
        "deterministic": deterministic,
        "vectors": build_sealed(pc, deterministic["test_keys"]),
        "rust_to_python": RUST_TO_PYTHON,
    }


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    Path(args.out).write_text(dumps(build_all(load_pii_crypto())), encoding="utf-8")
    print(f"generate_pii_vectors: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
