"""Task constants and the Redis lock client, shared with services.

Light on purpose: a service that needs one of these imports it from here
rather than loading ``app.tasks.sync_tasks`` (digitva-r8nh.13).
``sync_tasks`` re-exports both names.
"""

#: ``va_sync_runs.triggered_by`` of the hourly analytics MV refresh.
ANALYTICS_MV_TRIGGER = "analytics_mv"


def _lock_client():
    """The Redis client behind Flask-Caching, or ``None`` when there is none."""
    from app import cache

    try:
        return cache.cache._write_client  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a missing lock must not stop the work
        return None
