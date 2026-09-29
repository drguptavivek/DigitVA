"""User profile JSON API — /api/v1/profile/"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request, session
from flask_login import current_user, login_required

from app import db, limiter
from app.models import AuthWebauthnCredential
from app.models.mas_languages import MasLanguages
from app.services import totp_service
from app.services.security_event_service import credential_id_prefix, record_security_event
from app.services.webauthn_service import (
    PasskeyVerificationError,
    build_registration_options,
    clear_registration_challenge,
    verify_registration,
)
from app.utils.password_policy import password_error_message

bp = Blueprint("profile_api", __name__)

# docs/policy/authentication-factors.md section 7: registering, renaming or
# revoking a passkey needs a sign-in or reauthentication within this window.
REAUTH_TTL = timedelta(minutes=10)


def _error(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


def _rate_limit_key():
    """Per-account limiter key for passkey management: the signed-in user,
    not an attacker-controlled field."""
    return current_user.get_id() if current_user.is_authenticated else ""


def _reauthenticated_recently() -> bool:
    raw = session.get("auth_verified_at")
    if not raw:
        return False
    try:
        verified_at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return False
    return datetime.now(timezone.utc) - verified_at <= REAUTH_TTL


def _require_reauth():
    """Return an error response if reauthentication has expired, else None."""
    if not _reauthenticated_recently():
        return _error("reauth_required", 401)
    return None


def _invalidate_factor_setup_cache() -> None:
    """Drop the enrolment-enforcement guard's cached "has a factor" answer
    (app.create_app's ``enforce_factor_setup``) so the next request
    recomputes it -- called whenever this session's own factor set changes."""
    session.pop("factor_setup_needed", None)


def _would_leave_privileged_user_without_factor(
    user, *, removing_totp: bool = False, removing_passkey_id=None
) -> bool:
    """docs/policy/authentication-factors.md section 7: a privileged user
    cannot remove their last sign-in factor once enforcement has started
    (``AUTH_FACTOR_ENFORCE_FROM`` set and in the past). Before that date the
    guard is off, by design -- see totp_service.enforcement_active() and the
    section 6 redirect guard in app.create_app."""
    if not (user.is_admin() or user.is_data_manager()):
        return False
    if not totp_service.enforcement_active():
        return False
    has_totp = totp_service.has_confirmed_totp(user.user_id) and not removing_totp
    passkey_query = (
        sa.select(sa.func.count())
        .select_from(AuthWebauthnCredential)
        .where(AuthWebauthnCredential.user_id == user.user_id)
    )
    if removing_passkey_id is not None:
        passkey_query = passkey_query.where(AuthWebauthnCredential.id != removing_passkey_id)
    has_passkey = bool(db.session.scalar(passkey_query) or 0)
    return not has_totp and not has_passkey


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
        "year_of_birth": current_user.year_of_birth,
        "sex": current_user.sex,
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


# ---------------------------------------------------------------------------
# PATCH /api/v1/profile/interviewer  — year of birth and sex (optional)
# ---------------------------------------------------------------------------

@bp.patch("/interviewer")
@login_required
def update_interviewer_profile():
    """Set or clear the year of birth and sex web intake prefills and locks
    into WHO Id10010a / Id10010b (digitva-vzk.3). An omitted key keeps its
    value; null or blank clears it. Values are never logged."""
    body = request.get_json(silent=True) or {}
    try:
        current_user.set_interviewer_profile(
            body.get("year_of_birth", current_user.year_of_birth),
            body.get("sex", current_user.sex),
        )
    except ValueError as exc:
        return _error(str(exc))
    db.session.commit()
    return jsonify({
        "message": "Interviewer details updated.",
        "year_of_birth": current_user.year_of_birth,
        "sex": current_user.sex,
    })


# ---------------------------------------------------------------------------
# POST /api/v1/profile/reauth  — refresh the reauthentication window
# ---------------------------------------------------------------------------

@bp.post("/reauth")
@login_required
@limiter.limit("5 per minute", key_func=_rate_limit_key)
def reauth():
    """Re-verify the current user's password to refresh the 10-minute
    reauthentication window that passkey registration/rename/revoke need
    (docs/policy/authentication-factors.md section 7)."""
    body = request.get_json(silent=True) or {}
    password = body.get("password", "")
    if not password or not current_user.check_password(password):
        return _error("Incorrect password.", 403)
    session["auth_verified_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify({"message": "Reauthenticated."})


# ---------------------------------------------------------------------------
# Passkeys — /api/v1/profile/passkeys
# ---------------------------------------------------------------------------

def _serialize_credential(cred: AuthWebauthnCredential) -> dict:
    return {
        "id": str(cred.id),
        "name": cred.name,
        "created_at": cred.created_at.isoformat() if cred.created_at else None,
        "last_used_at": cred.last_used_at.isoformat() if cred.last_used_at else None,
        "backed_up": bool(cred.backed_up),
    }


@bp.get("/passkeys")
@login_required
def list_passkeys():
    creds = db.session.scalars(
        sa.select(AuthWebauthnCredential)
        .where(AuthWebauthnCredential.user_id == current_user.user_id)
        .order_by(AuthWebauthnCredential.created_at)
    ).all()
    return jsonify({"passkeys": [_serialize_credential(c) for c in creds]})


@bp.post("/passkeys/options")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def passkey_registration_options():
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error
    existing = db.session.scalars(
        sa.select(AuthWebauthnCredential.credential_id).where(
            AuthWebauthnCredential.user_id == current_user.user_id
        )
    ).all()
    options = build_registration_options(
        current_user._get_current_object(), existing_credential_ids=list(existing)
    )
    return jsonify(options)


@bp.post("/passkeys")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def register_passkey():
    """Verify a registration response and store the new passkey."""
    reauth_error = _require_reauth()
    if reauth_error:
        clear_registration_challenge()
        return reauth_error

    body = request.get_json(silent=True) or {}
    credential = body.get("credential")
    name = (body.get("name") or "").strip()[:64] or "Passkey"
    if not isinstance(credential, dict):
        clear_registration_challenge()
        return _error("Invalid passkey response.")

    try:
        verified = verify_registration(credential)
    except PasskeyVerificationError as exc:
        return _error(f"Could not verify the passkey: {exc}")

    record = AuthWebauthnCredential(
        user_id=current_user.user_id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        backup_eligible=verified.credential_device_type == "multi_device",
        backed_up=verified.credential_backed_up,
        transports=(credential.get("response") or {}).get("transports"),
        name=name,
    )
    db.session.add(record)
    try:
        db.session.flush()
    except sa.exc.IntegrityError:
        db.session.rollback()
        return _error("This passkey is already registered.")

    record_security_event(
        user_id=current_user.user_id,
        actor_user_id=current_user.user_id,
        event_type="passkey_registered",
        detail={"name": name, "credential_prefix": credential_id_prefix(record.credential_id)},
    )

    # docs/policy/authentication-factors.md section 4: recovery codes are
    # issued when a user enrols their FIRST factor. This is that moment only
    # when they hold no confirmed TOTP and have never had a recovery-code
    # set (has_recovery_codes stays true forever once issued, so a later
    # passkey addition never re-triggers this).
    recovery_codes = None
    user = current_user._get_current_object()
    if not totp_service.has_confirmed_totp(user.user_id) and not totp_service.has_recovery_codes(user.user_id):
        recovery_codes = totp_service.generate_recovery_codes(user)
        record_security_event(
            user_id=user.user_id,
            actor_user_id=user.user_id,
            event_type="recovery_codes_generated",
        )

    db.session.commit()
    # The "set up a passkey" nudge has done its job for this session.
    session.pop("passkey_nudge", None)
    _invalidate_factor_setup_cache()
    response = {"message": "Passkey added.", "passkey": _serialize_credential(record)}
    if recovery_codes is not None:
        response["recovery_codes"] = recovery_codes
    return jsonify(response)


@bp.patch("/passkeys/<uuid:passkey_id>")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def rename_passkey(passkey_id):
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error

    cred = db.session.scalar(
        sa.select(AuthWebauthnCredential).where(
            AuthWebauthnCredential.id == passkey_id,
            AuthWebauthnCredential.user_id == current_user.user_id,
        )
    )
    if cred is None:
        return _error("Passkey not found.", 404)

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()[:64]
    if not name:
        return _error("A name is required.")

    old_prefix = credential_id_prefix(cred.credential_id)
    cred.name = name
    record_security_event(
        user_id=current_user.user_id,
        actor_user_id=current_user.user_id,
        event_type="passkey_renamed",
        detail={"name": name, "credential_prefix": old_prefix},
    )
    db.session.commit()
    return jsonify({"message": "Passkey renamed.", "passkey": _serialize_credential(cred)})


@bp.delete("/passkeys/<uuid:passkey_id>")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def revoke_passkey(passkey_id):
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error

    cred = db.session.scalar(
        sa.select(AuthWebauthnCredential).where(
            AuthWebauthnCredential.id == passkey_id,
            AuthWebauthnCredential.user_id == current_user.user_id,
        )
    )
    if cred is None:
        return _error("Passkey not found.", 404)

    if _would_leave_privileged_user_without_factor(
        current_user._get_current_object(), removing_passkey_id=cred.id
    ):
        return _error("You cannot remove your last sign-in factor.", 409)

    prefix = credential_id_prefix(cred.credential_id)
    db.session.delete(cred)
    record_security_event(
        user_id=current_user.user_id,
        actor_user_id=current_user.user_id,
        event_type="passkey_revoked",
        detail={"name": cred.name, "credential_prefix": prefix},
    )
    db.session.commit()
    _invalidate_factor_setup_cache()
    return jsonify({"message": "Passkey revoked."})


# ---------------------------------------------------------------------------
# POST /api/v1/profile/dismiss-passkey-nudge  — dismiss the post-login banner
# ---------------------------------------------------------------------------

@bp.post("/dismiss-passkey-nudge")
@login_required
def dismiss_passkey_nudge():
    """Dismiss the "sign on faster" banner for the rest of this session."""
    session.pop("passkey_nudge", None)
    return jsonify({"message": "Dismissed."})


# ---------------------------------------------------------------------------
# TOTP — /api/v1/profile/totp
# ---------------------------------------------------------------------------

@bp.get("/totp")
@login_required
def totp_status():
    return jsonify({"enrolled": totp_service.has_confirmed_totp(current_user.user_id)})


@bp.post("/totp/enroll")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def totp_enroll():
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error

    try:
        result = totp_service.begin_enrolment(current_user._get_current_object())
    except totp_service.TotpEnrolmentError as exc:
        return _error(str(exc))
    db.session.commit()
    return jsonify({
        "secret": result["secret"],
        "provisioning_uri": result["provisioning_uri"],
        "qr_svg": totp_service.provisioning_qr_svg(result["provisioning_uri"]),
    })


@bp.post("/totp/confirm")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def totp_confirm():
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error

    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    if not code:
        return _error("A code is required.")

    user = current_user._get_current_object()
    if not totp_service.confirm_enrolment(user, code):
        db.session.rollback()
        return _error("Invalid code.")

    record_security_event(
        user_id=user.user_id, actor_user_id=user.user_id, event_type="totp_enrolled"
    )

    # docs/policy/authentication-factors.md section 4: recovery codes are
    # issued when a user enrols their FIRST factor -- here, only when they
    # hold no passkey and have never had a recovery-code set yet.
    recovery_codes = None
    has_passkey = db.session.scalar(
        sa.select(sa.exists().where(AuthWebauthnCredential.user_id == user.user_id))
    )
    if not has_passkey and not totp_service.has_recovery_codes(user.user_id):
        recovery_codes = totp_service.generate_recovery_codes(user)
        record_security_event(
            user_id=user.user_id, actor_user_id=user.user_id, event_type="recovery_codes_generated"
        )

    db.session.commit()
    _invalidate_factor_setup_cache()
    response = {"message": "TOTP enabled."}
    if recovery_codes is not None:
        response["recovery_codes"] = recovery_codes
    return jsonify(response)


@bp.delete("/totp")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def totp_remove():
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error

    user = current_user._get_current_object()
    if not totp_service.has_confirmed_totp(user.user_id):
        return _error("TOTP is not enrolled.", 404)
    if _would_leave_privileged_user_without_factor(user, removing_totp=True):
        return _error("You cannot remove your last sign-in factor.", 409)

    totp_service.remove(user)
    record_security_event(
        user_id=user.user_id, actor_user_id=user.user_id, event_type="totp_removed"
    )
    db.session.commit()
    _invalidate_factor_setup_cache()
    return jsonify({"message": "TOTP removed."})


# ---------------------------------------------------------------------------
# Recovery codes — /api/v1/profile/recovery-codes
# ---------------------------------------------------------------------------

@bp.get("/recovery-codes")
@login_required
def recovery_codes_status():
    return jsonify({
        "remaining": totp_service.remaining_recovery_code_count(current_user.user_id)
    })


@bp.post("/recovery-codes/regenerate")
@login_required
@limiter.limit("10 per minute", key_func=_rate_limit_key)
@limiter.limit("20 per hour", key_func=_rate_limit_key)
def recovery_codes_regenerate():
    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error

    user = current_user._get_current_object()
    codes = totp_service.generate_recovery_codes(user)
    record_security_event(
        user_id=user.user_id, actor_user_id=user.user_id, event_type="recovery_codes_generated"
    )
    db.session.commit()
    return jsonify({"recovery_codes": codes})
