"""Device enrolment, interviewer device sessions and bearer-token resolution.

Baseline: docs/policy/field-data-collection.md ("Path B design"); design and
API contract: .tasks/2026-09-30-android-collection-app.md. Routes:
app/routes/api/auth.py (sign-in API) and app/routes/admin_devices.py
(enrolment codes, device list, revoke).

Credentials. Enrolment codes, device secrets and access/refresh tokens are
``secrets.token_urlsafe(32)`` (256 bits). Only their SHA-256 hex digest is
stored: a slow hash buys nothing against a 256-bit random value, and a
digest lets every lookup be an indexed equality. The device secret is
compared with ``hmac.compare_digest``.

Sessions. One row per (device, interviewer) sign-in. The access token lives
``ACCESS_TTL``; the refresh token rotates on every use and its lifetime
slides (``DEVICE_REFRESH_TTL_DAYS``, proposed decision C1: 30 days), capped
at ``DEVICE_SESSION_MAX_DAYS`` from sign-in. A refresh must also present the
session's device id and secret. Presenting any of the last
``RETIRED_REFRESH_KEEP`` rotated-away refresh tokens is reuse and revokes the
session; the refusal code (``refresh_reused``, or ``refresh_retry_race``
inside ``REFRESH_RETRY_GRACE`` of the rotation) is distinct from
``session_revoked``, which the app treats as "wipe this interviewer's store"
and so is reserved for an administrative revoke, a withdrawn grant or a
changed account. Grant, device, project and account checks run at
sign-in and at every refresh; the per-request access-token check covers the
account (active, session version) and the device, so a withdrawn grant (the
worker holds no interviewer, coder, coding_tester or reviewer access left) ends
the session at the next refresh, within ``ACCESS_TTL``.

Native sign-in uses the account password after device authentication. TOTP and
recovery records remain historical compatibility data and are not consulted by
this flow.

Nothing here logs a token, secret, code, email or password.

Layout (bead digitva-r8nh.17). This module is the public face: every
caller imports through it and tests patch names on it. The code lives in
``app/services/device/`` by concern (see its ``__init__``); names a test
patches here are read back through ``device.facade()``, so patching this
module still reaches them.
"""

from app.services.device.demo_enrolment import (
    _check_demo_device_cap,
    _demo_code_hash,
    enrol_demo_device,
)
from app.services.device.eligibility import (
    _DEVICE_CODING_ROLES,
    _default_home_project,
    _eligible_projects,
    _native_grant_projects,
    _native_grants,
    _no_access_error,
    _project_active,
    eligible_device_projects,
    has_device_access,
)
from app.services.device.enrolment import (
    _PLAIN_HTTP_HOSTS,
    ENROLMENT_DEFAULT_MINUTES,
    ENROLMENT_MAX_MINUTES,
    ENROLMENT_MAX_USES,
    _bounded_int,
    _insecure_device_url_allowed,
    create_enrolment_code,
    device_public_url_problem,
    enrol_device,
    enrol_with_password,
    enrolment_qr_payload,
)
from app.services.device.outstanding_work import (
    OUTSTANDING_MAX_IDS,
    _uuid_list,
    record_outstanding,
)
from app.services.device.registry import (
    _APP_VERSION_MAX,
    _DEVICE_NAME_MAX,
    _PLATFORMS,
    _add_device,
    _clean_text,
    _device_fields,
    _get_device,
    _station_state,
    device_for_client_uuid,
    list_project_devices,
    parse_client_device_uuid,
    record_app_version,
    revoke_device,
    set_device_project,
)
from app.services.device.sessions import (
    _DUMMY_PASSWORD_HASH,
    _KEEP_DATA_REASONS,
    _REUSE_REASONS,
    DEVICE_LIMIT_MESSAGE,
    LAST_SEEN_INTERVAL,
    MAX_ACTIVE_USER_DEVICES,
    REFRESH_RETRY_GRACE,
    RETIRED_REFRESH_KEEP,
    _authenticate_device,
    _check_credentials,
    _create_session,
    _device_by_secret,
    _end_existing_pair_sessions,
    _issue,
    _live_session,
    _open_authorized_session,
    _refuse,
    _revoke,
    _revoked_error,
    _session_still_allowed,
    _sign_in_failed,
    _sign_in_user,
    check_device_slot,
    decommission_account_device,
    end_session,
    list_account_devices,
    live_session_clauses,
    open_session,
    record_profile_deletion,
    refresh_session,
    resolve_access_token,
)
from app.services.device.tokens import (
    ACCESS_TTL,
    API_V1_PREFIX,
    DEFAULT_REFRESH_TTL_DAYS,
    DEFAULT_SESSION_MAX_DAYS,
    UNAUTHENTICATED_ENDPOINTS,
    DeviceAuthError,
    IssuedTokens,
    _new_secret,
    _now,
    _refresh_ttl,
    _session_max_age,
    hash_token,
    log,
    request_bearer_token,
    serialize_tokens,
)
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff

