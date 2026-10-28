"""Strict validation and bounded Redis aggregation for app telemetry."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from app.services import app_telemetry_service as telemetry


def _payload(**changes):
    body = {
        "schema": 1,
        "batch_id": str(uuid4()),
        "day": datetime.now(UTC).date().isoformat(),
        "app_version": "0.3.10",
        "variant": "plus",
        "platform": "android",
        "device_type": "phone",
        "ram_bucket": "4_5",
        "core_bucket": "3_4",
        "manufacturer": "google",
        "metrics": {"foreground_ms": 100, "launches": 2, "crashes": 0, "errors": 1},
    }
    body.update(changes)
    return body


class FakeRedis:
    def __init__(self, results=None):
        self.results = iter(results or [1])
        self.eval_calls = []
        self.cells = {}
        self.pipeline_calls = 0

    def eval(self, script, keys_count, *args):
        self.eval_calls.append((script, keys_count, args))
        return next(self.results)

    def smembers(self, _key):
        return set(self.cells)

    def hgetall(self, key):
        return self.cells.get(key, self.cells.get(key.rsplit(":", 1)[-1], {}))

    def pipeline(self, transaction=False):
        self.pipeline_calls += 1
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.keys = []

    def hgetall(self, key):
        self.keys.append(key)

    def execute(self):
        return [self.redis.hgetall(key) for key in self.keys]


class AppTelemetryServiceTests(TestCase):
    def test_exact_schema_rejects_unknown_clinical_or_free_text_fields(self):
        for key, value in (("case_id", "x"), ("exception", "details"), ("model", "Pixel")):
            body = _payload(**{key: value})
            with self.subTest(key=key), self.assertRaises(telemetry.AppTelemetryError):
                telemetry.validate_batch(body)

    def test_schema_and_metric_bounds_are_strict(self):
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry.validate_batch(_payload(schema=True))
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry.validate_batch(_payload(schema=1.0))
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry.validate_batch(_payload(metrics={"foreground_ms": 1, "launches": 0, "crashes": 0}))
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry.validate_batch(_payload(metrics={
                "foreground_ms": 86_400_001, "launches": 0, "crashes": 0, "errors": 0,
            }))

    def test_date_window_and_version_are_bounded(self):
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry.validate_batch(_payload(day=(date.today() - timedelta(days=8)).isoformat()))
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry.validate_batch(_payload(app_version="1.2"))
        with self.assertRaises(telemetry.AppTelemetryError):
            telemetry._report_days(date.today() - timedelta(days=31), date.today())

    def test_acceptance_is_atomic_and_duplicate_is_idempotent(self):
        redis = FakeRedis([1, 0])
        body = _payload()
        with patch.object(telemetry, "_redis", return_value=redis), \
                patch.object(telemetry, "_prefix", return_value="test:telemetry:"), \
                patch.object(telemetry, "_authorized_dimensions", return_value=("unknown", "unknown")):
            accepted = telemetry.ingest(Mock(), Mock(), body)
            duplicate = telemetry.ingest(Mock(), Mock(), body)

        self.assertTrue(accepted)
        self.assertFalse(duplicate)
        self.assertEqual(len(redis.eval_calls), 2)
        _script, key_count, args = redis.eval_calls[0]
        self.assertEqual(key_count, 3)
        self.assertEqual(args[0], f"test:telemetry:batch:{body['batch_id']}")
        self.assertTrue(args[1].startswith("test:telemetry:day:"))
        self.assertTrue(args[2].startswith("test:telemetry:cell:"))
        self.assertEqual(args[3], telemetry.MAX_CELL_COUNT)
        self.assertEqual(args[5], telemetry.RETENTION_SECONDS)

    def test_invalid_project_country_is_not_reported_as_a_location(self):
        session = Mock(device_id=uuid4())
        with patch.object(telemetry.db.session, "scalar", return_value=SimpleNamespace(project_country_iso3="not-canonical")):
            self.assertEqual(telemetry._authorized_dimensions(session), ("unknown", "unknown"))
        with patch.object(telemetry.db.session, "scalar", return_value=SimpleNamespace(project_country_iso3="IND")):
            self.assertEqual(telemetry._authorized_dimensions(session), ("IND", "unknown"))

    def test_redis_outage_and_full_day_are_retryable(self):
        with patch.object(telemetry, "_redis", return_value=None):
            with self.assertRaises(telemetry.AppTelemetryError) as outage:
                telemetry.ingest(Mock(), Mock(), _payload())
        self.assertEqual((outage.exception.code, outage.exception.status), ("unavailable", 503))

        with patch.object(telemetry, "_redis", return_value=FakeRedis([-1])), \
                patch.object(telemetry, "_prefix", return_value="test:telemetry:"), \
                patch.object(telemetry, "_authorized_dimensions", return_value=("unknown", "unknown")):
            with self.assertRaises(telemetry.AppTelemetryError) as full:
                telemetry.ingest(Mock(), Mock(), _payload())
        self.assertEqual((full.exception.code, full.exception.status), ("unavailable", 503))

    def test_report_suppresses_cells_below_twenty_batches(self):
        day = date.today()
        redis = FakeRedis()
        redis.cells = {
            "small": {
                "accepted_batches": "19", "day": day.isoformat(), "variant": "plus",
            },
            "large": {
                "accepted_batches": "20", "day": day.isoformat(), "variant": "plus",
            },
        }
        with patch.object(telemetry, "_redis", return_value=redis), \
                patch.object(telemetry, "_prefix", return_value="test:telemetry:"):
            result = telemetry.report(day, day)

        self.assertEqual(len(result["cells"]), 1)
        self.assertEqual(result["cells"][0]["accepted_batches"], 20)
        self.assertEqual(result["summary"]["accepted_batches"], 39)
        self.assertEqual(redis.pipeline_calls, 1)
