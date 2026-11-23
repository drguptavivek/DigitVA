"""The device's report of unsent work for its interviewer. Part of
``device_auth_service``."""

from __future__ import annotations

import uuid

from app.models import AuthDeviceSession
from app.services.device.tokens import DeviceAuthError, _now

OUTSTANDING_MAX_IDS = 1000


def _uuid_list(values, name: str) -> list[str]:
    """*values* (None, or a list of at most OUTSTANDING_MAX_IDS UUID strings)
    sorted and normalised, else 400."""
    if values is None:
        return []
    try:
        if (
            not isinstance(values, list)
            or len(values) > OUTSTANDING_MAX_IDS
            or not all(isinstance(value, str) for value in values)
        ):
            raise ValueError
        return sorted({str(uuid.UUID(value)) for value in values})
    except ValueError:
        raise DeviceAuthError(
            f"{name} must be a list of at most {OUTSTANDING_MAX_IDS} UUIDs.", "invalid_request", 400
        ) from None


def record_outstanding(session: AuthDeviceSession, count, unique_ids, client_draft_ids=None,
                       client_death_ids=None) -> None:
    """Store the device's report of unsent work for this interviewer.
    ``count`` a whole number >= 0 (unsent interviews); ``unique_ids`` a list
    of case ids (text, at most 64 characters each, at most
    OUTSTANDING_MAX_IDS); ``client_draft_ids`` the app's draft UUIDs and
    ``client_death_ids`` its offline registrations not yet uploaded (UUIDs,
    same bound). Caller commits."""
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100_000:
        raise DeviceAuthError("count must be a whole number of at least 0.", "invalid_request", 400)
    if unique_ids is None:
        unique_ids = []
    if (
        not isinstance(unique_ids, list)
        or len(unique_ids) > OUTSTANDING_MAX_IDS
        or not all(isinstance(u, str) and 0 < len(u) <= 64 for u in unique_ids)
    ):
        raise DeviceAuthError(
            f"unique_ids must be a list of at most {OUTSTANDING_MAX_IDS} ids.", "invalid_request", 400
        )
    draft_ids = _uuid_list(client_draft_ids, "client_draft_ids")
    death_ids = _uuid_list(client_death_ids, "client_death_ids")
    session.outstanding_count = count
    session.outstanding_unique_ids = sorted(set(unique_ids))
    session.outstanding_client_draft_ids = draft_ids
    session.outstanding_client_death_ids = death_ids
    session.outstanding_reported_at = _now()
