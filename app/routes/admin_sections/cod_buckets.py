import json
import re
import uuid

import sqlalchemy as sa
from flask import current_app, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketSchemeAgeBand
from app.routes.admin import _json_error, admin
from app.services.cod_bucket_mapping_service import (
    NODE_DELETE_DISPOSITION_MOVE_TO_UNMAPPED,
    NODE_DELETE_DISPOSITION_UNMAP,
    NODE_TYPE_FIELD,
    create_cod_bucket_scheme,
    delete_cod_bucket_node,
    export_cod_bucket_scheme_json,
    get_cod_bucket_scheme,
    get_cod_bucket_scheme_editor_payload,
    get_cod_bucket_node_mappings_payload,
    list_cod_bucket_scheme_cards,
    list_cod_bucket_unmapped_icd_rows,
    reset_cod_bucket_scheme_age_band_to_source,
    search_cod_bucket_icd_candidates,
    update_cod_bucket_scheme,
)


def _cod_bucket_node_path_label(node):
    labels = [node.node_label]
    parent = node.parent
    while parent is not None:
        labels.append(parent.node_label)
        parent = parent.parent
    return " > ".join(reversed(labels))


def _cod_bucket_slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "node"


@admin.get("/panels/cod-buckets")
@role_required("admin")
def admin_panel_cod_buckets():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    return render_template(
        "admin/panels/cod_buckets.html",
        cod_bucket_schemes=list_cod_bucket_scheme_cards(),
    )


@admin.get("/api/cod-bucket-schemes")
@role_required("admin")
def admin_cod_bucket_schemes():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return jsonify({"schemes": list_cod_bucket_scheme_cards()})


@admin.post("/api/cod-bucket-schemes")
@role_required("admin")
def admin_cod_bucket_scheme_create():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    try:
        scheme, warnings = create_cod_bucket_scheme(
            scheme_name=(data.get("scheme_name") or "").strip(),
            scheme_code=(data.get("scheme_code") or "").strip(),
            age_bands=data.get("age_bands") or [],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    card = next(
        (
            item
            for item in list_cod_bucket_scheme_cards()
            if item["scheme_code"] == scheme.scheme_code
        ),
        None,
    )
    return jsonify({"scheme": card, "warnings": warnings}), 201


@admin.patch("/api/cod-bucket-schemes/<scheme_code>")
@role_required("admin")
def admin_cod_bucket_scheme_update(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    try:
        scheme, warnings = update_cod_bucket_scheme(
            scheme_code=scheme_code,
            scheme_name=(data.get("scheme_name") or "").strip(),
            age_bands=data.get("age_bands") or [],
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    card = next(
        (
            item
            for item in list_cod_bucket_scheme_cards()
            if item["scheme_code"] == scheme.scheme_code
        ),
        None,
    )
    return jsonify({"scheme": card, "warnings": warnings})


@admin.post("/api/cod-bucket-schemes/<scheme_code>/reset-default")
@role_required("admin")
def admin_cod_bucket_scheme_reset_default(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    raw_age_scope = (data.get("age_scope") or "").strip()
    reset_scope = (data.get("reset_scope") or "").strip().lower() or "age_band"
    try:
        scheme = reset_cod_bucket_scheme_age_band_to_source(
            scheme_code=scheme_code,
            age_scope=raw_age_scope or None,
            reset_entire_scheme=reset_scope == "scheme",
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return jsonify(
        {
            "message": (
                "Scheme reset from source."
                if reset_scope == "scheme"
                else "Scheme age band reset from source."
            ),
            "scheme_code": scheme.scheme_code,
            "age_scope": None if reset_scope == "scheme" else (raw_age_scope or None),
            "reset_scope": reset_scope,
        }
    )


@admin.get("/api/cod-bucket-schemes/<scheme_code>")
@role_required("admin")
def admin_cod_bucket_scheme_detail(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = get_cod_bucket_scheme_editor_payload(
            scheme_code=scheme_code,
            age_scope=(request.args.get("age_scope") or "").strip() or None,
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    return jsonify(payload)


@admin.get("/api/cod-bucket-schemes/<scheme_code>/export")
@role_required("admin")
def admin_cod_bucket_scheme_export(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = export_cod_bucket_scheme_json(scheme_code=scheme_code)
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)

    filename = f"cod_bucket_scheme_{scheme_code.lower()}.json"
    return current_app.response_class(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@admin.get("/api/cod-bucket-schemes/<scheme_code>/unmapped-icd")
@role_required("admin")
def admin_cod_bucket_scheme_unmapped_icd(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = list_cod_bucket_unmapped_icd_rows(scheme_code=scheme_code)
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    return jsonify(payload)


@admin.get("/api/cod-bucket-schemes/<scheme_code>/icd-search")
@role_required("admin")
def admin_cod_bucket_scheme_icd_search(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    age_scope = (request.args.get("age_scope") or "").strip() or None
    query = (request.args.get("q") or "").strip()
    selected_node_id = None
    selected_node_id_raw = (request.args.get("selected_node_id") or "").strip()
    if selected_node_id_raw:
        try:
            selected_node_id = uuid.UUID(selected_node_id_raw)
        except ValueError:
            return _json_error("selected_node_id must be a valid UUID.", 400)
    unmapped_only = (request.args.get("unmapped_only") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    try:
        results = search_cod_bucket_icd_candidates(
            scheme_code=scheme_code,
            age_scope=age_scope,
            query=query,
            selected_node_id=selected_node_id,
            unmapped_only=unmapped_only,
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)

    return jsonify(
        {"results": results, "query": query, "unmapped_only": unmapped_only}
    )


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
            MasCodBucketNode.parent_node_id
            == (parent_node.node_id if parent_node else None),
        )
    ) or 0

    node_code_base = _cod_bucket_slugify(node_label)
    node_code = node_code_base
    suffix = 2
    while db.session.scalar(
        sa.select(MasCodBucketNode.node_id).where(
            MasCodBucketNode.scheme_id == scheme.scheme_id,
            MasCodBucketNode.age_scope == age_scope,
            MasCodBucketNode.parent_node_id
            == (parent_node.node_id if parent_node else None),
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
                "parent_node_id": (
                    str(node.parent_node_id) if node.parent_node_id else None
                ),
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
    if (
        node is None
        or node.scheme_id != scheme.scheme_id
        or node.node_type != NODE_TYPE_FIELD
    ):
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
