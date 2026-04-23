"""Project and project-site serializers."""


def serialize_project(project):
    return {
        "project_id": project.project_id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "project_nickname": project.project_nickname,
        "status": project.project_status.value,
        "narrative_qa_enabled": project.narrative_qa_enabled,
        "social_autopsy_enabled": project.social_autopsy_enabled,
        "coding_intake_mode": project.coding_intake_mode,
        "demo_training_enabled": project.demo_training_enabled,
        "demo_retention_minutes": project.demo_retention_minutes,
    }


def serialize_project_site(row):
    return {
        "project_site_id": str(row.project_site_id),
        "project_id": row.project_id,
        "site_id": row.site_id,
        "project_name": row.project_name,
        "site_name": row.site_name,
        "status": row.project_site_status.value,
        "coding_enabled": row.coding_enabled,
        "coding_start_date": row.coding_start_date.isoformat() if row.coding_start_date else None,
        "coding_end_date": row.coding_end_date.isoformat() if row.coding_end_date else None,
        "daily_coder_limit": row.daily_coder_limit,
    }
