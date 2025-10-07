from app import db
from app.models import VaResearchProjects
from app.utils import validate_project_id, validate_project_code


def va_researchproject_addproject(
    project_id, project_name, project_nickname, project_code=None
):
    session = db.session
    if not all(
        [
            validate_project_id(project_id, session, False),
            validate_project_code(project_code),
        ]
    ):
        return
    data = {
        "project_id": project_id,
        "project_name": project_name,
        "project_nickname": project_nickname,
    }
    if project_code:
        data["project_code"] = project_code
    research_project = VaResearchProjects(**data)
    session.add(research_project)
    session.commit()
    print(f"Success [Research project '{project_id}' added.]")
