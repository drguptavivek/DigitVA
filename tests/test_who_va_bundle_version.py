"""The form bundle URL must change whenever the vendored bundle is rebuilt."""

import json

from app.utils import who_va_bundle


def test_version_is_the_manifest_checksum():
    with open(who_va_bundle._MANIFEST, encoding="utf-8") as fh:
        sha = json.load(fh)["sha256"]
    assert who_va_bundle.who_va_bundle_version("fallback") == sha[:16]


def test_missing_manifest_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(who_va_bundle, "_MANIFEST", str(tmp_path / "absent.json"))
    assert who_va_bundle.who_va_bundle_version("fallback") == "fallback"
