"""Access-grant serializers."""


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
