"""The inline stale-allocation sweep runs at most once per interval."""

from unittest import mock

from app import cache
from app.services import coder_workflow_service as cws
from tests.base import BaseTestCase

KEY = "coding:stale_sweep"


class CodingStaleSweepThrottleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        cache.delete(KEY)
        self.addCleanup(cache.delete, KEY)

    def _calls(self, interval, times=2):
        with mock.patch.dict(
            self.app.config, CODING_STALE_SWEEP_MIN_INTERVAL_SECONDS=interval
        ), mock.patch.object(cws, "release_stale_coding_allocations") as sweep:
            for _ in range(times):
                cws._release_stale_coding_allocations_throttled()
        return sweep.call_count

    def test_second_call_inside_the_window_skips_the_sweep(self):
        self.assertEqual(self._calls(30), 1)

    def test_zero_interval_always_sweeps(self):
        self.assertEqual(self._calls(0), 2)

    def test_cache_failure_runs_the_sweep(self):
        with mock.patch.dict(
            self.app.config, CODING_STALE_SWEEP_MIN_INTERVAL_SECONDS=30
        ), mock.patch.object(cache, "add", side_effect=RuntimeError("redis down")), \
                mock.patch.object(cws, "release_stale_coding_allocations") as sweep:
            cws._release_stale_coding_allocations_throttled()
        sweep.assert_called_once_with(timeout_hours=1)
