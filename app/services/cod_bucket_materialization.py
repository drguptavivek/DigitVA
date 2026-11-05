"""Keeps ``map_submission_cod_bucket`` equal to the live COD bucket derivation.

The table holds layer (a) of the bucket report
(``cod_bucket_mapping_service._cod_bucket_resolved_rows``) for every active
scheme; the reports read it once a scheme's ``reporting_rows_built_at`` is set.
Policy: docs/policy/cod-bucket-reporting.md ("Precomputed reporting rows").

Freshness:
- the worker's sweep rebuilds every scheme right after each hourly analytics
  MV refresh: final-COD, site, duplicate, date-of-death and unit changes only
  reach the source MVs then, so no per-write hook is needed for them;
- an admin edit to a scheme, age band, node, mapping or legacy alias queues a
  rebuild of the affected scheme(s) once its transaction commits (the
  ``after_flush``/``after_commit`` listeners below), as does an ICD-11
  catalogue import (``mark_all_schemes_stale``).

Every rebuild is a diff-sync, so a rerun is safe and changes nothing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from itertools import chain

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import db
from app.models import (
    MapIcd10LegacyReportingAlias,
    MapIcdCodBucket,
    MapSubmissionCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasCodBucketSchemeAgeBand,
)

log = logging.getLogger(__name__)

_TABLE = MapSubmissionCodBucket.__table__
_KEY = ("va_sid", "scheme_id", "age_band_id")
_ROW_COLUMNS = tuple(column.name for column in _TABLE.columns if column.name != "computed_at")
_VALUE_COLUMNS = tuple(name for name in _ROW_COLUMNS if name not in _KEY)
_TARGET_NAME = "cod_bucket_rebuild_target"
_TARGET = sa.table(_TARGET_NAME, *(sa.column(column.name) for column in _TABLE.columns))
_LOCK_PREFIX = "map_submission_cod_bucket:"

#: session.info key: scheme ids (or _ALL_SCHEMES) to rebuild after commit.
_PENDING = "cod_bucket_rebuild_pending"
_ALL_SCHEMES = "all"


def rebuild_scheme(scheme_id: uuid.UUID, va_sids=None) -> dict:
    """Diff-sync *scheme_id*'s rows with layer (a), in one transaction; commits.

    Inserts, updates and deletes only the rows that differ, so ``computed_at``
    moves only on a changed row and a rerun changes nothing. *va_sids* limits
    the sync to those submissions and leaves the readiness stamp alone; a full
    sync (None) sets ``reporting_rows_built_at``. An inactive scheme loses its
    rows and its stamp. Serialised per scheme by a transaction advisory lock,
    so two rebuilds of one scheme never interleave.

    Returns ``{"scheme_code", "inserted", "updated", "deleted", "rows"}``, or
    ``{"status": "missing"}`` for an unknown scheme. Raises (after rolling
    back) on a database error.
    """
    from app.services.case_list_service import _jit_off
    from app.services.cod_bucket_mapping_service import _cod_bucket_resolved_rows

    try:
        db.session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtext(:name))"),
            {"name": f"{_LOCK_PREFIX}{scheme_id}"},
        )
        # Read after the lock, so a rebuild queued behind another sees the
        # scheme as that one left it.
        scheme = db.session.scalar(
            sa.select(MasCodBucketScheme)
            .where(MasCodBucketScheme.scheme_id == scheme_id)
            .execution_options(populate_existing=True)
        )
        if scheme is None:
            db.session.rollback()
            return {"status": "missing"}

        scope = [_TABLE.c.scheme_id == scheme_id]
        if va_sids is not None:
            scope.append(_TABLE.c.va_sid.in_(sorted(va_sids)))

        if not scheme.is_active:
            deleted = db.session.execute(sa.delete(_TABLE).where(*scope)).rowcount
            _set_stamp(scheme_id, None)
            db.session.commit()
            return {"scheme_code": scheme.scheme_code, "inserted": 0, "updated": 0,
                    "deleted": deleted, "rows": 0}

        with _jit_off():
            db.session.execute(sa.text(
                f"CREATE TEMP TABLE {_TARGET_NAME} (LIKE {_TABLE.name}) ON COMMIT DROP"
            ))
            resolved = _cod_bucket_resolved_rows(scheme, va_sids=va_sids).subquery()
            db.session.execute(
                sa.insert(_TARGET).from_select(
                    [*_ROW_COLUMNS, "computed_at"],
                    sa.select(*(resolved.c[name] for name in _ROW_COLUMNS), sa.func.now()),
                )
            )
            db.session.execute(sa.text(f"ANALYZE {_TARGET_NAME}"))

            deleted = db.session.execute(
                sa.delete(_TABLE).where(
                    *scope,
                    ~sa.exists().where(
                        _TARGET.c.va_sid == _TABLE.c.va_sid,
                        _TARGET.c.age_band_id == _TABLE.c.age_band_id,
                    ),
                )
            ).rowcount

            upsert = pg_insert(_TABLE).from_select(
                [*_ROW_COLUMNS, "computed_at"],
                sa.select(*(_TARGET.c[name] for name in (*_ROW_COLUMNS, "computed_at"))),
            )
            upsert = upsert.on_conflict_do_update(
                index_elements=list(_KEY),
                set_={name: upsert.excluded[name] for name in (*_VALUE_COLUMNS, "computed_at")},
                where=sa.tuple_(*(_TABLE.c[name] for name in _VALUE_COLUMNS)).is_distinct_from(
                    sa.tuple_(*(upsert.excluded[name] for name in _VALUE_COLUMNS))
                ),
            ).returning(sa.literal_column("xmax = 0").label("inserted"))
            changed = upsert.cte("cod_bucket_changed")
            inserted, updated = db.session.execute(
                sa.select(
                    sa.func.count().filter(changed.c.inserted),
                    sa.func.count().filter(sa.not_(changed.c.inserted)),
                )
            ).one()
            rows = db.session.scalar(sa.select(sa.func.count()).select_from(_TARGET))
            # ON COMMIT DROP alone would leave it behind when the caller's
            # commit only releases a savepoint.
            db.session.execute(sa.text(f"DROP TABLE {_TARGET_NAME}"))

        if va_sids is None:
            _set_stamp(scheme_id, datetime.now(timezone.utc))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {"scheme_code": scheme.scheme_code, "inserted": inserted, "updated": updated,
            "deleted": deleted, "rows": rows}


def _set_stamp(scheme_id: uuid.UUID, value) -> None:
    """Set the readiness stamp with a Core UPDATE: no ORM flush, so the
    listeners below do not queue another rebuild, and ``updated_at`` (the
    admin's "last edited") stays as it was."""
    db.session.execute(
        sa.update(MasCodBucketScheme.__table__)
        .where(MasCodBucketScheme.__table__.c.scheme_id == scheme_id)
        .values(
            reporting_rows_built_at=value,
            updated_at=MasCodBucketScheme.__table__.c.updated_at,
        )
    )


def rebuild_all_active() -> dict[str, dict]:
    """Rebuild every scheme: build the active ones (a NULL stamp included) and
    clear the rows of any inactive one. ``{scheme_code: rebuild_scheme result}``."""
    results = {}
    for scheme_id in all_scheme_ids():
        result = rebuild_scheme(scheme_id)
        if "scheme_code" in result:
            results[result["scheme_code"]] = result
    return results


def all_scheme_ids() -> list[uuid.UUID]:
    """Every scheme, active first: there are a handful."""
    return list(db.session.scalars(
        sa.select(MasCodBucketScheme.scheme_id).order_by(
            MasCodBucketScheme.is_active.desc(), MasCodBucketScheme.scheme_code
        )
    ))


# ---------------------------------------------------------------------------
# Rebuild on admin edits: collect in after_flush, enqueue after the commit.
# ---------------------------------------------------------------------------

def _clear_stamps(session: Session, scheme_id: uuid.UUID | None) -> None:
    """Null the readiness stamp in the edit's own transaction, so reads fall
    back to live derivation until the rebuild lands instead of serving rows
    built before the edit. ``None`` clears every scheme. Core UPDATE on the
    session's connection: safe inside after_flush and queues nothing."""
    table = MasCodBucketScheme.__table__
    stmt = sa.update(table).where(table.c.reporting_rows_built_at.is_not(None))
    if scheme_id is not None:
        stmt = stmt.where(table.c.scheme_id == scheme_id)
    session.connection().execute(
        stmt.values(reporting_rows_built_at=None, updated_at=table.c.updated_at)
    )


def mark_scheme_stale(scheme_id: uuid.UUID, session: Session | None = None) -> None:
    """Stop serving *scheme_id*'s rows and queue its rebuild at the next
    commit: also for writes the flush listener cannot see (Core bulk deletes)."""
    session = session or db.session()
    # Always clear (a no-op once NULL): a rolled-back savepoint may have
    # undone an earlier clear while the pending set kept the id.
    _clear_stamps(session, scheme_id)
    session.info.setdefault(_PENDING, set()).add(scheme_id)


def mark_all_schemes_stale(session: Session | None = None) -> None:
    """Stop serving every scheme's rows and queue a rebuild of all at the next
    commit (an ICD-11 catalogue import, a legacy alias edit)."""
    session = session or db.session()
    _clear_stamps(session, None)
    session.info.setdefault(_PENDING, set()).add(_ALL_SCHEMES)


@sa.event.listens_for(Session, "after_flush")
def _collect_edited_schemes(session, flush_context):
    for obj in chain(session.new, session.dirty, session.deleted):
        if isinstance(obj, MapIcd10LegacyReportingAlias):
            # An alias is not scheme-scoped: it can move a death in any scheme.
            mark_all_schemes_stale(session)
        elif isinstance(obj, (MasCodBucketScheme, MasCodBucketSchemeAgeBand,
                              MasCodBucketNode, MapIcdCodBucket)):
            if obj.scheme_id is not None:
                mark_scheme_stale(obj.scheme_id, session)


@sa.event.listens_for(Session, "after_commit")
def _enqueue_rebuilds(session):
    # A savepoint release also fires after_commit: enqueue only at the outer
    # commit, so a later rollback cannot rebuild for edits that never landed.
    if session.in_nested_transaction():
        return
    pending = session.info.pop(_PENDING, None)
    if not pending or not current_app.config.get("COD_BUCKET_REBUILD_ON_COMMIT", True):
        return
    try:
        from app.tasks.sync_tasks import (
            rebuild_cod_bucket_rows_task,
            rebuild_cod_bucket_scheme_task,
        )

        if _ALL_SCHEMES in pending:
            rebuild_cod_bucket_rows_task.delay()
        else:
            for scheme_id in pending:
                rebuild_cod_bucket_scheme_task.delay(str(scheme_id))
    except Exception:
        # The edit is committed; the next sweep (after the hourly MV refresh)
        # rebuilds the scheme anyway.
        log.warning("Could not queue a COD bucket rebuild", exc_info=True)


@sa.event.listens_for(Session, "after_soft_rollback")
def _drop_pending_rebuilds(session, previous_transaction):
    if previous_transaction.parent is None:
        session.info.pop(_PENDING, None)
