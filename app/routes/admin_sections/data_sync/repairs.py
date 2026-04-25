from flask import jsonify
from flask_login import current_user
import sqlalchemy as sa

from app import db
from app.decorators import role_required
from app.models import MapProjectSiteOdk, VaSyncRun
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.routes.admin_sections.data_sync.helpers import _reconcile_orphaned_running_sync_rows


@admin.post("/api/sync/backfill/form/<form_id>")
@role_required("admin")
def admin_sync_backfill_form(form_id: str):
    try:
        from app.models.va_forms import VaForms
        from app.tasks.sync_tasks import run_single_form_backfill

        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            return _json_error(f"Form '{form_id}' not found.", 404)
        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(sa.select(VaSyncRun).where(VaSyncRun.status == "running").limit(1))
        if running:
            return _json_error("A sync is already in progress.", 409)
        task = run_single_form_backfill.delay(
            form_id=form_id,
            triggered_by="backfill",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": f"Repair started for form {form_id}.", "task_id": task.id, "form_id": form_id}), 202
    except Exception:
        return _json_error(f"Failed to trigger repair for form {form_id}", 500)


@admin.post("/api/sync/legacy-attachment-repair")
@role_required("admin")
def admin_sync_legacy_attachment_repair():
    try:
        from app.tasks.sync_tasks import run_legacy_attachment_repair

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(sa.select(VaSyncRun).where(VaSyncRun.status == "running").limit(1))
        if running:
            return _json_error("A sync is already in progress.", 409)
        task = run_legacy_attachment_repair.delay(
            triggered_by="legacy-repair",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": "Legacy attachment repair started.", "task_id": task.id}), 202
    except Exception:
        return _json_error("Failed to trigger legacy attachment repair", 500)


@admin.post("/api/sync/form/<form_id>")
@role_required("admin")
def admin_sync_form(form_id: str):
    try:
        from app.models.va_forms import VaForms
        from app.services.forms.runtime_registry import get_active_mapping_for_form
        from app.tasks.sync_tasks import run_single_form_sync

        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            return _json_error(f"Form '{form_id}' not found.", 404)
        if get_active_mapping_for_form(va_form) is None:
            return _json_error(f"Active runtime mapping not found for form '{form_id}'.", 404)
        _reconcile_orphaned_running_sync_rows()
        task = run_single_form_sync.delay(
            form_id=form_id,
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": f"Force-resync started for form {form_id}.", "task_id": task.id}), 202
    except Exception:
        return _json_error(f"Failed to trigger Force-resync for form {form_id}", 500)


@admin.post("/api/sync/project-site/<project_id>/<site_id>")
@role_required("admin")
def admin_sync_project_site(project_id: str, site_id: str):
    try:
        from app.services.forms.runtime_registry import ensure_runtime_form_for_mapping, sync_runtime_forms_from_site_mappings
        from app.tasks.sync_tasks import run_single_form_sync

        active_form = next(
            (
                form
                for form in sync_runtime_forms_from_site_mappings()
                if form.project_id == project_id and form.site_id == site_id
            ),
            None,
        )
        if active_form is None:
            return _json_error(
                f"Active runtime mapping not found for project/site '{project_id}/{site_id}'.",
                404,
            )
        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == project_id,
                MapProjectSiteOdk.site_id == site_id,
            )
        )
        if mapping is None:
            return _json_error(f"ODK mapping not found for project/site '{project_id}/{site_id}'.", 404)
        va_form = ensure_runtime_form_for_mapping(mapping)
        db.session.commit()
        task = run_single_form_sync.delay(
            form_id=va_form.form_id,
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return jsonify(
            {
                "message": f"Sync started for {project_id}/{site_id} using form {va_form.form_id}.",
                "task_id": task.id,
                "form_id": va_form.form_id,
            }
        ), 202
    except Exception:
        return _json_error(f"Failed to trigger sync for project/site {project_id}/{site_id}.", 500)
