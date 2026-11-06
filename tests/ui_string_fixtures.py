"""Shared fixture for the UI string tests: a throwaway Expo export on disk.

Writes ``<root>/ui-strings/<locale>.json`` for each locale, the layout that
``npm run export:web`` produces. Tests point ``EXPO_CLIENT_DIST`` at ``root``.
"""
import json
from pathlib import Path

EN = {
    "loginTitle": "Sign in to DigitVA",
    "navCoding": "Coding",
    "loginHelp": "Use the existing sign-in.",
    "syncResult": "Sent {sent}. Not accepted {failed}.",
}

HI = {
    "loginTitle": "DigitVA में साइन इन करें",
    "navCoding": "कोडिंग",
    "syncResult": "भेजे {sent}. स्वीकार नहीं {failed}.",
}


#: The WHO form's labels (second namespace), as scripts/export-form-ui-strings.mjs writes them.
FORM_EN = {"next": "Next", "required": "{label} is required"}
FORM_HI = {"next": "आगे"}


def write_export(root: Path, locales: dict[str, dict]) -> Path:
    """Write ``<root>/ui-strings/<name>.json``; a name may be ``form-en`` or ``theme-hi``."""
    folder = root / "ui-strings"
    folder.mkdir(parents=True, exist_ok=True)
    for code, strings in locales.items():
        (folder / f"{code}.json").write_text(json.dumps(strings, ensure_ascii=False), encoding="utf-8")
    return folder
