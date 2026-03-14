import logging
import threading
from datetime import datetime, timezone

from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15


def va_odk_delta_count(
    odk_project_id: int,
    odk_form_id: str,
    since: datetime,
    app_project_id: str | None = None,
) -> int:
    """Return count of submissions created or updated after `since`.

    Calls OData with:
      $filter=(__system/submissionDate gt 2026-03-14T06:56:35.000Z)
           or (__system/updatedAt gt 2026-03-14T06:56:35.000Z)
      &$top=0&$count=true

    `since` MUST be a timezone-aware datetime (UTC). ODK evaluates only the
    filter predicate — no submission data is serialised or transferred.
    A bare date string (e.g. "2026-03-14") would be treated as midnight UTC
    by ODK, silently missing same-day submissions. Always pass a full datetime.

    Returns @odata.count. Raises on HTTP error or timeout so the caller can
    decide whether to fall through to a full download.
    """
    if since.tzinfo is None:
        raise ValueError("va_odk_delta_count: `since` must be timezone-aware (UTC)")

    since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    odata_filter = (
        f"(__system/submissionDate gt {since_str})"
        f" or (__system/updatedAt gt {since_str})"
    )

    client = va_odk_clientsetup(project_id=app_project_id)

    result: list = [None]
    error: list = [None]

    def _fetch():
        try:
            url = f"projects/{odk_project_id}/forms/{odk_form_id}.svc/Submissions"
            response = client.session.get(
                url,
                params={"$filter": odata_filter, "$top": 0, "$count": "true"},
            )
            if response.status_code not in (200, 201):
                raise Exception(
                    f"ODK API returned HTTP {response.status_code}: {response.text[:200]}"
                )
            data = response.json()
            count = int(data.get("@odata.count") or 0)
            log.info(
                "ODK deltaCount project=%s form=%s since=%s: %d",
                odk_project_id, odk_form_id, since_str, count,
            )
            result[0] = count
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=_TIMEOUT_SECONDS)

    if t.is_alive():
        raise Exception(
            f"ODK delta check did not respond within {_TIMEOUT_SECONDS}s "
            f"(project {odk_project_id}, form {odk_form_id})"
        )
    if error[0] is not None:
        raise Exception(
            f"ODK delta check error (project {odk_project_id}, form {odk_form_id}): {error[0]}"
        )
    return result[0]
