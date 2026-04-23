"""Mapping-oriented COD bucket routes."""

import re
import uuid

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MapIcdCodBucket, MasCodBucketNode
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.services.cod_bucket_mapping_service import (
    NODE_TYPE_FIELD,
    get_cod_bucket_scheme,
)

from .common import _cod_bucket_node_path_label


@admin.patch("/api/cod-bucket-schemes/<scheme_code>/mappings/<uuid:mapping_id>")
@role_required("admin")
def admin_cod_bucket_scheme_update_mapping(scheme_code, mapping_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    scheme = get_cod_bucket_scheme(scheme_code)
    if scheme is None:
        return _json_error("COD bucket scheme not found.", 404)

    mapping = db.session.get(MapIcdCodBucket, mapping_id)
    if mapping is None or mapping.scheme_id != scheme.scheme_id:
        return _json_error("COD bucket mapping not found.", 404)

    data = request.get_json(silent=True) or {}
    node_id_raw = (data.get("node_id") or "").strip()
    if not node_id_raw:
        return _json_error("node_id is required.", 400)
    try:
        node_id = uuid.UUID(node_id_raw)
    except ValueError:
        return _json_error("node_id must be a valid UUID.", 400)

    node = db.session.get(MasCodBucketNode, node_id)
    if (
        node is None
        or node.scheme_id != scheme.scheme_id
        or node.node_type != NODE_TYPE_FIELD
        or node.age_scope != mapping.age_scope
    ):
        return _json_error(
            "Target disease node not found for this scheme and age scope.",
            404,
        )

    mapping.node_id = node.node_id
    db.session.commit()
    return jsonify(
        {
            "mapping": {
                "mapping_id": str(mapping.mapping_id),
                "icd_code": mapping.icd_code,
                "node_id": str(mapping.node_id),
                "path_label": _cod_bucket_node_path_label(node),
            }
        }
    )


@admin.delete("/api/cod-bucket-schemes/<scheme_code>/mappings/<uuid:mapping_id>")
@role_required("admin")
def admin_cod_bucket_scheme_delete_mapping(scheme_code, mapping_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    scheme = get_cod_bucket_scheme(scheme_code)
    if scheme is None:
        return _json_error("COD bucket scheme not found.", 404)

    mapping = db.session.get(MapIcdCodBucket, mapping_id)
    if mapping is None or mapping.scheme_id != scheme.scheme_id:
        return _json_error("COD bucket mapping not found.", 404)

    icd_code = mapping.icd_code
    node_id = str(mapping.node_id)
    db.session.delete(mapping)
    db.session.commit()
    return jsonify(
        {"message": "ICD code unmapped.", "icd_code": icd_code, "node_id": node_id}
    )


@admin.post("/api/cod-bucket-schemes/<scheme_code>/mappings")
@role_required("admin")
def admin_cod_bucket_scheme_add_mappings(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    scheme = get_cod_bucket_scheme(scheme_code)
    if scheme is None:
        return _json_error("COD bucket scheme not found.", 404)

    data = request.get_json(silent=True) or {}
    node_id_raw = (data.get("node_id") or "").strip()
    icd_codes_raw = data.get("icd_codes")
    if not node_id_raw:
        return _json_error("node_id is required.", 400)
    if icd_codes_raw is None:
        return _json_error("icd_codes is required.", 400)

    try:
        node_id = uuid.UUID(node_id_raw)
    except ValueError:
        return _json_error("node_id must be a valid UUID.", 400)

    node = db.session.get(MasCodBucketNode, node_id)
    if node is None or node.scheme_id != scheme.scheme_id or node.node_type != NODE_TYPE_FIELD:
        return _json_error("Target disease node not found.", 404)

    if isinstance(icd_codes_raw, str):
        raw_codes = re.split(r"[\s,;\n]+", icd_codes_raw)
    elif isinstance(icd_codes_raw, list):
        raw_codes = icd_codes_raw
    else:
        return _json_error("icd_codes must be a string or list.", 400)

    icd_codes = []
    for raw_code in raw_codes:
        code = (raw_code or "").strip().upper()
        if not code:
            continue
        if code not in icd_codes:
            icd_codes.append(code)
    if not icd_codes:
        return _json_error("At least one ICD code is required.", 400)

    added_codes = []
    for icd_code in icd_codes:
        existing = db.session.scalar(
            sa.select(MapIcdCodBucket).where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id,
                MapIcdCodBucket.age_scope == node.age_scope,
                MapIcdCodBucket.icd_code == icd_code,
            )
        )
        if existing is None:
            existing = MapIcdCodBucket(
                scheme_id=scheme.scheme_id,
                age_scope=node.age_scope,
                icd_code=icd_code,
                node_id=node.node_id,
                is_active=True,
            )
            db.session.add(existing)
        else:
            existing.node_id = node.node_id
        added_codes.append(icd_code)

    db.session.commit()
    return jsonify(
        {
            "node_id": str(node.node_id),
            "path_label": _cod_bucket_node_path_label(node),
            "icd_codes": added_codes,
        }
    ), 201
