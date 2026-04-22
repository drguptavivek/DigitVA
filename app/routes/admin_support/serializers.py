def serialize_user(user):
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "status": user.user_status.value,
        "email_verified": bool(user.email_verified),
        "phone": user.phone,
        "landing_page": user.landing_page,
        "languages": user.vacode_language or [],
        "is_admin": user.is_admin(),
    }


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


def serialize_site(site):
    return {
        "site_id": site.site_id,
        "site_name": site.site_name,
        "site_abbr": site.site_abbr,
        "status": site.site_status.value,
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


def serialize_grant(row):
    return {
        "grant_id": str(row.grant_id),
        "user_id": str(row.user_id),
        "user_email": row.email,
        "user_name": row.name,
        "role": row.role.value,
        "scope_type": row.scope_type.value,
        "project_id": row.resolved_project_id,
        "site_id": row.resolved_site_id,
        "project_site_id": str(row.project_site_id) if row.project_site_id else None,
        "status": row.grant_status.value,
        "notes": row.notes,
    }


def serialize_odk_connection(conn, project_ids: list[str], guard: dict) -> dict:
    return {
        "connection_id": str(conn.connection_id),
        "connection_name": conn.connection_name,
        "base_url": conn.base_url,
        "status": conn.status.value,
        "notes": conn.notes or "",
        "project_ids": project_ids,
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
        "guard": guard,
    }
