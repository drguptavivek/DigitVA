"""Centralized SmartVA generation service."""

import logging
import math
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import pandas as pd
import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    VaSmartvaFormRun,
    VaSmartvaRun,
    VaSmartvaRunOutput,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def smartva_runs_base_dir() -> str:
    return current_app.config["APP_SMARTVA_RUNS"]


def resolve_form_run_disk_path(disk_path: str | None) -> str | None:
    if not disk_path:
        return None
    normalized = str(disk_path).replace("\\", "/").lstrip("/")
    if normalized.startswith("smartva_runs/"):
        return os.path.join(current_app.config["APP_DATA"], normalized)
    return os.path.join(smartva_runs_base_dir(), normalized)


def _normalize_json_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _smartva_output_payload(record) -> dict:
    if hasattr(record, "_asdict"):
        return {
            key: _normalize_json_value(value)
            for key, value in record._asdict().items()
            if key != "Index"
        }
    return {}


def _smartva_source_name(result_for: str | None) -> str | None:
    if result_for == "for_adult":
        return "adult-likelihoods.csv"
    if result_for == "for_child":
        return "child-likelihoods.csv"
    if result_for == "for_neonate":
        return "neonate-likelihoods.csv"
    return None


def _likelihood_output_path_map(workspace_dir: str) -> dict[str, str]:
    output_dir = os.path.join(
        workspace_dir,
        "smartva_output",
        "4-monitoring-and-quality",
        "intermediate-files",
    )
    return {
        "for_adult": os.path.join(output_dir, "adult-likelihoods.csv"),
        "for_child": os.path.join(output_dir, "child-likelihoods.csv"),
        "for_neonate": os.path.join(output_dir, "neonate-likelihoods.csv"),
    }


def _read_smartva_csv(file_path: str) -> pd.DataFrame:
    """Read a SmartVA output CSV, stripping null bytes before pandas parsing.

    SmartVA's intermediate files (e.g. adult-likelihoods.csv) sometimes pad
    fixed-width string fields with leading \\x00 null bytes.  Pandas' C CSV
    parser treats \\x00 as a string terminator, so the SID value is silently
    truncated to an empty string and the column is cast to float64 (NaN).
    Reading the raw bytes and replacing \\x00 before parsing avoids this.
    """
    import io
    with open(file_path, "rb") as fh:
        raw = fh.read()
    if b"\x00" in raw:
        log.debug(
            "SmartVA output file contains null bytes, stripping before parse: %s",
            file_path,
        )
        raw = raw.replace(b"\x00", b"")
    return pd.read_csv(io.BytesIO(raw))


def _read_raw_likelihood_outputs(
    workspace_dir: str,
    pending_sids: set[str],
) -> dict[str, list[tuple[str | None, dict]]]:
    outputs_by_sid: dict[str, list[tuple[str | None, dict]]] = {}
    for result_for, file_path in _likelihood_output_path_map(workspace_dir).items():
        if not os.path.exists(file_path):
            log.debug("SmartVA likelihood file not found (expected): %s", file_path)
            continue
        df = _read_smartva_csv(file_path)
        df = df.replace({pd.NA: None, float("nan"): None})
        if "sid" not in df.columns:
            log.warning("SmartVA likelihood file missing 'sid' column: %s", file_path)
            continue
        log.debug(
            "SmartVA likelihood file %s: %d rows, sample sid=%r",
            os.path.basename(file_path),
            len(df),
            str(df["sid"].iloc[0]) if len(df) else "(empty)",
        )
        for record in df.itertuples():
            payload = _smartva_output_payload(record)
            sid = payload.get("sid")
            if sid is None or sid not in pending_sids:
                continue
            payload["result_for"] = result_for
            outputs_by_sid.setdefault(sid, []).append(
                (_smartva_source_name(result_for), payload)
            )
    log.debug(
        "SmartVA likelihood outputs matched %d/%d pending SIDs.",
        len(outputs_by_sid),
        len(pending_sids),
    )
    return outputs_by_sid


def _read_formatted_results(output_file: str) -> pd.DataFrame | None:
    if not output_file or not os.path.exists(output_file):
        log.debug("SmartVA formatted output file not found: %s", output_file)
        return None
    df = _read_smartva_csv(output_file)
    df = df.replace({pd.NA: None, float("nan"): None})
    if "sid" not in df.columns:
        log.warning("SmartVA formatted output missing 'sid' column: %s", output_file)
        return None
    valid = df[df["sid"].notna() & (df["sid"].astype(str) != "nan") & (df["sid"].astype(str) != "")]
    log.debug(
        "SmartVA formatted output %s: %d total rows, %d with valid sid.",
        os.path.basename(output_file),
        len(df),
        len(valid),
    )
    return valid


