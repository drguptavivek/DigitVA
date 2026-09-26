"""Bounded, release-pinned WHO MMS postcoordination and hierarchy reads."""

from __future__ import annotations

import html
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from app.services.who_icd_api import (
    DEFAULT_ICD11_RELEASE,
    WhoIcdApiUnavailable,
    get_icd11_codeinfo,
    proxy_who_icd_request,
)

_TAG_RE = re.compile(r"<[^>]+>")
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9./&+-]{0,127}$")
_MAX_AXES = 12
_MAX_OPTIONS = 12
_MAX_PATH = 12
_MAX_TERMS = 12
_MAX_CALLS = 48
_GUIDANCE_SECONDS = 10.0
_guidance_capacity = BoundedSemaphore(2)
_budget: ContextVar[tuple[float, list[int]] | None] = ContextVar(
    "icd11_guidance_budget", default=None
)


class PostcoordinationError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(message)


@contextmanager
def guidance_request():
    """Keep guidance calls bounded without using public Process capacity."""
    if not _guidance_capacity.acquire(blocking=False):
        raise PostcoordinationError("GUIDANCE_BUSY", "WHO guidance is busy.", 429)
    token = _budget.set((time.monotonic() + _GUIDANCE_SECONDS, [0]))
    try:
        yield
    finally:
        _budget.reset(token)
        _guidance_capacity.release()


def _check_budget():
    budget = _budget.get()
    if budget is None:
        return
    deadline, calls = budget
    calls[0] += 1
    if calls[0] > _MAX_CALLS or time.monotonic() > deadline:
        raise PostcoordinationError(
            "GUIDANCE_LIMIT", "WHO guidance exceeded its request limit.", 503
        )


def _plain(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("@value") or value.get("label") or ""
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAG_RE.sub("", value)).strip()[:200]


def _resource(uri: str, *, foundation: bool = False) -> str:
    if not isinstance(uri, str) or len(uri) > 400:
        raise PostcoordinationError("INVALID_URI", "Invalid WHO entity URI.")
    parsed = urlsplit(uri)
    prefix = "icd/entity/" if foundation else f"icd/release/11/{DEFAULT_ICD11_RELEASE}/mms/"
    path = parsed.path.lstrip("/")
    if (
        parsed.scheme != "http"
        or parsed.netloc != "id.who.int"
        or parsed.query
        or parsed.fragment
        or not path.startswith(prefix)
        or not re.fullmatch(r"\d+(?:/(?:unspecified|other))?", path[len(prefix):])
    ):
        raise PostcoordinationError("INVALID_URI", "Invalid WHO entity URI.")
    return path


def _entity(uri: str, *, foundation: bool = False) -> dict:
    _check_budget()
    response = proxy_who_icd_request(_resource(uri, foundation=foundation))
    if response.status_code == 404:
        raise PostcoordinationError("CODE_NOT_FOUND", "WHO entity was not found.")
    if response.status_code != 200:
        raise WhoIcdApiUnavailable("WHO entity response was unusable")
    try:
        data = response.json()
    except ValueError as exc:
        raise WhoIcdApiUnavailable("WHO entity response was malformed") from exc
    if not isinstance(data, dict):
        raise WhoIcdApiUnavailable("WHO entity response was malformed")
    return data


def _stem(code: str) -> tuple[dict, dict]:
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        raise PostcoordinationError("INVALID_INPUT", "Select one valid ICD-11 stem code.")
    _check_budget()
    info = get_icd11_codeinfo(code)
    if not isinstance(info, dict) or info.get("code") != code:
        raise PostcoordinationError("CODE_NOT_FOUND", "ICD-11 stem code was not found.")
    uri = info.get("stemId")
    entity = _entity(uri)
    if entity.get("code") != code:
        raise PostcoordinationError("CODE_NOT_FOUND", "ICD-11 stem metadata did not match.")
    return {"code": code, "title": _plain(entity.get("title")), "uri": uri}, entity


