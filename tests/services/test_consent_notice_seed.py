"""The seeded consent notice (digitva-athy) is the policy draft's text: the
"English seed" / "Hindi seed" blocks of
docs/policy/respondent-consent-notice-draft.md and app/services/consent_notice_seed.py
must not drift apart."""

import pathlib
import re
import unittest

from app.services.consent_notice_seed import PROJECT_NAME_PLACEHOLDER, SEED_PURPOSES, SEED_TEXT

_DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "policy" / "respondent-consent-notice-draft.md"


def _block(heading: str) -> str:
    match = re.search(rf"### {heading}\n\n```text\n(.*?)\n```", _DOC.read_text(encoding="utf-8"), re.S)
    assert match, heading
    return match.group(1)


class ConsentNoticeSeedTests(unittest.TestCase):
    def test_seed_texts_equal_the_policy_draft(self):
        self.assertEqual(SEED_TEXT["en"], _block("English seed"))
        self.assertEqual(SEED_TEXT["hi"], _block("Hindi seed"))

    def test_both_languages_name_the_project_and_share_purposes(self):
        for language in ("en", "hi"):
            self.assertTrue(SEED_TEXT[language].startswith(PROJECT_NAME_PLACEHOLDER))
        self.assertEqual(*[[(p["code"], p["required"]) for p in SEED_PURPOSES[lang]] for lang in ("en", "hi")])
