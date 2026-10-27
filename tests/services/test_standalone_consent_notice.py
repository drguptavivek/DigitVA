"""Drift guard: the notice Collect Plus bundles for a standalone phone equals the server seed."""

import hashlib
import json

from app.services.consent_notice_seed import SEED_PURPOSES, SEED_TEXT
from scripts.export_standalone_consent_notice import ASSET_PATH, build_asset, render


def test_committed_asset_equals_script_output():
    assert ASSET_PATH.read_text(encoding="utf-8") == render(build_asset()), (
        "run scripts/export_standalone_consent_notice.py and commit the asset"
    )


def test_asset_carries_seed_text_codes_and_item_seven():
    asset = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    assert asset["text"] == SEED_TEXT
    for language in ("en", "hi"):
        assert [p["code"] for p in asset["purposes"][language]] == [p["code"] for p in SEED_PURPOSES[language]]
    assert "narrative_automated_processing" in [p["code"] for p in asset["purposes"]["en"]]
    content = {k: asset[k] for k in ("text", "purposes", "allowed_modes")}
    body = json.dumps(content, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert asset["sha256"] == hashlib.sha256(body).hexdigest()
