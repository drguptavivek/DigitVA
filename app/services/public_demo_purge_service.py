"""Public demo retention (digitva-77v5.6): delete an account and everything it
created. Policy: docs/policy/public-demo.md sections 8 (eviction) and 9.

Two callers share ``delete_account``: the daily purge (accounts idle for
``PUBLIC_DEMO_PURGE_IDLE_DAYS``, one transaction each) and the eviction at the
account cap (``evict_one``, inside the sign-up transaction under its lock,
accounts idle for ``PUBLIC_DEMO_EVICT_IDLE_DAYS``).

Idle means no sign-in and no activity since the cutoff: the latest of
``va_users.last_signed_in_at`` (web and device sign-in, and a remember-me
return at most once a day, stamp it), creation, the account's newest
``auth_device_sessions`` row (a refreshed app session is use without a new
sign-in) and its newest ``va_web_intake_drafts`` row (work on a phone or in a
remembered browser tab).

The daily run also removes the SmartVA run folders of the demo project older
than the same idle period (``purge_smartva_runs``).

Guards, checked in the selection and again per account under the row lock:
``PUBLIC_DEMO_ENABLED``, ``PUBLIC_DEMO_PURGE_ENABLED`` (on only once the
nightly backup is verified), no project in ``va_project_master`` but the demo
project (the main-database guard), ``is_public_demo``, and per account: every
draft, death registration, submission, grant and device belongs to the demo
project, and no other account shares a case. Any miss refuses that account and
deletes nothing.

Rows go in explicit dependency order (``PLAN``): most ``va_sid`` foreign keys
have no ``ondelete``. Sign-in QR tokens and devices reference each other
(``redeemed_device_id`` / ``enrolled_via_sign_in_token``): the back-reference
is nulled first, then the tokens (issued to the account or redeemed on its
devices) go before the devices. ``auth_security_events`` is kept (its user columns go to
NULL). Stored files are removed after the commit, never before: the paths wait
in ``session.info`` and are dropped by a rollback. Logs and audit rows carry
counts only, never a username or content.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.orm import Session

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceEnrolmentCode,
    AuthDeviceSession,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaSmartvaFormRun,
    VaSmartvaRun,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
)
from app.services import public_demo_service as demo
from app.services.security_event_service import record_security_event

log = logging.getLogger(__name__)

PURGE_EVENT = "public_demo_purge"
EVICT_EVENT = "public_demo_evict"
#: Upper bounds on the candidates one run looks at, so accounts the guards
#: refuse (they stay idle and are reselected every night) cannot starve the
#: batch, and a bad table cannot make a run unbounded.
PURGE_SCAN_LIMIT = 1000
EVICT_SCAN_LIMIT = 25
#: SmartVA run folders handled per daily run.
SMARTVA_RUN_BATCH = 200

#: Tables the deletion empties for the account, in deletion order. ``:u`` is
#: the account, ``:drafts`` / ``:deaths`` / ``:sids`` the ids it created and
#: ``:devices`` the devices only it signed in on. Children before parents.
#:
#: ponytail: several of these filters (notifications by draft/sid/death, bundle
#: and audit rows by actor) have no index; each is a scan of a table the demo
#: keeps small (bounded accounts, 30-day retention, notification purge). Add
#: indexes by migration if a demo table grows past some tens of thousands of rows.
PLAN: tuple[tuple[str, str], ...] = (
    ("map_user_notifications",
     "user_id = :u OR draft_id IN :drafts OR va_sid IN :sids OR death_id IN :deaths"),
    ("va_submission_notifications", "va_sid IN :sids"),
    ("va_submission_upstream_changes", "va_sid IN :sids"),
    ("va_final_cod_authority", "va_sid IN :sids"),
    ("va_coding_episodes", "va_sid IN :sids"),
    ("va_reviewer_final_assessments", "va_sid IN :sids"),
    ("va_reviewer_initial_assessments", "va_sid IN :sids"),
    ("va_reviewer_review", "va_sid IN :sids"),
    ("va_final_assessments", "va_sid IN :sids"),
    ("va_initial_assessments", "va_sid IN :sids"),
    ("va_narrative_assessments", "va_sid IN :sids"),
    ("va_social_autopsy_analysis_options",
     "va_saa_id IN (SELECT va_saa_id FROM va_social_autopsy_analyses WHERE va_sid IN :sids)"),
    ("va_social_autopsy_analyses", "va_sid IN :sids"),
    ("va_coder_review", "va_sid IN :sids"),
    ("va_data_manager_review", "va_sid IN :sids"),
    ("va_allocations", "va_sid IN :sids"),
    ("va_usernotes", "note_vasubmission IN :sids"),
    ("va_submissions_auditlog", "va_sid IN :sids"),
    ("va_submission_workflow_events", "va_sid IN :sids"),
    ("va_submission_workflow", "va_sid IN :sids"),
    ("va_bundle_pending_coding", "va_sid IN :sids OR death_id IN :deaths OR actor_user_id = :u"),
    ("va_smartva_run_outputs",
     "va_smartva_run_id IN (SELECT va_smartva_run_id FROM va_smartva_runs WHERE va_sid IN :sids)"),
    ("va_smartva_results", "va_sid IN :sids"),
    ("va_smartva_runs", "va_sid IN :sids"),
    ("va_submission_attachments", "va_sid IN :sids"),
    ("map_payload_version_pii", "va_sid IN :sids"),
    ("va_submission_payload_versions", "va_sid IN :sids"),
    ("map_bundle_records",
     "death_id IN :deaths OR bundle_id IN (SELECT bundle_id FROM va_bundle_ingests "
     "WHERE uploader_user_id = :u OR device_id IN :devices)"),
    ("map_case_contact_attempts", "death_id IN :deaths"),
    ("map_case_transitions", "death_id IN :deaths"),
    ("map_death_identifier", "death_id IN :deaths"),
    ("va_consent_record_purposes",
     "consent_id IN (SELECT consent_id FROM va_consent_records WHERE death_id IN :deaths)"),
    ("va_consent_records", "death_id IN :deaths"),
    ("va_web_intake_attachments", "draft_id IN :drafts"),
    ("va_web_intake_draft_sections", "draft_id IN :drafts"),
    ("va_web_intake_drafts", "draft_id IN :drafts"),
    ("va_death_register", "death_id IN :deaths"),
    ("va_submissions", "va_sid IN :sids"),
    ("va_bundle_ingests", "uploader_user_id = :u OR device_id IN :devices"),
    ("auth_device_sessions", "user_id = :u"),
    ("auth_device_signing_keys", "device_id IN :devices"),
    ("auth_sign_in_tokens", "user_id = :u OR redeemed_device_id IN :devices"),
    ("auth_devices", "device_id IN :devices"),
    ("auth_device_enrolment_codes",
     "created_by = :u AND NOT EXISTS (SELECT 1 FROM auth_devices d "
     "WHERE d.enrolled_via = auth_device_enrolment_codes.id)"),
    ("map_consent_audit", "actor_user_id = :u"),
    ("map_identifier_audit", "actor_user_id = :u"),
    ("mas_pii_access_log", "user_id = :u"),
    ("auth_mobile_codes", "user_id = :u"),
    ("auth_recovery_codes", "user_id = :u"),
    ("auth_totp", "user_id = :u"),
    ("auth_webauthn_credentials", "user_id = :u"),
    ("map_mentor_institute_user", "user_id = :u"),
    ("mas_org_unit_worker", "user_id = :u"),
    ("map_training_participants", "user_id = :u"),
    ("va_user_access_grants", "user_id = :u"),
    ("va_users", "user_id = :u"),
)
PURGED_TABLES = frozenset(table for table, _ in PLAN)

#: Tables that reference an account or a case and are deliberately left alone.
#: A row here that points at a purged account makes the delete fail (and roll
#: back) rather than lose data, except where the key is SET NULL.
RETAINED_TABLES = {
    "auth_security_events": "audit trail; user columns are ON DELETE SET NULL",
    "va_smartva_form_runs": "one run per form, shared by every account, no account key; aged out by purge_smartva_runs",
    "auth_station_configs": "offline station setup, admin only; a demo account never has one",
    "auth_station_custodians": "offline station setup, admin only",
    "auth_station_roster": "offline station setup, admin only",
    "map_training_cases": "training project only",
    "map_instrument_translations": "admin-edited translations",
    "map_instrument_translation_suggestions": "admin-edited translations",
    "map_mentor_institute_org_unit": "admin configuration",
    "map_org_unit_va_presets": "admin configuration",
    "mas_consent_notice_versions": "admin configuration (notice approval)",
    "mas_instrument_locales": "admin configuration",
    "mas_mentor_institute": "admin configuration",
    "mas_project_consent_settings": "admin configuration",
    "mas_training_sessions": "training project only",
    "mas_ui_string_override": "admin configuration",
    "mas_va_cause_definitions": "admin configuration; ON DELETE SET NULL",
    "va_cod_bucket_scheme_snapshots": "admin configuration",
    "va_db_backups": "admin operations",
    "va_site_maintenance": "admin operations",
    "va_sync_runs": "admin operations",
}


class PurgeRefused(RuntimeError):
    """An account the guards will not delete; ``reason`` is a fixed code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def refusal(*, apply: bool = True) -> str | None:
    """Why deletion cannot run on this deployment, or None. A dry run needs
    only the flag and the main-database guard; applying also needs
    ``PUBLIC_DEMO_PURGE_ENABLED``."""
    if not demo.enabled():
        return "not_enabled"
    if apply and not current_app.config.get("PUBLIC_DEMO_PURGE_ENABLED"):
        return "purge_disabled"
    if demo.foreign_projects_exist():
        demo.log_main_database_refusal()
        return "main_database"
    return None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _last_activity():
    """SQL: the latest of last sign-in, creation (``timestamp`` in UTC), the
    account's newest device-session row and its newest draft row. GREATEST
    ignores NULLs."""
    draft = (
        sa.select(sa.func.max(sa.func.greatest(VaWebIntakeDraft.updated_at, VaWebIntakeDraft.created_at)))
        .where(VaWebIntakeDraft.user_id == VaUsers.user_id)
        .correlate(VaUsers)
        .scalar_subquery()
    )
    device = (
        sa.select(sa.func.max(sa.func.greatest(
            AuthDeviceSession.created_at, AuthDeviceSession.last_seen_at, AuthDeviceSession.refreshed_at,
        )))
        .where(AuthDeviceSession.user_id == VaUsers.user_id)
        .correlate(VaUsers)
        .scalar_subquery()
    )
    return sa.func.greatest(
        VaUsers.last_signed_in_at, sa.func.timezone("UTC", VaUsers.user_created_at), device, draft,
    )


