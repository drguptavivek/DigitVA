from datetime import datetime, timedelta, timezone

from app import db, limiter
from app.models import AuthWebauthnCredential, VaUsers
from app.forms import (
    ConfirmLinkForm,
    EmailStepForm,
    PasswordStepForm,
    RedeemCodeForm,
    SecondFactorForm,
    ForgotPasswordForm,
)
import sqlalchemy as sa
import uuid
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_user, logout_user, current_user
from urllib.parse import urlparse
from werkzeug.security import check_password_hash, generate_password_hash

from app.services import mobile_sign_in_service, totp_service
from app.services.pow_captcha_service import issue_challenge, verify_challenge
from app.services.security_event_service import credential_id_prefix, record_security_event
from app.services import user_account_service as accounts
from app.services.user_account_service import canonical_mobile
from app.services.site_maintenance_service import (
    get_active_site_maintenance,
    serialize_site_maintenance,
    should_block_non_admin_after_cutoff,
)
from app.services.webauthn_service import (
    PasskeyVerificationError,
    base64url_to_bytes,
    build_authentication_options,
    clear_authentication_challenge,
    verify_authentication,
)

va_auth = Blueprint("va_auth", __name__)

# docs/policy/authentication-factors.md section 1: pre-auth state is bound to
# one email (or, docs/policy/mobile-sign-in.md section 2, one canonical
# mobile number), allows one outstanding challenge, and expires 5 minutes
# after the email step.
PREAUTH_TTL = timedelta(minutes=5)
INVALID_LOGIN_MESSAGE = "Invalid email or password. Please, re-check and login again."
INVALID_SECOND_FACTOR_MESSAGE = "Invalid code. Please try again."
INVALID_SIGN_IN_CODE_MESSAGE = (
    "That email or mobile number and code do not match. Please check and try again."
)
MOBILE_RESET_MESSAGE = (
    "If you sign in with a mobile number, ask your data manager for a new "
    "sign-in code, then use \"I have a code\" on the sign-in page."
)
#: One answer for every mobile number typed into "Forgot password", whether
#: it is unknown, mobile-only or has a verified email (policy section 6).
MOBILE_FORGOT_MESSAGE = (
    "If that number belongs to an account with a verified email, we've sent a "
    "password reset link to that email. Otherwise ask your data manager for a "
    "new sign-in code, then use \"I have a code\" on the sign-in page."
)
PASSWORD_EMAILED_MESSAGE = "Your password has been emailed to you."
INVALID_LINK_MESSAGE = "This link is invalid or has expired."
_DUMMY_PASSWORD_HASH = generate_password_hash("digitva-timing-equaliser")

# docs/policy/authentication-factors.md section 1: five failed second-factor
# attempts clear the pre-auth state and send the user back to the email step.
SECOND_FACTOR_MAX_FAILURES = 5


def _preauth_email_key_func():
    """Per-account limiter key for the password step: the pre-auth email or
    mobile number, not a form field an attacker controls."""
    state = _preauth_state() or {}
    if state.get("email"):
        return state["email"]
    return f"mobile:{state.get('mobile') or ''}"


def _login_identifier_key_func(field: str = "email"):
    """Per-identifier limiter key for a posted email or mobile number: a
    mobile number keys on its canonical form, so spacing or a ``+91`` prefix
    does not buy a fresh bucket."""
    value = (request.form.get(field) or "").strip()
    if "@" in value:
        return value.lower()
    return f"mobile:{canonical_mobile(value) or value}"


def _preauth_state() -> dict | None:
    """The current pre-auth state if present and not expired, else None.
    Names either an ``email`` or a ``mobile`` (canonical, or "" for a value
    that is not a 10-digit number, which then matches no account)."""
    state = session.get("preauth")
    if not isinstance(state, dict) or not state.get("issued_at"):
        return None
    if not state.get("email") and "mobile" not in state:
        return None
    try:
        issued_at = datetime.fromisoformat(state["issued_at"])
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - issued_at > PREAUTH_TTL:
        return None
    return state


def _set_preauth(identifier: str, next_url: str | None) -> None:
    """Start pre-auth for a typed email or mobile number, without looking
    the account up (the email step never branches on existence)."""
    state = {"issued_at": datetime.now(timezone.utc).isoformat(), "next": next_url}
    identifier = (identifier or "").strip()
    if "@" in identifier:
        state["email"] = identifier.lower()
    else:
        state["mobile"] = canonical_mobile(identifier) or ""
    session["preauth"] = state


