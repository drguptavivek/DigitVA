import sqlalchemy as sa
from app import db
from app.models import VaResearchProjects
from app.utils import validate_project_code


def va_researchproject_updateproject(
    project_id, project_name=None, project_nickname=None, project_code=None
):
    session = db.session
    va_researchproject = session.scalars(
        sa.select(VaResearchProjects).where(VaResearchProjects.project_id == project_id)
    ).first()
    if not va_researchproject:
        print(f"Failed [Research project '{project_id}' not found.]")
        return
    if project_name:
        va_researchproject.project_name = project_name
    if project_nickname:
        va_researchproject.project_nickname = project_nickname
    if project_code:
        if validate_project_code(project_code):
            va_researchproject.project_code = project_code
        else:
            return
    session.commit()
    print(f"Success [Research project '{project_id}' updated.]")