def _eligible(idle_days: int, now: datetime):
    return (VaUsers.is_public_demo.is_(True), _last_activity() <= now - timedelta(days=idle_days))


def idle_user_ids(idle_days: int, *, limit: int, active_only: bool = False, lock: bool = False,
                  now: datetime | None = None) -> list:
    """Ids of public-demo accounts idle at least *idle_days*, oldest first, at
    most *limit*. *lock* takes the rows (skipping any another transaction
    holds). Public-demo accounts are capped, so this is a short scan of the
    ``is_public_demo`` rows."""
    stmt = (
        sa.select(VaUsers.user_id)
        .where(*_eligible(idle_days, now or datetime.now(UTC)))
        .order_by(_last_activity(), VaUsers.user_id)
        .limit(limit)
    )
    if active_only:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    if lock:
        stmt = stmt.with_for_update(skip_locked=True, of=VaUsers)
    return list(db.session.scalars(stmt))


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

_FILES = "public_demo_files_to_delete"


def _bind(name: str, params: dict):
    """A typed bind: an empty list otherwise renders as an INTEGER set, which
    does not compare with a uuid column."""
    kind = sa.String if name == "sids" else sa.Uuid
    return sa.bindparam(name, expanding=isinstance(params[name], list), type_=kind)


def _run(table: str, where: str, params: dict) -> int:
    """One DELETE; *table* and *where* are the literals of ``PLAN``, every
    value is a bound parameter (lists expand)."""
    names = set(re.findall(r":([a-z]+)", where))
    stmt = sa.text(f"DELETE FROM {table} WHERE {where}").bindparams(*[_bind(name, params) for name in names])
    return db.session.execute(stmt, {name: params[name] for name in names}).rowcount


