"""Migration e8c4f2a7b913 (respondent consent): chains on the committed head,
creates the append-only trigger, and refuses to downgrade while consent
records exist (they are the only record of what a respondent agreed to)."""

import importlib.util
import pathlib
import unittest
from unittest import mock

_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations" / "versions" / "e8c4f2a7b913_add_respondent_consent.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("respondent_consent_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RespondentConsentMigrationTests(unittest.TestCase):
    def _downgrade(self, rows: int):
        module = _load_migration()
        with mock.patch.object(module, "op") as op:
            op.get_bind.return_value.execute.return_value.scalar.return_value = rows
            try:
                module.downgrade()
            finally:
                self.dropped = [call.args[0] for call in op.drop_table.call_args_list]

    def test_chains_on_the_pii_side_table(self):
        module = _load_migration()
        self.assertEqual((module.revision, module.down_revision), ("e8c4f2a7b913", "b9e4f2a7c1d3"))

    def test_upgrade_creates_the_tables_and_the_update_trigger(self):
        module = _load_migration()
        with mock.patch.object(module, "op") as op:
            module.upgrade()
        created = {call.args[0] for call in op.create_table.call_args_list}
        self.assertEqual(created, {
            "mas_project_consent_settings", "mas_consent_notice_versions", "va_consent_records",
            "va_consent_record_purposes", "map_consent_audit",
        })
        sql = " ".join(str(call.args[0]) for call in op.execute.call_args_list)
        self.assertIn("BEFORE UPDATE ON va_consent_records", sql)
        self.assertIn("BEFORE UPDATE ON va_consent_record_purposes", sql)

    def test_downgrade_refuses_while_records_exist(self):
        with self.assertRaises(RuntimeError) as raised:
            self._downgrade(2)
        self.assertIn("consent record", str(raised.exception))
        self.assertEqual(self.dropped, [])

    def test_downgrade_drops_the_empty_tables(self):
        self._downgrade(0)
        self.assertIn("va_consent_records", self.dropped)
        self.assertIn("mas_consent_notice_versions", self.dropped)


if __name__ == "__main__":
    unittest.main()
