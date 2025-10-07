from app.services.va_form.va_form_01_addform import va_form_addform


def va_db_initialise_vaforms():
    va_form_addform(
        form_id="UNSW01NC0101",
        project_id="UNSW01",
        site_id="NC01",
        odk_form_id="NC01_DS_WHOVA2022",
        odk_project_id="3",
        form_type="WHO VA 2022",
    )
    va_form_addform(
        form_id="UNSW01KA0101",
        project_id="UNSW01",
        site_id="KA01",
        odk_form_id="KA01_DS_WHOVA2022",
        odk_project_id="5",
        form_type="WHO VA 2022",
    )
    va_form_addform(
        form_id="UNSW01KL0101",
        project_id="UNSW01",
        site_id="KL01",
        odk_form_id="KL01_DS_WHOVA2022",
        odk_project_id="4",
        form_type="WHO VA 2022",
    )
    va_form_addform(
        form_id="UNSW01TR0101",
        project_id="UNSW01",
        site_id="TR01",
        odk_form_id="TR01_DS_WHOVA2022",
        odk_project_id="6",
        form_type="WHO VA 2022",
    )
