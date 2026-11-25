"""Leaf helpers shared by the ODK sync tasks and the open-submission repair.

They lived in app.tasks.sync_tasks; services import them from here so they do
not depend on the task module. sync_tasks imports them back, so its own calls
and the tests that patch ``app.tasks.sync_tasks.<name>`` still resolve there.
"""
from celery.utils.log import get_task_logger

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
