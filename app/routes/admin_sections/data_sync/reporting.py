import os

from flask import current_app, jsonify
from flask_login import current_user
import sqlalchemy as sa

from app import db, limiter
from app.decorators import role_required
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.routes.admin_sections import data_sync as sync_routes
from app.services.forms.runtime_registry import sync_runtime_forms_from_site_mappings


@admin.get("/api/sync/coverage")
@role_required("admin")
def admin_sync_coverage():
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.models.va_submissions import VaSubmissions
        from app.services.odk.submission_count import va_odk_submissioncount

        forms = sync_runtime_forms_from_site_mappings()
        mappings = {
            (mapping.project_id, mapping.site_id): mapping
            for mapping in sync_routes.get_all_project_site_mappings()
        }

        local_data = {}
        for form in forms:
            local_count = (
                db.session.scalar(
                    sa.select(sa.func.count()).where(VaSubmissions.va_form_id == form.form_id)
                )
                or 0
            )
            local_data[(form.project_id, form.site_id)] = {
                "form": form,
                "local_count": local_count,
            }

        flask_app = current_app._get_current_object()

        def fetch_odk_count(form):
            with flask_app.app_context():
                mapping = mappings.get((form.project_id, form.site_id))
                if mapping is None:
                    return form, None, "Active runtime form is missing a site mapping."
                try:
                    count = va_odk_submissioncount(
                        mapping.odk_project_id,
                        mapping.odk_form_id,
                        app_project_id=form.project_id,
                    )
                    return form, count, None
                except Exception:
                    return form, None, "ODK count failed."

        odk_results = {}
        with ThreadPoolExecutor(max_workers=len(forms) or 1) as ex:
            futures = {ex.submit(fetch_odk_count, form): form for form in forms}
            for future in as_completed(futures):
                form, odk_count, odk_error = future.result()
                odk_results[(form.project_id, form.site_id)] = (odk_count, odk_error)

        rows = []
        odk_total = 0
        local_total = 0
        for form in forms:
            key = (form.project_id, form.site_id)
            odk_count, odk_error = odk_results.get(key, (None, "No result"))
            local_count = local_data[key]["local_count"]
            mapping = mappings.get(key)
            if mapping is None:
                continue
            rows.append(
                {
                    "project_id": form.project_id,
                    "site_id": form.site_id,
                    "odk_project_id": mapping.odk_project_id,
                    "odk_form_id": mapping.odk_form_id,
                    "form_id": form.form_id,
                    "can_site_sync": True,
                    "odk_total": odk_count,
                    "local_total": local_count,
                    "missing": (odk_count - local_count) if odk_count is not None else None,
                    "error": odk_error,
                    "last_synced_at": (
                        mapping.last_synced_at.isoformat() if mapping.last_synced_at else None
                    ),
                }
            )
            if odk_count is not None:
                odk_total += odk_count
            local_total += local_count

        return jsonify(
            {"mappings": rows, "totals": {"odk_total": odk_total, "local_total": local_total}}
        )
    except Exception:
        return _json_error("Failed to load coverage data", 500)


