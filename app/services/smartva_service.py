"""Centralized SmartVA generation service.

All SmartVA operations go through this module. Protected workflow states
(coder_finalized, revoked_va_data_changed, closed) are excluded from
automatic generation unless force=True is passed (admin only).
"""
import uuid
import tempfile
import logging

import sqlalchemy as sa

from app import db
from app.models import (
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)

log = logging.getLogger(__name__)


def _protected_states():
    from app.services.submission_workflow_service import (
        WORKFLOW_CODER_FINALIZED,
        WORKFLOW_REVOKED_VA_DATA_CHANGED,
        WORKFLOW_CLOSED,
    )
    return frozenset({WORKFLOW_CODER_FINALIZED, WORKFLOW_REVOKED_VA_DATA_CHANGED, WORKFLOW_CLOSED})


def pending_smartva_sids(form_id: str) -> set[str]:
    """Return va_sids that need SmartVA for a form.

    Excludes:
    - submissions that already have an active SmartVA result
    - submissions in protected workflow states
    """
    from app.models import VaSubmissionWorkflow

    all_sids = set(
        db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_form_id == form_id)
        ).all()
    )
    if not all_sids:
        return set()

    done_sids = set(
        db.session.scalars(
            sa.select(VaSmartvaResults.va_sid).where(
                VaSmartvaResults.va_sid.in_(all_sids),
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        ).all()
    )

    protected_sids = set(
        db.session.scalars(
            sa.select(VaSubmissionWorkflow.va_sid).where(
                VaSubmissionWorkflow.va_sid.in_(all_sids),
                VaSubmissionWorkflow.workflow_state.in_(_protected_states()),
            )
        ).all()
    )

    return all_sids - done_sids - protected_sids


def _save_smartva_result(
    va_sid: str,
    record,
    *,
    existing=None,
    audit_action: str = "va_smartva_creation_during_datasync",
) -> uuid.UUID:
    """Deactivate any existing active result and persist a new SmartVA result.

    Does NOT commit — caller is responsible for committing.
    Returns the new result UUID.
    """
    if existing:
        existing.va_smartva_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=existing.va_smartva_id,
                va_audit_byrole="vaadmin",
                va_audit_operation="d",
                va_audit_action="va_smartva_deletion_during_datasync",
            )
        )

    result_id = uuid.uuid4()
    db.session.add(
        VaSmartvaResults(
            va_smartva_id=result_id,
            va_sid=va_sid,
            va_smartva_age=(
                format(float(getattr(record, "age", None)), ".1f")
                if getattr(record, "age", None) is not None
                else None
            ),
            va_smartva_gender=getattr(record, "sex", None),
            va_smartva_cause1=getattr(record, "cause1", None),
            va_smartva_likelihood1=getattr(record, "likelihood1", None),
            va_smartva_keysymptom1=getattr(record, "key_symptom1", None),
            va_smartva_cause2=getattr(record, "cause2", None),
            va_smartva_likelihood2=getattr(record, "likelihood2", None),
            va_smartva_keysymptom2=getattr(record, "key_symptom2", None),
            va_smartva_cause3=getattr(record, "cause3", None),
            va_smartva_likelihood3=getattr(record, "likelihood3", None),
            va_smartva_keysymptom3=getattr(record, "key_symptom3", None),
            va_smartva_allsymptoms=getattr(record, "all_symptoms", None),
            va_smartva_resultfor=getattr(record, "result_for", None),
            va_smartva_cause1icd=getattr(record, "cause1_icd", None),
            va_smartva_cause2icd=getattr(record, "cause2_icd", None),
            va_smartva_cause3icd=getattr(record, "cause3_icd", None),
        )
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_entityid=result_id,
            va_audit_byrole="vaadmin",
            va_audit_operation="c",
            va_audit_action=audit_action,
        )
    )
    return result_id