def _option(uri: str, *, block_uri: str | None = None) -> dict:
    entity = _entity(uri)
    children = entity.get("child") or []
    if not isinstance(children, list):
        children = []
    code = entity.get("code")
    title = _plain(entity.get("title"))
    if not isinstance(code, str) or not title or (not code and not children):
        raise WhoIcdApiUnavailable("WHO option metadata was incomplete")
    option = {
        "code": code,
        "title": title,
        "uri": uri,
        "has_children": bool(children),
    }
    if block_uri is not None:
        option["block_uri"] = block_uri
    return option


def _axes(entity: dict) -> tuple[list[dict], bool]:
    raw = entity.get("postcoordinationScale") or []
    if not isinstance(raw, list):
        raise WhoIcdApiUnavailable("WHO postcoordination scale was malformed")
    axes = []
    if len(raw) > _MAX_AXES:
        raise PostcoordinationError(
            "GUIDANCE_LIMIT", "WHO returned too many postcoordination axes.", 503
        )
    for scale in raw[:_MAX_AXES]:
        if not isinstance(scale, dict):
            raise WhoIcdApiUnavailable("WHO postcoordination scale was malformed")
        name = scale.get("axisName")
        roots = scale.get("scaleEntity")
        required_value = scale.get("requiredPostcoordination")
        multiple_value = scale.get("allowMultipleValues")
        if (
            not isinstance(name, str)
            or not isinstance(roots, list)
            or not (
                type(required_value) is bool
                or required_value in ("true", "false")
            )
            or multiple_value not in (
                "AllowAlways", "NotAllowed", "AllowedExceptFromSameBlock"
            )
        ):
            raise WhoIcdApiUnavailable("WHO postcoordination scale was incomplete")
        axis_id = name.rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", axis_id):
            raise WhoIcdApiUnavailable("WHO postcoordination axis was invalid")
        label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", axis_id).capitalize()
        options = [_option(uri, block_uri=uri) for uri in roots[:_MAX_OPTIONS]]
        axes.append({
            "id": axis_id,
            "label": label,
            "required": required_value is True or required_value == "true",
            "allow_multiple": multiple_value != "NotAllowed",
            "allow_multiple_values": multiple_value,
            "options": options,
            "truncated": len(roots) > _MAX_OPTIONS,
        })
    return axes, False


def postcoordination(code: str) -> dict:
    stem, entity = _stem(code)
    axes, truncated = _axes(entity)
    return {
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "stem": stem,
        "axes": axes,
        "truncated": truncated,
    }


def postcoordination_capability(code: str, info: dict | None = None) -> bool:
    """Read the stem scale without expanding option descendants."""
    if info is None:
        _, entity = _stem(code)
    else:
        if info.get("code") != code:
            raise PostcoordinationError("CODE_NOT_FOUND", "ICD-11 stem code was not found.")
        entity = _entity(info.get("stemId"))
        if entity.get("code") != code:
            raise PostcoordinationError("CODE_NOT_FOUND", "ICD-11 stem metadata did not match.")
    scale = entity.get("postcoordinationScale") or []
    if not isinstance(scale, list):
        raise WhoIcdApiUnavailable("WHO postcoordination scale was malformed")
    return bool(scale)


def postcoordination_options(stem_code: str, axis_id: str, parent_uri: str) -> dict:
    stem, entity = _stem(stem_code)
    scales = entity.get("postcoordinationScale") or []
    if not isinstance(scales, list):
        raise WhoIcdApiUnavailable("WHO postcoordination scale was malformed")
    scale = next(
        (item for item in scales[:_MAX_AXES]
         if isinstance(item, dict)
         and isinstance(item.get("axisName"), str)
         and item["axisName"].rsplit("/", 1)[-1] == axis_id),
        None,
    )
    if scale is None:
        raise PostcoordinationError("INVALID_AXIS", "This axis is not available for the stem.")
    roots = scale.get("scaleEntity") or []
    if not isinstance(roots, list):
        raise WhoIcdApiUnavailable("WHO axis roots were malformed")
    _resource(parent_uri)
    current = parent_uri
    for _ in range(_MAX_PATH):
        if current in roots:
            break
        parents = _entity(current).get("parent") or []
        if not isinstance(parents, list) or not parents:
            raise PostcoordinationError("INVALID_PARENT", "Parent is outside the selected axis.")
        current = parents[0]
        _resource(current)
    else:
        raise PostcoordinationError("INVALID_PARENT", "Parent is outside the selected axis.")
    block_uri = current
    children = _entity(parent_uri).get("child") or []
    if not isinstance(children, list):
        raise WhoIcdApiUnavailable("WHO option children were malformed")
    return {
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "stem": stem,
        "axis_id": axis_id,
        "parent_uri": parent_uri,
        "items": [
            _option(uri, block_uri=block_uri) for uri in children[:_MAX_OPTIONS]
        ],
        "truncated": len(children) > _MAX_OPTIONS,
    }