def _preauth_user(preauth: dict):
    """The account the pre-auth state names, or None. A mobile number
    matches only a unique sign-in number (``mobile_login``); shared or
    malformed numbers are never set there, so they match no one."""
    if preauth.get("email"):
        return db.session.scalar(sa.select(VaUsers).where(VaUsers.email == preauth["email"]))
    if preauth.get("mobile"):
        return db.session.scalar(
            sa.select(VaUsers).where(VaUsers.mobile_login == preauth["mobile"])
        )
    return None


def _preauth_names(user, preauth: dict) -> bool:
    """Whether the pre-auth state still names *user* (same email or number)."""
    if preauth.get("email"):
        return user.email == preauth["email"]
    return bool(preauth.get("mobile")) and user.mobile_login == preauth["mobile"]


def _preauth_display(preauth: dict) -> str:
    """What the person typed, for "Signing in as" on their own page."""
    return preauth.get("email") or preauth.get("mobile") or "your mobile number"


def _clear_preauth() -> None:
    session.pop("preauth", None)


def _complete_login(user, *, remember: bool, nudge_if_no_passkey: bool) -> None:
    """Finish sign-in exactly once, shared by the password and passkey
    paths: drop every session key issued before authentication (the pre-auth
    state included), give the authenticated session a new ID, and record the
    reauthentication timestamp that Profile's passkey-management routes
    require to be fresh (docs/policy/authentication-factors.md section 7 --
    the 10-minute window itself is enforced in app/routes/api/profile.py).

    ``nudge_if_no_passkey`` flags the post-login passkey banner (section 2):
    the password path passes True, the passkey path False (a passkey
    sign-in needs no nudge to use a passkey).

    Caller is responsible for every check that must pass first (active,
    verified email, maintenance) and for the redirect afterwards.
    """
    has_passkey = db.session.scalar(
        sa.select(
            sa.exists().where(AuthWebauthnCredential.user_id == user.user_id)
        )
    )
    _clear_preauth()
    clear_authentication_challenge()
    # Session fixation: drop everything issued before authentication, then
    # give the authenticated session a new ID. regenerate() no-ops on an
    # empty session, so it must run after login_user has populated it.
    session.clear()
    session.permanent = True
    login_user(user, remember=remember)
    session["auth_verified_at"] = datetime.now(timezone.utc).isoformat()
    if nudge_if_no_passkey and not has_passkey:
        session["passkey_nudge"] = True
    current_app.session_interface.regenerate(session)