def generate_for_form(
    va_form,
    *,
    amended_sids: set[str] | None = None,
    log_progress=None,
) -> int:
    """Run SmartVA for one form, saving results for pending and amended submissions.

    - Excludes protected workflow states.
    - Amended sids that are now protected are also excluded.
    - Returns count of results saved.
    - Caller should NOT pre-commit before calling; this function commits internally.
    """
    from app.utils import (
        va_smartva_prepdata,
        va_smartva_runsmartva,
        va_smartva_formatsmartvaresult,
        va_smartva_appendsmartvaresults,
    )
    from app.models import VaSubmissionWorkflow

    amended_sids = amended_sids or set()

    # Base pending set (no active result, not protected)
    pending = pending_smartva_sids(va_form.form_id)

    # Add amended sids that belong to this form and are not protected
    if amended_sids:
        form_amended = set(
            db.session.scalars(
                sa.select(VaSubmissions.va_sid).where(
                    VaSubmissions.va_form_id == va_form.form_id,
                    VaSubmissions.va_sid.in_(amended_sids),
                )
            ).all()
        )
        if form_amended:
            protected_amended = set(
                db.session.scalars(
                    sa.select(VaSubmissionWorkflow.va_sid).where(
                        VaSubmissionWorkflow.va_sid.in_(form_amended),
                        VaSubmissionWorkflow.workflow_state.in_(_protected_states()),
                    )
                ).all()
            )
            pending |= (form_amended - protected_amended)

    if not pending:
        log.info("SmartVA [%s]: all results up to date, skipping.", va_form.form_id)
        if log_progress:
            log_progress(f"SmartVA {va_form.form_id}: all results up to date, skipping.")
        return 0

    log.info("SmartVA [%s]: preparing input (%d pending).", va_form.form_id, len(pending))
    if log_progress:
        log_progress(f"SmartVA {va_form.form_id}: preparing input ({len(pending)} pending)…")

    with tempfile.TemporaryDirectory() as workspace_dir:
        va_smartva_prepdata(va_form, workspace_dir, pending_sids=pending)
        va_smartva_runsmartva(va_form, workspace_dir)
        output_file = va_smartva_formatsmartvaresult(va_form, workspace_dir)
        if not output_file:
            log.warning("SmartVA [%s]: no output file produced.", va_form.form_id)
            return 0

        new_results, existing_active = va_smartva_appendsmartvaresults(
            db.session, {va_form: output_file}
        )

    if new_results is None:
        log.info("SmartVA [%s]: no new results.", va_form.form_id)
        return 0

    saved = 0
    for record in new_results.itertuples():
        va_sid = getattr(record, "sid", None)
        existing = existing_active.get(va_sid)

        # Skip if not amended and result already exists
        if va_sid not in amended_sids and existing:
            continue

        _save_smartva_result(va_sid, record, existing=existing)
        saved += 1

    db.session.commit()
    log.info("SmartVA [%s]: committed %d result(s).", va_form.form_id, saved)
    if log_progress:
        log_progress(f"SmartVA {va_form.form_id}: {saved} result(s) saved.")
    return saved


def generate_for_submission(va_sid: str, *, log_progress=None) -> int:
    """Run SmartVA for a single submission if it is not in a protected state.

    Returns 1 if a result was generated, 0 if skipped or nothing produced.
    """
    from app.utils import (
        va_smartva_prepdata,
        va_smartva_runsmartva,
        va_smartva_formatsmartvaresult,
        va_smartva_appendsmartvaresults,
    )
    from app.models import VaForms, VaSubmissionWorkflow

    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        log.warning("SmartVA generate_for_submission: submission %s not found.", va_sid)
        return 0

    current_state = db.session.scalar(
        sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == va_sid
        )
    )
    if current_state in _protected_states():
        log.info("SmartVA [%s]: skipped — protected state %s.", va_sid, current_state)
        if log_progress:
            log_progress(f"[{va_sid}] SmartVA skipped — protected state: {current_state}")
        return 0

    va_form = db.session.get(VaForms, submission.va_form_id)
    if va_form is None:
        log.warning("SmartVA generate_for_submission: form %s not found.", submission.va_form_id)
        return 0

    with tempfile.TemporaryDirectory() as workspace_dir:
        va_smartva_prepdata(va_form, workspace_dir, pending_sids={va_sid})
        va_smartva_runsmartva(va_form, workspace_dir)
        output_file = va_smartva_formatsmartvaresult(va_form, workspace_dir)
        if not output_file:
            return 0

        new_results, existing_active = va_smartva_appendsmartvaresults(
            db.session, {va_form: output_file}
        )

    if new_results is None:
        return 0

    saved = 0
    for record in new_results.itertuples():
        result_sid = getattr(record, "sid", None)
        if result_sid != va_sid:
            continue
        existing = existing_active.get(result_sid)
        _save_smartva_result(result_sid, record, existing=existing)
        saved += 1

    db.session.commit()
    return saved


def generate_all_pending(*, log_progress=None) -> dict:
    """Run SmartVA for all active forms (standalone Phase 2 run).

    Protected states are excluded. Returns {"smartva_updated": N}.
    """
    from app.services.runtime_form_sync_service import sync_runtime_forms_from_site_mappings

    if log_progress:
        log_progress("SmartVA-only run started.")
    log.info("SmartVA generate_all_pending: starting.")

    va_forms = sync_runtime_forms_from_site_mappings()
    if not va_forms:
        if log_progress:
            log_progress("No active mapped VA forms found.")
        return {"smartva_updated": 0}

    total = 0
    for va_form in va_forms:
        try:
            saved = generate_for_form(va_form, log_progress=log_progress)
            total += saved
        except Exception as exc:
            db.session.rollback()
            log.warning("SmartVA-only [%s] failed: %s", va_form.form_id, exc, exc_info=True)
            if log_progress:
                log_progress(f"SmartVA {va_form.form_id}: FAILED — {exc}")

    log.info("SmartVA generate_all_pending: complete, %d result(s) saved.", total)
    return {"smartva_updated": total}