_SMARTVA_REPORT_REJECTION_RE = re.compile(
    r"^SID:\s+(?P<sid>\S+)\s+\(row\s+\d+\)\s+(?P<reason>.+)$"
)


def _read_rejected_sids_from_report(
    workspace_dir: str,
    pending_sids: set[str],
) -> dict[str, str]:
    report_path = os.path.join(
        workspace_dir,
        "smartva_output",
        "4-monitoring-and-quality",
        "report.txt",
    )
    if not os.path.exists(report_path):
        return {}

    rejected: dict[str, str] = {}
    with open(report_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            match = _SMARTVA_REPORT_REJECTION_RE.match(line)
            if not match:
                continue
            sid = match.group("sid")
            if sid not in pending_sids:
                continue
            rejected[sid] = match.group("reason").strip()
    return rejected


def _smartva_form_run_relpath(form_run: VaSmartvaFormRun) -> str:
    return os.path.join(
        form_run.project_id,
        form_run.form_id,
        str(form_run.form_run_id),
    ).replace(os.sep, "/")


def _copy_form_run_workspace(
    form_run: VaSmartvaFormRun,
    *,
    workspace_dir: str | None,
) -> None:
    if not workspace_dir or not os.path.isdir(workspace_dir):
        return
    rel_path = _smartva_form_run_relpath(form_run)
    abs_path = resolve_form_run_disk_path(rel_path)
    if os.path.exists(abs_path):
        shutil.rmtree(abs_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    shutil.copytree(workspace_dir, abs_path)
    form_run.disk_path = rel_path


def _create_smartva_form_run(
    va_form,
    *,
    pending_sid_count: int,
    trigger_source: str,
) -> VaSmartvaFormRun:
    form_run = VaSmartvaFormRun(
        form_run_id=uuid.uuid4(),
        form_id=va_form.form_id,
        project_id=va_form.project_id,
        trigger_source=trigger_source[:32],
        pending_sid_count=pending_sid_count,
        outcome=None,
        disk_path=None,
        run_started_at=_utcnow(),
        run_completed_at=None,
    )
    db.session.add(form_run)
    db.session.flush()
    return form_run


def _finalize_smartva_form_run(
    form_run: VaSmartvaFormRun,
    *,
    workspace_dir: str | None,
    outcome: str,
) -> None:
    _copy_form_run_workspace(form_run, workspace_dir=workspace_dir)
    form_run.outcome = outcome
    form_run.run_completed_at = _utcnow()


def _create_smartva_run(
    va_sid: str,
    *,
    form_run_id,
    payload_version_id,
    trigger_source: str,
    outcome: str,
    failure_stage: str | None = None,
    failure_detail: str | None = None,
    run_metadata: dict | None = None,
) -> VaSmartvaRun:
    now = _utcnow()
    smartva_run = VaSmartvaRun(
        va_smartva_run_id=uuid.uuid4(),
        form_run_id=form_run_id,
        va_sid=va_sid,
        payload_version_id=payload_version_id,
        trigger_source=trigger_source,
        va_smartva_outcome=outcome,
        va_smartva_failure_stage=failure_stage[:32] if failure_stage else None,
        va_smartva_failure_detail=failure_detail[:4000] if failure_detail else None,
        run_metadata=run_metadata,
        va_smartva_run_started_at=now,
        va_smartva_run_completed_at=now,
        va_smartva_run_updated_at=now,
    )
    db.session.add(smartva_run)
    db.session.flush()
    return smartva_run


def _create_smartva_run_output(
    smartva_run_id: uuid.UUID,
    *,
    payload: dict,
    output_source_name: str | None,
) -> None:
    db.session.add(
        VaSmartvaRunOutput(
            va_smartva_run_output_id=uuid.uuid4(),
            va_smartva_run_id=smartva_run_id,
            output_kind="likelihood_row",
            output_source_name=output_source_name,
            output_row_index=0,
            output_sid=payload.get("sid"),
            output_resultfor=payload.get("result_for"),
            output_payload=payload,
        )
    )


def _transition_to_ready_after_smartva_if_pending(va_sid: str) -> None:
    from app.services.workflow.definition import WORKFLOW_SMARTVA_PENDING
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import mark_smartva_completed, system_actor

    if get_submission_workflow_state(va_sid) != WORKFLOW_SMARTVA_PENDING:
        return

    mark_smartva_completed(
        va_sid,
        reason="smartva_completed_for_current_payload",
        actor=system_actor(),
    )


def _transition_to_ready_after_smartva_failure_if_pending(va_sid: str) -> None:
    from app.services.workflow.definition import WORKFLOW_SMARTVA_PENDING
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import (
        mark_smartva_failed_recorded,
        system_actor,
    )

    if get_submission_workflow_state(va_sid) != WORKFLOW_SMARTVA_PENDING:
        return

    mark_smartva_failed_recorded(
        va_sid,
        reason="smartva_failed_for_current_payload",
        actor=system_actor(),
    )


def _protected_states():
    from app.services.workflow.definition import SMARTVA_BLOCKED_WORKFLOW_STATES

    return SMARTVA_BLOCKED_WORKFLOW_STATES


def pending_smartva_sids(form_id: str) -> set[str]:
    from app.models import VaSubmissionWorkflow

    all_sids = set(
        db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_form_id == form_id)
        ).all()
    )
    if not all_sids:
        return set()

    current_payload_done = set(
        db.session.scalars(
            sa.select(VaSubmissions.va_sid)
            .join(
                VaSmartvaResults,
                sa.and_(
                    VaSmartvaResults.va_sid == VaSubmissions.va_sid,
                    VaSmartvaResults.payload_version_id
                    == VaSubmissions.active_payload_version_id,
                ),
            )
            .where(
                VaSubmissions.va_form_id == form_id,
                VaSubmissions.va_sid.in_(all_sids),
                VaSubmissions.active_payload_version_id.is_not(None),
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

    return all_sids - current_payload_done - protected_sids


def _save_smartva_result(
    va_sid: str,
    record,
    *,
    form_run_id,
    payload_version_id,
    trigger_source: str,
    raw_outputs: list[tuple[str | None, dict]] | None = None,
    existing=None,
    audit_action: str = "va_smartva_creation_during_datasync",
) -> uuid.UUID:
    _deactivate_active_smartva_results(
        va_sid,
        existing if isinstance(existing, list) else ([existing] if existing else []),
    )

    smartva_run = _create_smartva_run(
        va_sid,
        form_run_id=form_run_id,
        payload_version_id=payload_version_id,
        trigger_source=trigger_source,
        outcome=VaSmartvaRun.OUTCOME_SUCCESS,
    )
    for output_source_name, raw_payload in raw_outputs or []:
        _create_smartva_run_output(
            smartva_run.va_smartva_run_id,
            payload=raw_payload,
            output_source_name=output_source_name,
        )

    result_id = uuid.uuid4()
    db.session.add(
        VaSmartvaResults(
            va_smartva_id=result_id,
            va_sid=va_sid,
            payload_version_id=payload_version_id,
            smartva_run_id=smartva_run.va_smartva_run_id,
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
            va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
            va_smartva_failure_stage=None,
            va_smartva_failure_detail=None,
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


def _active_smartva_results_for_sids(
    active_payload_by_sid: dict[str, uuid.UUID],
) -> dict[str, list[VaSmartvaResults]]:
    if not active_payload_by_sid:
        return {}
    rows = db.session.scalars(
        sa.select(VaSmartvaResults)
        .where(
            VaSmartvaResults.va_sid.in_(set(active_payload_by_sid)),
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
        )
        .order_by(VaSmartvaResults.va_smartva_addedat.desc())
    ).all()
    grouped: dict[str, list[VaSmartvaResults]] = {}
    for row in rows:
        grouped.setdefault(row.va_sid, []).append(row)
    return grouped


def _deactivate_active_smartva_results(
    va_sid: str,
    rows: list[VaSmartvaResults],
) -> None:
    for row in rows:
        row.va_smartva_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_smartva_id,
                va_audit_byrole="vaadmin",
                va_audit_operation="d",
                va_audit_action="va_smartva_deletion_during_datasync",
            )
        )


def promote_active_smartva_to_payload(
    va_sid: str,
    *,
    from_payload_version_id,
    to_payload_version_id,
) -> bool:
    """Rebind the currently preserved SmartVA result to a newly active payload."""
    active_rows = db.session.scalars(
        sa.select(VaSmartvaResults)
        .where(
            VaSmartvaResults.va_sid == va_sid,
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
        )
        .order_by(
            sa.case(
                (VaSmartvaResults.payload_version_id == from_payload_version_id, 0),
                else_=1,
            ),
            VaSmartvaResults.va_smartva_addedat.desc(),
        )
    ).all()
    if not active_rows:
        return False

    keeper = active_rows[0]
    extras = active_rows[1:]
    if extras:
        _deactivate_active_smartva_results(va_sid, extras)

    keeper.payload_version_id = to_payload_version_id
    if keeper.smartva_run_id is not None:
        run = db.session.get(VaSmartvaRun, keeper.smartva_run_id)
        if run is not None:
            run.payload_version_id = to_payload_version_id

    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_entityid=keeper.va_smartva_id,
            va_audit_byrole="vaadmin",
            va_audit_operation="u",
            va_audit_action="va_smartva_promoted_to_current_payload",
        )
    )
    return True


def _reactivate_latest_historical_smartva_to_payload(
    va_sid: str,
    *,
    to_payload_version_id,
) -> bool:
    """Reactivate the latest historical SmartVA projection on the current payload."""
    historical_rows = db.session.scalars(
        sa.select(VaSmartvaResults)
        .where(VaSmartvaResults.va_sid == va_sid)
        .order_by(
            sa.case(
                (
                    VaSmartvaResults.va_smartva_outcome
                    == VaSmartvaResults.OUTCOME_SUCCESS,
                    0,
                ),
                else_=1,
            ),
            VaSmartvaResults.va_smartva_addedat.desc(),
        )
    ).all()
    if not historical_rows:
        return False

    keeper = historical_rows[0]
    for row in historical_rows[1:]:
        if row.va_smartva_status == VaStatuses.active:
            row.va_smartva_status = VaStatuses.deactive

    keeper.va_smartva_status = VaStatuses.active
    keeper.payload_version_id = to_payload_version_id
    if keeper.smartva_run_id is not None:
        run = db.session.get(VaSmartvaRun, keeper.smartva_run_id)
        if run is not None:
            run.payload_version_id = to_payload_version_id

    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_entityid=keeper.va_smartva_id,
            va_audit_byrole="vaadmin",
            va_audit_operation="u",
            va_audit_action="va_smartva_reactivated_for_current_payload",
        )
    )
    return True