def _collect(user_id) -> dict:
    """The ids the account owns, after the project checks. Raises PurgeRefused."""
    project = demo.demo_project_id()
    session = db.session
    drafts = session.execute(
        sa.select(VaWebIntakeDraft.draft_id, VaWebIntakeDraft.project_id, VaWebIntakeDraft.va_sid)
        .where(VaWebIntakeDraft.user_id == user_id)
    ).all()
    deaths = session.execute(
        sa.select(VaDeathRegister.death_id, VaDeathRegister.project_id, VaDeathRegister.va_sid)
        .where(sa.or_(VaDeathRegister.registered_by == user_id, VaDeathRegister.started_by_user_id == user_id))
    ).all()
    if any(row.project_id != project for row in (*drafts, *deaths)):
        raise PurgeRefused("not_demo_project")
    draft_ids = [row.draft_id for row in drafts]
    death_ids = [row.death_id for row in deaths]
    sids = sorted({row.va_sid for row in (*drafts, *deaths) if row.va_sid})

    if sids:
        foreign = session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissions)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(VaSubmissions.va_sid.in_(sids), VaForms.project_id != project)
        )
        if foreign:
            raise PurgeRefused("not_demo_project")
    shared = session.scalar(
        sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id != user_id,
            sa.or_(VaWebIntakeDraft.va_sid.in_(sids), VaWebIntakeDraft.death_id.in_(death_ids)),
        )
    ) + session.scalar(
        sa.select(sa.func.count()).select_from(VaDeathRegister).where(
            VaDeathRegister.va_sid.in_(sids),
            VaDeathRegister.registered_by != user_id,
            sa.or_(VaDeathRegister.started_by_user_id.is_(None), VaDeathRegister.started_by_user_id != user_id),
        )
    )
    if shared:
        raise PurgeRefused("shared_case")

    outside_grants = session.scalar(
        sa.select(sa.func.count()).select_from(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user_id,
            sa.not_(sa.and_(
                VaUserAccessGrants.project_id == project,
                VaUserAccessGrants.role.in_(demo.DEMO_ROLES),
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            )),
        )
    )
    if outside_grants:
        raise PurgeRefused("grant_outside_demo")

    devices = session.execute(
        sa.select(AuthDevice.device_id, AuthDevice.project_id)
        .where(sa.or_(
            AuthDevice.device_id.in_(
                sa.select(AuthDeviceSession.device_id).where(AuthDeviceSession.user_id == user_id)),
            # Enrolled by the account through the demo enrolment, signed in or not.
            AuthDevice.enrolled_via.in_(
                sa.select(AuthDeviceEnrolmentCode.id).where(AuthDeviceEnrolmentCode.created_by == user_id)),
        ))
    ).all()
    if any(row.project_id != project for row in devices):
        raise PurgeRefused("not_demo_project")
    shared_devices = set(session.scalars(
        sa.select(AuthDeviceSession.device_id).where(
            AuthDeviceSession.user_id != user_id,
            AuthDeviceSession.device_id.in_([row.device_id for row in devices]),
        )
    ))
    return {
        "u": user_id,
        "drafts": draft_ids,
        "deaths": death_ids,
        "sids": sids,
        "devices": [row.device_id for row in devices if row.device_id not in shared_devices],
    }


