"""Migration d4f1b8c2a6e9 (map_payload_version_pii): the downgrade refuses
while the table holds rows, since the sealed fields exist nowhere else
(docs/kb/pii-slice-1b.md, "Release procedure", rollback)."""

import importlib.util
import pathlib
import unittest
from unittest import mock

_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations" / "versions" / "d4f1b8c2a6e9_add_map_payload_version_pii.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("map_payload_version_pii_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MapPayloadVersionPiiDowngradeTests(unittest.TestCase):
    def _downgrade(self, rows: int):
        module = _load_migration()
        with mock.patch.object(module, "op") as op:
            op.get_bind.return_value.execute.return_value.scalar.return_value = rows
            try:
                module.downgrade()
            finally:
                self.dropped = op.drop_table.called
        return op

    def test_refuses_while_rows_exist_and_points_to_restore(self):
        with self.assertRaises(RuntimeError) as raised:
            self._downgrade(3)
        self.assertIn("split-payloads --restore", str(raised.exception))
        self.assertFalse(self.dropped)

    def test_drops_the_empty_table(self):
        self._downgrade(0)
        self.assertTrue(self.dropped)

    def test_upgrade_has_the_sealed_ids_column(self):
        self.assertIn('sa.Column("sealed_ids"', _PATH.read_text())


if __name__ == "__main__":
    unittest.main()
