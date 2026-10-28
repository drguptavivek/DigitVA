"""Authorized SmartVA settings for the native interview target picker."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaProjectMaster, VaStatuses
from app.services.org_grant_service import resolve_unit_va_presets

_PRESET_TO_OPTION = {"high": True, "low": False, "veryl": False}
_PRESET_FIELDS = (("hiv", "hiv_mortality"), ("malaria", "malaria_mortality"))
SmartVaTargetKey = tuple[str, str, str | None]


def _strict_form_flag(value: object) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError("SmartVA form flag is malformed")


def _form_options(form: VaForms, country: str, presets: dict) -> dict[str, object]:
    options: dict[str, object] = {"country": country}
    for option, field in _PRESET_FIELDS:
        preset = presets.get(field)
        if preset is None:
            options[option] = _strict_form_flag(getattr(form, f"form_smartva{option}"))
        else:
            try:
                options[option] = _PRESET_TO_OPTION[preset["value"]]
            except (KeyError, TypeError):
                raise ValueError("SmartVA area preset is malformed") from None
    options["hce"] = _strict_form_flag(form.form_smartvahce)
    options["freetext"] = _strict_form_flag(form.form_smartvafreetext)
    return options


def _form_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _options_digest(form_id: str, form_updated_at: str, options: dict[str, object]) -> str:
    canonical = json.dumps(
        {"schema_version": 1, "form_id": form_id, "form_updated_at": form_updated_at, "options": options},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode("ascii")).hexdigest()}"


def build_smartva_targets(targets: Iterable[SmartVaTargetKey]) -> dict[SmartVaTargetKey, dict]:
    """Resolve exact active web forms/options for already-authorized targets.

    Missing or duplicate active web forms, unsupported target identifiers, or
    malformed SmartVA settings omit only the affected target. All form rows and
    all unit presets are read in bounded batches.
    """
    keys: list[SmartVaTargetKey] = []
    unit_ids: set[uuid.UUID] = set()
    for project_id, site_id, unit_id in targets:
        if not project_id or not site_id:
            continue
        if unit_id is not None:
            try:
                unit_ids.add(uuid.UUID(unit_id))
            except (ValueError, TypeError, AttributeError):
                continue
        key = (project_id, site_id, unit_id)
        if key not in keys:
            keys.append(key)
    if not keys:
        return {}

    pairs = sorted({(project_id, site_id) for project_id, site_id, _ in keys})
    form_rows = db.session.scalars(
        sa.select(VaForms).where(
            sa.tuple_(VaForms.project_id, VaForms.site_id).in_(pairs),
            VaForms.form_source == "web",
            VaForms.form_status == VaStatuses.active,
        )
    ).all()
    forms_by_pair: dict[tuple[str, str], list[VaForms]] = defaultdict(list)
    for form in form_rows:
        forms_by_pair[(form.project_id, form.site_id)].append(form)

    unique_forms = [forms[0] for forms in forms_by_pair.values() if len(forms) == 1]
    if not unique_forms:
        return {}
    project_ids = {form.project_id for form in unique_forms}
    # smartva_country() calls project_country(), which uses db.session.get().
    # Load those project rows in one query so that helper stays query-free here.
    project_rows = {
        project.project_id: project
        for project in db.session.scalars(
            sa.select(VaProjectMaster).where(VaProjectMaster.project_id.in_(project_ids))
        ).all()
    }
    presets_by_unit = resolve_unit_va_presets(sorted(unit_ids)) if unit_ids else {}
    from app.utils.va_smartva.va_smartva_03_runsmartva import smartva_country

    projections: dict[SmartVaTargetKey, dict] = {}
    for key in keys:
        project_id, site_id, unit_id = key
        forms = forms_by_pair.get((project_id, site_id), [])
        if len(forms) != 1:
            continue
        form = forms[0]
        if project_id not in project_rows:
            continue
        country = smartva_country(form)
        if not isinstance(country, str) or not country or country != country.strip() or "\x00" in country:
            continue
        try:
            unit_uuid = uuid.UUID(unit_id) if unit_id is not None else None
            options = _form_options(form, country, presets_by_unit.get(unit_uuid, {}))
        except (KeyError, TypeError, ValueError):
            continue
        try:
            form_updated_at = _form_timestamp(form.form_updated_at)
        except (AttributeError, TypeError, ValueError):
            continue
        projections[key] = {
            "schema_version": 1,
            "site_id": site_id,
            "org_unit_id": unit_id,
            "form_id": form.form_id,
            "form_updated_at": form_updated_at,
            "options": options,
            "options_digest": _options_digest(form.form_id, form_updated_at, options),
        }
    return projections