__all__ = [
    "ACCESS_TTL",
    "API_V1_PREFIX",
    "DEFAULT_REFRESH_TTL_DAYS",
    "DEFAULT_SESSION_MAX_DAYS",
    "DEVICE_LIMIT_MESSAGE",
    "DeviceAuthError",
    "ENROLMENT_DEFAULT_MINUTES",
    "ENROLMENT_MAX_MINUTES",
    "ENROLMENT_MAX_USES",
    "IssuedTokens",
    "LAST_SEEN_INTERVAL",
    "MAX_ACTIVE_USER_DEVICES",
    "OUTSTANDING_MAX_IDS",
    "REFRESH_RETRY_GRACE",
    "RETIRED_REFRESH_KEEP",
    "UNAUTHENTICATED_ENDPOINTS",
    "_APP_VERSION_MAX",
    "_DEVICE_CODING_ROLES",
    "_DEVICE_NAME_MAX",
    "_DUMMY_PASSWORD_HASH",
    "_KEEP_DATA_REASONS",
    "_PLAIN_HTTP_HOSTS",
    "_PLATFORMS",
    "_REUSE_REASONS",
    "_add_device",
    "_authenticate_device",
    "_bounded_int",
    "_check_credentials",
    "_check_demo_device_cap",
    "_clean_text",
    "_create_session",
    "_default_home_project",
    "_demo_code_hash",
    "_device_by_secret",
    "_device_fields",
    "_eligible_projects",
    "_end_existing_pair_sessions",
    "_get_device",
    "_insecure_device_url_allowed",
    "_issue",
    "_live_session",
    "_native_grant_projects",
    "_native_grants",
    "_new_secret",
    "_no_access_error",
    "_now",
    "_open_authorized_session",
    "_project_active",
    "_refresh_ttl",
    "_refuse",
    "_revoke",
    "_revoked_error",
    "_session_max_age",
    "_session_still_allowed",
    "_sign_in_failed",
    "_sign_in_user",
    "_station_state",
    "_uuid_list",
    "check_device_slot",
    "create_enrolment_code",
    "decommission_account_device",
    "device_for_client_uuid",
    "device_public_url_problem",
    "eligible_device_projects",
    "end_session",
    "enrol_demo_device",
    "enrol_device",
    "enrol_with_password",
    "enrolment_qr_payload",
    "has_device_access",
    "hash_token",
    "list_account_devices",
    "list_project_devices",
    "live_session_clauses",
    "log",
    "open_session",
    "parse_client_device_uuid",
    "record_app_version",
    "record_outstanding",
    "record_profile_deletion",
    "refresh_session",
    "request_bearer_token",
    "resolve_access_token",
    "revoke_device",
    "serialize_tokens",
    "set_device_project",
    "should_block_non_admin_after_cutoff",
]
