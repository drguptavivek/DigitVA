"""Cache-related helpers for workflow form partials."""

from app import cache as flask_cache, db
from app.models import VaSubmissions
from app.services.forms.category_rendering import get_visible_category_codes
from app.services.submissions.payload_version import get_active_payload_version

_SECTION_CACHE_TIMEOUT = 1800  # 30 minutes


def _section_data_cache_key(va_sid: str, va_partial: str) -> str:
    return f"form_data:{va_sid}:{va_partial}"


def _response_contains_user_specific_artifacts(
    va_partial: str,
    va_action: str,
) -> bool:
    if va_action != "vacode":
        return False
    return va_partial in {"vanarrationanddocuments", "social_autopsy"}


def _apply_partial_cache_policy(response, va_partial: str, va_action: str):
    response.cache_control.private = True
    if _response_contains_user_specific_artifacts(va_partial, va_action):
        response.cache_control.no_store = True
        response.cache_control.max_age = 0
    else:
        response.cache_control.max_age = 300
    return response


def _invalidate_section_data_cache(va_sid: str) -> None:
    sub = db.session.get(VaSubmissions, va_sid)
    if not sub:
        return
    payload_version = get_active_payload_version(va_sid)
    payload_data = payload_version.payload_data if payload_version else None
    visible = get_visible_category_codes(payload_data, sub.va_form_id)
    for partial in visible:
        flask_cache.delete(_section_data_cache_key(va_sid, partial))
