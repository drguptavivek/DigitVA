"""The DORIS warning table is generated; both runtimes must carry exactly what the generator writes."""

import importlib.util
from pathlib import Path

from tests.base import BaseTestCase

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_doris_messages", ROOT / "scripts" / "generate_doris_messages.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DorisMessagesGeneratedTests(BaseTestCase):
    def test_web_and_expo_tables_match_the_generator(self):
        generator = _generator()
        self.assertEqual(
            generator.TARGET.read_text(encoding="utf-8"),
            generator.render_js(),
            "run python scripts/generate_doris_messages.py",
        )
        self.assertEqual(
            generator.TARGET_TS.read_text(encoding="utf-8"),
            generator.render_ts(),
            "run python scripts/generate_doris_messages.py",
        )

    def test_every_pattern_names_its_fields_as_capture_groups(self):
        for entry in _generator().PATTERNS:
            groups = entry["pattern"].count("(") - entry["pattern"].count("(?:")
            self.assertEqual(groups, len(entry["fields"]), entry["id"])
