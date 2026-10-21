"""Generate the registration-identifier key material.

Writes a new hybrid KEM private key to ``--private-file`` (mode 0600, never
overwritten) and appends ``PII_KEM_PUBLIC_KEY``, ``PII_KEM_KEY_ID`` and
``PII_BLIND_INDEX_KEY`` to ``--env-file``. Prints no key material. Refuses if
the private file exists or the env file already sets any of the three names.

    python scripts/generate_pii_keys.py --private-file private/pii_kem_private_key --env-file .env

Back both up apart from the database: losing the private key loses the
numbers (docs/current-state/runtime-and-operations.md). Loads
``app/utils/pii_crypto.py`` by path so it needs only ``cryptography``, not the
Flask app.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / "app" / "utils" / "pii_crypto.py"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--private-file", required=True)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location("pii_crypto_standalone", _MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through it
    spec.loader.exec_module(module)
    try:
        module.write_new_keyset(args.private_file, args.env_file)
    except module.PiiKeyConfigError as exc:
        print(f"generate_pii_keys: {exc}", file=sys.stderr)
        return 1
    print("generate_pii_keys: wrote the private key file and appended the public settings -- back both up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
