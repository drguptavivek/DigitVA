"""Export the consent notice Collect Plus bundles for a phone used without a server (Path C).

Writes ``mobile/digitva-collect/assets/standalone-consent-notice.json`` from
``app/services/consent_notice_seed.py``: English and Hindi text, purposes (code, label, required),
allowed modes, a version string and a sha256 of the content. Never edit the asset by hand; the drift
test tests/services/test_standalone_consent_notice.py fails until it equals this script's output.

The text keeps the seed's ``[PROJECT NAME]`` / ``[ORGANISATION]`` and other bracketed gaps; the phone
fills them at display time (mobile/digitva-collect/src/standaloneConsent.ts), so the hash of what a
respondent saw is taken on the phone and travels with the record. Policy: docs/policy/respondent-consent-notice-draft.md
"Standalone notice".

Run: docker compose exec -T minerva_app_service uv run --no-sync python scripts/export_standalone_consent_notice.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.consent_notice_seed import (
    SEED_ALLOWED_MODES,
    SEED_PURPOSES,
    SEED_TEXT,
    standalone_bundle_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
ASSET_PATH = ROOT / "mobile/digitva-collect/assets/standalone-consent-notice.json"
SCHEMA = 1


def build_asset() -> dict:
    """The asset as a dict; ``sha256`` is over the compact JSON of everything but ``version`` and ``sha256``."""
    content = {
        "text": SEED_TEXT,
        "purposes": SEED_PURPOSES,
        "allowed_modes": SEED_ALLOWED_MODES,
    }
    digest = standalone_bundle_sha256()
    return {"schema": SCHEMA, "version": f"seed-{digest[:12]}", "sha256": digest, **content}


def render(asset: dict) -> str:
    return json.dumps(asset, indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    ASSET_PATH.write_text(render(build_asset()), encoding="utf-8")
    print(f"wrote {ASSET_PATH.relative_to(ROOT)}")
