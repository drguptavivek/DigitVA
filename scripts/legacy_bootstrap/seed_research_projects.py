from app.services.projects.research_projects import va_researchproject_addproject


def va_db_initialise_researchprojects():
    va_researchproject_addproject(
        project_id="UNSW01",
        project_name="Using Digital Solutions To Improve Cause Of Death Data In India",
        project_nickname="UNSW - VA DigitalSolutions",
        project_code="N2438",
    )
