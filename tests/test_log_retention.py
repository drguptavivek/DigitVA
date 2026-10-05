"""Log files rotate every 6 h, are gzipped, and are kept 210 days (digitva-dea)."""
import gzip
import logging

from app.logging import va_logger


def test_backup_count_is_210_days_of_six_hour_files():
    assert va_logger.LOG_ROTATION_HOURS == 6
    assert va_logger.LOG_BACKUP_COUNT == 840 == 210 * 24 // va_logger.LOG_ROTATION_HOURS


def test_rotation_gzips_and_cleanup_prunes_gz_beyond_the_count(tmp_path):
    log = tmp_path / "x.log"
    handler = va_logger.build_rotating_handler(
        str(log), logging.Formatter("%(message)s"), backup_count=2
    )
    assert handler.backupCount == 2
    logger = logging.Logger("test_log_retention")
    logger.addHandler(handler)
    first_period_end = 1_700_000_000
    try:
        for i in range(4):
            logger.warning("line %d", i)
            # The rotated name comes from rolloverAt, so give each rotation
            # its own 6 h period instead of waiting for the clock.
            handler.rolloverAt = first_period_end + i * 6 * 3600
            handler.doRollover()
    finally:
        handler.close()

    rotated = sorted(p.name for p in tmp_path.iterdir() if p.name != "x.log")
    assert len(rotated) == 2  # the oldest two of four rotations were deleted
    assert all(name.startswith("x.log.") and name.endswith(".gz") for name in rotated)
    with gzip.open(tmp_path / rotated[-1], "rt") as fh:
        assert fh.read() == "line 3\n"
