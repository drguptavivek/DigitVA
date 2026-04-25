"""Project-level coding intake mode helpers.

Intake mode controls how a coder enters work. It is not a submission workflow
state and must remain separate from the submission state machine.
"""

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaProjectMaster


CODING_INTAKE_RANDOM = "random_form_allocation"
CODING_INTAKE_PICK = "pick_and_choose"
CODING_INTAKE_MODES = {
    CODING_INTAKE_RANDOM,
    CODING_INTAKE_PICK,
}


def get_project_coding_intake_mode(project_id: str | None) -> str:
    """Return the configured project-level coding intake mode."""
    if not project_id:
        return CODING_INTAKE_RANDOM
    project = db.session.get(VaProjectMaster, project_id)
    if not project or not project.coding_intake_mode:
        return CODING_INTAKE_RANDOM
    if project.coding_intake_mode not in CODING_INTAKE_MODES:
        return CODING_INTAKE_RANDOM
    return project.coding_intake_mode


def get_project_coding_intake_modes(project_ids: list[str] | set[str]) -> dict[str, str]:
    """Return configured coding intake mode per project id with safe defaults."""
    if not project_ids:
        return {}

    rows = db.session.execute(
        sa.select(VaProjectMaster.project_id, VaProjectMaster.coding_intake_mode).where(
            VaProjectMaster.project_id.in_(project_ids)
        )
    ).all()
    resolved = {
        project_id: (
            coding_intake_mode
            if coding_intake_mode in CODING_INTAKE_MODES
            else CODING_INTAKE_RANDOM
        )
        for project_id, coding_intake_mode in rows
    }
    for project_id in project_ids:
        resolved.setdefault(project_id, CODING_INTAKE_RANDOM)
    return resolved


def split_form_ids_by_coding_intake_mode(form_ids: list[str] | set[str]) -> tuple[set[str], set[str]]:
    """Split accessible form ids into random-allocation and pick-and-choose sets."""
    if not form_ids:
        return set(), set()

    rows = db.session.execute(
        sa.select(VaForms.form_id, VaForms.project_id).where(VaForms.form_id.in_(form_ids))
    ).all()
    project_modes = get_project_coding_intake_modes(
        [project_id for _, project_id in rows if project_id]
    )
    random_form_ids = {
        form_id
        for form_id, project_id in rows
        if project_modes.get(project_id, CODING_INTAKE_RANDOM) == CODING_INTAKE_RANDOM
    }
    pick_form_ids = {
        form_id
        for form_id, project_id in rows
        if project_modes.get(project_id, CODING_INTAKE_RANDOM) == CODING_INTAKE_PICK
    }
    return random_form_ids, pick_form_ids
