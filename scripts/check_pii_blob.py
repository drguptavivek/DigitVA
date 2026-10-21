"""Check PII envelope blobs against ``app/utils/pii_crypto.py`` with TEST keys.

Spec: docs/policy/pii-envelope-format.md. Reads a vectors-style JSON file
(``tests/fixtures/pii_envelope_vectors.json`` or one emitted by another
implementation in the same shape), opens every sealed vector with the test
keys it names and checks the expected plaintext or the expected failure, then
checks the deterministic section (blind indexes, combiner, reference vectors)
when the file has one. Prints counts and failing vector ids only: never a
plaintext, ciphertext or key. Exit code 0 when everything matches, 1 otherwise.

    python scripts/check_pii_blob.py tests/fixtures/pii_envelope_vectors.json
    python scripts/check_pii_blob.py rust_vectors.json --keys tests/fixtures/pii_envelope_vectors.json

Never point it at real keys: the keys come from the JSON file, never from the
app configuration. Loads ``app/utils/pii_crypto.py`` by path, so it needs only
``cryptography`` and ``flask``, not the Flask app.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PII_CRYPTO_PATH = ROOT / "app" / "utils" / "pii_crypto.py"
DEFAULT_KEYS = ROOT / "tests" / "fixtures" / "pii_envelope_vectors.json"
_MODULE_NAME = "pii_crypto_vectors"
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def load_pii_crypto():
    """``app/utils/pii_crypto.py`` loaded by path, once per process."""
    module = sys.modules.get(_MODULE_NAME)
    if module is None:
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, PII_CRYPTO_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module  # dataclasses resolve annotations through it
        spec.loader.exec_module(module)
    return module


def keyring_from_test_keys(pc, test_keys: dict, current_key_id: str | None = None):
    """A ``Keyring`` holding every test KEM key of *test_keys* (current one
    *current_key_id*, default ``test_keys["current_key_id"]``) and the test
    blind key. Each key's file text and public config must agree with its hex
    fields and with each other, so a vectors file cannot carry a mismatched
    pair. Raises ``ValueError`` (or ``PiiKeyConfigError``) when they do not."""
    private, public = {}, {}
    for entry in test_keys["kem_keys"]:
        key = pc.parse_private_key(entry["private_key_file_text"])
        pub = pc.parse_public_key(entry["public_key_config"], entry["key_id"])
        if (
            key.key_id != entry["key_id"]
            or key.mlkem_seed.hex() != entry["mlkem_seed_hex"]
            or key.x25519.hex() != entry["x25519_private_hex"]
            or key.public_key() != pub
        ):
            raise ValueError("test key entry is inconsistent")
        private[key.key_id], public[key.key_id] = key, pub
    current = current_key_id or test_keys["current_key_id"]
    return pc.Keyring(public[current], private, pc.parse_blind_key(test_keys["blind_index_key_hex"]))


@contextmanager
def use_keyring(keyring):
    """An app context of a bare Flask app carrying *keyring*: what
    ``pii_crypto`` reads its keys from. Touches no app configuration."""
    from flask import Flask

    app = Flask("pii-envelope-vectors")
    app.extensions["pii_keyring"] = keyring
    with app.app_context():
        yield


def _open(pc, vector: dict):
    if vector["kind"] == "value":
        return pc.decrypt_value(
            vector["value_ciphertext"], vector["dek_wrapped"], bytes.fromhex(vector["aad_hex"]),
            row_ref=vector["row_ref"],
        )
    if vector["kind"] == "record":
        return pc.open_record(
            vector["sealed"], vector["dek_wrapped"], table=vector["table"],
            row_id=bytes.fromhex(vector["row_id_hex"]), row_ref=vector["row_ref"],
            only=vector.get("only"),
        )
    raise ValueError("unknown vector kind")


def _generic_message(vector: dict) -> re.Pattern:
    return re.compile(
        r"PII value could not be decrypted \(row " + re.escape(vector["row_ref"])
        + r", key ([A-Za-z0-9_-]{1,16}|\?)\)\."
    )


def check_vector(pc, vector: dict) -> bool:
    """True when *vector* behaves as it says: ``expect: ok`` opens to its
    ``plaintext`` (and ``plaintext_hex`` / ``intermediate.dek_hex`` when
    given); ``expect: fail`` raises exactly ``PiiCryptoError`` with the one
    generic message. Any other exception is a failed check."""
    pc.clear_dek_cache()
    try:
        if vector["expect"] == "fail":
            try:
                _open(pc, vector)
            except pc.PiiCryptoError as exc:
                return bool(_generic_message(vector).fullmatch(str(exc)))
            return False
        if vector["expect"] != "ok":
            return False
        got = _open(pc, vector)
        if got != vector["plaintext"]:
            return False
        hexed = vector.get("plaintext_hex")
        if hexed is not None:
            have = got.encode("utf-8").hex() if vector["kind"] == "value" else {
                name: text.encode("utf-8").hex() for name, text in got.items()
            }
            if have != hexed:
                return False
        dek_hex = (vector.get("intermediate") or {}).get("dek_hex")
        if dek_hex is not None and pc.unwrap_dek(vector["dek_wrapped"], row_ref=vector["row_ref"]).hex() != dek_hex:
            return False
        return True
    except Exception:  # a malformed vector or an unexpected error: a failed check, no detail
        return False


def _deterministic_checks(pc, det: dict):
    """``(name, passed)`` for every deterministic expectation in *det*."""
    from cryptography.hazmat.primitives.asymmetric import mlkem, x25519

    def run(name, fn):
        try:
            return name, bool(fn())
        except Exception:
            return name, False

    checks = []
    bidx = det.get("blind_index", {})
    if "blind_key_id" in bidx:
        checks.append(run("blind_key_id", lambda: pc.blind_key_id() == bidx["blind_key_id"]))
    for i, item in enumerate(bidx.get("identifier", [])):
        checks.append(run(f"identifier-{i}", lambda item=item: pc.blind_index(
            bytes.fromhex(item["context_hex"]), item["normalised"]) == item["index_hex"]))
    for label, item in sorted(bidx.get("subkeys", {}).items()):
        checks.append(run(f"subkey-{label}", lambda label=label, item=item: pc.subkey(label).hex() == item))
    for i, item in enumerate(bidx.get("class", [])):
        checks.append(run(f"class-{i}", lambda item=item: pc.class_index(
            item["class"], item["normalised"]) == item["index_hex"]))
    comb = det.get("combiner")
    if comb:
        def combiner():
            args = [bytes.fromhex(comb["inputs"][k]) if k != "key_id" else comb["inputs"][k] for k in (
                "ss_mlkem_hex", "ss_x25519_hex", "key_id", "mlkem_ct_hex", "eph_pub_hex",
                "mlkem_pub_hex", "x25519_pub_hex")]
            return pc.combine(*args).hex() == comb["kek_hex"]
        checks.append(run("combiner", combiner))
    ref = det.get("reference", {})
    if "x25519_rfc7748_6_1" in ref:
        r = ref["x25519_rfc7748_6_1"]
        checks.append(run("x25519-rfc7748", lambda: x25519.X25519PrivateKey.from_private_bytes(
            bytes.fromhex(r["alice_private_hex"])).exchange(x25519.X25519PublicKey.from_public_bytes(
                bytes.fromhex(r["bob_public_hex"]))).hex() == r["shared_hex"]))
    for i, r in enumerate(ref.get("hmac_sha512_rfc4231", [])):
        checks.append(run(f"hmac-rfc4231-{i}", lambda r=r: hmac.new(
            bytes.fromhex(r["key_hex"]), bytes.fromhex(r["data_hex"]), hashlib.sha512).hexdigest() == r["mac_hex"]))
    if "mlkem768_pinned" in ref:
        r = ref["mlkem768_pinned"]

        def mlkem_kat():
            sk = mlkem.MLKEM768PrivateKey.from_seed_bytes(bytes.fromhex(r["seed"]))
            return (hashlib.sha256(sk.public_key().public_bytes_raw()).hexdigest() == r["public_sha256"]
                    and sk.decapsulate(bytes.fromhex(r["ciphertext"])).hex() == r["shared_secret"])
        checks.append(run("mlkem768-pinned", mlkem_kat))
    return checks


def run_checks(data: dict, keys: dict | None = None) -> dict:
    """Check every sealed vector of *data* (and its ``deterministic`` section
    when present) with the test keys of *data*, else of *keys*. Returns counts
    and the ids (only) of what failed."""
    pc = load_pii_crypto()
    test_keys = (data.get("deterministic") or {}).get("test_keys") or (keys or {})["deterministic"]["test_keys"]
    result = {"vectors_passed": 0, "vectors_failed": 0, "failed_ids": [],
              "deterministic_passed": 0, "deterministic_failed": 0, "failed_checks": []}
    keyrings = {}
    for index, vector in enumerate(data.get("vectors", [])):
        raw_id = vector.get("id") if isinstance(vector, dict) else None
        vid = raw_id if isinstance(raw_id, str) and _SAFE_ID.fullmatch(raw_id) else f"#{index}"
        try:
            current = vector.get("current_key_id") or test_keys["current_key_id"]
            if current not in keyrings:
                keyrings[current] = keyring_from_test_keys(pc, test_keys, current)
            with use_keyring(keyrings[current]):
                passed = check_vector(pc, vector)
        except Exception:
            passed = False
        result["vectors_passed" if passed else "vectors_failed"] += 1
        if not passed:
            result["failed_ids"].append(vid)
    det = data.get("deterministic")
    if det:
        with use_keyring(keyring_from_test_keys(pc, test_keys)):
            for name, passed in _deterministic_checks(pc, det):
                result["deterministic_passed" if passed else "deterministic_failed"] += 1
                if not passed:
                    result["failed_checks"].append(name)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vectors", help="vectors-style JSON file to check")
    parser.add_argument("--keys", default=str(DEFAULT_KEYS),
                        help="file whose deterministic.test_keys to use when VECTORS has none")
    args = parser.parse_args(argv)
    try:
        data = json.loads(Path(args.vectors).read_text(encoding="utf-8"))
        keys = None if (data.get("deterministic") or {}).get("test_keys") else json.loads(
            Path(args.keys).read_text(encoding="utf-8"))
        result = run_checks(data, keys)
    except Exception:
        print("check_pii_blob: the vectors or keys file could not be read", file=sys.stderr)
        return 1
    print(
        f"check_pii_blob: vectors {result['vectors_passed']} passed, {result['vectors_failed']} failed; "
        f"deterministic {result['deterministic_passed']} passed, {result['deterministic_failed']} failed"
    )
    if result["failed_ids"] or result["failed_checks"]:
        print("check_pii_blob: failed: " + ", ".join(result["failed_ids"] + result["failed_checks"]))
        return 1
    if not result["vectors_passed"]:
        print("check_pii_blob: no vectors checked")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
