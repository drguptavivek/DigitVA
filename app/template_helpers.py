"""Jinja globals, filters and the context processor create_app registers
through ``register_template_helpers(app)`` (app/__init__.py)."""
from datetime import datetime

import pytz
from flask import url_for
from flask_login import current_user

from app import _current_user_timezone
from app.models.va_selectives import ROLE_LABELS
from app.services.cod_certificate_service import cert_date
from app.services.icd11_licence import DIGITVA_ADDITION_LABEL, ICD11_CITATION
from app.services.icd11_titles import icd11_alternatives_label, stored_cod_label
from app.services.icd_coding_value import (
    classification_of_value,
    get_icd_classification_for_submission,
)
from app.services.organization_service import district_reference_model
from app.services.site_maintenance_service import get_site_maintenance_banner_context
from app.services.smartva_icd11 import smartva_icd11_mapping
from app.services.smartva_service import smartva_panel
from app.utils.number_format import whole_number
from app.utils.smartva_gender import smartva_gender
from app.utils.who_va_bundle import who_va_bundle_version


def register_template_helpers(app):
    """Globals, then the context processor, then filters, in that order."""
    # The coding screens' ICD classification switch
    # (va_form_partials/_icd_classification_switch.html).
    app.add_template_global(get_icd_classification_for_submission, "icd_classification_for")
    app.add_template_global(classification_of_value, "icd_classification_of")
    app.add_template_global(smartva_icd11_mapping, "smartva_icd11_mapping")
    app.add_template_global(icd11_alternatives_label, "icd11_alternatives_label")
    app.add_template_global(stored_cod_label, "stored_cod_label")
    app.add_template_global(smartva_panel, "smartva_panel")
    app.add_template_global(who_va_bundle_version, "who_va_bundle_version")
    # The Organization panel's reference card, standalone or inside Project Setup.
    app.add_template_global(district_reference_model, "district_reference_model")
    # The admin Access grants panel's role labels, shared with the API.
    app.add_template_global(ROLE_LABELS, "role_labels")
    app.add_template_global(training_page_url, "training_page_url")

    app.context_processor(inject_template_globals)

    app.add_template_filter(whole_number)
    app.add_template_filter(smartva_gender)
    app.add_template_filter(cert_date)
    app.add_template_filter(user_timezone_filter, "user_timezone")


def training_page_url():
    """Where "my training checklist" opens: the Expo page while its export is present, else the Flask fallback."""
    # Local: app.routes is not imported by create_app(register_routes=False),
    # and tests patch export_ready at its source.
    from app.routes.expo_client import export_ready

    return "/app/training" if export_ready() else url_for("training_demo.welcome")


def inject_template_globals():
    is_authenticated = bool(current_user and current_user.is_authenticated)
    is_admin = bool(
        current_user and current_user.is_authenticated and current_user.is_admin()
    )
    return {
        "current_year": datetime.now(pytz.UTC).astimezone(
            _current_user_timezone()
        ).year,
        # Today in the user's zone, for date inputs' max (never the UTC date).
        "current_user_today": datetime.now(pytz.UTC).astimezone(
            _current_user_timezone()
        ).date().isoformat(),
        "site_maintenance_banner": get_site_maintenance_banner_context(
            is_authenticated=is_authenticated,
            is_admin=is_admin,
        ),
        "icd11_citation": ICD11_CITATION,
        "digitva_addition_label": DIGITVA_ADDITION_LABEL,
        "site_maintenance_watcher_enabled": is_authenticated,
        "site_maintenance_user_is_admin": is_admin,
    }


def user_timezone_filter(dt, format='%Y-%m-%d %H:%M:%S'):
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            return dt

    # If naive, assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.UTC)

    local_dt = dt.astimezone(_current_user_timezone())
    return local_dt.strftime(format)