def _files(ids: dict) -> list[tuple[str, str | None, str | None]]:
    """``(form_id, storage_name, local_path)`` of every stored object the
    account's draft uploads and submission attachments hold."""
    session = db.session
    rows = session.execute(
        sa.select(VaWebIntakeDraft.form_id, VaWebIntakeAttachment.storage_name, VaWebIntakeAttachment.local_path)
        .join(VaWebIntakeDraft, VaWebIntakeDraft.draft_id == VaWebIntakeAttachment.draft_id)
        .where(VaWebIntakeAttachment.draft_id.in_(ids["drafts"]))
    ).all() + session.execute(
        sa.select(VaSubmissions.va_form_id, VaSubmissionAttachments.storage_name, VaSubmissionAttachments.local_path)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(VaSubmissionAttachments.va_sid.in_(ids["sids"]))
    ).all()
    return sorted({tuple(row) for row in rows if row[1] or row[2]}, key=str)


def _delete_rows(user_id, idle_days: int, *, apply: bool, now: datetime | None):
    """The deletion proper: ``(counts, files)``. Queues nothing; the caller
    decides when the files may be removed."""
    reason = refusal(apply=apply)
    if reason:
        raise PurgeRefused(reason)
    locked = db.session.scalar(
        sa.select(VaUsers.user_id)
        .where(VaUsers.user_id == user_id, *_eligible(idle_days, now or datetime.now(UTC)))
        .with_for_update(skip_locked=True, of=VaUsers)
    )
    if locked is None:
        raise PurgeRefused("not_eligible")
    ids = _collect(user_id)
    files = _files(ids)
    counts: dict[str, int] = {}
    db.session.execute(
        sa.text("UPDATE va_death_register SET duplicate_of_death_id = NULL WHERE duplicate_of_death_id IN :deaths")
        .bindparams(_bind("deaths", ids)), {"deaths": ids["deaths"]},
    )
    db.session.execute(
        sa.text("UPDATE va_submissions SET active_payload_version_id = NULL WHERE va_sid IN :sids")
        .bindparams(_bind("sids", ids)), {"sids": ids["sids"]},
    )
    # The device -> token side of the cycle; the token -> device side is the
    # ``auth_sign_in_tokens`` step, which runs before ``auth_devices``.
    db.session.execute(
        sa.text("UPDATE auth_devices SET enrolled_via_sign_in_token = NULL WHERE enrolled_via_sign_in_token IN "
                "(SELECT id FROM auth_sign_in_tokens WHERE user_id = :u OR redeemed_device_id IN :devices)")
        .bindparams(_bind("u", ids), _bind("devices", ids)), {"u": ids["u"], "devices": ids["devices"]},
    )
    for table, where in PLAN:
        deleted = _run(table, where, ids)
        if deleted:
            counts[table] = deleted
    if counts.get("va_users") != 1:
        raise PurgeRefused("not_eligible")
    db.session.expire_all()
    counts["files"] = len(files)
    return counts, files


