"""Email a new data collector the app enrolment QR (digitva-o0nq).

Baseline: docs/policy/mobile-sign-in.md section 6. The QR is the Devices
page's: a project enrolment code from device_auth_service, its payload from
``enrolment_qr_payload``. The code is a credential, so the email goes out
synchronously after the caller's commit, never through Celery.
"""

import logging
from urllib.parse import urlparse

from flask import current_app

from app import db
from app.services import device_auth_service as devices
from app.services import email_service
from app.services.totp_service import provisioning_qr_png

log = logging.getLogger(__name__)

DATA_COLLECTOR_ROLES = frozenset({"interviewer", "death_reporter"})
#: 24 hours, one device: inside the Devices page's 5 minutes to 7 days.
ENROLMENT_EMAIL_MINUTES = 24 * 60
SEND_FAILED_WARNING = "Enrolment email could not be sent."


def valid_android_apk_url() -> str | None:
    """Return the configured APK URL only when it is a credential-free HTTPS URL."""
    value = (current_app.config.get("DIGITVA_ANDROID_APK_URL") or "").strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return value


def newly_collecting_user_ids(changed_grants) -> list:
    """User ids that gained or regained a data-collector grant, from the
    ``(grant_dict, action)`` audit list the worker save already builds. An
    unchanged grant is not in that list, so a plain re-save sends nothing."""
    ids = []
    for grant, action in changed_grants:
        if (
            grant["role"] in DATA_COLLECTOR_ROLES
            and action in ("grant_created", "grant_reactivated")
            and grant["user_id"] not in ids
        ):
            ids.append(grant["user_id"])
    return ids


def send_enrolment_email(project_id: str, user, *, actor) -> str:
    """Issue a 24-hour single-use enrolment code for *project_id*, commit it,
    and email *user* its QR. Call after the save's own commit.

    Returns ``"sent"``, ``"no_email"`` (nothing to send to; the Devices page
    QR remains) or ``"failed"``. Never raises: a failure is logged with ids
    only and the caller shows SEND_FAILED_WARNING.
    """
    if not user.email:
        return "no_email"
    user_id = user.user_id
    if not email_service.can_deliver_to(user.email):
        log.warning("enrolment email not sent: mail unavailable | project=%s user_id=%s", project_id, user_id)
        return "failed"
    try:
        row, code = devices.create_enrolment_code(
            project_id, actor=actor, expires_in_minutes=ENROLMENT_EMAIL_MINUTES, max_uses=1,
            subject_user_id=user_id,
        )
        db.session.commit()
    except devices.DeviceAuthError as exc:
        db.session.rollback()
        log.warning("enrolment email not sent: %s | project=%s user_id=%s", exc.code, project_id, user_id)
        return "failed"
    apk_url = valid_android_apk_url()
    if apk_url is None:
        log.warning("enrolment email without APK link: DIGITVA_ANDROID_APK_URL unset or invalid | project=%s", project_id)
    try:
        email_service.send_enrolment_email(
            user,
            code=code,
            qr_png=provisioning_qr_png(devices.enrolment_qr_payload(row, code)),
            apk_url=apk_url,
        )
    except Exception as exc:  # SMTP text can carry the address: log the type only
        log.warning("enrolment email send failed: %s | project=%s user_id=%s", type(exc).__name__, project_id, user_id)
        return "failed"
    return "sent"
