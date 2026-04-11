import logging

from app.logging import va_logger


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )


def test_log_context_filter_defaults_without_request_or_task(monkeypatch):
    va_logger.clear_request_id()
    monkeypatch.setattr(va_logger, "_extract_celery_context", lambda: ("-", "-"))

    record = _make_record()
    assert va_logger.LogContextFilter().filter(record) is True
    assert record.request_id == "-"
    assert record.task_name == "-"
    assert record.task_id == "-"


def test_log_context_filter_uses_request_id_context(monkeypatch):
    monkeypatch.setattr(va_logger, "_extract_celery_context", lambda: ("-", "-"))
    va_logger.set_request_id("req-123")

    record = _make_record()
    assert va_logger.LogContextFilter().filter(record) is True
    assert record.request_id == "req-123"

    va_logger.clear_request_id()


def test_payload_summary_limits_key_count():
    payload = {f"k{i}": i for i in range(25)}
    summary = va_logger._payload_summary(payload)

    assert summary.startswith("keys=")
    assert "+5" in summary
