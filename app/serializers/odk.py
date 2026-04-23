"""ODK connection serializers."""


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