def _queue_files(files) -> None:
    """Remove *files* when the outermost transaction commits (never on a
    rollback). Call only once nothing can roll the deletion back on its own,
    that is after a savepoint block succeeded."""
    db.session().info.setdefault(_FILES, []).extend(files)


def delete_account(user_id, idle_days: int, *, apply: bool = True, now: datetime | None = None) -> dict[str, int]:
    """Delete one public-demo account and everything it created, in the
    caller's transaction (the caller commits, which then removes the stored
    files). Returns rows deleted per table plus ``files`` queued.

    *apply* False is the dry run's guard set (the purge flag may be off).

    Raises PurgeRefused: ``not_enabled`` / ``purge_disabled`` /
    ``main_database`` from the deployment guards, ``not_eligible`` when the
    row is not a public-demo account idle that long (or another transaction
    holds it), ``not_demo_project`` / ``shared_case`` / ``grant_outside_demo``
    from the per-account guards. A refusal deletes nothing.
    """
    counts, files = _delete_rows(user_id, idle_days, apply=apply, now=now)
    _queue_files(files)
    return counts


def _remove_files(files) -> None:
    from app.services.attachment_store import StoreTarget, get_attachment_store

    store = get_attachment_store()
    failed = 0
    for form_id, storage_name, local_path in files:
        try:
            store.delete(StoreTarget(va_form_id=form_id, storage_name=storage_name, local_path=local_path))
        except Exception:  # noqa: BLE001 - an orphan is reported by `attachment integrity`, not fatal
            failed += 1
    log.info("public demo files removed | files=%d | failed=%d", len(files), failed)


