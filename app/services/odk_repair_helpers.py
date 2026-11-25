"""Leaf helpers shared by the ODK sync tasks and the open-submission repair.

They lived in app.tasks.sync_tasks; services import them from here so they do
not depend on the task module. sync_tasks imports them back, so its own calls
and the tests that patch ``app.tasks.sync_tasks.<name>`` still resolve there.
"""
import sqlalchemy as sa
from celery.utils.log import get_task_logger

from app.services.attachment_service import attachment_state_by_submission

# Same logger as before the move, when this code lived in app.tasks.sync_tasks.
log = get_task_logger("app.tasks.sync_tasks")


def _normalize_batch_plan(batch_map: dict | None) -> dict[str, dict]:
    """Normalize legacy and stage-aware batch payloads into one shape."""
    normalized: dict[str, dict] = {}
    for va_sid, value in (batch_map or {}).items():
        if isinstance(value, dict):
            normalized[va_sid] = {
                "instance_id": value.get("instance_id") or value.get("KEY") or "",
                "needs_metadata": bool(value.get("needs_metadata")),
                "needs_attachments": bool(value.get("needs_attachments")),
                "needs_smartva": bool(value.get("needs_smartva")),
                "payload_revalidated": bool(value.get("payload_revalidated")),
                "legacy_attachment_rows": int(value.get("legacy_attachment_rows") or 0),
            }
        else:
            normalized[va_sid] = {
                "instance_id": value or "",
                "needs_metadata": True,
                "needs_attachments": True,
                "needs_smartva": True,
                "payload_revalidated": False,
                "legacy_attachment_rows": 0,
            }
    return normalized


def _get_single_form_odk_client(va_form):
    """Return one pyODK client for the single-form sync run."""
    from app.services.runtime_form_sync_service import get_active_mapping_for_form
    from app.utils import va_odk_clientsetup

    mapping = get_active_mapping_for_form(va_form)
    if mapping is None:
        raise ValueError(
            f"Active runtime mapping not found for form '{va_form.form_id}'."
        )

    return va_odk_clientsetup(project_id=va_form.project_id)


def _release_read_transaction(*entities) -> None:
    """Detach loaded rows and end the current read transaction before remote I/O."""
    from app import db

    for entity in entities:
        if entity is None:
            continue
        try:
            db.session.expunge(entity)
        except Exception:
            log.debug("_release_read_transaction: expunge failed for %r", entity, exc_info=True)
            continue
    db.session.rollback()


def _legacy_attachment_rows_by_submission(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
) -> dict[str, int]:
    """Return counts of attachment rows that still lack opaque storage names."""
    from app import db
    from app.models import VaSubmissions, VaSubmissionAttachments

    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            sa.func.count().label("legacy_count"),
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == form_id,
            VaSubmissionAttachments.exists_on_odk.is_(True),
            VaSubmissionAttachments.storage_name.is_(None),
        )
        .group_by(VaSubmissionAttachments.va_sid)
    )
    if target_sids:
        stmt = stmt.where(VaSubmissionAttachments.va_sid.in_(target_sids))

    return {
        row["va_sid"]: int(row["legacy_count"] or 0)
        for row in db.session.execute(stmt).mappings().all()
    }


def _refresh_batch_plan_after_enrichment(
    *,
    form_id: str,
    batch_plan: dict[str, dict],
    raw_submissions: list[dict],
    upserted_map: dict[str, str],
) -> tuple[dict[str, dict], dict[str, int], int]:
    """Re-evaluate repair needs after metadata enrichment updates local state."""
    from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED
    from app.services.workflow.state_store import get_submission_workflow_state

    refreshed_plan = _normalize_batch_plan(batch_plan)
    repair_map, summary = _build_repair_map_for_form(
        form_id,
        _instance_ids_by_sid(raw_submissions),
        {},
    )
    upstream_changed_count = 0
    for va_sid, item in refreshed_plan.items():
        item["needs_metadata"] = False
        item["payload_revalidated"] = True
        if get_submission_workflow_state(va_sid) == WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
            item["needs_attachments"] = False
            item["needs_smartva"] = False
            upstream_changed_count += 1
            continue
        recalculated = repair_map.get(va_sid)
        if recalculated is None:
            item["needs_attachments"] = False
            item["needs_smartva"] = False
            continue
        item["instance_id"] = recalculated.get("instance_id") or item.get("instance_id") or ""
        item["needs_attachments"] = bool(recalculated.get("needs_attachments"))
        item["needs_smartva"] = bool(recalculated.get("needs_smartva"))
    return refreshed_plan, summary, upstream_changed_count


def _instance_ids_by_sid(records: list[dict] | None) -> dict[str, str]:
    """Return ``{sid: KEY}`` for the fetched records that carry both."""
    return {
        record.get("sid"): record.get("KEY")
        for record in records or []
        if record.get("sid") and record.get("KEY")
    }


