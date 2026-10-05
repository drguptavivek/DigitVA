"""Polled per-user notifications (digitva-hdrv, docs/policy/app-notifications.md).

A nudge, never the truth: ``map_user_notifications`` rows say "something
changed for you" with ids and a fixed kind (no name, phone or answer), and the
app then runs its normal sync. Postgres holds the rows; Redis only lets an
empty poll skip the database.

Write side: ``notify`` inserts in the caller's transaction (so a rolled-back
event leaves no row) and, once that transaction commits, raises the per-user
key ``<prefix><user_id>`` to the newest id with a short TTL. Read side: ``poll``
answers empty from the key alone when nothing newer than the cursor exists,
else runs one indexed query. Redis errors are logged and swallowed: a lost key
write costs at most one TTL of poll delay, the database is the truth.

Ids are assigned at insert, not at commit, so two concurrent transactions can
commit out of id order; a poll between the two commits can pass the older row.
That costs one missed nudge (the next sync carries the state), by design.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask import current_app, has_app_context
from sqlalchemy.orm import Session

from app import db
from app.models import MapUserNotification, VaWebIntakeDraft

log = logging.getLogger(__name__)

REVISION_REQUESTED = "revision_requested"
OTHER_DRAFT_STARTED = "other_draft_started"
CASE_SUBMITTED_BY_OTHER = "case_submitted_by_other"
CASE_REOPENED = "case_reopened"
INTERVIEW_CHOSEN = "interview_chosen"

#: Rows one poll returns; a client at the limit polls again with next_cursor.
PAGE_SIZE = 100
#: Most recipients of one event (a case rarely has more open drafts).
MAX_RECIPIENTS = 200
#: Redis key lifetime: a stale or failed set heals itself within this.
CACHE_TTL_SECONDS = 300
RETENTION_DAYS = 30
PURGE_BATCH = 5000
BIGINT_MAX = 2**63 - 1

_PENDING = "notification_latest_ids"

# Raise the key to ARGV[1] only when it is absent or lower, so commits that
# finish out of id order never move it backwards.
_RAISE = """
local cur = redis.call('GET', KEYS[1])
if cur and tonumber(cur) >= tonumber(ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""


def _client():
    """The Redis client, or None when the cache is off or not Redis."""
    if not has_app_context() or not current_app.config.get("NOTIFICATION_CACHE_ENABLED"):
        return None
    from app import cache

    try:
        return getattr(cache.cache, "_write_client", None)
    except (KeyError, RuntimeError):
        return None


def _key(user_id) -> str:
    return f"{current_app.config.get('NOTIFICATION_CACHE_PREFIX', 'digitva_msg:last:')}{user_id}"


def notify(user_ids: Iterable, kind: str, *, project_id: str, death_id=None, draft_id=None, va_sid=None) -> int:
    """Insert one *kind* row per recipient in the current transaction; returns
    the count. One bulk INSERT, no flush per row. The caller commits.

    *draft_id* is one id for every recipient, or a ``{user_id: draft_id}``
    mapping when each holds their own. At most ``MAX_RECIPIENTS`` users are
    notified; callers bound their own recipient query the same way.
    """
    recipients = list(dict.fromkeys(u for u in user_ids if u is not None))
    if len(recipients) > MAX_RECIPIENTS:
        log.warning("notification fan-out capped | kind=%s | wanted=%d", kind, len(recipients))
        recipients = recipients[:MAX_RECIPIENTS]
    if not recipients:
        return 0
    rows = [
        {
            "user_id": user_id, "kind": kind, "project_id": project_id, "death_id": death_id, "va_sid": va_sid,
            "draft_id": draft_id.get(user_id) if isinstance(draft_id, Mapping) else draft_id,
        }
        for user_id in recipients
    ]
    inserted = db.session.execute(
        sa.insert(MapUserNotification).returning(MapUserNotification.user_id, MapUserNotification.id), rows
    ).all()
    latest = db.session().info.setdefault(_PENDING, {})
    for user_id, row_id in inserted:
        latest[user_id] = max(latest.get(user_id, 0), row_id)
    return len(inserted)


def open_draft_holders(death_id, *, exclude_user_id=None) -> dict:
    """``{user_id: draft_id}`` of the open drafts on a case, other than
    *exclude_user_id*'s: one query on ``ix_va_web_intake_drafts_death``,
    capped at ``MAX_RECIPIENTS``."""
    query = sa.select(VaWebIntakeDraft.user_id, VaWebIntakeDraft.draft_id).where(
        VaWebIntakeDraft.death_id == death_id, VaWebIntakeDraft.status == "draft"
    )
    if exclude_user_id is not None:
        query = query.where(VaWebIntakeDraft.user_id != exclude_user_id)
    return dict(db.session.execute(query.limit(MAX_RECIPIENTS)).all())


@sa.event.listens_for(Session, "after_commit")
def _publish_latest_ids(session):
    # A savepoint release also fires after_commit; publish only at the outer
    # commit, so a later outer rollback cannot leave a key for ids that never
    # existed. ponytail: a rolled-back savepoint's own ids stay pending and are
    # published at the outer commit: a too-high key only costs one database
    # read per poll until its 300 s TTL; never a missed row (poll rewinds).
    if session.in_nested_transaction():
        return
    latest = session.info.pop(_PENDING, None)
    if not latest:
        return
    client = _client()
    if client is None:
        return
    try:
        pipe = client.pipeline(transaction=False)
        for user_id, row_id in latest.items():
            pipe.eval(_RAISE, 1, _key(user_id), row_id, CACHE_TTL_SECONDS)
        pipe.execute()
    except Exception:
        # The rows are committed; polls fall back to the database once the
        # key expires (or immediately, when it is absent).
        log.warning("Could not publish notification ids to Redis", exc_info=True)


@sa.event.listens_for(Session, "after_soft_rollback")
def _drop_latest_ids(session, previous_transaction):
    if previous_transaction.parent is None:
        session.info.pop(_PENDING, None)


def poll(user_id, after: int = 0) -> dict:
    """The caller's notifications with id > *after*, oldest first, at most
    ``PAGE_SIZE``: ``{notifications, next_cursor}``.

    Zero queries when the Redis key says nothing is newer than *after*; else
    one query on (user_id, id). A complete read (fewer than ``PAGE_SIZE`` rows)
    seeds an absent key with the caller's real newest id (one more index-only
    read when nothing is newer); a full page seeds nothing. A cursor above the
    caller's real newest id (a restored database, a client bug) is answered
    with that id as ``next_cursor``, so the client rewinds instead of missing
    every later notification.
    """
    client, key = _client(), _key(user_id)
    if client is not None:
        try:
            cached = client.get(key)
        except Exception:
            log.warning("Could not read notification key from Redis", exc_info=True)
            cached = None
        if cached is not None and int(cached) <= after:
            return {"notifications": [], "next_cursor": int(cached)}
    rows = db.session.execute(
        sa.select(
            MapUserNotification.id, MapUserNotification.kind, MapUserNotification.created_at,
            MapUserNotification.project_id, MapUserNotification.death_id, MapUserNotification.draft_id,
            MapUserNotification.va_sid,
        )
        .where(MapUserNotification.user_id == user_id, MapUserNotification.id > after)
        .order_by(MapUserNotification.id)
        .limit(PAGE_SIZE)
    ).all()
    if rows:
        next_cursor = rows[-1].id
    else:
        newest = db.session.scalar(
            sa.select(sa.func.max(MapUserNotification.id)).where(MapUserNotification.user_id == user_id)
        ) or 0
        next_cursor = min(after, newest)
    if client is not None and len(rows) < PAGE_SIZE:
        try:
            client.set(key, next_cursor, nx=True, ex=CACHE_TTL_SECONDS)
        except Exception:
            log.warning("Could not seed notification key in Redis", exc_info=True)
    return {
        "notifications": [
            {
                "id": r.id, "kind": r.kind, "created_at": r.created_at.isoformat(), "project_id": r.project_id,
                "death_id": str(r.death_id) if r.death_id else None,
                "draft_id": str(r.draft_id) if r.draft_id else None, "va_sid": r.va_sid,
            }
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


def purge_expired() -> int:
    """Delete rows older than ``RETENTION_DAYS``, ``PURGE_BATCH`` per
    statement, one short transaction each; returns the total. A missed day only
    makes the next run longer."""
    total = 0
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    while True:
        # Two statements, both index-driven: the oldest ids by created_at, then
        # a delete of exactly that bound list (an IN (subquery) planned a scan).
        ids = db.session.scalars(
            sa.select(MapUserNotification.id).where(MapUserNotification.created_at < cutoff)
            .order_by(MapUserNotification.created_at).limit(PURGE_BATCH)
        ).all()
        deleted = db.session.execute(
            sa.delete(MapUserNotification).where(MapUserNotification.id.in_(ids))
        ).rowcount if ids else 0
        db.session.commit()
        total += deleted
        if deleted < PURGE_BATCH:
            return total
