"""User profile JSON API — /api/v1/profile/"""

from datetime import UTC, datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request, session
from flask_login import current_user, login_required

from app import db, limiter
from app.models import AuthWebauthnCredential
from app.routes.api.request_helpers import error as api_error
from app.routes.api.request_helpers import parse_body
from app.services import totp_service
from app.services.security_event_service import credential_id_prefix, record_security_event
from app.services.webauthn_service import (
    PasskeyVerificationError,
    base64url_to_bytes,
    build_authentication_options,
    build_registration_options,
    clear_authentication_challenge,
    clear_registration_challenge,
    verify_authentication,
    verify_registration,
)

bp = Blueprint("profile_api", __name__)

#: Reachable with a device bearer token. Everything else here (password,
#: reauthentication, passkeys, TOTP, recovery codes) is account security and
#: needs the browser session, so a stolen device token can never change it.
_BEARER_ALLOWED = frozenset({"get_profile", "update_timezone", "update_interviewer_profile", "accept_terms"})


@bp.before_request
def _account_security_is_cookie_only():
    from app.services.device_auth_service import request_bearer_token

    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if request_bearer_token(request) is not None and endpoint not in _BEARER_ALLOWED:
        return jsonify({"error": "Sign in on the web to manage account security.",
                        "code": "cookie_session_required"}), 403
    return None

# docs/policy/authentication-factors.md section 7: registering, renaming or
# revoking a passkey needs a sign-in or reauthentication within this window.
REAUTH_TTL = timedelta(minutes=10)

#: Reauthentication by passkey failed, whatever the reason.
PASSKEY_REAUTH_FAILED_MESSAGE = "That passkey could not be verified."

#: Profile generate for an account whose email is not yet verified: a
#: password goes only to a verified email (onboarding policy sections 1, 6).
EMAIL_UNVERIFIED_GENERATE_MESSAGE = (
    "Verify your email address first; your new password will then be emailed "
    "to you. Or ask your data manager for a sign-in code."
)


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
        return api_error("reauth_required", "reauth_required", 401)
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
        "job_title": current_user.job_title,
        "mobile_only": current_user.is_mobile_only,
        "languages": current_user.vacode_language or [],
        "timezone": current_user.timezone,
        "year_of_birth": current_user.year_of_birth,
        "sex": current_user.sex,
    })


# ---------------------------------------------------------------------------
# POST /api/v1/profile/password/generate  — a new generated password
# ---------------------------------------------------------------------------
# Nobody chooses a password (docs/policy/account-onboarding-and-passwords.md
# section 1), so there is no "change password" endpoint.

@bp.post("/password/generate")
@login_required
@limiter.limit("5 per hour", key_func=_rate_limit_key)
def generate_password():
    """A new server-generated password, after a reauthentication within the
    last ten minutes (authentication-factors.md section 7). An account with a
    verified email gets it by email and this response carries no password; a
    mobile-only account (no email) sees it once in this response. An account
    whose email is still awaiting verification is refused (409
    ``email_unverified``): a password never goes to an unverified address
    nor, for an email account, onto the screen (onboarding policy section 6).
    The old password stops working and every session ends, this one
    included: the page sends the person to sign in again."""
    from app.services import mobile_sign_in_service
    from app.services import user_account_service as accounts

    reauth_error = _require_reauth()
    if reauth_error:
        return reauth_error
    if current_user.email and not current_user.email_verified:
        return jsonify({"error": EMAIL_UNVERIFIED_GENERATE_MESSAGE, "code": "email_unverified"}), 409
    by_email = bool(current_user.email)
    try:
        if by_email:
            accounts.email_new_password(
                current_user, path="profile", actor_user_id=current_user.user_id
            )
        else:
            password = mobile_sign_in_service.set_new_password(
                current_user, path="profile", actor_user_id=current_user.user_id
            )
    except (mobile_sign_in_service.PasswordGenerationUnavailable,
            accounts.PasswordEmailFailed) as exc:
        db.session.rollback()
        return api_error(exc.message, status_code=503)
    db.session.commit()
    if by_email:
        response = jsonify({"message": "Your new password has been emailed to you."})
    else:
        response = jsonify({
            "password": password,
            "message": "Write this down. It will not be shown again.",
        })
    response.headers["Cache-Control"] = "no-store"
    return response


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
        return api_error("Timezone is required.")
    if timezone not in pytz.common_timezones:
        return api_error("Invalid timezone.")

    current_user.timezone = timezone
    db.session.commit()
    return jsonify({"message": "Timezone updated successfully.", "timezone": timezone})


# ---------------------------------------------------------------------------
# PATCH /api/v1/profile/job-title  — the person's own post (public text)
# ---------------------------------------------------------------------------

@bp.patch("/job-title")
@login_required
def update_job_title():
    """Set or clear the current user's job title (digitva-04u4). Public free
    text, validated by the same function as every other write path; it
    grants nothing."""
    from app.services import user_account_service as accounts

    body = parse_body()
    if "job_title" not in body:
        return api_error("job_title is required (null clears it).", "invalid_request", 400)
    try:
        current_user.job_title = accounts.clean_job_title(body["job_title"])
    except accounts.UserAccountError as exc:
        return api_error(str(exc))
    db.session.commit()
    return jsonify({"message": "Job title updated.", "job_title": current_user.job_title})


# ---------------------------------------------------------------------------
# PATCH /api/v1/profile/interviewer  — year of birth and sex (optional)
# ---------------------------------------------------------------------------

