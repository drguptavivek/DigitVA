"""Registration-only, identity-free refusal receipt."""
from flask import g, jsonify
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app import db
from app.decorators import role_required
from app.routes.api.intake import _site_id, bp
from app.routes.api.request_helpers import parse_body, request_project_id
from app.services import registration_refusal_service as service
from app.services.authz.actions import DEATH_REGISTERING_ROLES


@bp.post("/refusals")
@role_required("interviewer", "death_reporter")
def registration_refusal():
    body = parse_body()
    project = request_project_id(body, roles=DEATH_REGISTERING_ROLES)
    site = _site_id(body)
    channel = "device" if g.get("device_session") is not None else "web"
    try:
        created = service.record(current_user, body, project, site, channel)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        created = service.record(current_user, body, project, site, channel)
        db.session.commit()
    return jsonify({"client_draft_id": body["client_draft_id"]}), 201 if created else 200
