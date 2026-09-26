"""Anonymous, non-persisting API for the public DORIS training page."""

from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlencode

from flask import Blueprint, Response, current_app, jsonify, render_template, request
from flask_wtf.csrf import generate_csrf

from app.public_doris import csrf, limiter
from app.services.doris_certificate import DorisCertificateError, expected_expression_uri
from app.services.doris_processing import process_certificate
from app.services.icd11_postcoordination import (
    PostcoordinationError,
    guidance_request,
    postcoordination_availability,
    postcoordination_capability,
)
from app.services.icd11_postcoordination import (
    hierarchy as get_hierarchy,
)
from app.services.icd11_postcoordination import (
    postcoordination as get_postcoordination,
)
from app.services.icd11_postcoordination import (
    postcoordination_options as get_postcoordination_options,
)
from app.services.who_icd_api import (
    DEFAULT_ICD11_RELEASE,
    WhoIcdApiUnavailable,
    get_icd11_codeinfo,
    proxy_who_icd_request,
)

bp = Blueprint("public_doris", __name__)
_TAG_RE = re.compile(r"<[^>]+>")
_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="doris-public")
_capacity = BoundedSemaphore(5)


def _process_with_app_context(app, payload: dict, image_digest: str) -> dict:
    with app.app_context():
        return process_certificate(
            payload,
            release=DEFAULT_ICD11_RELEASE,
            who_image_digest=image_digest,
        )


def _error(code: str, message: str, status: int, fields: list[dict] | None = None):
    payload = {"schema_version": 1, "error": {"code": code, "message": message}}
    if fields is not None:
        payload["error"]["fields"] = fields
    return jsonify(payload), status


