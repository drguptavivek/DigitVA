"""Every request is decided by authz: the consultation marker (digitva-5hmc).

Policy: docs/policy/access-control-model.md, "Every access goes through
authz". Each authz decision (``role_required``'s gate, ``effective_roles``,
``can``/``require``, ``scope_filter``, ``reaches``, ``codes_as_tester``,
``reachable_unit_ids``, ``can_grant``, ``grant_list_filter``) calls
``mark_consulted``; the ``VaUsers.is_*`` helpers do not (templates call them
on every page). ``install`` wraps every
registered view that is not on ``EXEMPT_ENDPOINTS``; after the view returns
(or raises an HTTP error) the wrapper asks whether authz decided. If it did
not, it logs the endpoint and user id, and with ``AUTHZ_ENFORCE_CONSULTED``
on (production) refuses with 403.

Why wrap the view, not ``after_request``: the wrapper sees the view's own
outcome before any body is sent, so a streamed response (a generator body)
is refused before its first byte; the decision must therefore be made in
the view body, never lazily inside the generator. Refusals from
``before_request`` hooks (CSRF, rate limits, the device API's bearer check)
never reach the view and are not this check's business: they refuse. A
401, 403 or 429 raised inside the view chain before authz ran (a route rate
limit) passes through for the same reason; any other outcome, a 404 raised
before authz included, is a gap.

What it does not do. The view has already run when it is refused, so a
mutation it made stays made: enforcement stops exposure, not writes; the
route probe (tests/test_route_authz_probe.py) is what keeps writes behind
authz. An anonymous request is passed through: authentication guards
(``role_required``, ``login_required``) answer it, base.js depends on their
401, and tests/test_route_auth_coverage.py proves every non-exempt route
carries one.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import abort, current_app, has_request_context, jsonify, request
from flask_login import current_user
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)

_ENVIRON_KEY = "digitva.authz.consulted"
_REFUSALS = frozenset({401, 403, 429})

# ---------------------------------------------------------------------------
# The reviewed exemption list (one place; tests/test_route_auth_coverage.py
# reads PUBLIC_ENDPOINTS from here). Each entry says why it is not decided by
# authz. An entry for a route that no longer exists fails that test.
# ---------------------------------------------------------------------------

# Reachable with no session at all.
PUBLIC_ENDPOINTS = {
    "static": "The app's own static assets (CSS, JS, fonts, icons). No VA "
              "attachment is ever stored under app/static (attachment-storage.md); "
              "the probe asserts it.",
    "expo_client.expo_index": "Public Expo web-app shell; no case data.",
    "expo_client.expo_asset": "Public Expo bundle assets; no case data.",
    "api_v1.client_api.bootstrap": "Answers identity for the client shell: JSON 401 "
                                   "before any session metadata; authenticates, "
                                   "does not authorize.",
    "health.health_check": "Liveness probe; must answer before login.",
    "va_auth.va_login": "Sign-in form and its POST; cannot require a session.",
    "va_auth.va_login_password": "Two-step login, password step: guarded in body by "
                                 "the live pre-auth session state "
                                 "(authentication-factors.md section 1).",
    "va_auth.va_login_passkey_options": "Two-step login, passkey step: options carry "
                                        "no allowCredentials, identical for every "
                                        "account (section 1).",
    "va_auth.va_login_passkey_verify": "Two-step login, passkey verify: checks the "
                                       "credential belongs to the pre-auth account.",
    "va_auth.va_login_second_factor": "Two-step login, TOTP or recovery code: only "
                                      "after the password step set the pre-auth "
                                      "state (section 3).",
    "va_auth.va_login_redeem_code": "Sign-in code redeem: one-time code from a data "
                                    "manager, CAPTCHA-gated and rate-limited "
                                    "(mobile-sign-in.md section 3).",
    "va_auth.va_login_captcha_challenge": "CAPTCHA proof-of-work challenge; no user "
                                          "or session data.",
    "va_auth.va_logout": "Sign-out (POST); an anonymous POST is only a redirect.",
    "va_auth.site_maintenance_status": "Maintenance banner polled by the login page; "
                                       "no user or submission data.",
    "va_auth.forgot_password": "Password reset request; runs with no session.",
    "va_auth.reset_password": "Password reset link; reachable only with a signed token.",
    "va_auth.resend_verification": "Verification email resend; runs with no session.",
    "va_auth.verify_email": "Verification link; reachable only with a signed token.",
    "va_auth.factor_reset": "Break-glass factor reset link; single-use one-hour token "
                            "(authentication-factors.md section 8).",
    "va_main.va_index": "Public landing page; renders no user data.",
    "va_main.who_va_document": "Published WHO VA reference PDFs from a fixed registry.",
    "help.index": "Public help index; pages filtered per user in the body.",
    "help.page": "Public help page; role-restricted pages abort 403 in the body.",
    "help.docs_index": "Index of the curated, published engineering docs.",
    "help.doc_page": "One curated published doc; slug must be a registry key.",
    "help.va_code_mappings": "Published ICD-to-VA-cause reference data.",
    "help.va_code_mappings_csv": "Published ICD-to-VA-cause reference data (CSV).",
    "help.va_code_mappings_compare": "Published ICD-10 vs ICD-11 reference data.",
    "help.va_code_mappings_unmapped": "Published ICD-11 catalogue reference data.",
    "help.va_code_mappings_unmapped_csv": "Published ICD-11 catalogue reference data (CSV).",
    "help.icd_codes_search_demo": "Public help demo; same in-body role check as help.page.",
    "help.icd10_codes_browser": "Published ICD-10 reference browser.",
    "help.icd10_codes_browser_children": "Published ICD-10 reference browser.",
    "help.icd10_codes_browser_csv": "Published ICD-10 reference browser.",
    "help.icd10_codes_browser_node": "Published ICD-10 reference browser.",
    "help.icd10_codes_browser_search": "Published ICD-10 reference browser.",
    "help.icd11_codes_browser": "Published ICD-11 reference browser.",
    "help.icd11_codes_browser_children": "Published ICD-11 reference browser.",
    "help.icd11_codes_browser_csv": "Published ICD-11 reference browser.",
    "help.icd11_codes_browser_node": "Published ICD-11 reference browser.",
    "help.icd11_codes_browser_search": "Published ICD-11 reference browser.",
    "api_v1.device.enroll": "Device enrol: authenticates (one-time hashed enrolment "
                            "code), does not authorize; rate-limited.",
    "api_v1.device.open_session": "Device sign-in: authenticates (device secret, "
                                  "password, second factor), does not authorize.",
    "api_v1.device.refresh_session": "Device session refresh: authenticates (live "
                                     "refresh token, reuse revokes), does not authorize.",
}

# Signed in, but never another user's or any submission's data: the account's
# own settings and factors, reference data, or a page shell that renders no
# data. login_required authenticates; there is nothing for authz to decide.
SELF_SERVICE_ENDPOINTS = {
    "area.dashboard": "Area dashboard page shell: renders no data; every count comes "
                      "from /api/v1/area/*, which authz decides (effective_roles, "
                      "reachable_unit_ids). A user with no grant sees an empty page "
                      "(area-dashboard.md).",
    "profile.view": "The signed-in user's own profile page.",
    "profile.force_password_change": "The signed-in user's own forced password change.",
    "api_v1.profile_api.get_profile": "Own profile.",
    "api_v1.profile_api.accept_terms": "Own terms acceptance.",
    "api_v1.me_api.accept_terms": "Own terms acceptance (same view as profile's).",
    "api_v1.profile_api.dismiss_passkey_nudge": "Own UI preference.",
    "api_v1.profile_api.generate_password": "Own password.",
    "api_v1.profile_api.list_passkeys": "Own passkeys.",
    "api_v1.profile_api.passkey_registration_options": "Own passkeys.",
    "api_v1.profile_api.register_passkey": "Own passkeys.",
    "api_v1.profile_api.rename_passkey": "Own passkeys (scoped to the user in the body).",
    "api_v1.profile_api.revoke_passkey": "Own passkeys (scoped to the user in the body).",
    "api_v1.profile_api.reauth": "Own re-authentication.",
    "api_v1.profile_api.reauth_passkey": "Own re-authentication.",
    "api_v1.profile_api.reauth_passkey_options": "Own re-authentication.",
    "api_v1.profile_api.recovery_codes_regenerate": "Own recovery codes.",
    "api_v1.profile_api.recovery_codes_status": "Own recovery codes.",
    "api_v1.profile_api.totp_confirm": "Own TOTP factor.",
    "api_v1.profile_api.totp_enroll": "Own TOTP factor.",
    "api_v1.profile_api.totp_remove": "Own TOTP factor.",
    "api_v1.profile_api.totp_status": "Own TOTP factor.",
    "api_v1.profile_api.update_interviewer_profile": "Own year of birth and sex.",
    "api_v1.profile_api.update_timezone": "Own timezone.",
    "api_v1.device.accept_terms": "Own terms acceptance from the device; open before "
                                  "any role (onboarding policy 5.4).",
    "api_v1.device.end_session": "Own device sign-out; must work after a grant is "
                                 "withdrawn.",
    "api_v1.icd10_api.icd10_search": "ICD-10 reference search; the same data the public "
                                     "help browser serves.",
    "api_v1.instruments_api.instrument_translations": "Questionnaire strings of a "
                                                      "standard instrument; reference "
                                                      "data, no case data.",
}

EXEMPT_ENDPOINTS = frozenset(PUBLIC_ENDPOINTS) | frozenset(SELF_SERVICE_ENDPOINTS)


# ---------------------------------------------------------------------------
# The marker
# ---------------------------------------------------------------------------

def mark_consulted() -> None:
    """Record that authz decided something in this request."""
    if has_request_context():
        request.environ[_ENVIRON_KEY] = True


def consulted() -> bool | None:
    """True once authz decided in this request; False when a guarded view
    ran without it; None when no guarded view ran."""
    return request.environ.get(_ENVIRON_KEY)


def _refuse(endpoint: str) -> bool:
    """Whether the guarded view that just finished must be refused (and log
    it when it skipped authz)."""
    if request.environ.get(_ENVIRON_KEY) or not current_user.is_authenticated:
        return False
    log.warning(
        "authz not consulted: endpoint=%s user=%s method=%s",
        endpoint, getattr(current_user, "user_id", None), request.method,
    )
    return bool(current_app.config.get("AUTHZ_ENFORCE_CONSULTED"))


def _refusal():
    from app.decorators.role_required import API_PATH_PREFIXES

    if request.path.startswith(API_PATH_PREFIXES):
        return jsonify({"error": "Access denied.", "code": "forbidden"}), 403
    abort(403)


def _guard(endpoint: str, view):
    @wraps(view)
    def guarded(*args, **kwargs):
        request.environ[_ENVIRON_KEY] = False
        try:
            response = view(*args, **kwargs)
        except HTTPException as exc:
            # A refusal raised before authz ran (a route rate limit's 429,
            # say) exposes nothing; anything else unconsulted is a gap.
            if exc.code not in _REFUSALS and _refuse(endpoint):
                return _refusal()
            raise
        if _refuse(endpoint):
            return _refusal()
        return response

    return guarded


def install(app) -> None:
    """Wrap every registered non-exempt view. Call once, after every
    blueprint is registered (create_app)."""
    for endpoint, view in list(app.view_functions.items()):
        if endpoint not in EXEMPT_ENDPOINTS:
            app.view_functions[endpoint] = _guard(endpoint, view)
