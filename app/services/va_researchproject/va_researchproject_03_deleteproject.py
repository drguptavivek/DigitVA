import sqlalchemy as sa
from app import db
from app.models import VaResearchProjects, VaStatuses


def va_researchproject_deleteproject(project_id):
    session = db.session
    va_research_project = session.scalars(
        sa.select(VaResearchProjects).where(VaResearchProjects.project_id == project_id)
    ).first()
    if not va_research_project:
        print(f"Failed [Project '{project_id}' not found.]")
        return
    va_research_project.project_status = VaStatuses.deactive
    session.commit()
    print(f"Success [Deleted project '{project_id}'.]")
