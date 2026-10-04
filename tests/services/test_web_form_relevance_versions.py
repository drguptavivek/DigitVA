"""Re-checking an upload against the form version it was filled on
(app/services/web_form_relevance_service.py ``version=``; beads digitva-6pwq).
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app import db
from app.models import MasInstrumentVersions
from app.services import web_form_relevance_service as svc
from app.services.served_form_service import INSTRUMENT_CODE
from tests.base import BaseTestCase

NOW = datetime(2024, 6, 15, 9, 0, 0, tzinfo=UTC)
OLD = "2025010101-0123456789"

# A minimal older version: ``gate`` guards ``child`` (a ``relevant`` source stored
# as the composed definition stores it, an object with ``.source``), and ``age``
# carries a constraint. None of these names exist in the current instrument.
OLD_DEFINITION = {
    "sections": [{"name": "s_old", "relevant": None}],
    "questions": [
        {"name": "gate_old", "sectionPath": ["s_old"], "control": "text"},
        {
            "name": "child_old", "sectionPath": ["s_old"], "control": "text",
            "relevant": {"source": "${gate_old} = 'yes'"},
        },
        {
            "name": "age_old", "sectionPath": ["s_old"], "control": "integer",
            "constraint": {"source": ". < 10"},
        },
    ],
}


class FormVersionOfTests(unittest.TestCase):
    def test_reads_instrument_version_only(self):
        self.assertEqual(svc.form_version_of({"instrumentVersion": " 2026-abc "}), "2026-abc")
        self.assertIsNone(svc.form_version_of({"formVersion": "2022"}))
        self.assertIsNone(svc.form_version_of({"instrumentVersion": "  "}))
        self.assertIsNone(svc.form_version_of({"instrumentVersion": 5}))
        self.assertIsNone(svc.form_version_of(None))


class RecheckByVersionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        svc._stored_rules.cache_clear()
        self.addCleanup(svc._stored_rules.cache_clear)
        db.session.add(
            MasInstrumentVersions(
                instrument_code=INSTRUMENT_CODE, version=OLD, definition=OLD_DEFINITION,
            )
        )
        db.session.commit()

    ANSWERS = {"gate_old": "no", "child_old": "x", "age_old": "12"}

    def test_without_a_version_the_current_instrument_judges(self):
        # Present first: the current instrument has no such questions, so it
        # neither strips nor flags them.
        names = {q["name"] for q in svc._current_rules().questions}
        self.assertNotIn("child_old", names)
        stripped, removed = svc.strip_irrelevant_answers(self.ANSWERS, now=NOW)
        self.assertEqual((stripped, removed), (self.ANSWERS, set()))
        self.assertEqual(svc.derive_validation_errors(self.ANSWERS, now=NOW), [])

    def test_a_stored_version_judges_by_its_own_rules(self):
        stripped, removed = svc.strip_irrelevant_answers(self.ANSWERS, now=NOW, version=OLD)
        self.assertEqual(removed, {"child_old"})
        self.assertNotIn("child_old", stripped)
        self.assertEqual(
            svc.derive_validation_errors(self.ANSWERS, now=NOW, version=OLD),
            [{"question": "child_old", "rule": "relevant"}, {"question": "age_old", "rule": "constraint"}],
        )

    def test_an_unknown_version_falls_back_to_the_current_instrument(self):
        self.assertEqual(
            svc.strip_irrelevant_answers(self.ANSWERS, now=NOW, version="nope-0000000000"),
            svc.strip_irrelevant_answers(self.ANSWERS, now=NOW),
        )
        self.assertEqual(svc.derive_validation_errors(self.ANSWERS, now=NOW, version="nope-0000000000"), [])

    def test_a_version_recorded_later_is_found_after_a_miss(self):
        later = "2025020202-9876543210"
        self.assertEqual(svc.derive_validation_errors(self.ANSWERS, now=NOW, version=later), [])
        db.session.add(MasInstrumentVersions(instrument_code=INSTRUMENT_CODE, version=later, definition=OLD_DEFINITION))
        db.session.commit()
        self.assertTrue(svc.derive_validation_errors(self.ANSWERS, now=NOW, version=later))