def repair_protected_current_payload_smartva(
    *,
    form_id: str | None = None,
    va_sids: set[str] | None = None,
) -> int:
    """Repair protected submissions by rebinding historical SmartVA to current payloads."""
    current_projection_exists = sa.exists(
        sa.select(1)
        .select_from(VaSmartvaResults)
        .where(
            VaSmartvaResults.va_sid == VaSubmissions.va_sid,
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
            VaSmartvaResults.payload_version_id == VaSubmissions.active_payload_version_id,
        )
    )
    any_history_exists = sa.exists(
        sa.select(1)
        .select_from(VaSmartvaResults)
        .where(VaSmartvaResults.va_sid == VaSubmissions.va_sid)
    )

    conditions = [
        VaSubmissions.active_payload_version_id.is_not(None),
        VaSubmissionWorkflow.workflow_state.in_(_protected_states()),
        ~current_projection_exists,
        any_history_exists,
    ]
    if form_id is not None:
        conditions.append(VaSubmissions.va_form_id == form_id)
    if va_sids:
        conditions.append(VaSubmissions.va_sid.in_(va_sids))

    rows = db.session.execute(
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.active_payload_version_id,
        )
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*conditions))
    ).all()

    repaired = 0
    for va_sid, payload_version_id in rows:
        if _reactivate_latest_historical_smartva_to_payload(
            va_sid,
            to_payload_version_id=payload_version_id,
        ):
            repaired += 1
    return repaired


