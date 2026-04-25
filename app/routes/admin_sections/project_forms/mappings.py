"""Site-mapping CRUD routes for admin project-form mapping."""

import uuid as _uuid

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    MapProjectSiteOdk,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
)
from app.http.responses import json_error as _json_error
from app.routes.admin import admin

from .common import get_active_project_site


@admin.get("/api/projects/<project_id>/odk-site-mappings")
@role_required("admin")
def admin_odk_site_mappings_list(project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    project_id = project_id.upper()
    rows = db.session.scalars(
        sa.select(MapProjectSiteOdk)
        .join(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == MapProjectSiteOdk.project_id,
                VaProjectSites.site_id == MapProjectSiteOdk.site_id,
            ),
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == MapProjectSiteOdk.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == MapProjectSiteOdk.site_id)
        .where(
            MapProjectSiteOdk.project_id == project_id,
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    ).all()
    forms_by_site = {
        form.site_id: form
        for form in db.session.scalars(
            sa.select(VaForms).where(VaForms.project_id == project_id)
        ).all()
    }
    return jsonify(
        {
            "mappings": [
                {
                    "site_id": row.site_id,
                    "odk_project_id": row.odk_project_id,
                    "odk_form_id": row.odk_form_id,
                    "form_type_id": str(row.form_type_id) if row.form_type_id else None,
                    "form_type_code": row.form_type.form_type_code if row.form_type else None,
                    "form_id": forms_by_site.get(row.site_id).form_id if forms_by_site.get(row.site_id) else None,
                    "form_smartvahiv": forms_by_site.get(row.site_id).form_smartvahiv if forms_by_site.get(row.site_id) else "False",
                    "form_smartvamalaria": forms_by_site.get(row.site_id).form_smartvamalaria if forms_by_site.get(row.site_id) else "False",
                    "form_smartvahce": forms_by_site.get(row.site_id).form_smartvahce if forms_by_site.get(row.site_id) else "True",
                    "form_smartvafreetext": forms_by_site.get(row.site_id).form_smartvafreetext if forms_by_site.get(row.site_id) else "True",
                    "form_smartvacountry": forms_by_site.get(row.site_id).form_smartvacountry if forms_by_site.get(row.site_id) else "IND",
                }
                for row in rows
            ]
        }
    )


@admin.post("/api/projects/<project_id>/odk-site-mappings")
@role_required("admin")
def admin_odk_site_mappings_save(project_id):
    from app.models.va_field_mapping import MasFormTypes
    from app.services.forms.runtime_registry import ensure_runtime_form_for_mapping
    from app.validators.forms import (
        validate_boolean_string,
        validate_smartva_country,
    )

    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    project_id = project_id.upper()
    site_id = (data.get("site_id") or "").upper()
    odk_project_id = data.get("odk_project_id")
    odk_form_id = (data.get("odk_form_id") or "").strip()
    form_type_id_raw = (data.get("form_type_id") or "").strip()
    form_smartvahiv = (data.get("form_smartvahiv") or "False").strip()
    form_smartvamalaria = (data.get("form_smartvamalaria") or "False").strip()
    form_smartvahce = (data.get("form_smartvahce") or "True").strip()
    form_smartvafreetext = (data.get("form_smartvafreetext") or "True").strip()
    form_smartvacountry = (data.get("form_smartvacountry") or "IND").strip().upper()

    if not site_id or odk_project_id is None or not odk_form_id:
        return _json_error("site_id, odk_project_id, and odk_form_id are required.", 400)

    try:
        odk_project_id = int(odk_project_id)
    except (TypeError, ValueError):
        return _json_error("odk_project_id must be an integer.", 400)

    form_type_id = None
    if form_type_id_raw:
        try:
            parsed_uuid = _uuid.UUID(form_type_id_raw)
        except ValueError:
            return _json_error("form_type_id must be a valid UUID.", 400)
        form_type = db.session.get(MasFormTypes, parsed_uuid)
        if not form_type:
            return _json_error("form_type_id not found.", 404)
        form_type_id = parsed_uuid

    for value in (
        form_smartvahiv,
        form_smartvamalaria,
        form_smartvahce,
        form_smartvafreetext,
    ):
        if not validate_boolean_string(value):
            return _json_error("SmartVA boolean settings must be 'True' or 'False'.", 400)
    if not validate_smartva_country(form_smartvacountry):
        return _json_error("form_smartvacountry is invalid.", 400)

    project = db.session.get(VaProjectMaster, project_id)
    if not project or project.project_status != VaStatuses.active:
        return _json_error("Active project not found.", 404)

    site = db.session.get(VaSiteMaster, site_id)
    if not site or site.site_status != VaStatuses.active:
        return _json_error("Active site not found.", 404)

    project_site = get_active_project_site(project_id, site_id)
    if project_site is None:
        return _json_error("Active project-site mapping not found.", 404)

    existing = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if existing:
        existing.odk_project_id = odk_project_id
        existing.odk_form_id = odk_form_id
        existing.form_type_id = form_type_id
        status_code = 200
    else:
        existing = MapProjectSiteOdk(
            project_id=project_id,
            site_id=site_id,
            odk_project_id=odk_project_id,
            odk_form_id=odk_form_id,
            form_type_id=form_type_id,
        )
        db.session.add(existing)
        status_code = 201

    runtime_form = ensure_runtime_form_for_mapping(existing)
    runtime_form.form_smartvahiv = form_smartvahiv
    runtime_form.form_smartvamalaria = form_smartvamalaria
    runtime_form.form_smartvahce = form_smartvahce
    runtime_form.form_smartvafreetext = form_smartvafreetext
    runtime_form.form_smartvacountry = form_smartvacountry

    db.session.commit()
    db.session.refresh(existing)
    db.session.refresh(runtime_form)
    return jsonify(
        {
            "mapping": {
                "site_id": existing.site_id,
                "odk_project_id": existing.odk_project_id,
                "odk_form_id": existing.odk_form_id,
                "form_type_id": str(existing.form_type_id) if existing.form_type_id else None,
                "form_type_code": existing.form_type.form_type_code if existing.form_type else None,
                "form_id": runtime_form.form_id,
                "form_smartvahiv": runtime_form.form_smartvahiv,
                "form_smartvamalaria": runtime_form.form_smartvamalaria,
                "form_smartvahce": runtime_form.form_smartvahce,
                "form_smartvafreetext": runtime_form.form_smartvafreetext,
                "form_smartvacountry": runtime_form.form_smartvacountry,
            }
        }
    ), status_code


@admin.delete("/api/projects/<project_id>/odk-site-mappings/<site_id>")
@role_required("admin")
def admin_odk_site_mappings_delete(project_id, site_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    project_id = project_id.upper()
    site_id = site_id.upper()

    project = db.session.get(VaProjectMaster, project_id)
    if not project or project.project_status != VaStatuses.active:
        return _json_error("Active project not found.", 404)

    site = db.session.get(VaSiteMaster, site_id)
    if not site or site.site_status != VaStatuses.active:
        return _json_error("Active site not found.", 404)

    project_site = get_active_project_site(project_id, site_id)
    if project_site is None:
        return _json_error("Active project-site mapping not found.", 404)

    mapping = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if not mapping:
        return _json_error("Mapping not found.", 404)

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Mapping removed."})
