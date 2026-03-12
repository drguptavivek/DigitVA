from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup


def va_odk_submissioncount(odk_project_id: int, odk_form_id: str) -> int:
    """Return total submission count from ODK Central for a given project/form.

    Uses the OData $count endpoint — downloads no submission data.
    """
    client = va_odk_clientsetup()
    try:
        result = client.submissions.get_table(
            project_id=odk_project_id,
            form_id=odk_form_id,
            top=0,
            count=True,
        )
        return int(result.get("@odata.count") or 0)
    except Exception as e:
        raise Exception(
            f"Failed to fetch submission count from ODK "
            f"(project {odk_project_id}, form {odk_form_id}): {str(e)}"
        )