def _save_smartva_failure(
    va_sid: str,
    *,
    form_run_id,
    payload_version_id,
    trigger_source: str,
    failure_stage: str,
    failure_detail: str,
    existing=None,
    audit_action: str = "va_smartva_failure_recorded",
) -> uuid.UUID:
    _deactivate_active_smartva_results(
        va_sid,
        existing if isinstance(existing, list) else ([existing] if existing else []),
    )

    smartva_run = _create_smartva_run(
        va_sid,
        form_run_id=form_run_id,
        payload_version_id=payload_version_id,
        trigger_source=trigger_source,
        outcome=VaSmartvaRun.OUTCOME_FAILED,
        failure_stage=failure_stage,
        failure_detail=failure_detail,
    )
    result_id = uuid.uuid4()
    db.session.add(
        VaSmartvaResults(
            va_smartva_id=result_id,
            va_sid=va_sid,
            payload_version_id=payload_version_id,
            smartva_run_id=smartva_run.va_smartva_run_id,
            va_smartva_outcome=VaSmartvaResults.OUTCOME_FAILED,
            va_smartva_failure_stage=failure_stage[:32],
            va_smartva_failure_detail=failure_detail[:4000],
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


def _record_smartva_failures(
    va_sids: set[str],
    *,
    form_run_id,
    trigger_source: str,
    failure_stage: str,
    failure_detail: str,
    failure_details_by_sid: dict[str, str] | None = None,
) -> int:
    active_payload_by_sid = _active_payload_versions_by_sid(va_sids)
    existing_active = _active_smartva_results_for_sids(active_payload_by_sid)
    recorded = 0
    for va_sid in sorted(va_sids):
        payload_version_id = active_payload_by_sid.get(va_sid)
        _save_smartva_failure(
            va_sid,
            form_run_id=form_run_id,
            payload_version_id=payload_version_id,
            trigger_source=trigger_source,
            failure_stage=failure_stage,
            failure_detail=(
                (failure_details_by_sid or {}).get(va_sid, failure_detail)
            ),
            existing=existing_active.get(va_sid),
        )
        _transition_to_ready_after_smartva_failure_if_pending(va_sid)
        recorded += 1
    return recorded


def _active_payload_versions_by_sid(va_sids: set[str]) -> dict[str, uuid.UUID | None]:
    if not va_sids:
        return {}
    rows = db.session.execute(
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.active_payload_version_id,
        ).where(VaSubmissions.va_sid.in_(va_sids))
    ).all()
    return {va_sid: payload_version_id for va_sid, payload_version_id in rows}


def _form_run_outcome(success_count: int, failure_count: int) -> str:
    if success_count > 0 and failure_count > 0:
        return VaSmartvaFormRun.OUTCOME_PARTIAL
    if success_count > 0:
        return VaSmartvaFormRun.OUTCOME_SUCCESS
    return VaSmartvaFormRun.OUTCOME_FAILED


SMARTVA_BATCH_SIZE = 50  # max submissions per SmartVA binary invocation


def _generate_batch(
    va_form,
    batch_sids: set[str],
    *,
    trigger_source: str = "form_batch",
    log_progress=None,
) -> int:
    """Run one SmartVA binary invocation for a bounded set of submissions.

    Creates its own workspace, form run, and nested transaction.
    Returns the total number of result rows (successes + failures) saved.
    """
    from app.utils import (
        va_smartva_formatsmartvaresult,
        va_smartva_prepdata,
        va_smartva_runsmartva,
    )

    if not batch_sids:
        return 0

    active_payload_by_sid = _active_payload_versions_by_sid(batch_sids)

    with tempfile.TemporaryDirectory() as workspace_dir:
        form_run = _create_smartva_form_run(
            va_form,
            pending_sid_count=len(batch_sids),
            trigger_source=trigger_source,
        )
        processing_tx = db.session.begin_nested()
        try:
            prep_result = va_smartva_prepdata(
                va_form, workspace_dir, pending_sids=batch_sids
            )
            run_options = prep_result.get("run_options", {})
            va_smartva_runsmartva(
                va_form,
                workspace_dir,
                run_options=run_options,
            )
            raw_outputs_by_sid = _read_raw_likelihood_outputs(
                workspace_dir, batch_sids
            )
            rejected_by_sid = _read_rejected_sids_from_report(
                workspace_dir, batch_sids
            )
            output_file = va_smartva_formatsmartvaresult(va_form, workspace_dir)
            new_results = _read_formatted_results(output_file)

            rejected_failure_count = 0
            if rejected_by_sid:
                rejected_failure_count = _record_smartva_failures(
                    set(rejected_by_sid),
                    form_run_id=form_run.form_run_id,
                    trigger_source=trigger_source,
                    failure_stage="smartva_rejected",
                    failure_detail=(
                        "SmartVA rejected this submission for quality reasons."
                    ),
                    failure_details_by_sid=rejected_by_sid,
                )
            eligible_pending = batch_sids - set(rejected_by_sid)

            if new_results is None:
                remaining_failure_count = 0
                if eligible_pending:
                    remaining_failure_count = _record_smartva_failures(
                        eligible_pending,
                        form_run_id=form_run.form_run_id,
                        trigger_source=trigger_source,
                        failure_stage="format_output",
                        failure_detail=(
                            "SmartVA produced no output file for the current payload."
                        ),
                    )
                _finalize_smartva_form_run(
                    form_run,
                    workspace_dir=workspace_dir,
                    outcome=VaSmartvaFormRun.OUTCOME_FAILED,
                )
                db.session.commit()
                return rejected_failure_count + remaining_failure_count

            current_existing = _active_smartva_results_for_sids(
                active_payload_by_sid
            )
            success_count = 0
            seen_sids: set[str] = set()
            for record in new_results.itertuples():
                va_sid = getattr(record, "sid", None)
                if va_sid is None or va_sid not in eligible_pending:
                    continue
                seen_sids.add(va_sid)
                existing = current_existing.get(va_sid, [])
                payload_version_id = active_payload_by_sid.get(va_sid)
                # Skip only if there is already a *successful* result for this
                # payload version — a failed result must not block a new
                # successful re-run (e.g. after fixing missing data files).
                has_successful_payload_result = any(
                    row.payload_version_id == payload_version_id
                    and row.va_smartva_outcome == VaSmartvaResults.OUTCOME_SUCCESS
                    for row in existing
                )
                if has_successful_payload_result:
                    continue

                _save_smartva_result(
                    va_sid,
                    record,
                    form_run_id=form_run.form_run_id,
                    payload_version_id=payload_version_id,
                    trigger_source=trigger_source,
                    raw_outputs=raw_outputs_by_sid.get(va_sid),
                    existing=existing,
                )
                _transition_to_ready_after_smartva_if_pending(va_sid)
                success_count += 1

            missing_sids = eligible_pending - seen_sids
            failure_count = rejected_failure_count
            if missing_sids:
                failure_count += _record_smartva_failures(
                    missing_sids,
                    form_run_id=form_run.form_run_id,
                    trigger_source=trigger_source,
                    failure_stage="missing_row",
                    failure_detail=(
                        "SmartVA completed but returned no row for this submission."
                    ),
                )

            _finalize_smartva_form_run(
                form_run,
                workspace_dir=workspace_dir,
                outcome=_form_run_outcome(success_count, failure_count),
            )
            processing_tx.commit()
            db.session.commit()
            total_saved = success_count + failure_count
            log.info(
                "SmartVA [%s]: batch committed %d result row(s).",
                va_form.form_id,
                total_saved,
            )
            return total_saved
        except Exception as exc:
            try:
                processing_tx.rollback()
            except Exception:
                db.session.rollback()
                log.warning(
                    "SmartVA [%s]: savepoint rollback failed (stale DB "
                    "connection), falling back to full session rollback.",
                    va_form.form_id,
                )
            try:
                failure_count = _record_smartva_failures(
                    batch_sids,
                    form_run_id=form_run.form_run_id,
                    trigger_source=trigger_source,
                    failure_stage="execution",
                    failure_detail=str(exc),
                )
                _finalize_smartva_form_run(
                    form_run,
                    workspace_dir=workspace_dir,
                    outcome=VaSmartvaFormRun.OUTCOME_FAILED,
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                failure_count = 0
                log.error(
                    "SmartVA [%s]: failed to record failures after exception.",
                    va_form.form_id,
                    exc_info=True,
                )
            log.error(
                "SmartVA [%s]: batch failed — recorded %d failure row(s): %s",
                va_form.form_id,
                failure_count,
                exc,
                exc_info=True,
            )
            if log_progress:
                log_progress(
                    f"SmartVA {va_form.form_id}: {failure_count} failure record(s) saved."
                )
            return failure_count


def generate_for_form(
    va_form,
    *,
    amended_sids: set[str] | None = None,
    target_sids: set[str] | None = None,
    force: bool = False,
    trigger_source: str = "form_batch",
    log_progress=None,
) -> int:
    from app.models import VaSubmissionWorkflow

    amended_sids = amended_sids or set()
    target_sids = target_sids or set()
    requested_sids = amended_sids | target_sids

    preserved_count = repair_protected_current_payload_smartva(
        form_id=va_form.form_id,
        va_sids=requested_sids or None,
    )
    if preserved_count:
        log.info(
            "SmartVA [%s]: rebound %d protected projection(s).",
            va_form.form_id,
            preserved_count,
        )
        if log_progress:
            log_progress(
                f"SmartVA {va_form.form_id}: rebound {preserved_count} preserved result(s)."
            )

    pending = pending_smartva_sids(va_form.form_id)
    if target_sids:
        pending &= target_sids

    if requested_sids:
        form_requested = set(
            db.session.scalars(
                sa.select(VaSubmissions.va_sid).where(
                    VaSubmissions.va_form_id == va_form.form_id,
                    VaSubmissions.va_sid.in_(requested_sids),
                )
            ).all()
        )
        if form_requested and not force:
            protected_requested = set(
                db.session.scalars(
                    sa.select(VaSubmissionWorkflow.va_sid).where(
                        VaSubmissionWorkflow.va_sid.in_(form_requested),
                        VaSubmissionWorkflow.workflow_state.in_(_protected_states()),
                    )
                ).all()
            )
            form_requested -= protected_requested
        pending |= form_requested

    if not pending:
        log.info("SmartVA [%s]: all results up to date, skipping.", va_form.form_id)
        if log_progress:
            log_progress(
                f"SmartVA {va_form.form_id}: all results up to date, skipping."
            )
        if preserved_count:
            db.session.commit()
        return preserved_count

    pending_list = sorted(pending)
    batches = [
        pending_list[i : i + SMARTVA_BATCH_SIZE]
        for i in range(0, len(pending_list), SMARTVA_BATCH_SIZE)
    ]

    log.info(
        "SmartVA [%s]: %d pending in %d batch(es) of ≤%d.",
        va_form.form_id,
        len(pending),
        len(batches),
        SMARTVA_BATCH_SIZE,
    )
    if log_progress:
        log_progress(
            f"SmartVA {va_form.form_id}: {len(pending)} pending → "
            f"{len(batches)} batch(es)."
        )

    total = preserved_count
    for batch_index, batch_sids_list in enumerate(batches, 1):
        batch_sids = set(batch_sids_list)
        if log_progress:
            log_progress(
                f"SmartVA {va_form.form_id}: batch {batch_index}/{len(batches)} "
                f"({len(batch_sids)} submission(s))…"
            )
        try:
            saved = _generate_batch(
                va_form,
                batch_sids,
                trigger_source=trigger_source,
                log_progress=log_progress,
            )
            total += saved
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            db.session.remove()
            log.error(
                "SmartVA [%s] batch %d/%d failed: %s",
                va_form.form_id,
                batch_index,
                len(batches),
                exc,
                exc_info=True,
            )
            if log_progress:
                log_progress(
                    f"SmartVA {va_form.form_id}: batch {batch_index} FAILED — {exc}"
                )

    return total


def generate_for_submission(
    va_sid: str,
    *,
    force: bool = False,
    trigger_source: str = "single_submission",
    log_progress=None,
) -> int:
    from app.models import VaForms, VaSubmissionWorkflow

    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        log.warning(
            "SmartVA generate_for_submission: submission %s not found.",
            va_sid,
        )
        return 0

    current_state = db.session.scalar(
        sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == va_sid
        )
    )
    if current_state in _protected_states() and not force:
        log.info("SmartVA [%s]: skipped — protected state %s.", va_sid, current_state)
        if log_progress:
            log_progress(
                f"[{va_sid}] SmartVA skipped — protected state: {current_state}"
            )
        return 0

    va_form = db.session.get(VaForms, submission.va_form_id)
    if va_form is None:
        log.warning(
            "SmartVA generate_for_submission: form %s not found.",
            submission.va_form_id,
        )
        return 0

    saved = _generate_batch(
        va_form,
        {va_sid},
        trigger_source=trigger_source,
        log_progress=log_progress,
    )
    log.info(
        "SmartVA [%s]: single-submission committed %d result row(s).",
        va_sid,
        saved,
    )
    return saved


def generate_all_pending(*, log_progress=None) -> dict:
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
            db.session.remove()
            log.error(
                "SmartVA-only [%s] failed: %s",
                va_form.form_id,
                exc,
                exc_info=True,
            )
            if log_progress:
                log_progress(f"SmartVA {va_form.form_id}: FAILED — {exc}")

    if log_progress:
        log_progress(f"SmartVA-only run finished. Updated: {total}")
    return {"smartva_updated": total}