@sa.event.listens_for(Session, "after_commit")
def _remove_committed_files(session) -> None:
    """Remove the stored files of accounts deleted by the transaction that
    just committed. A savepoint release fires this event too and is ignored:
    the outer transaction may still roll back."""
    if session.get_nested_transaction() is not None or _FILES not in session.info:
        return
    files = session.info.pop(_FILES)
    try:
        _remove_files(files)
    except Exception:  # noqa: BLE001 - never fail a commit that already happened
        log.error("public demo file removal failed", exc_info=True)


@sa.event.listens_for(Session, "after_soft_rollback")
def _drop_queued_files(session, previous_transaction) -> None:
    if previous_transaction.parent is None:
        session.info.pop(_FILES, None)


# ---------------------------------------------------------------------------
# Callers
# ---------------------------------------------------------------------------


def _add(totals: dict, counts: dict) -> None:
    for table, n in counts.items():
        totals[table] = totals.get(table, 0) + n


def purge_run(*, apply: bool) -> dict:
    """The daily purge. ``apply`` False deletes inside each account's
    transaction and rolls it back, so the counts are exact and nothing
    changes. Never raises for one account's failure: it is counted.

    Returns ``{status, accounts, refused, failed, rows}``; ``status`` is
    ``ok`` or the deployment refusal code (nothing touched). One security
    event with the counts is written when applying and something was deleted.
    """
    config = current_app.config
    reason = refusal(apply=apply)
    if reason:
        return {"status": reason, "accounts": 0, "refused": {}, "failed": 0, "rows": {}}
    days = int(config.get("PUBLIC_DEMO_PURGE_IDLE_DAYS", 30))
    batch = int(config.get("PUBLIC_DEMO_PURGE_BATCH", 100))
    # Look past refused accounts: the run ends at *batch* deletions, the end of
    # the candidates or PURGE_SCAN_LIMIT, whichever comes first.
    ids = idle_user_ids(days, limit=max(batch, PURGE_SCAN_LIMIT))
    db.session.rollback()
    done, failed, refused, rows = 0, 0, {}, {}
    for user_id in ids:
        if done >= batch:
            break
        try:
            counts = delete_account(user_id, days, apply=apply)
            (db.session.commit if apply else db.session.rollback)()
            done += 1
            _add(rows, counts)
        except PurgeRefused as exc:
            db.session.rollback()
            refused[exc.reason] = refused.get(exc.reason, 0) + 1
        except Exception:  # noqa: BLE001 - one account must not stop the run
            db.session.rollback()
            failed += 1
            log.error("public demo purge failed for one account", exc_info=True)
    smartva = purge_smartva_runs(days, apply=apply)
    if apply and (done or smartva["runs"] or smartva["files_only"]):
        record_security_event(user_id=None, event_type=PURGE_EVENT, detail={
            "accounts": done, "refused": refused, "failed": failed, "rows": rows, "smartva_runs": smartva,
        })
        db.session.commit()
    log.info(
        "public demo purge | apply=%s | accounts=%d | refused=%s | failed=%d | smartva_runs=%s",
        apply, done, refused, failed, smartva,
    )
    return {"status": "ok", "accounts": done, "refused": refused, "failed": failed, "rows": rows,
            "smartva_runs": smartva}


# ---------------------------------------------------------------------------
# SmartVA run folders
# ---------------------------------------------------------------------------


def _remove_run_files(run: VaSmartvaFormRun) -> None:
    """Delete one run's folder on disk and its objects in the store. Raises on
    a failure so the row is kept for tomorrow."""
    from app.services.smartva_run_archive_service import archive_key_prefix_for, archiving_enabled
    from app.services.smartva_service import resolve_form_run_disk_path

    run_id = str(run.form_run_id)
    if run.disk_path:
        path = resolve_form_run_disk_path(run.disk_path)
        # Only a folder named for this run, never a parent that a bad path could name.
        if os.path.basename(os.path.normpath(path)) != run_id or os.path.islink(path):
            raise OSError("unexpected run path")
        if os.path.isdir(path):
            shutil.rmtree(path)
    if run.archive_key_prefix or run.archive_state == VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED:
        if not archiving_enabled():
            raise OSError("archived run but the store is not S3")
        from app.services.attachment_store import get_attachment_store

        store = get_attachment_store()
        prefix = archive_key_prefix_for(run)  # derived, never the stored text
        for key, _size, _etag in list(store.iter_keys(store.absolute_key(prefix))):
            store.delete_key(key[len(store.key_prefix):])