def _build_repair_map_for_form(
    form_id: str,
    instance_ids_by_sid: dict[str, str],
    upserted_map: dict[str, str],
    *,
    target_sids: list[str] | None = None,
) -> tuple[dict[str, dict], dict[str, int]]:
    """Return submissions that still need post-upsert repair for a form.

    Includes newly added/updated rows plus existing rows whose current payload is
    metadata-incomplete or whose local attachment cache is incomplete.
    ``instance_ids_by_sid`` is the ``{sid: KEY}`` of the fetched records (see
    ``_instance_ids_by_sid``), not the records themselves; when non-empty it
    scopes the check to those sids, otherwise ``target_sids`` does.
    """
    from app import db
    from app.models import VaSubmissions, VaSmartvaResults
    from app.models.va_selectives import VaStatuses
    from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion

    # The payload keys the repair decision reads (metadata completeness, instance id).
    _REPAIR_PAYLOAD_KEYS = (
        "KEY",
        "FormVersion",
        "DeviceID",
        "SubmitterID",
        "instanceID",
        "AttachmentsExpected",
        "AttachmentsPresent",
    )

    instance_ids_by_sid = instance_ids_by_sid or {}

    smartva_current_sq = (
        sa.select(VaSmartvaResults.va_sid.label("va_sid"))
        .join(
            VaSubmissions,
            sa.and_(
                VaSubmissions.va_sid == VaSmartvaResults.va_sid,
                VaSubmissions.active_payload_version_id
                == VaSmartvaResults.payload_version_id,
            ),
        )
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .group_by(VaSmartvaResults.va_sid)
        .subquery()
    )

    if instance_ids_by_sid:
        scoped_target_sids = list(instance_ids_by_sid)
    else:
        scoped_target_sids = target_sids
    attachment_states = attachment_state_by_submission(
        form_id,
        target_sids=scoped_target_sids,
    )
    legacy_attachment_rows = _legacy_attachment_rows_by_submission(
        form_id,
        target_sids=scoped_target_sids,
    )

    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            # Only the keys read below, not the whole payload (~50 KB a row).
            *[
                VaSubmissionPayloadVersion.payload_data[key]
                for key in _REPAIR_PAYLOAD_KEYS
            ],
            VaSubmissions.va_summary,
            VaSubmissions.va_category_list,
            smartva_current_sq.c.va_sid.label("smartva_present_sid"),
        )
        .outerjoin(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .outerjoin(
            smartva_current_sq,
            smartva_current_sq.c.va_sid == VaSubmissions.va_sid,
        )
        .where(VaSubmissions.va_form_id == form_id)
    )
    if scoped_target_sids:
        stmt = stmt.where(VaSubmissions.va_sid.in_(scoped_target_sids))

    rows = db.session.execute(stmt).all()

    repair_map = {
        va_sid: {
            "instance_id": instance_id,
            "needs_metadata": True,
            "needs_attachments": True,
            "needs_smartva": True,
        }
        for va_sid, instance_id in (upserted_map or {}).items()
    }
    summary = {
        "metadata_missing": 0,
        "attachments_missing": 0,
        "smartva_missing": 0,
        "legacy_attachment_rows": 0,
    }
    for va_sid, *payload_values, va_summary, va_category_list, smartva_present_sid in rows:
        payload = dict(zip(_REPAIR_PAYLOAD_KEYS, payload_values))
        instance_id = (
            instance_ids_by_sid.get(va_sid)
            or payload.get("KEY")
            or (va_sid.rsplit(f"-{form_id.lower()}", 1)[0] if va_sid.endswith(f"-{form_id.lower()}") else None)
        )
        if not instance_id:
            continue
        metadata_complete = all(
            [
                va_summary is not None,
                va_category_list is not None,
                payload.get("FormVersion") is not None,
                payload.get("DeviceID") is not None,
                payload.get("SubmitterID") is not None,
                payload.get("instanceID") is not None,
                payload.get("AttachmentsExpected") is not None,
                payload.get("AttachmentsPresent") is not None,
            ]
        )
        try:
            attachments_expected = int(payload.get("AttachmentsExpected") or 0)
        except (TypeError, ValueError):
            attachments_expected = 0
        legacy_attachment_count = int(legacy_attachment_rows.get(va_sid) or 0)
        # Completeness is readiness, not a file count: a row counts only when
        # its blob is in DigitVA's store and, for audio, its MP3 derivative is
        # ready. A submission retired from ODK is complete by policy — its
        # source is gone and no repair may ever run
        # (docs/policy/odk-retired-submissions.md).
        attachment_state = attachment_states.get(va_sid)
        if attachment_state is not None and attachment_state.retired:
            attachments_complete = True
        else:
            # A file refused for size is accounted for, not missing; so is
            # audit.csv, which AttachmentsExpected counts but readiness skips.
            ready_attachment_count = (
                attachment_state.ready_count
                + attachment_state.refused_count
                + attachment_state.audit_count
                if attachment_state else 0
            )
            unready_attachments = (
                attachment_state.unready if attachment_state else ()
            )
            attachments_complete = (
                ready_attachment_count >= attachments_expected
                and not unready_attachments
                and legacy_attachment_count == 0
            )
        summary["legacy_attachment_rows"] += legacy_attachment_count
        smartva_complete = smartva_present_sid is not None
        if not metadata_complete:
            summary["metadata_missing"] += 1
        if not attachments_complete:
            summary["attachments_missing"] += 1
        if not smartva_complete:
            summary["smartva_missing"] += 1
        if not metadata_complete or not attachments_complete or not smartva_complete:
            existing = repair_map.get(
                va_sid,
                {
                    "instance_id": instance_id,
                    "needs_metadata": False,
                    "needs_attachments": False,
                    "needs_smartva": False,
                    "legacy_attachment_rows": 0,
                },
            )
            existing["instance_id"] = existing.get("instance_id") or instance_id
            existing["needs_metadata"] = bool(existing.get("needs_metadata")) or (not metadata_complete)
            existing["needs_attachments"] = bool(existing.get("needs_attachments")) or (not attachments_complete)
            existing["needs_smartva"] = bool(existing.get("needs_smartva")) or (not smartva_complete)
            existing["legacy_attachment_rows"] = max(
                int(existing.get("legacy_attachment_rows") or 0),
                legacy_attachment_count,
            )
            repair_map[va_sid] = existing

    return repair_map, summary