def _json_object():
    if request.content_length is None or request.content_length > 32 * 1024:
        return None
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _plain_text(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("@value") or value.get("label") or ""
    if isinstance(value, list):
        value = " ".join(item for item in value if isinstance(item, str))
    return html.unescape(_TAG_RE.sub("", value if isinstance(value, str) else "")).strip()


def _item_from_codeinfo(info: dict) -> dict | None:
    code = info.get("code")
    uri = info.get("stemId")
    title = _plain_text(info.get("title") or info.get("label"))
    if not all(isinstance(value, str) and value for value in (code, uri, title)):
        return None
    return {
        "code": code,
        "title": title,
        "uri": uri,
        "release": DEFAULT_ICD11_RELEASE,
        "postcoordination": False,
    }


def _codeinfo_item(code: str) -> dict | None:
    info = get_icd11_codeinfo(code, release=DEFAULT_ICD11_RELEASE)
    if not isinstance(info, dict):
        return None
    item = _item_from_codeinfo(info)
    if item is not None:
        item["uri"] = expected_expression_uri(code) or item["uri"]
        if "&" not in code and "/" not in code:
            item["postcoordination"] = postcoordination_capability(code, info)
        return item
    uri = info.get("stemId")
    if not isinstance(uri, str) or not uri.startswith("http://id.who.int/"):
        return None
    resource = uri.removeprefix("http://id.who.int/")
    upstream = proxy_who_icd_request(resource)
    entity = upstream.json()
    if not isinstance(entity, dict):
        return None
    enriched = dict(info)
    enriched["title"] = entity.get("title")
    item = _item_from_codeinfo(enriched)
    if item is not None:
        item["uri"] = expected_expression_uri(code) or item["uri"]
        if "&" not in code and "/" not in code:
            item["postcoordination"] = bool(entity.get("postcoordinationScale"))
    return item


@bp.get("/health")
def health():
    return {"status": "ok"}


@bp.get("/help/doris-demo")
def demo():
    return render_template("public_doris_demo.html", csrf_token=generate_csrf)


@bp.get("/api/v1/doris-demo/config")
@limiter.limit("120 per minute")
def config():
    path = Path(current_app.config["DORIS_EXAMPLES_PATH"])
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
        examples = [
            {key: item[key] for key in ("id", "label", "purpose", "certificate")}
            for item in source["examples"]
        ]
    except (OSError, KeyError, TypeError, ValueError):
        return _error("CONFIG_UNAVAILABLE", "Training examples are unavailable.", 503)
    response = jsonify(
        schema_version=1,
        icd_release=DEFAULT_ICD11_RELEASE,
        examples=examples,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/api/v1/doris-demo/terms")
@limiter.limit("120 per minute")
def terms():
    payload = _json_object()
    if payload is None:
        return _error("MALFORMED_JSON", "A JSON request is required.", 400)
    if set(payload) - {"schema_version", "query", "limit", "cursor"}:
        return _error("INVALID_INPUT", "The terminology request is invalid.", 422)
    query = payload.get("query")
    limit = payload.get("limit", 20)
    cursor = payload.get("cursor")
    if (
        payload.get("schema_version") != 1
        or not isinstance(query, str)
        or not 2 <= len(query.strip()) <= 80
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 20
        or cursor is not None
    ):
        return _error("INVALID_INPUT", "The terminology request is invalid.", 422)

    body = urlencode(
        {
            "q": f"{query.strip()}%",
            "includePostcoordination": "true",
            "flatResults": "true",
            "highlightingEnabled": "true",
            "medicalCodingMode": "true",
        }
    ).encode()
    try:
        upstream = proxy_who_icd_request(
            f"icd/release/11/{DEFAULT_ICD11_RELEASE}/mms/search",
            method="POST",
            body=body,
            content_type="application/x-www-form-urlencoded",
        )
        raw = upstream.json()
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_UNAVAILABLE", "ICD-11 terminology is unavailable.", 503)
    entities = raw.get("destinationEntities") if isinstance(raw, dict) else None
    if not isinstance(entities, list):
        return _error("WHO_UNAVAILABLE", "ICD-11 terminology returned an invalid response.", 503)
    items = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        code = entity.get("theCode") or entity.get("code")
        uri = entity.get("id") or entity.get("uri") or entity.get("@id")
        title = _plain_text(entity.get("title") or entity.get("titleWithoutCodes"))
        if not all(isinstance(value, str) and value for value in (code, uri, title)):
            continue
        matching_text = _plain_text(
            entity.get("matchingPVs") or entity.get("matchingText")
        )
        available, raw_availability = postcoordination_availability(
            entity.get("postcoordinationAvailability")
        )
        items.append(
            {
                "code": code,
                "title": title,
                "uri": uri,
                "release": DEFAULT_ICD11_RELEASE,
                "matching_text": matching_text or title,
                "postcoordination": available,
                "postcoordination_availability": raw_availability,
            }
        )
        if len(items) == limit:
            break
    chopped = bool(raw.get("resultChopped")) or len(entities) > len(items)
    return jsonify(
        schema_version=1,
        items=items,
        truncated=chopped,
        next_cursor=None,
    )


@bp.post("/api/v1/doris-demo/codeinfo")
@limiter.limit("120 per minute")
def codeinfo():
    payload = _json_object()
    code = payload.get("code") if payload else None
    if (
        payload is None
        or set(payload) != {"schema_version", "code"}
        or payload.get("schema_version") != 1
        or not isinstance(code, str)
        or not code.strip()
        or len(code.strip()) > 128
    ):
        return _error("INVALID_INPUT", "The code request is invalid.", 422)
    try:
        item = _codeinfo_item(code.strip())
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_UNAVAILABLE", "ICD-11 terminology is unavailable.", 503)
    if item is None:
        return _error("CODE_NOT_FOUND", "Select a valid ICD-11 code.", 422)
    return jsonify(schema_version=1, item=item)


@bp.post("/api/v1/doris-demo/selection-check")
@limiter.limit("120 per minute")
def selection_check():
    payload = _json_object()
    code = payload.get("code") if payload else None
    uri = payload.get("uri") if payload else None
    if (
        payload is None
        or payload.get("schema_version") != 1
        or not isinstance(code, str)
        or not isinstance(uri, str)
        or not code.strip()
        or len(code.strip()) > 128
        or len(uri) > 2048
    ):
        return _error("INVALID_INPUT", "The selected ICD-11 code is invalid.", 422)
    try:
        item = _codeinfo_item(code.strip())
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_UNAVAILABLE", "ICD-11 terminology is unavailable.", 503)
    if item is None or item["uri"] != uri.strip():
        return _error("INVALID_SELECTION", "The selected code does not match its WHO URI.", 422)
    return jsonify(schema_version=1, item=item)


def _guidance_request(operation, fields: set[str]):
    payload = _json_object()
    if payload is None or set(payload) != fields or payload.get("schema_version") != 1:
        return _error("INVALID_INPUT", "The ICD-11 guidance request is invalid.", 422)
    try:
        with guidance_request():
            return jsonify(operation(payload))
    except PostcoordinationError as exc:
        return _error(exc.code, str(exc), exc.status)
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_UNAVAILABLE", "ICD-11 guidance is unavailable.", 503)


@bp.post("/api/v1/doris-demo/postcoordination")
@limiter.limit("120 per minute")
def postcoordination():
    return _guidance_request(
        lambda body: get_postcoordination(body["code"]), {"schema_version", "code"}
    )


@bp.post("/api/v1/doris-demo/postcoordination-options")
@limiter.limit("120 per minute")
def postcoordination_options():
    return _guidance_request(
        lambda body: get_postcoordination_options(
            body["stem_code"], body["axis_id"], body["parent_uri"]
        ),
        {"schema_version", "stem_code", "axis_id", "parent_uri"},
    )


@bp.post("/api/v1/doris-demo/hierarchy")
@limiter.limit("120 per minute")
def hierarchy():
    return _guidance_request(
        lambda body: get_hierarchy(body["code"]), {"schema_version", "code"}
    )


@bp.post("/api/v1/doris-demo/process")
@limiter.limit("30 per minute")
def process():
    payload = _json_object()
    if payload is None:
        return _error("MALFORMED_JSON", "A JSON request is required.", 400)
    if not _capacity.acquire(blocking=False):
        return _error("PROCESS_BUSY", "All training processors are busy. Try again shortly.", 429)
    try:
        app = current_app._get_current_object()
        future = _executor.submit(
            _process_with_app_context,
            app,
            payload,
            current_app.config["DORIS_WHO_IMAGE_DIGEST"],
        )
    except BaseException:
        _capacity.release()
        raise
    future.add_done_callback(lambda _future: _capacity.release())
    try:
        result = future.result(timeout=float(current_app.config["DORIS_PROCESS_DEADLINE_SECONDS"]))
    except TimeoutError:
        return _error("PROCESS_TIMEOUT", "Mortality processing exceeded its deadline.", 503)
    except DorisCertificateError as exc:
        return _error(
            "INVALID_INPUT",
            "The DORIS certificate is invalid.",
            422,
            [{"path": field.path, "message": field.message} for field in exc.fields],
        )
    except ValueError:
        return _error("INVALID_INPUT", "The DORIS request is invalid.", 422)
    except WhoIcdApiUnavailable:
        return _error("WHO_UNAVAILABLE", "Mortality processing is unavailable.", 503)
    status = 503 if all(result[name]["status"] not in {"completed", "rejected"} for name in ("doris", "codedit")) else 200
    response = jsonify(result)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/api/v1/doris-demo/who-api/<path:resource>", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("240 per minute")
def who_api(resource: str):
    if resource.rstrip("/") == "analytics/clientanalytics":
        return Response(status=204)
    if request.content_length is not None and request.content_length > 128 * 1024:
        return _error("INVALID_INPUT", "WHO ICD API request is too large.", 400)
    try:
        upstream = proxy_who_icd_request(
            resource,
            method=request.method,
            query_string=request.query_string,
            body=request.get_data(cache=True) if request.method == "POST" else b"",
            content_type=request.content_type,
        )
        json.loads(upstream.content)
    except ValueError:
        return _error("INVALID_INPUT", "WHO ICD API request is invalid.", 400)
    except WhoIcdApiUnavailable:
        return _error("WHO_UNAVAILABLE", "ICD-11 terminology is unavailable.", 503)
    response = Response(upstream.content, status=upstream.status_code, content_type="application/json")
    response.headers["Cache-Control"] = "no-store"
    return response