@bp.patch("/interviewer")
@login_required
def update_interviewer_profile():
    """Set or clear the year of birth and sex (digitva-vzk.3). Web intake
    prefills and locks the sex into WHO Id10010b; the year of birth no longer
    feeds Id10010a (digitva-q219). An omitted key keeps its
    value; null or blank clears it. Values are never logged."""
    body = request.get_json(silent=True) or {}
    try:
        current_user.set_interviewer_profile(
            body.get("year_of_birth", current_user.year_of_birth),
            body.get("sex", current_user.sex),
        )
    except ValueError as exc:
        return api_error(str(exc))
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
        return api_error("Incorrect password.", status_code=403)
    session["auth_verified_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify({"message": "Reauthenticated."})


@bp.post("/reauth/passkey/options")
@login_required
@limiter.limit("5 per minute", key_func=_rate_limit_key)
def reauth_passkey_options():
    """WebAuthn request options for reauthenticating with a passkey
    (authentication-factors.md section 7: password or passkey). The same
    discoverable-credential options as sign-in; verify checks the owner."""
    return jsonify(build_authentication_options())


@bp.post("/reauth/passkey")
@login_required
@limiter.limit("5 per minute", key_func=_rate_limit_key)
def reauth_passkey():
    """Verify a passkey assertion from the signed-in user's own passkey and
    refresh the reauthentication window. Mirrors the sign-in passkey check
    (app/routes/va_auth.py ``va_login_passkey_verify``): the credential must
    be this user's, the signature-counter rule and the atomic counter update
    are the same. Any failure answers 403 with one message."""
    body = request.get_json(silent=True)
    credential = body.get("credential") if isinstance(body, dict) else None
    if not isinstance(credential, dict):
        clear_authentication_challenge()
        return api_error(PASSKEY_REAUTH_FAILED_MESSAGE, status_code=403)
    try:
        raw_id = base64url_to_bytes(credential.get("rawId") or credential.get("id") or "")
    except Exception:
        clear_authentication_challenge()
        return api_error(PASSKEY_REAUTH_FAILED_MESSAGE, status_code=403)
    stored = db.session.scalar(
        sa.select(AuthWebauthnCredential).where(
            AuthWebauthnCredential.credential_id == raw_id,
            AuthWebauthnCredential.user_id == current_user.user_id,
        )
    )
    if stored is None:
        clear_authentication_challenge()
        return api_error(PASSKEY_REAUTH_FAILED_MESSAGE, status_code=403)
    try:
        verified = verify_authentication(credential, credential_public_key=stored.public_key)
    except PasskeyVerificationError:
        return api_error(PASSKEY_REAUTH_FAILED_MESSAGE, status_code=403)
    if stored.sign_count > 0 and verified.new_sign_count <= stored.sign_count:
        record_security_event(
            user_id=current_user.user_id,
            event_type="counter_regression",
            detail={"credential_prefix": credential_id_prefix(stored.credential_id)},
        )
        db.session.commit()
        return api_error(PASSKEY_REAUTH_FAILED_MESSAGE, status_code=403)
    result = db.session.execute(
        sa.update(AuthWebauthnCredential)
        .where(
            AuthWebauthnCredential.id == stored.id,
            AuthWebauthnCredential.sign_count == stored.sign_count,
        )
        .values(sign_count=verified.new_sign_count, last_used_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        db.session.rollback()
        return api_error(PASSKEY_REAUTH_FAILED_MESSAGE, status_code=403)
    db.session.commit()
    session["auth_verified_at"] = datetime.now(UTC).isoformat()
    return jsonify({"message": "Reauthenticated."})


# ---------------------------------------------------------------------------
# POST /api/v1/profile/terms  — accept the terms of use (JSON)
# ---------------------------------------------------------------------------

@bp.post("/terms")
@login_required
@limiter.shared_limit("5 per minute", scope="api_v1_terms", key_func=_rate_limit_key)  # one counter with /me/terms
def accept_terms():
    """The app's terms screen for a browser session (onboarding policy 5.4):
    records the acceptance exactly as the web terms page does. Body
    ``{"accept_terms": true}``; anything else is 400. Exempt from the terms
    gate (``force_password_update``); CSRF via ``X-CSRFToken``."""
    from app.services.user_account_service import accept_terms as record_acceptance

    request.max_content_length = 16 * 1024  # the device /terms cap
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("accept_terms") is not True:
        return jsonify({"error": "Please accept the terms of use.", "code": "invalid_request"}), 400
    record_acceptance(current_user._get_current_object(), via="device" if g.get("device_session") else "api")
    db.session.commit()
    return jsonify({"message": "Terms accepted.", "terms_accepted": True})


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
        return api_error("Invalid passkey response.")

    try:
        verified = verify_registration(credential)
    except PasskeyVerificationError as exc:
        return api_error(f"Could not verify the passkey: {exc}")

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
        return api_error("This passkey is already registered.")

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
        return api_error("Passkey not found.", status_code=404)

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()[:64]
    if not name:
        return api_error("A name is required.")

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
        return api_error("Passkey not found.", status_code=404)

    if _would_leave_privileged_user_without_factor(
        current_user._get_current_object(), removing_passkey_id=cred.id
    ):
        return api_error("You cannot remove your last sign-in factor.", status_code=409)

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
        return api_error(str(exc))
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
        return api_error("A code is required.")

    user = current_user._get_current_object()
    if not totp_service.confirm_enrolment(user, code):
        db.session.rollback()
        return api_error("Invalid code.")

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
        return api_error("TOTP is not enrolled.", status_code=404)
    if _would_leave_privileged_user_without_factor(user, removing_totp=True):
        return api_error("You cannot remove your last sign-in factor.", status_code=409)

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
