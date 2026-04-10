"""Tests for demo_project_schema_ready() caching behaviour.

These are isolated unit tests that mock sa.inspect so they do not require
a live database connection.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.services.demo_project_service as _svc


class TestDemoProjectSchemaReadyCache(unittest.TestCase):
    def setUp(self):
        # Reset module-level cache before each test.
        _svc._SCHEMA_READY = None

    def _make_inspector(self, columns: list[str]) -> MagicMock:
        inspector = MagicMock()
        inspector.get_columns.return_value = [{"name": c} for c in columns]
        return inspector

    def test_returns_true_when_columns_present(self):
        inspector = self._make_inspector(
            ["demo_training_enabled", "demo_retention_minutes", "other_col"]
        )
        with patch("app.services.demo_project_service.sa") as mock_sa:
            mock_sa.inspect.return_value = inspector
            result = _svc.demo_project_schema_ready()

        self.assertTrue(result)

    def test_returns_false_when_columns_missing(self):
        inspector = self._make_inspector(["project_id", "project_name"])
        with patch("app.services.demo_project_service.sa") as mock_sa:
            mock_sa.inspect.return_value = inspector
            result = _svc.demo_project_schema_ready()

        self.assertFalse(result)

    def test_caches_result_on_second_call(self):
        inspector = self._make_inspector(
            ["demo_training_enabled", "demo_retention_minutes"]
        )
        with patch("app.services.demo_project_service.sa") as mock_sa:
            mock_sa.inspect.return_value = inspector
            first = _svc.demo_project_schema_ready()
            second = _svc.demo_project_schema_ready()
            # inspect should only be called once
            mock_sa.inspect.assert_called_once()

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertTrue(_svc._SCHEMA_READY)

    def test_does_not_cache_on_exception(self):
        inspector = MagicMock()
        inspector.get_columns.side_effect = Exception("connection refused")

        with patch("app.services.demo_project_service.sa") as mock_sa:
            mock_sa.inspect.return_value = inspector
            result = _svc.demo_project_schema_ready()

        self.assertFalse(result)
        self.assertIsNone(_svc._SCHEMA_READY)

    def test_retries_after_transient_exception(self):
        failing_inspector = MagicMock()
        failing_inspector.get_columns.side_effect = Exception("transient error")

        ok_inspector = self._make_inspector(
            ["demo_training_enabled", "demo_retention_minutes"]
        )

        with patch("app.services.demo_project_service.sa") as mock_sa:
            mock_sa.inspect.return_value = failing_inspector
            first = _svc.demo_project_schema_ready()

            # Simulate recovery: next call should retry
            mock_sa.inspect.return_value = ok_inspector
            second = _svc.demo_project_schema_ready()

        self.assertFalse(first)
        self.assertTrue(second)
        self.assertTrue(_svc._SCHEMA_READY)
