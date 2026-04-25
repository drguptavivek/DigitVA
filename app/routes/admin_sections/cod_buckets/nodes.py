"""Node-oriented COD bucket routes."""

import uuid

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MasCodBucketNode, MasCodBucketSchemeAgeBand
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.services.analytics.cod_buckets import (
    NODE_DELETE_DISPOSITION_MOVE_TO_UNMAPPED,
    NODE_DELETE_DISPOSITION_UNMAP,
    delete_cod_bucket_node,
    get_cod_bucket_node_mappings_payload,
    get_cod_bucket_scheme,
)

from .common import _cod_bucket_node_path_label, _cod_bucket_slugify


@admin.get("/api/cod-bucket-schemes/<scheme_code>/nodes/<uuid:node_id>/mappings")
@role_required("admin")
def admin_cod_bucket_scheme_node_mappings(scheme_code, node_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = get_cod_bucket_node_mappings_payload(
            scheme_code=scheme_code,
            node_id=node_id,
        )
    except LookupError:
        return _json_error("COD bucket scheme or node not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify(payload)


@admin.patch("/api/cod-bucket-schemes/<scheme_code>/nodes/<uuid:node_id>")
@role_required("admin")
def admin_cod_bucket_scheme_update_node(scheme_code, node_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    scheme = get_cod_bucket_scheme(scheme_code)
    if scheme is None:
        return _json_error("COD bucket scheme not found.", 404)

    node = db.session.get(MasCodBucketNode, node_id)
    if node is None or node.scheme_id != scheme.scheme_id:
        return _json_error("COD bucket node not found.", 404)

    data = request.get_json(silent=True) or {}
    node_label = (data.get("node_label") or "").strip()
    if not node_label:
        return _json_error("node_label is required.", 400)

    sort_order = data.get("sort_order")
    try:
        sort_order = int(sort_order)
    except (TypeError, ValueError):
        return _json_error("sort_order must be an integer.", 400)

    node.node_label = node_label
    node.sort_order = sort_order
    db.session.commit()
    return jsonify(
        {
            "node": {
                "node_id": str(node.node_id),
                "node_type": node.node_type,
                "node_label": node.node_label,
                "sort_order": node.sort_order,
            }
        }
    )


@admin.delete("/api/cod-bucket-schemes/<scheme_code>/nodes/<uuid:node_id>")
@role_required("admin")
def admin_cod_bucket_scheme_delete_node(scheme_code, node_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    mapping_disposition = (data.get("mapping_disposition") or "").strip().lower()
    if mapping_disposition not in {
        NODE_DELETE_DISPOSITION_UNMAP,
        NODE_DELETE_DISPOSITION_MOVE_TO_UNMAPPED,
    }:
        return _json_error(
            "mapping_disposition must be unmap or move_to_unmapped.",
            400,
        )

    try:
        payload = delete_cod_bucket_node(
            scheme_code=scheme_code,
            node_id=node_id,
            mapping_disposition=mapping_disposition,
        )
    except LookupError:
        return _json_error("COD bucket scheme or node not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify(payload)


@admin.post("/api/cod-bucket-schemes/<scheme_code>/nodes")
@role_required("admin")
def admin_cod_bucket_scheme_create_node(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    scheme = get_cod_bucket_scheme(scheme_code)
    if scheme is None:
        return _json_error("COD bucket scheme not found.", 404)

    data = request.get_json(silent=True) or {}
    node_label = (data.get("node_label") or "").strip()
    node_type = (data.get("node_type") or "").strip()
    age_scope = (data.get("age_scope") or "").strip() or None
    parent_node_id_raw = (data.get("parent_node_id") or "").strip() or None

    if not node_label:
        return _json_error("node_label is required.", 400)
    if node_type not in {"category", "subcategory", "field"}:
        return _json_error("node_type must be category, subcategory, or field.", 400)
    age_band = db.session.scalar(
        sa.select(MasCodBucketSchemeAgeBand).where(
            MasCodBucketSchemeAgeBand.scheme_id == scheme.scheme_id,
            MasCodBucketSchemeAgeBand.age_scope == age_scope,
        )
    )
    if age_band is None:
        return _json_error("Selected age band was not found for this scheme.", 404)

    parent_node = None
    if parent_node_id_raw:
        try:
            parent_node_id = uuid.UUID(parent_node_id_raw)
        except ValueError:
            return _json_error("parent_node_id must be a valid UUID.", 400)
        parent_node = db.session.get(MasCodBucketNode, parent_node_id)
        if parent_node is None or parent_node.scheme_id != scheme.scheme_id:
            return _json_error("Parent node not found.", 404)
        if parent_node.age_scope != age_scope:
            return _json_error("Parent node age scope does not match.", 400)

    max_sort = db.session.scalar(
        sa.select(sa.func.max(MasCodBucketNode.sort_order)).where(
            MasCodBucketNode.scheme_id == scheme.scheme_id,
            MasCodBucketNode.age_scope == age_scope,
            MasCodBucketNode.parent_node_id == (parent_node.node_id if parent_node else None),
        )
    ) or 0

    node_code_base = _cod_bucket_slugify(node_label)
    node_code = node_code_base
    suffix = 2
    while db.session.scalar(
        sa.select(MasCodBucketNode.node_id).where(
            MasCodBucketNode.scheme_id == scheme.scheme_id,
            MasCodBucketNode.age_scope == age_scope,
            MasCodBucketNode.parent_node_id == (parent_node.node_id if parent_node else None),
            MasCodBucketNode.node_type == node_type,
            MasCodBucketNode.node_code == node_code,
        )
    ):
        node_code = f"{node_code_base}_{suffix}"
        suffix += 1

    node = MasCodBucketNode(
        scheme_id=scheme.scheme_id,
        age_scope=age_scope,
        node_type=node_type,
        parent=parent_node,
        node_code=node_code,
        node_label=node_label,
        sort_order=max_sort + 1,
        is_active=True,
    )
    db.session.add(node)
    db.session.commit()
    return jsonify(
        {
            "node": {
                "node_id": str(node.node_id),
                "node_type": node.node_type,
                "node_label": node.node_label,
                "sort_order": node.sort_order,
                "parent_node_id": str(node.parent_node_id) if node.parent_node_id else None,
                "path_label": _cod_bucket_node_path_label(node),
            }
        }
    ), 201


@admin.post("/api/cod-bucket-schemes/<scheme_code>/nodes/reorder")
@role_required("admin")
def admin_cod_bucket_scheme_reorder_nodes(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    scheme = get_cod_bucket_scheme(scheme_code)
    if scheme is None:
        return _json_error("COD bucket scheme not found.", 404)

    data = request.get_json(silent=True) or {}
    node_ids_raw = data.get("node_ids") or []
    if not isinstance(node_ids_raw, list) or not node_ids_raw:
        return _json_error("node_ids must be a non-empty list.", 400)

    try:
        node_ids = [uuid.UUID(str(node_id)) for node_id in node_ids_raw]
    except ValueError:
        return _json_error("node_ids must contain valid UUIDs.", 400)

    nodes = list(
        db.session.scalars(
            sa.select(MasCodBucketNode).where(
                MasCodBucketNode.scheme_id == scheme.scheme_id,
                MasCodBucketNode.node_id.in_(node_ids),
            )
        )
    )
    if len(nodes) != len(node_ids):
        return _json_error("One or more nodes were not found.", 404)

    first = nodes[0]
    for node in nodes[1:]:
        if (
            node.parent_node_id != first.parent_node_id
            or node.age_scope != first.age_scope
            or node.node_type != first.node_type
        ):
            return _json_error(
                "All reordered nodes must be sibling nodes of the same type.",
                400,
            )

    node_map = {node.node_id: node for node in nodes}
    for index, node_id in enumerate(node_ids, start=1):
        node_map[node_id].sort_order = index

    db.session.commit()
    return jsonify({"message": "Node order updated."})