@va_auth.route("/valogin", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"], key_func=_login_identifier_key_func)
def va_login():
    """Step 1: email or mobile number plus the proof-of-work CAPTCHA. A value
    with ``@`` is an email, anything else a mobile number (docs/policy/
    mobile-sign-in.md section 2). Never looks the user up
    or branches on whether the account exists -- see docs/policy/
    authentication-factors.md section 1.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    # A fresh visit to the email step always starts over (policy: "replaced
    # by a new email step"), including via the password page's "not you?"
    # link.
    _clear_preauth()
    form = EmailStepForm()
    maintenance_notice = None
    if should_block_non_admin_after_cutoff():
        maintenance = get_active_site_maintenance()
        if maintenance is not None:
            maintenance_notice = {
                "title": "Site is under maintenance.",
                "body": "Only admin login is allowed right now.",
                "message": maintenance.message or "",
            }
    if form.validate_on_submit():
        solved = verify_challenge(
            salt=form.captcha_salt.data,
            difficulty=form.captcha_difficulty.data,
            expires=form.captcha_expires.data,
            signature=form.captcha_signature.data,
            solution=form.captcha_solution.data,
        )
        if not solved:
            flash(
                "We couldn't verify that request. Please try again.",
                "primary",
            )
            return render_template(
                "va_frontpages/va_login.html",
                form=EmailStepForm(email=form.email.data),
                maintenance_notice=maintenance_notice,
            )

        next_url = _safe_next_url(request.args.get("next"))
        _set_preauth(form.email.data, next_url)
        password_url = url_for("va_auth.va_login_password")
        if next_url:
            password_url = url_for("va_auth.va_login_password", next=next_url)
        return redirect(password_url)
    return render_template(
        "va_frontpages/va_login.html",
        form=form,
        maintenance_notice=maintenance_notice,
    )


@va_auth.route("/valogin/captcha-challenge", methods=["GET"])
def va_login_captcha_challenge():
    """JSON challenge for the email step's proof-of-work CAPTCHA."""
    return jsonify(issue_challenge())


@va_auth.route("/valogin/password", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"], key_func=_preauth_email_key_func)
def va_login_password():
    """Step 2: the same page (a passkey button plus password) for every
    email, known or unknown -- see docs/policy/authentication-factors.md
    section 1. Passkey verification runs through the JSON routes below.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    preauth = _preauth_state()
    if preauth is None:
        flash("Please sign in again.", "primary")
        return redirect(url_for("va_auth.va_login"))

    next_url = _safe_next_url(request.args.get("next")) or preauth.get("next")
    form = PasswordStepForm()
    if form.validate_on_submit():
        # Re-check freshness: a long-open tab could submit after expiry.
        preauth = _preauth_state()
        if preauth is None:
            flash("Please sign in again.", "primary")
            return redirect(url_for("va_auth.va_login"))

        user = _preauth_user(preauth)
        # Inactive accounts get the wrong-password response: no enumeration.
        if user is None:
            # Spend a hash check anyway so unknown emails take as long.
            check_password_hash(_DUMMY_PASSWORD_HASH, form.password.data)
        if (
            user is None
            or not user.check_password(form.password.data)
            or not user.is_active
        ):
            flash(INVALID_LOGIN_MESSAGE, "primary")
            return redirect(_password_step_url(next_url))

        if not user.sign_in_verified:
            if user.is_mobile_only:
                # Unreachable in practice (a mobile-only password comes only
                # from redeeming a code), kept so the check is never skipped.
                flash(INVALID_LOGIN_MESSAGE, "primary")
            else:
                flash("Please verify your email address before logging in.", "email_unverified")
            return redirect(_password_step_url(next_url))

        if not user.is_admin() and should_block_non_admin_after_cutoff():
            flash(
                "Site is under maintenance. Only admin login is allowed right now.",
                "warning",
            )
            return redirect(_password_step_url(next_url))

        if totp_service.needs_second_factor(user):
            # Bind the verified password to the same pre-auth state (same
            # email, same 5-minute expiry) rather than completing sign-in --
            # docs/policy/authentication-factors.md section 3.
            preauth["second_factor_user_id"] = str(user.user_id)
            preauth["second_factor_failures"] = 0
            preauth["remember"] = bool(form.remember_me.data)
            session["preauth"] = preauth
            return redirect(_second_factor_step_url(next_url))

        _complete_login(user, remember=form.remember_me.data, nudge_if_no_passkey=True)

        return redirect(next_url or current_user.landing_url())
    return render_template(
        "va_frontpages/va_login_password.html",
        form=form,
        email=_preauth_display(preauth),
        next_url=next_url,
    )


def _password_step_url(next_url):
    if next_url:
        return url_for("va_auth.va_login_password", next=next_url)
    return url_for("va_auth.va_login_password")


def _second_factor_step_url(next_url):
    if next_url:
        return url_for("va_auth.va_login_second_factor", next=next_url)
    return url_for("va_auth.va_login_second_factor")


def _second_factor_state() -> dict | None:
    """The pre-auth state, only if a password has already been verified for
    it in this same state -- the second-factor page is unreachable without
    that (docs/policy/authentication-factors.md section 1)."""
    preauth = _preauth_state()
    if preauth is None or not preauth.get("second_factor_user_id"):
        return None
    return preauth


@va_auth.route("/valogin/second-factor", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"], key_func=_preauth_email_key_func)
def va_login_second_factor():
    """Step 3, only for users who must give a second factor: a TOTP code or
    a recovery code (docs/policy/authentication-factors.md section 3).
    Reachable only after a correct password in the same pre-auth state.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    preauth = _second_factor_state()
    if preauth is None:
        flash("Please sign in again.", "primary")
        return redirect(url_for("va_auth.va_login"))

    user = db.session.scalar(
        sa.select(VaUsers).where(VaUsers.user_id == uuid.UUID(preauth["second_factor_user_id"]))
    )
    if user is None or not user.is_active or not _preauth_names(user, preauth):
        _clear_preauth()
        flash("Please sign in again.", "primary")
        return redirect(url_for("va_auth.va_login"))

    has_passkey = db.session.scalar(
        sa.select(sa.exists().where(AuthWebauthnCredential.user_id == user.user_id))
    )
    has_totp = totp_service.has_confirmed_totp(user.user_id)
    next_url = _safe_next_url(request.args.get("next")) or preauth.get("next")
    form = SecondFactorForm()

    if form.validate_on_submit():
        # Re-check freshness and state: a long-open tab could submit after
        # expiry, or after the pre-auth state was cleared some other way.
        preauth = _second_factor_state()
        if preauth is None:
            flash("Please sign in again.", "primary")
            return redirect(url_for("va_auth.va_login"))

        code = (form.code.data or "").strip()
        verified_by_totp = has_totp and totp_service.verify(user, code)
        verified_by_recovery = (not verified_by_totp) and totp_service.verify_recovery_code(user, code)
        verified = verified_by_totp or verified_by_recovery

        if not verified:
            db.session.rollback()
            failures = preauth.get("second_factor_failures", 0) + 1
            if failures >= SECOND_FACTOR_MAX_FAILURES:
                _clear_preauth()
                record_security_event(user_id=user.user_id, event_type="second_factor_lockout")
                db.session.commit()
                flash("Too many attempts. Please sign in again.", "primary")
                return redirect(url_for("va_auth.va_login"))
            preauth["second_factor_failures"] = failures
            session["preauth"] = preauth
            flash(INVALID_SECOND_FACTOR_MESSAGE, "primary")
            return redirect(_second_factor_step_url(next_url))

        if verified_by_recovery:
            remaining = totp_service.remaining_recovery_code_count(user.user_id)
            record_security_event(
                user_id=user.user_id,
                event_type="recovery_code_used",
                detail={"remaining": remaining},
            )

        if not user.is_admin() and should_block_non_admin_after_cutoff():
            db.session.commit()
            flash(
                "Site is under maintenance. Only admin login is allowed right now.",
                "warning",
            )
            return redirect(_second_factor_step_url(next_url))

        remember = bool(preauth.get("remember"))
        _complete_login(user, remember=remember, nudge_if_no_passkey=not has_passkey)
        db.session.commit()
        return redirect(next_url or current_user.landing_url())

    return render_template(
        "va_frontpages/va_login_second_factor.html",
        form=form,
        email=_preauth_display(preauth),
        next_url=next_url,
        has_totp=has_totp,
        has_passkey=has_passkey,
    )


@va_auth.route("/valogin/passkey/options", methods=["POST"])
@limiter.limit("10 per minute")
@limiter.limit("20 per hour", key_func=_preauth_email_key_func)
def va_login_passkey_options():
    """Discoverable-credential options for the passkey sign-in button.

    No ``allowCredentials`` and nothing derived from the pre-auth email --
    the response is identical for every email, known or not (section 1).
    Still requires a live pre-auth state, so this is unreachable without
    having passed the CAPTCHA-gated email step first.
    """
    if _preauth_state() is None:
        return jsonify({"error": "Please sign in again."}), 400
    return jsonify(build_authentication_options())


@va_auth.route("/valogin/passkey/verify", methods=["POST"])
@limiter.limit("10 per minute")
@limiter.limit("20 per hour", key_func=_preauth_email_key_func)
def va_login_passkey_verify():
    """Verify a passkey assertion and complete sign-in.

    The credential must belong to the account named by the pre-auth email
    (never the credential's own claim) -- an assertion for a real credential
    of a *different* account, or for no account at all, gets the same
    generic message as a wrong password (docs/policy/authentication-factors.md
    section 2).
    """
    preauth = _preauth_state()
    if preauth is None:
        clear_authentication_challenge()
        return jsonify({"error": "Please sign in again."}), 400

    body = request.get_json(silent=True) or {}
    credential = body.get("credential")
    if not isinstance(credential, dict):
        clear_authentication_challenge()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    try:
        raw_id = base64url_to_bytes(credential.get("rawId") or credential.get("id") or "")
    except Exception:
        clear_authentication_challenge()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    preauth_user = _preauth_user(preauth)
    stored = db.session.scalar(
        sa.select(AuthWebauthnCredential).where(
            AuthWebauthnCredential.credential_id == raw_id
        )
    )
    # The credential must belong to the pre-auth email's own account -- a
    # real credential of a different account (or of no account) is refused
    # with the same generic message, never distinguished.
    if (
        preauth_user is None
        or stored is None
        or stored.user_id != preauth_user.user_id
        or not preauth_user.is_active
    ):
        clear_authentication_challenge()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    user = preauth_user

    try:
        verified = verify_authentication(
            credential, credential_public_key=stored.public_key
        )
    except PasskeyVerificationError:
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    # Signature-counter policy (section 2): 0/0 is fine (synced passkeys);
    # only a non-zero stored counter the new value fails to exceed is a
    # possible clone.
    if stored.sign_count > 0 and verified.new_sign_count <= stored.sign_count:
        record_security_event(
            user_id=user.user_id,
            event_type="counter_regression",
            detail={"credential_prefix": credential_id_prefix(stored.credential_id)},
        )
        db.session.commit()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    if not user.sign_in_verified:
        return jsonify(
            {"error": "Please verify your email address before logging in."}
        ), 400

    if not user.is_admin() and should_block_non_admin_after_cutoff():
        return jsonify(
            {"error": "Site is under maintenance. Only admin login is allowed right now."}
        ), 400

    next_url = preauth.get("next")

    # Atomic counter update: only succeeds if sign_count still matches what
    # was just checked, so a concurrent use of the same credential cannot
    # both apply their counter bump.
    result = db.session.execute(
        sa.update(AuthWebauthnCredential)
        .where(
            AuthWebauthnCredential.id == stored.id,
            AuthWebauthnCredential.sign_count == stored.sign_count,
        )
        .values(
            sign_count=verified.new_sign_count,
            last_used_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    _complete_login(user, remember=False, nudge_if_no_passkey=False)
    db.session.commit()

    return jsonify({"redirect": next_url or current_user.landing_url()})


@va_auth.route("/valogout", methods=["POST"])
def va_logout():
    if current_user.is_anonymous:
        return redirect(url_for("va_main.va_index"))
    logout_user()
    flash("You have been successfully logged out.", "primary")
    return redirect(url_for("va_main.va_index"))


@va_auth.route("/site-maintenance-status", methods=["GET"])
def site_maintenance_status():
    maintenance = get_active_site_maintenance()
    return jsonify({"maintenance": serialize_site_maintenance(maintenance)})


# ---------------------------------------------------------------------------
# Sign-in codes for mobile-only accounts (docs/policy/mobile-sign-in.md s.3)
# ---------------------------------------------------------------------------

@va_auth.route("/valogin/code", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("10 per hour", methods=["POST"],
               key_func=lambda: _login_identifier_key_func("mobile"))
def va_login_redeem_code():
    """"I have a code": an email or mobile number plus the one-time code a
    data manager issued (any account, docs/policy/account-onboarding-and-
    passwords.md section 6). On a match the server generates a password and shows it once,
    on this response only (no-store; a refresh re-posts a spent code and
    fails). A wrong identifier and a wrong code get the same answer. Public by
    design, CAPTCHA-gated and rate-limited per IP and per number; the person
    then signs in normally, so every factor rule still applies.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    form = RedeemCodeForm()
    if form.validate_on_submit():
        solved = verify_challenge(
            salt=form.captcha_salt.data,
            difficulty=form.captcha_difficulty.data,
            expires=form.captcha_expires.data,
            signature=form.captcha_signature.data,
            solution=form.captcha_solution.data,
        )
        if not solved:
            flash("We couldn't verify that request. Please try again.", "primary")
            return render_template(
                "va_frontpages/va_login_code.html", form=RedeemCodeForm(mobile=form.mobile.data)
            )
        try:
            result = mobile_sign_in_service.redeem_code(form.mobile.data, form.code.data)
        except mobile_sign_in_service.PasswordGenerationUnavailable as exc:
            db.session.rollback()
            flash(exc.message, "warning")
            return render_template(
                "va_frontpages/va_login_code.html", form=RedeemCodeForm(mobile=form.mobile.data)
            )
        db.session.commit()
        if result is None:
            flash(INVALID_SIGN_IN_CODE_MESSAGE, "primary")
            return render_template(
                "va_frontpages/va_login_code.html", form=RedeemCodeForm(mobile=form.mobile.data)
            )
        user, password = result
        if user.email:
            # Security review: the address on file hears of the change
            # (no password, no code). Non-critical, so never blocks the page.
            try:
                from app.services.email_service import send_code_redeemed_notice

                send_code_redeemed_notice(user)
            except Exception as exc:
                current_app.logger.warning(
                    "code redeemed notice failed | user_id=%s | %s", user.user_id, type(exc).__name__
                )
        response = make_response(render_template(
            "va_frontpages/va_login_code_password.html", password=password
        ))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response
    return render_template("va_frontpages/va_login_code.html", form=form)


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------

@va_auth.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def forgot_password():
    """Email a single-use reset link to the account's *verified* email,
    found by email or mobile number. Typing an identifier never changes a
    password by itself: only opening the link and pressing its button does
    (docs/policy/account-onboarding-and-passwords.md section 6). One answer
    per kind of identifier, whether or not an account matches."""
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        typed = form.email.data.strip()
        if "@" in typed:
            match = VaUsers.email == typed.lower()
            message = (
                "If that email address is registered, we've sent a password reset link. "
                "Please check your inbox (and spam folder)."
            )
        else:
            match = VaUsers.mobile_login == (canonical_mobile(typed) or "")
            message = MOBILE_FORGOT_MESSAGE
        user = db.session.scalar(sa.select(VaUsers).where(match))
        if user is not None and user.email and user.email_verified:
            _send_password_reset(user)
        flash(message, "info")
        return redirect(url_for("va_auth.forgot_password"))
    return render_template("va_frontpages/va_forgot_password.html", form=form)


def _link_user(token: str, purpose: str):
    """The account a still-valid emailed link names, or None."""
    from app.services.token_service import validate_token

    user_id = validate_token(token, purpose)
    if not user_id:
        return None
    try:
        return db.session.get(VaUsers, uuid.UUID(user_id))
    except (ValueError, TypeError):
        return None


def _confirm_page(template: str, token: str, *, valid: bool, status: int = 200, **context):
    return render_template(
        template, form=ConfirmLinkForm(), token=token, token_valid=valid, **context
    ), status


def _password_delivery_failed(exc, retry_url: str):
    """Roll back a password change whose generation or email failed (the old
    password, if any, keeps working) and send the person back to retry."""
    db.session.rollback()
    flash(exc.message, "warning")
    return redirect(retry_url)


@va_auth.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def reset_password(token):
    """The reset link. GET shows a button and changes nothing (mail scanners
    prefetch links); POST generates a new password, ends every session and
    emails it -- the page shows no password and has no password box
    (account-onboarding-and-passwords.md section 6). Single use: the token
    fingerprints the password hash, which the POST changes."""
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    template = "va_frontpages/va_reset_password.html"
    user = _link_user(token, "password_reset")
    # A mobile-only account has no address to email (mobile-sign-in.md s.3).
    if user is None or not user.email or not user.is_active:
        return _confirm_page(template, token, valid=False)
    if request.method == "GET":
        return _confirm_page(template, token, valid=True)
    if not ConfirmLinkForm().validate_on_submit():
        return _confirm_page(template, token, valid=True, status=400)

    try:
        accounts.email_new_password(user, path="password_reset")
    except (mobile_sign_in_service.PasswordGenerationUnavailable,
            accounts.PasswordEmailFailed) as exc:
        return _password_delivery_failed(exc, url_for("va_auth.reset_password", token=token))
    # Terms are accepted again at next sign-in, as after every reset.
    user.pw_reset_t_and_c = False
    db.session.commit()
    flash(f"{PASSWORD_EMAILED_MESSAGE} Please sign in with it.", "success")
    return redirect(url_for("va_auth.va_login"))


# ---------------------------------------------------------------------------
# Break-glass factor reset (docs/policy/authentication-factors.md section 8)
# ---------------------------------------------------------------------------

@va_auth.route("/factor-reset/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def factor_reset(token):
    """Land the break-glass CLI's single-use magic link. GET shows a button
    and changes nothing; POST verifies the email, ends every other session
    (which also spends this and any other factor-reset token), signs the
    user straight in and sends them to the Profile factor-setup section. No
    password is chosen or changed here: the existing one keeps working, and
    a fresh sign-in leaves Profile's "Generate a new password" open for ten
    minutes. Public by design -- reachable only with a valid, unexpired,
    single-use token; see ``PUBLIC_BY_DESIGN`` in tests/test_route_auth_coverage.py.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    template = "va_frontpages/va_reset_password.html"
    action_url = url_for("va_auth.factor_reset", token=token)
    user = _link_user(token, "factor_reset")
    # login_user() refuses an inactive user silently: refuse here instead.
    if user is None or not user.is_active:
        return _confirm_page(template, token, valid=False, action_url=action_url)
    if request.method == "GET":
        return _confirm_page(template, token, valid=True, action_url=action_url, factor_reset=True)
    if not ConfirmLinkForm().validate_on_submit():
        return _confirm_page(template, token, valid=True, status=400,
                             action_url=action_url, factor_reset=True)

    if not user.email_verified:
        user.email_verified = True
    user.bump_session_version()
    _complete_login(user, remember=False, nudge_if_no_passkey=False)
    # Set after _complete_login: it calls session.clear() first.
    session["factor_setup_forced"] = True
    db.session.commit()
    flash(
        "You are signed in. Please add a passkey or authenticator app. If you "
        "need a new password, use \"Generate a new password\" below now.",
        "success",
    )
    return redirect(url_for("profile.view") + "#passkeys-card")


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------

@va_auth.route("/verify-email/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def verify_email(token):
    """The verification link. GET shows a button and changes nothing; POST
    marks the email verified and, for an account that has no usable password
    yet, generates one and emails it to that address. An account that
    already has one keeps it (account-onboarding-and-passwords.md 5.1, 5.3).
    The page never shows a password. Reopening a used link does nothing.
    """
    user = _link_user(token, "email_verify")
    if user is None or not user.is_active:
        flash(
            "This verification link is invalid or has expired. "
            "Please request a new one.",
            "danger",
        )
        return redirect(url_for("va_auth.va_login"))
    if user.email_verified:
        flash("Your email is already verified. You can sign in.", "success")
        return redirect(url_for("va_auth.va_login"))
    if request.method == "GET" or not ConfirmLinkForm().validate_on_submit():
        return render_template("va_frontpages/va_verify_email.html", form=ConfirmLinkForm(), token=token)

    needs_password = not accounts.has_usable_password(user)
    user.email_verified = True
    record_security_event(user_id=user.user_id, event_type="email_verified")
    if needs_password:
        try:
            accounts.email_new_password(user, path="email_verification")
        except (mobile_sign_in_service.PasswordGenerationUnavailable,
                accounts.PasswordEmailFailed) as exc:
            return _password_delivery_failed(exc, url_for("va_auth.verify_email", token=token))
    db.session.commit()
    if needs_password:
        flash(f"Your email is verified. {PASSWORD_EMAILED_MESSAGE}", "success")
    else:
        flash("Your email is verified. You can sign in with your password.", "success")
    return redirect(url_for("va_auth.va_login"))


@va_auth.route("/resend-verification", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def resend_verification():
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        if "@" not in form.email.data:
            flash(MOBILE_RESET_MESSAGE, "info")
            return redirect(url_for("va_auth.resend_verification"))
        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == form.email.data.strip().lower())
        )
        if user and not user.email_verified:
            _send_email_verification(user)
        # Same message regardless to prevent enumeration
        flash(
            "If that email address needs verification, we've sent a new link. "
            "Please check your inbox (and spam folder).",
            "info",
        )
        return redirect(url_for("va_auth.resend_verification"))
    return render_template("va_frontpages/va_resend_verification.html", form=form)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_next_url(target):
    """Return ``target`` if it is a safe post-login redirect, else None.

    Accepts a path starting with exactly one ``/`` (no scheme, no host), or an
    absolute http(s) URL on this request's host (role_required sends
    ``next=request.url``). Rejects backslashes, whitespace and control
    characters anywhere, since browsers normalise ``/\\host`` and ``///host``
    into off-site URLs.
    """
    if not target or "\\" in target:
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in target):
        return None
    if target.startswith("//"):
        return None
    parsed = urlparse(target)
    if not parsed.scheme and not parsed.netloc:
        return target if target.startswith("/") else None
    if parsed.scheme in ("http", "https") and parsed.netloc == request.host:
        return target
    return None


def _send_password_reset(user):
    """Generate a password-reset token and dispatch the email."""
    from app.services.token_service import generate_token
    from app.services.email_service import send_password_reset_email

    token = generate_token(user.user_id, "password_reset")
    send_password_reset_email(user, token)


def _send_email_verification(user):
    """Generate an email-verification token and dispatch the email."""
    from app.services.token_service import generate_token
    from app.services.email_service import send_verification_email

    token = generate_token(user.user_id, "email_verify")
    send_verification_email(user, token)
