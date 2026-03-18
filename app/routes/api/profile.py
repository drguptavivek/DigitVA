"""User profile JSON API — /api/v1/profile/"""

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.models.mas_languages import MasLanguages
from app.utils.password_policy import password_error_message

bp = Blueprint("profile_api", __name__)


def _error(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


# ---------------------------------------------------------------------------
# GET /api/v1/profile/  — current user profile
# ---------------------------------------------------------------------------

@bp.get("/")
@login_required
def get_profile():
    """Return the current user's profile data."""
    return jsonify({
        "user_id": current_user.user_id,
        "name": current_user.name,
        "email": current_user.email,
        "languages": current_user.vacode_language or [],
        "timezone": current_user.timezone,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/profile/languages  — available language choices
# ---------------------------------------------------------------------------

@bp.get("/languages")
@login_required
def get_languages():
    """Return available VA language options."""
    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return jsonify({
        "languages": [{"code": l.language_code, "name": l.language_name} for l in languages],
        "selected": current_user.vacode_language or [],
    })


# ---------------------------------------------------------------------------
# PATCH /api/v1/profile/password  — change password
# ---------------------------------------------------------------------------

@bp.patch("/password")
@login_required
@limiter.limit("5 per minute")
def update_password():
    """Change the current user's password."""
    body = request.get_json(silent=True) or {}
    current_pw = body.get("current_password", "")
    new_pw = body.get("new_password", "")
    confirm_pw = body.get("confirm_password", "")

    if not current_pw or not new_pw or not confirm_pw:
        return _error("All password fields are required.")
    if not current_user.check_password(current_pw):
        return _error("Incorrect current password.", 403)
    if new_pw != confirm_pw:
        return _error("New passwords do not match.")
    if current_user.check_password(new_pw):
        return _error("New password must differ from your current password.")
    policy_error = password_error_message(new_pw)
    if policy_error:
        return _error(policy_error)

    current_user.set_password(new_pw)
    db.session.commit()
    return jsonify({"message": "Password updated successfully."})


# ---------------------------------------------------------------------------
# PATCH /api/v1/profile/language  — update VA language preferences
# ---------------------------------------------------------------------------

@bp.patch("/language")
@login_required
def update_language():
    """Update the current user's VA coding language preferences."""
    body = request.get_json(silent=True) or {}
    languages = body.get("languages")

    if not isinstance(languages, list) or not languages:
        return _error("At least one language must be selected.")

    # Validate codes against available languages
    valid_codes = set(db.session.scalars(
        sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
    ).all())
    invalid = [c for c in languages if c not in valid_codes]
    if invalid:
        return _error(f"Invalid language codes: {invalid}")

    current_user.vacode_language = languages
    db.session.commit()
    return jsonify({"message": "Languages updated successfully.", "languages": languages})


# ---------------------------------------------------------------------------
# PATCH /api/v1/profile/timezone  — update timezone
# ---------------------------------------------------------------------------

@bp.patch("/timezone")
@login_required
def update_timezone():
    """Update the current user's timezone."""
    import pytz
    body = request.get_json(silent=True) or {}
    timezone = (body.get("timezone") or "").strip()

    if not timezone:
        return _error("Timezone is required.")
    if timezone not in pytz.common_timezones:
        return _error("Invalid timezone.")

    current_user.timezone = timezone
    db.session.commit()
    return jsonify({"message": "Timezone updated successfully.", "timezone": timezone})
