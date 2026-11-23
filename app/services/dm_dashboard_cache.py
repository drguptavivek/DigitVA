"""Generation counter for the data-manager dashboard caches (digitva-r8nh.4).

Policy: docs/policy/data-manager-workflow.md, "Dashboard caches". Every
dashboard cache key carries ``generation()``; a data-manager action that
changes dashboard figures calls ``bump()``, which strands every older entry
(they expire on their own TTL) with one write: no key scan, and nothing else
in the cache is touched.

A reader takes the generation before it computes, so a bump that lands
mid-compute leaves that result under the old generation: unreachable, never
stale.
"""

from __future__ import annotations

import logging
import uuid

from app import cache

log = logging.getLogger(__name__)

_KEY = "dm_dashboard_generation"
# Expires so Redis (volatile-lru) can evict it; a missing counter reads as
# "0", and entries made under "0" are long past their 5-minute life by then.
_TTL_SECONDS = 24 * 60 * 60


def generation() -> str:
    """The current generation token ("0" when none is set or the cache is down)."""
    try:
        value = cache.get(_KEY)
    except Exception:
        return "0"
    return str(value) if value else "0"


def bump() -> None:
    """Invalidate every dashboard cache entry. Failure is logged, not raised:
    a stale figure for one TTL is not a failed action."""
    try:
        cache.set(_KEY, uuid.uuid4().hex, timeout=_TTL_SECONDS)
    except Exception as exc:
        log.warning("Dashboard cache generation bump failed: %s", exc, exc_info=True)
