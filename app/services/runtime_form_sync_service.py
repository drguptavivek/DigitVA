import re

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
)


_FORM_ID_SUFFIX_RE = re.compile(r"^(\d{2})$")


def sync_runtime_forms_from_site_mappings() -> list[VaForms]:
    """Materialize legacy ``va_forms`` rows from active site mappings.

    ``map_project_site_odk`` is the source of truth for which ODK forms should be
    synced. We still upsert compatibility ``va_forms`` rows because submissions,
    media paths, permissions, and several legacy workflow paths still key off the
    legacy form registry.
    """

    mappings = db.session.scalars(
        sa.select(MapProjectSiteOdk)
        .join(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == MapProjectSiteOdk.project_id,
                VaProjectSites.site_id == MapProjectSiteOdk.site_id,
            ),
        )
        .join(
            VaProjectMaster,
            VaProjectMaster.project_id == MapProjectSiteOdk.project_id,
        )
        .join(
            VaSiteMaster,
            VaSiteMaster.site_id == MapProjectSiteOdk.site_id,
        )
        .where(
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
        .order_by(MapProjectSiteOdk.project_id, MapProjectSiteOdk.site_id)
    ).all()

    if not mappings:
        return []

    existing_forms = db.session.scalars(
        sa.select(VaForms).order_by(
            VaForms.project_id,
            VaForms.site_id,
            VaForms.form_id,
        )
    ).all()
    forms_by_project_site = {
        (form.project_id, form.site_id): form
        for form in existing_forms
    }
    form_ids_in_use = {form.form_id for form in existing_forms}

    runtime_forms: list[VaForms] = []
    for mapping in mappings:
        _ensure_legacy_project_site_rows(mapping.project_id, mapping.site_id)

        existing = forms_by_project_site.get((mapping.project_id, mapping.site_id))
        if existing is None:
            existing = VaForms(
                form_id=_next_form_id(
                    mapping.project_id,
                    mapping.site_id,
                    form_ids_in_use,
                ),
                project_id=mapping.project_id,
                site_id=mapping.site_id,
                odk_form_id=mapping.odk_form_id,
                odk_project_id=str(mapping.odk_project_id),
                form_type=_form_type_name(mapping),
                form_type_id=mapping.form_type_id,
                form_status=VaStatuses.active,
            )
            db.session.add(existing)
            forms_by_project_site[(mapping.project_id, mapping.site_id)] = existing
            form_ids_in_use.add(existing.form_id)
        else:
            existing.odk_form_id = mapping.odk_form_id
            existing.odk_project_id = str(mapping.odk_project_id)
            existing.form_type = _form_type_name(mapping, existing.form_type)
            existing.form_type_id = mapping.form_type_id
            existing.form_status = VaStatuses.active

        runtime_forms.append(existing)

    db.session.flush()
    return runtime_forms


def _form_type_name(mapping: MapProjectSiteOdk, fallback: str | None = None) -> str:
    if mapping.form_type and mapping.form_type.form_type_name:
        return mapping.form_type.form_type_name
    if fallback:
        return fallback
    return "WHO VA 2022"


def _next_form_id(project_id: str, site_id: str, form_ids_in_use: set[str]) -> str:
    prefix = f"{project_id}{site_id}"
    used_numbers: set[int] = set()

    for form_id in form_ids_in_use:
        if not form_id.startswith(prefix):
            continue
        suffix = form_id[len(prefix):]
        match = _FORM_ID_SUFFIX_RE.match(suffix)
        if match:
            used_numbers.add(int(match.group(1)))

    for number in range(1, 100):
        if number in used_numbers:
            continue
        return f"{prefix}{number:02d}"

    raise ValueError(
        f"Could not allocate a runtime form_id for {project_id}/{site_id}"
    )


def _ensure_legacy_project_site_rows(project_id: str, site_id: str) -> None:
    project = db.session.get(VaResearchProjects, project_id)
    if project is None:
        project_master = db.session.get(VaProjectMaster, project_id)
        if project_master is None:
            raise ValueError(f"Project {project_id} is missing from va_project_master")
        db.session.add(
            VaResearchProjects(
                project_id=project_master.project_id,
                project_code=project_master.project_code,
                project_name=project_master.project_name,
                project_nickname=project_master.project_nickname,
                project_status=project_master.project_status,
            )
        )

    site = db.session.get(VaSites, site_id)
    if site is None:
        site_master = db.session.get(VaSiteMaster, site_id)
        if site_master is None:
            raise ValueError(f"Site {site_id} is missing from va_site_master")
        db.session.add(
            VaSites(
                site_id=site_master.site_id,
                project_id=project_id,
                site_name=site_master.site_name,
                site_abbr=site_master.site_abbr,
                site_status=site_master.site_status,
            )
        )
