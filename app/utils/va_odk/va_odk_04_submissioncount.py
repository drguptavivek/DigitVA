import logging
import threading

from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15


def va_odk_submissioncount(
    odk_project_id: int,
    odk_form_id: str,
    app_project_id: str | None = None,
) -> int:
    """Return total submission count from ODK Central for a given project/form.

    Uses the OData submissions endpoint with $count=true&$top=0, which returns
    @odata.count without fetching any submission records.

    Pass app_project_id (e.g. "UNSW01") to resolve the DB-configured
    connection rather than falling back to the legacy TOML.

    A daemon thread enforces a hard timeout of _TIMEOUT_SECONDS so a
    slow or unreachable ODK server cannot block the caller indefinitely.
    Daemon threads do not prevent the process from exiting.
    """
    client = va_odk_clientsetup(project_id=app_project_id)

    result: list = [None]
    error: list = [None]

    def _fetch():
        try:
            url = f"projects/{odk_project_id}/forms/{odk_form_id}.svc/Submissions"
            response = client.session.get(url, params={"$top": 0, "$count": "true"})
            if response.status_code != 200:
                raise Exception(
                    f"ODK API returned HTTP {response.status_code}: {response.text[:200]}"
                )
            data = response.json()
            count = int(data.get("@odata.count") or 0)
            log.info(
                "ODK submissionCount project=%s form=%s: %d",
                odk_project_id, odk_form_id, count,
            )
            result[0] = count
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=_TIMEOUT_SECONDS)

    if t.is_alive():
        raise Exception(
            f"ODK server did not respond within {_TIMEOUT_SECONDS}s "
            f"(project {odk_project_id}, form {odk_form_id})"
        )
    if error[0] is not None:
        raise Exception(
            f"ODK error (project {odk_project_id}, form {odk_form_id}): {error[0]}"
        )
    return result[0]
