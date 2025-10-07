from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup


def va_odk_submissionupdatedate(va_form):
    client = va_odk_clientsetup()
    try:
        submissions = client.submissions.get_table(
            project_id=va_form.odk_project_id,
            form_id=va_form.odk_form_id,
            select="__id,__system/updatedAt",
        ).get("value")
        processed_data = {}
        for submission in submissions:
            processed_data[submission.get("__id")] = submission.get("__system").get(
                "updatedAt"
            )
        return processed_data
    except Exception as e:
        raise Exception(
            f"Failed to fetch update dates for submissions in ODK VA form: {va_form.form_id}: {str(e)}"
        )
