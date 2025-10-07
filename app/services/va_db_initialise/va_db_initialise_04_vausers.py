from app.services.va_user.va_user_01_create import va_user_create


def va_db_initialise_vausers():
    va_user_create(
        name="Tenam Sobti",
        email="sobti.tenam@gmail.com",
        password="HelloTenam",
        vacode_language=["english", "hindi"],
        landing_page="coder",
        permission_coder=["UNSW01NC0101"],
    )
    va_user_create(
        name="Dr. Apoorva",
        email="apoorva.sindhu@yahoo.com",
        password="pilotnc01",
        vacode_language=["english", "hindi"],
        landing_page="coder",
        permission_coder=["UNSW01NC0101"],
    )
    va_user_create(
        name="Dr. Anand",
        email="anand.drk@gmail.com",
        password="aiimsccm",
        vacode_language=["english", "hindi"],
        landing_page="coder",
        permission_coder=["UNSW01NC0101"],
    )
    va_user_create(
        name="Dr. Biju Soman",
        email="bijusoman@sctimst.ac.in",
        password="pilotkl01",
        vacode_language=["english", "malayalam"],
        landing_page="coder",
        permission_coder=["UNSW01KL0101"],
    )
    va_user_create(
        name="Dr. Mubashir",
        email="drmubi@gmail.com",
        password="pilotka01",
        vacode_language=["english", "hindi", "marathi", "kannada"],
        landing_page="coder",
        permission_coder=["UNSW01KA0101"],
    )
    va_user_create(
        name="Dr. Subrata",
        email="drsubratabaidya@gmail.com",
        password="pilottr01",
        vacode_language=["english", "bangla"],
        landing_page="coder",
        permission_coder=["UNSW01TR0101"],
    )