@admin.get("/api/sync/backfill-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_backfill_stats():
    try:
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites
        from app.models.va_smartva_results import VaSmartvaResults
        from app.models.va_submission_attachments import VaSubmissionAttachments
        from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
        from app.models.va_submissions import VaSubmissions

        forms = sync_runtime_forms_from_site_mappings()
        if not forms:
            return jsonify(
                {
                    "projects": [],
                    "totals": {
                        "local_total": 0,
                        "metadata_complete": 0,
                        "attachments_complete": 0,
                        "smartva_complete": 0,
                        "smartva_failed": 0,
                        "smartva_missing": 0,
                        "smartva_no_consent": 0,
                    },
                }
            )

        app_data_root = current_app.config.get("APP_DATA")

        def resolve_attachment_file_path(
            form_id: str,
            local_path: str | None,
            storage_name: str | None,
            *,
            include_audit: bool = False,
        ) -> str | None:
            if storage_name and app_data_root:
                disk_path = os.path.join(app_data_root, form_id, "media", storage_name)
                if sync_routes.os.path.exists(disk_path):
                    return disk_path
            if local_path:
                if os.path.isabs(local_path):
                    if sync_routes.os.path.exists(local_path):
                        return local_path
                elif app_data_root:
                    disk_path = os.path.join(app_data_root, local_path)
                    if sync_routes.os.path.exists(disk_path):
                        return disk_path
            if include_audit and app_data_root and storage_name:
                audit_disk_path = os.path.join(app_data_root, form_id, "media", storage_name)
                if sync_routes.os.path.exists(audit_disk_path):
                    return audit_disk_path
            return None

        attachment_expected_counts = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_sid,
                    sa.func.count(VaSubmissionAttachments.va_sid).label("attachment_count"),
                )
                .select_from(VaSubmissions)
                .join(
                    VaSubmissionAttachments,
                    VaSubmissionAttachments.va_sid == VaSubmissions.va_sid,
                    isouter=True,
                )
                .where(VaSubmissionAttachments.exists_on_odk.is_(True))
                .group_by(VaSubmissions.va_sid)
            ).all()
        )

        local_counts = {}
        submission_rows = db.session.execute(
            sa.select(
                VaSubmissions.va_form_id,
                VaSubmissions.va_sid,
                VaSubmissions.va_consent,
                VaSubmissionPayloadVersion.has_required_metadata,
                VaSubmissionPayloadVersion.attachments_expected,
                VaSmartvaResults.va_smartva_outcome,
                VaSmartvaResults.va_smartva_status,
            )
            .select_from(VaSubmissions)
            .join(
                VaSubmissionPayloadVersion,
                VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
                isouter=True,
            )
            .join(
                VaSmartvaResults,
                sa.and_(
                    VaSmartvaResults.va_sid == VaSubmissions.va_sid,
                    VaSmartvaResults.va_smartva_status.is_not(None),
                ),
                isouter=True,
            )
        ).all()
        for row in submission_rows:
            counts = local_counts.setdefault(
                row.va_form_id,
                {
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "smartva_complete": 0,
                    "smartva_failed": 0,
                    "smartva_eligible": 0,
                    "smartva_no_consent": 0,
                },
            )
            counts["local_total"] += 1
            if row.has_required_metadata:
                counts["metadata_complete"] += 1
            attachments_expected = row.attachments_expected or 0
            if attachments_expected <= int(attachment_expected_counts.get(row.va_sid) or 0):
                counts["attachments_complete"] += 1
            if (row.va_consent or "").strip().lower() == "yes":
                counts["smartva_eligible"] += 1
            else:
                counts["smartva_no_consent"] += 1
            if row.va_smartva_outcome == VaSmartvaResults.OUTCOME_SUCCESS:
                counts["smartva_complete"] += 1
            elif row.va_smartva_outcome == VaSmartvaResults.OUTCOME_FAILED:
                counts["smartva_failed"] += 1

        attachment_rows = db.session.execute(
            sa.select(
                VaSubmissions.va_form_id,
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.local_path,
                VaSubmissionAttachments.storage_name,
            )
            .select_from(VaSubmissionAttachments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        ).all()
        non_audit_expected = {}
        non_audit_present = {}
        audit_expected = {}
        audit_present = {}
        legacy_rows_total = {}
        for row in attachment_rows:
            is_audit = row.filename == "audit.csv"
            file_path = resolve_attachment_file_path(
                row.va_form_id,
                row.local_path,
                row.storage_name,
                include_audit=is_audit,
            )
            if is_audit:
                if row.storage_name is None:
                    legacy_rows_total[row.va_form_id] = legacy_rows_total.get(row.va_form_id, 0) + 1
                    continue
                audit_expected[row.va_form_id] = audit_expected.get(row.va_form_id, 0) + 1
                if file_path:
                    audit_present[row.va_form_id] = audit_present.get(row.va_form_id, 0) + 1
                continue
            non_audit_expected[row.va_form_id] = non_audit_expected.get(row.va_form_id, 0) + 1
            if file_path:
                non_audit_present[row.va_form_id] = non_audit_present.get(row.va_form_id, 0) + 1
            if row.storage_name is None:
                legacy_rows_total[row.va_form_id] = legacy_rows_total.get(row.va_form_id, 0) + 1

        projects_map = {}
        totals = {
            "local_total": 0,
            "metadata_complete": 0,
            "attachments_complete": 0,
            "non_audit_attachments_expected": 0,
            "non_audit_attachments_present": 0,
            "audit_attachments_expected": 0,
            "audit_attachments_present": 0,
            "legacy_attachment_rows_total": 0,
            "smartva_complete": 0,
            "smartva_failed": 0,
            "smartva_missing": 0,
            "smartva_no_consent": 0,
        }
        for form in forms:
            counts = local_counts.get(form.form_id, {})
            local_total = int(counts.get("local_total") or 0)
            metadata_complete = int(counts.get("metadata_complete") or 0)
            attachments_complete = int(counts.get("attachments_complete") or 0)
            non_audit_attachments_expected = int(non_audit_expected.get(form.form_id) or 0)
            non_audit_attachments_present = int(non_audit_present.get(form.form_id) or 0)
            audit_attachments_expected = int(audit_expected.get(form.form_id) or 0)
            audit_attachments_present = int(audit_present.get(form.form_id) or 0)
            legacy_attachment_rows_total = int(legacy_rows_total.get(form.form_id) or 0)
            smartva_complete = int(counts.get("smartva_complete") or 0)
            smartva_failed = int(counts.get("smartva_failed") or 0)
            smartva_eligible = int(counts.get("smartva_eligible") or 0)
            smartva_no_consent = int(counts.get("smartva_no_consent") or 0)
            smartva_missing = max(smartva_eligible - smartva_complete - smartva_failed, 0)

            for key, value in (
                ("local_total", local_total),
                ("metadata_complete", metadata_complete),
                ("attachments_complete", attachments_complete),
                ("non_audit_attachments_expected", non_audit_attachments_expected),
                ("non_audit_attachments_present", non_audit_attachments_present),
                ("audit_attachments_expected", audit_attachments_expected),
                ("audit_attachments_present", audit_attachments_present),
                ("legacy_attachment_rows_total", legacy_attachment_rows_total),
                ("smartva_complete", smartva_complete),
                ("smartva_failed", smartva_failed),
                ("smartva_missing", smartva_missing),
                ("smartva_no_consent", smartva_no_consent),
            ):
                totals[key] += value

            project = projects_map.setdefault(
                form.project_id,
                {
                    "project_id": form.project_id,
                    "project_name": None,
                    "sites": {},
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "non_audit_attachments_expected": 0,
                    "non_audit_attachments_present": 0,
                    "audit_attachments_expected": 0,
                    "audit_attachments_present": 0,
                    "legacy_attachment_rows_total": 0,
                    "smartva_complete": 0,
                    "smartva_failed": 0,
                    "smartva_missing": 0,
                    "smartva_no_consent": 0,
                },
            )
            for key, value in (
                ("local_total", local_total),
                ("metadata_complete", metadata_complete),
                ("attachments_complete", attachments_complete),
                ("non_audit_attachments_expected", non_audit_attachments_expected),
                ("non_audit_attachments_present", non_audit_attachments_present),
                ("audit_attachments_expected", audit_attachments_expected),
                ("audit_attachments_present", audit_attachments_present),
                ("legacy_attachment_rows_total", legacy_attachment_rows_total),
                ("smartva_complete", smartva_complete),
                ("smartva_failed", smartva_failed),
                ("smartva_missing", smartva_missing),
                ("smartva_no_consent", smartva_no_consent),
            ):
                project[key] += value
            site = project["sites"].setdefault(
                form.site_id,
                {
                    "site_id": form.site_id,
                    "site_name": None,
                    "forms": [],
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "non_audit_attachments_expected": 0,
                    "non_audit_attachments_present": 0,
                    "audit_attachments_expected": 0,
                    "audit_attachments_present": 0,
                    "legacy_attachment_rows_total": 0,
                    "smartva_complete": 0,
                    "smartva_failed": 0,
                    "smartva_missing": 0,
                    "smartva_no_consent": 0,
                },
            )
            for key, value in (
                ("local_total", local_total),
                ("metadata_complete", metadata_complete),
                ("attachments_complete", attachments_complete),
                ("non_audit_attachments_expected", non_audit_attachments_expected),
                ("non_audit_attachments_present", non_audit_attachments_present),
                ("audit_attachments_expected", audit_attachments_expected),
                ("audit_attachments_present", audit_attachments_present),
                ("legacy_attachment_rows_total", legacy_attachment_rows_total),
                ("smartva_complete", smartva_complete),
                ("smartva_failed", smartva_failed),
                ("smartva_missing", smartva_missing),
                ("smartva_no_consent", smartva_no_consent),
            ):
                site[key] += value
            site["forms"].append(
                {
                    "form_id": form.form_id,
                    "local_total": local_total,
                    "metadata_complete": metadata_complete,
                    "metadata_missing": max(local_total - metadata_complete, 0),
                    "attachments_complete": attachments_complete,
                    "attachments_missing": max(local_total - attachments_complete, 0),
                    "non_audit_attachments_expected": non_audit_attachments_expected,
                    "non_audit_attachments_present": non_audit_attachments_present,
                    "non_audit_attachments_missing": max(non_audit_attachments_expected - non_audit_attachments_present, 0),
                    "audit_attachments_expected": audit_attachments_expected,
                    "audit_attachments_present": audit_attachments_present,
                    "audit_attachments_missing": max(audit_attachments_expected - audit_attachments_present, 0),
                    "legacy_attachment_rows_total": legacy_attachment_rows_total,
                    "smartva_complete": smartva_complete,
                    "smartva_failed": smartva_failed,
                    "smartva_missing": smartva_missing,
                    "smartva_no_consent": smartva_no_consent,
                }
            )

        project_names = {
            r.project_id: r.project_name for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, project in projects_map.items():
            project["project_name"] = project_names.get(pid, pid)
            for sid, site in project["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
                site["forms"] = sorted(site["forms"], key=lambda item: item["form_id"])
            project["sites"] = sorted(project["sites"].values(), key=lambda item: item["site_id"])

        totals["non_audit_attachments_missing"] = max(
            totals["non_audit_attachments_expected"] - totals["non_audit_attachments_present"],
            0,
        )
        totals["audit_attachments_missing"] = max(
            totals["audit_attachments_expected"] - totals["audit_attachments_present"],
            0,
        )
        return jsonify(
            {"projects": sorted(projects_map.values(), key=lambda item: item["project_id"]), "totals": totals}
        )
    except Exception:
        return _json_error("Failed to load backfill stats", 500)


@admin.get("/api/sync/legacy-attachment-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_legacy_attachment_stats():
    try:
        from app.models.va_submission_attachments import VaSubmissionAttachments
        from app.services.attachments.storage_name import legacy_attachment_storage_name

        counts = db.session.execute(
            sa.select(
                sa.func.count().label("total_null_rows"),
                sa.func.count().filter(VaSubmissionAttachments.exists_on_odk.is_(True)).label("exists_on_odk_null_rows"),
                sa.func.count().filter(VaSubmissionAttachments.filename == "audit.csv").label("audit_csv_null_rows"),
                sa.func.count().filter(VaSubmissionAttachments.filename != "audit.csv").label("legacy_media_null_rows"),
                sa.func.count().filter(
                    sa.and_(
                        VaSubmissionAttachments.filename != "audit.csv",
                        VaSubmissionAttachments.exists_on_odk.is_(True),
                    )
                ).label("legacy_media_exists_on_odk_null_rows"),
            )
            .select_from(VaSubmissionAttachments)
            .where(VaSubmissionAttachments.storage_name.is_(None))
        ).mappings().one()

        repaired_legacy_media_rows = 0
        repaired_rows = db.session.execute(
            sa.select(
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.storage_name,
            )
            .where(VaSubmissionAttachments.storage_name.is_not(None))
            .where(VaSubmissionAttachments.filename != "audit.csv")
            .execution_options(yield_per=1000)
        )
        for row in repaired_rows:
            expected_storage_name = legacy_attachment_storage_name(row.va_sid, row.filename)
            if row.storage_name == expected_storage_name:
                repaired_legacy_media_rows += 1

        return jsonify(
            {
                "total_null_rows": int(counts["total_null_rows"] or 0),
                "exists_on_odk_null_rows": int(counts["exists_on_odk_null_rows"] or 0),
                "audit_csv_null_rows": int(counts["audit_csv_null_rows"] or 0),
                "legacy_media_null_rows": int(counts["legacy_media_null_rows"] or 0),
                "legacy_media_exists_on_odk_null_rows": int(counts["legacy_media_exists_on_odk_null_rows"] or 0),
                "repaired_legacy_media_rows": repaired_legacy_media_rows,
            }
        )
    except Exception:
        return _json_error("Failed to load legacy attachment stats", 500)


@admin.get("/api/sync/revoked-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_revoked_stats():
    try:
        from app.models.va_forms import VaForms
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites
        from app.models.va_submission_workflow import VaSubmissionWorkflow
        from app.models.va_submissions import VaSubmissions
        from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED

        revoked_by_form = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_form_id,
                    sa.func.count(VaSubmissions.va_sid).label("cnt"),
                )
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(VaSubmissionWorkflow.workflow_state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
                .group_by(VaSubmissions.va_form_id)
            ).all()
        )
        if not revoked_by_form:
            return jsonify({"projects": [], "totals": {"revoked": 0}})

        forms = db.session.scalars(
            sa.select(VaForms).where(VaForms.form_id.in_(revoked_by_form.keys()))
        ).all()
        projects_map = {}
        total_revoked = 0
        for form in forms:
            revoked_count = revoked_by_form.get(form.form_id, 0)
            if revoked_count == 0:
                continue
            total_revoked += revoked_count
            proj = projects_map.setdefault(
                form.project_id,
                {"project_id": form.project_id, "project_name": None, "sites": {}, "revoked": 0},
            )
            proj["revoked"] += revoked_count
            site = proj["sites"].setdefault(
                form.site_id,
                {"site_id": form.site_id, "site_name": None, "forms": {}, "revoked": 0},
            )
            site["revoked"] += revoked_count
            site["forms"][form.form_id] = {"form_id": form.form_id, "revoked": revoked_count}

        project_names = {
            r.project_id: r.project_name for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, proj in projects_map.items():
            proj["project_name"] = project_names.get(pid, pid)
            for sid, site in proj["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
            proj["sites"] = list(proj["sites"].values())
        return jsonify({"projects": list(projects_map.values()), "totals": {"revoked": total_revoked}})
    except Exception:
        return _json_error("Failed to load revoked stats", 500)
