"""The weekly reset schema is opt-in, uniquely audited and reversible."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


class SyntheticDemoMigrationTests(unittest.TestCase):
    def test_additive_opt_in_unique_week_and_reversible_downgrade(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "migrations/versions/b8d2f4a6c901_synthetic_demo_reset.py"
        )
        spec = importlib.util.spec_from_file_location("demo_reset_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "a4c9e1f2b7d3")
        with mock.patch.object(migration, "op") as operations:
            migration.upgrade()
            column = operations.add_column.call_args.args[1]
            self.assertEqual(column.name, "synthetic_demo_reset_enabled")
            self.assertFalse(column.nullable)
            self.assertEqual(str(column.server_default.arg), "false")
            self.assertEqual(operations.create_check_constraint.call_count, 1)
            args = operations.create_table.call_args.args
            self.assertEqual(args[0], "va_demo_reset_runs")
            self.assertTrue(
                any(getattr(arg, "name", None) == "uq_demo_reset_project_week" for arg in args[1:])
            )
            migration.downgrade()
            operations.drop_table.assert_called_once_with("va_demo_reset_runs")
            operations.drop_column.assert_called_once_with(
                "va_project_master", "synthetic_demo_reset_enabled"
            )
