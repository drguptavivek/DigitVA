from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

_TIMEOUT_SECONDS = 15


def va_odk_submissioncount(
    odk_project_id: int,
    odk_form_id: str,
    app_project_id: str | None = None,
) -> int:
    """Return total submission count from ODK Central for a given project/form.

    Uses the OData $count endpoint — downloads no submission data.

    Pass app_project_id (e.g. "UNSW01") to resolve the DB-configured
    connection rather than falling back to the legacy TOML.
    A hard timeout of _TIMEOUT_SECONDS is applied so a slow/unreachable
    ODK server does not block the caller indefinitely.
    """
    client = va_odk_clientsetup(project_id=app_project_id)

    def _fetch():
        return client.submissions.get_table(
            project_id=odk_project_id,
            form_id=odk_form_id,
            top=0,
            count=True,
        )

    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_fetch)
        try:
            result = future.result(timeout=_TIMEOUT_SECONDS)
            return int(result.get("@odata.count") or 0)
        except FuturesTimeout:
            raise Exception(
                f"ODK server did not respond within {_TIMEOUT_SECONDS}s "
                f"(project {odk_project_id}, form {odk_form_id})"
            )
        except Exception as e:
            raise Exception(
                f"ODK error (project {odk_project_id}, form {odk_form_id}): {str(e)}"
            )
