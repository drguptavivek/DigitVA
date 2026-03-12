import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

log = logging.getLogger("ERROR_LOG")

_TIMEOUT_SECONDS = 15


def va_odk_submissioncount(
    odk_project_id: int,
    odk_form_id: str,
    app_project_id: str | None = None,
) -> int:
    """Return total submission count from ODK Central for a given project/form.

    Uses the lightweight ODK Central form metadata endpoint with
    X-Extended-Metadata: true, which returns submissionCount directly.
    This is cheaper than the OData $count endpoint which processes submissions.

    Pass app_project_id (e.g. "UNSW01") to resolve the DB-configured
    connection rather than falling back to the legacy TOML.
    A hard timeout of _TIMEOUT_SECONDS is applied so a slow/unreachable
    ODK server does not block the caller indefinitely.
    """
    client = va_odk_clientsetup(project_id=app_project_id)

    def _fetch():
        url = f"v1/projects/{odk_project_id}/forms/{odk_form_id}"
        response = client.session.get(url, headers={"X-Extended-Metadata": "true"})
        if response.status_code != 200:
            raise Exception(
                f"ODK API returned HTTP {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        count = data.get("submissionCount")
        log.info(
            "ODK submissionCount for project=%s form=%s: %s",
            odk_project_id, odk_form_id, count,
        )
        return int(count or 0)

    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_fetch)
        try:
            return future.result(timeout=_TIMEOUT_SECONDS)
        except FuturesTimeout:
            raise Exception(
                f"ODK server did not respond within {_TIMEOUT_SECONDS}s "
                f"(project {odk_project_id}, form {odk_form_id})"
            )
        except Exception as e:
            raise Exception(
                f"ODK error (project {odk_project_id}, form {odk_form_id}): {str(e)}"
            )
