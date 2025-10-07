from app.services.va_site.va_site_01_addsite import va_site_addsite


def va_db_initialise_researchsites():
    va_site_addsite(
        site_id="NC01",
        project_id="UNSW01",
        site_name="All India Institute Of Medical Sciences, New Delhi",
        site_abbr="AIIMS, New Delhi",
    )
    va_site_addsite(
        site_id="KA01",
        project_id="UNSW01",
        site_name="K.L.E. Academy of Higher Education & Research, Belagavi",
        site_abbr="KLE, Belagavi",
    )
    va_site_addsite(
        site_id="KL01",
        project_id="UNSW01",
        site_name="Sree Chitra Tirunal Institute for Medical Sciences and Technology, Trivandrum",
        site_abbr="SCTIMST, Trivandrum",
    )
    va_site_addsite(
        site_id="TR01",
        project_id="UNSW01",
        site_name="Agartala Government Medical College, Tripura",
        site_abbr="AGMC, Tripura",
    )
