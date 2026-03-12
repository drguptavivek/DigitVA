import sqlalchemy as sa

from app import db
from app.models import MasFormTypes
from app.models.va_forms import VaForms
from app.services.field_mapping_service import get_mapping_service


def va_get_form_type_code_for_form(va_form_id: str | None) -> str:
    """Resolve the effective form type code for a VA form.

    Resolution order:
    1. `va_forms.form_type_id` -> `mas_form_types.form_type_code`
    2. legacy `va_forms.form_type` if it matches an active registered form type
    3. field-mapping service default form type
    """
    mapping_service = get_mapping_service()
    default_form_type = mapping_service.get_default_form_type()

    if not va_form_id:
        return default_form_type

    form = db.session.get(VaForms, va_form_id)
    if not form:
        return default_form_type

    if form.form_type_id:
        form_type = db.session.get(MasFormTypes, form.form_type_id)
        if form_type and form_type.is_active and form_type.form_type_code:
            return form_type.form_type_code

    legacy_form_type = (form.form_type or "").strip().upper()
    if legacy_form_type:
        legacy_match = db.session.scalar(
            sa.select(MasFormTypes).where(
                MasFormTypes.form_type_code == legacy_form_type,
                MasFormTypes.is_active == True,
            )
        )
        if legacy_match:
            return legacy_match.form_type_code

    return default_form_type