def hierarchy(code: str) -> dict:
    expression = None
    stem_code = code
    if isinstance(code, str) and ("&" in code or "/" in code):
        if not _CODE_RE.fullmatch(code):
            raise PostcoordinationError("INVALID_INPUT", "Select a valid ICD-11 expression.")
        _check_budget()
        info = get_icd11_codeinfo(code)
        if not isinstance(info, dict) or info.get("code") != code:
            raise PostcoordinationError("CODE_NOT_FOUND", "ICD-11 expression was not found.")
        stem_code = info.get("stemCode")
        if not isinstance(stem_code, str) or not stem_code:
            raise WhoIcdApiUnavailable("WHO expression stem was missing")
        expression = {"code": code, "stem_code": stem_code}
    selected, entity = _stem(stem_code)
    ancestors = []
    current = entity
    seen = {selected["uri"]}
    for _ in range(_MAX_PATH):
        parents = current.get("parent") or []
        if not isinstance(parents, list) or not parents:
            break
        parent_uri = parents[0]
        if parent_uri == f"http://id.who.int/icd/release/11/{DEFAULT_ICD11_RELEASE}/mms":
            break
        if parent_uri in seen:
            break
        seen.add(parent_uri)
        current = _entity(parent_uri)
        ancestors.append({
            "code": current.get("code") or "",
            "title": _plain(current.get("title")),
            "uri": parent_uri,
        })
    ancestors.reverse()
    parent_children = []
    if ancestors:
        parent_children = _entity(ancestors[-1]["uri"]).get("child") or []
    children = entity.get("child") or []
    if not isinstance(parent_children, list) or not isinstance(children, list):
        raise WhoIcdApiUnavailable("WHO hierarchy was malformed")
    siblings = [uri for uri in parent_children if uri != selected["uri"]]
    terms = entity.get("indexTerm") or []
    if not isinstance(terms, list):
        terms = []
    related = {}
    for output_name, source_name in (
        ("related_maternal", "relatedEntitiesInMaternalChapter"),
        ("related_perinatal", "relatedEntitiesInPerinatalChapter"),
    ):
        uris = entity.get(source_name) or []
        if not isinstance(uris, list):
            uris = []
        related[output_name] = [
            {"title": _plain(_entity(uri, foundation=True).get("title")), "uri": uri}
            for uri in uris[:_MAX_OPTIONS]
        ]
    return {
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "selected": selected,
        "selected_expression": expression,
        "ancestors": ancestors,
        "siblings": [_option(uri) for uri in siblings[:_MAX_OPTIONS]],
        "children": [_option(uri) for uri in children[:_MAX_OPTIONS]],
        "matching_terms": [
            _plain(term.get("label")) for term in terms[:_MAX_TERMS]
            if isinstance(term, dict) and _plain(term.get("label"))
        ],
        **related,
        "truncated": (
            len(ancestors) == _MAX_PATH
            or len(siblings) > _MAX_OPTIONS
            or len(children) > _MAX_OPTIONS
            or len(terms) > _MAX_TERMS
            or any(len(entity.get(name) or []) > _MAX_OPTIONS for name in (
                "relatedEntitiesInMaternalChapter", "relatedEntitiesInPerinatalChapter"
            ))
        ),
    }


def postcoordination_availability(value: object) -> tuple[bool, int | None]:
    """Return WHO's search flag without guessing from isLeaf or code syntax."""
    flag = value if type(value) is int and value in {0, 1, 2} else None
    return bool(flag), flag
