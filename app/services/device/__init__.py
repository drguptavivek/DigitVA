"""Device enrolment, sessions and bearer tokens, split by concern (bead
digitva-r8nh.17). ``app.services.device_auth_service`` stays the one public
module: callers import through it and tests patch names on it.

- ``tokens``: bearer parsing, token hashing and issue primitives, ``DeviceAuthError``
- ``eligibility``: which grants open the app and which projects may be home
- ``registry``: device rows: fields, insert, home project, revoke, admin list
- ``sessions``: sign-in, device cap, refresh, sign-out, access-token resolution
- ``enrolment``: enrolment codes and QR, code and password enrolment
- ``demo_enrolment``: public-demo enrolment without a code
- ``outstanding_work``: the device's unsent-work report
"""


def facade():
    """The ``device_auth_service`` module, looked up at call time. Code here
    reads the names tests patch on it (``has_device_access``,
    ``_create_session``, ``should_block_non_admin_after_cutoff``,
    ``MAX_ACTIVE_USER_DEVICES``, ``_insecure_device_url_allowed``) through
    this, so such a patch still reaches them. Imported lazily: the facade
    imports these modules."""
    from app.services import device_auth_service

    return device_auth_service
