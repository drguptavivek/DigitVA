"""logs/slow_requests.log records route pattern, status, timing and SQL count."""

from tests.base import BaseTestCase

LOGGER = "SLOW_REQUEST_LOG"
SID = "uuid:secret-case-id-123"
URL = f"/api/v1/va/{SID}/workspace"


class SlowRequestLogTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.app.config.update, SLOW_REQUEST_LOG_MS=self.app.config["SLOW_REQUEST_LOG_MS"])

    def test_slow_request_logs_pattern_not_path(self):
        self.app.config["SLOW_REQUEST_LOG_MS"] = 0
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.client.get(URL)
        lines = [m for m in logs.output if "event=slow_request" in m]
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("rule=/api/v1/va/<va_sid>/workspace", line)
        self.assertIn("method=GET", line)
        self.assertRegex(line, r"sql_count=\d+ sql_ms=")
        self.assertNotIn("secret-case-id", line)

    def test_unmatched_route_logs_dash_rule(self):
        self.app.config["SLOW_REQUEST_LOG_MS"] = 0
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.client.get("/no/such/route")
        self.assertIn("rule=- ", logs.output[0])

    def test_fast_request_not_logged(self):
        self.app.config["SLOW_REQUEST_LOG_MS"] = 10**9
        with self.assertNoLogs(LOGGER, level="INFO"):
            self.client.get(URL)