def purge_smartva_runs(idle_days: int, *, apply: bool, limit: int = SMARTVA_RUN_BATCH) -> dict[str, int]:
    """Remove SmartVA run folders (disk and object store) of the demo project
    started more than *idle_days* ago; they hold the inputs and outputs of
    users who are gone. The ``va_smartva_form_runs`` row goes too unless a
    ``va_smartva_runs`` row still references it (an account still in use has
    older submissions): then only the stored files go, the row stays with
    ``disk_path`` / ``archive_key_prefix`` cleared and state ``absent``.

    Bounded by *limit* runs; a run whose files cannot be removed is counted in
    ``failed`` and retried the next day. *apply* False counts and removes
    nothing. Returns ``{runs, files_only, failed}``.
    """
    result = {"runs": 0, "files_only": 0, "failed": 0}
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=idle_days)  # column is naive UTC
    referenced = sa.exists().where(VaSmartvaRun.form_run_id == VaSmartvaFormRun.form_run_id)
    candidates = list(db.session.scalars(
        sa.select(VaSmartvaFormRun)
        .where(
            VaSmartvaFormRun.project_id == demo.demo_project_id(),
            VaSmartvaFormRun.run_started_at < cutoff,
            sa.or_(
                VaSmartvaFormRun.disk_path.is_not(None),
                VaSmartvaFormRun.archive_key_prefix.is_not(None),
                sa.not_(referenced),
            ),
        )
        .order_by(VaSmartvaFormRun.run_started_at, VaSmartvaFormRun.form_run_id)
        .limit(limit)
    ))
    for run in candidates:
        is_referenced = db.session.scalar(sa.select(sa.exists().where(VaSmartvaRun.form_run_id == run.form_run_id)))
        if not apply:
            result["files_only" if is_referenced else "runs"] += 1
            continue
        try:
            _remove_run_files(run)
            if is_referenced:
                run.disk_path = None
                run.archive_key_prefix = None
                run.archive_state = VaSmartvaFormRun.ARCHIVE_STATE_ABSENT
            else:
                db.session.delete(run)
            db.session.commit()
            result["files_only" if is_referenced else "runs"] += 1
        except Exception:  # noqa: BLE001 - one run must not stop the others
            db.session.rollback()
            result["failed"] += 1
            log.error("public demo SmartVA run folder removal failed", exc_info=True)
    if not apply:
        db.session.rollback()
    return result


def evict_one() -> bool:
    """At the account cap: delete the active account idle longest, if it has
    been idle at least ``PUBLIC_DEMO_EVICT_IDLE_DAYS``; True when one went.

    Runs in the sign-up transaction under its cap lock and writes no commit:
    the sign-up's commit ends it and removes the files; its rollback undoes
    it. Each try is a savepoint, so a failing candidate is skipped without
    poisoning the sign-up. False (nothing deleted) when the purge is off, the
    guards refuse or nobody has been idle that long.
    """
    if refusal() is not None:
        return False
    days = int(current_app.config.get("PUBLIC_DEMO_EVICT_IDLE_DAYS", 7))
    for user_id in idle_user_ids(days, limit=EVICT_SCAN_LIMIT, active_only=True, lock=True):
        try:
            with db.session.begin_nested():
                counts, files = _delete_rows(user_id, days, apply=True, now=None)
                record_security_event(user_id=None, event_type=EVICT_EVENT, detail={"rows": counts})
        except PurgeRefused as exc:
            log.warning("public demo eviction skipped an account | reason=%s", exc.reason)
        except Exception:  # noqa: BLE001
            log.error("public demo eviction failed for one account", exc_info=True)
        else:
            # Only now: a failed attempt above rolled its savepoint back, so its
            # files must never reach the queue the sign-up's commit empties.
            _queue_files(files)
            log.info("public demo account evicted at the cap | rows=%d", sum(counts.values()))
            return True
    return False
