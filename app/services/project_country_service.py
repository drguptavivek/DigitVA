"""Project country (ISO 3166-1 alpha-3, SmartVA's list).

Policy: docs/policy/va-form-project-configuration.md ("Project country").
"""
from app import db
from app.models import VaProjectMaster
from app.utils.va_smartva.va_smartva_06_smartvacountries import smartva_allowed_countries

_UNKNOWN = {"", "UNK", "UNKNOWN"}


def parse_project_country(value) -> tuple[str | None, str | None]:
    """``(code, error)``: null/blank/Unknown mean no country (``None``)."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, "project_country_iso3 must be a country code."
    code = value.strip().upper()
    if code in _UNKNOWN:
        return None, None
    if code not in smartva_allowed_countries:
        return None, "project_country_iso3 is not in the SmartVA country list."
    return code, None


def project_country(project_id: str) -> str | None:
    """The project's current country. A primary-key get, so a project the
    request already loaded costs no query. No autoflush: the caller is mid
    unit of work and a lookup must not split its flush."""
    with db.session.no_autoflush:
        project = db.session.get(VaProjectMaster, project_id)
    return project.project_country_iso3 if project else None
