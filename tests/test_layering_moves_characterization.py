"""Characterization for digitva-r8nh.13 (services stop importing routes and
tasks): pins the behaviour of the moved pieces no other test reaches."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import db
from app.models import VaSyncRun
from app.services import area_dashboard_service as area
from app.services import ui_string_machine_job as job
from app.services import ui_string_service as uis
from tests.base import BaseTestCase


class SnapshotRefreshedAtTests(BaseTestCase):
    """``snapshot_refreshed_at`` reads the last successful hourly MV run."""

    def _run(self, triggered_by, status, finished_at):
        db.session.add(VaSyncRun(
            triggered_by=triggered_by,
            started_at=finished_at - timedelta(minutes=1),
            finished_at=finished_at,
            status=status,
        ))
        db.session.flush()

    def test_latest_successful_analytics_mv_run(self):
        base = datetime(2026, 11, 1, 10, tzinfo=UTC)
        self._run("analytics_mv", "success", base)
        self._run("analytics_mv", "success", base + timedelta(hours=1))
        self._run("analytics_mv", "error", base + timedelta(hours=2))
        self._run("scheduled", "success", base + timedelta(hours=3))
        self.assertEqual(area.snapshot_refreshed_at(), base + timedelta(hours=1))


class MachineJobLockClientTests(BaseTestCase):
    """The machine-translation lock uses the Flask-Caching Redis write client,
    and ``None`` when there is none."""

    def test_lock_client_is_the_cache_write_client(self):
        sentinel = object()
        fake = SimpleNamespace(cache=SimpleNamespace(_write_client=sentinel))
        with mock.patch("app.cache", fake):
            self.assertIs(job._redis(), sentinel)

    def test_no_write_client_means_no_lock(self):
        with mock.patch("app.cache", SimpleNamespace(cache=SimpleNamespace())):
            self.assertIsNone(job._redis())


class UiStringDirTests(BaseTestCase):
    """UI strings live under the Expo export's ``ui-strings`` folder."""

    def test_configured_export(self):
        with mock.patch.dict(self.app.config, {"EXPO_CLIENT_DIST": "/tmp/expo-dist-r8nh13"}):
            self.assertEqual(uis._ui_dir(), Path("/tmp/expo-dist-r8nh13").resolve() / "ui-strings")

    def test_default_export(self):
        with mock.patch.dict(self.app.config, {"EXPO_CLIENT_DIST": None}), \
                mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("EXPO_CLIENT_DIST", None)
            expected = (
                Path(self.app.root_path).parent / "mobile" / "digitva-collect" / "dist"
            ).resolve() / "ui-strings"
            self.assertEqual(uis._ui_dir(), expected)
