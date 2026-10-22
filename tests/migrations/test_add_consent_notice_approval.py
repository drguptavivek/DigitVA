"""Migration d4a7c9e2f5b1 (consent notice approval): chains on the committed
head and adds, then drops, the two nullable approval columns."""

import importlib.util
import pathlib
import unittest
from unittest import mock

_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations" / "versions" / "d4a7c9e2f5b1_add_consent_notice_approval.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("consent_notice_approval_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConsentNoticeApprovalMigrationTests(unittest.TestCase):
    def test_chains_on_the_recode_window(self):
        module = _load_migration()
        self.assertEqual((module.revision, module.down_revision), ("d4a7c9e2f5b1", "c8e4a2f6b1d3"))

    def test_upgrade_adds_nullable_columns_and_downgrade_drops_them(self):
        module = _load_migration()
        with mock.patch.object(module, "op") as op:
            module.upgrade()
        added = {call.args[1].name: call.args[1].nullable for call in op.add_column.call_args_list}
        self.assertEqual(added, {"approved_at": True, "approved_by": True})
        with mock.patch.object(module, "op") as op:
            module.downgrade()
        self.assertEqual({call.args[1] for call in op.drop_column.call_args_list}, {"approved_at", "approved_by"})
