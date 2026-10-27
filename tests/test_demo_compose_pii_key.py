"""Every demo service that mounts the PII private key is told to use it.

pii_crypto refuses to start a process that can read a key file it was not
configured with, so a mount without PII_KEM_PRIVATE_KEY_FILE fails at boot
(the first demo start on 2026-10-27).
"""
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.demo.yml"


def test_services_mounting_the_pii_key_set_its_path():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    mounting = [
        name for name, svc in services.items()
        if any(isinstance(s, dict) and s.get("target") == "pii_kem_private_key" for s in svc.get("secrets", []))
    ]
    assert mounting, "expected the demo app and worker to mount the key"
    for name in mounting:
        env = services[name].get("environment", {})
        assert env.get("PII_KEM_PRIVATE_KEY_FILE") == "/run/secrets/pii_kem_private_key", name
