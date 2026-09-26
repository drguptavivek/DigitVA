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


def _plain(value: object, max_chars: int = 200) -> str:
    if isinstance(value, dict):
        value = value.get("@value") or value.get("label") or ""
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAG_RE.sub("", value)).strip()[:max_chars]


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


def _option(uri: str, *, block_uri: str | None = None,
            skip_uncoded_leaf: bool = False) -> dict | None:
    entity = _entity(uri)
    children = entity.get("child") or []
    if not isinstance(children, list):
        children = []
    code = entity.get("code")
    title = _plain(entity.get("title"))
    if code == "" and not children and title and skip_uncoded_leaf:
        return None
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
        instruction = (
            "code also" if axis_id == "hasCausingCondition" and required_value in (True, "true")
            else "use additional code" if required_value in (True, "true")
            else "use additional code, if desired"
        )
        axes.append({
            "id": axis_id,
            "label": label,
            "required": required_value is True or required_value == "true",
            "instruction": instruction,
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
    options = []
    for uri in children[:_MAX_OPTIONS]:
        option = _option(uri, block_uri=block_uri, skip_uncoded_leaf=True)
        if option is not None:
            options.append(option)
    return {
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "stem": stem,
        "axis_id": axis_id,
        "parent_uri": parent_uri,
        "items": options,
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
        related[output_name] = []
        for uri in uris[:_MAX_OPTIONS]:
            related_entity = _entity(uri, foundation=True)
            related[output_name].append({
                "code": related_entity.get("code") or "",
                "title": _plain(related_entity.get("title")),
                "uri": uri,
            })
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


def related_terms(code: str, chapter: str) -> dict:
    """Return coded MMS relatives for one WHO maternal or perinatal marker."""
    source = {
        "maternal": "relatedEntitiesInMaternalChapter",
        "perinatal": "relatedEntitiesInPerinatalChapter",
    }.get(chapter)
    if source is None:
        raise PostcoordinationError("INVALID_INPUT", "Choose a valid related chapter.")
    selected, entity = _stem(_stem_code(code))
    related_uris = entity.get(source) or []
    if not isinstance(related_uris, list):
        raise WhoIcdApiUnavailable("WHO related terms were malformed")
    terms = []
    truncated = len(related_uris) > _MAX_OPTIONS
    for foundation_uri in related_uris[:_MAX_OPTIONS]:
        entity_id = _resource(foundation_uri, foundation=True).rsplit("/", 1)[-1]
        mms_uri = f"http://id.who.int/icd/release/11/{DEFAULT_ICD11_RELEASE}/mms/{entity_id}"
        try:
            related_entity = _entity(mms_uri)
        except PostcoordinationError as exc:
            if exc.code == "CODE_NOT_FOUND":
                continue
            raise
        candidates = [related_entity]
        children = related_entity.get("child") or []
        if not isinstance(children, list):
            raise WhoIcdApiUnavailable("WHO related children were malformed")
        for child_uri in children[:_MAX_OPTIONS]:
            candidates.append(_entity(child_uri))
        truncated = truncated or len(children) > _MAX_OPTIONS
        for candidate in candidates:
            candidate_code = candidate.get("code")
            candidate_title = _plain(candidate.get("title"))
            if isinstance(candidate_code, str) and candidate_code and candidate_title:
                scales = candidate.get("postcoordinationScale") or []
                required = isinstance(scales, list) and any(
                    isinstance(scale, dict)
                    and scale.get("requiredPostcoordination") in (True, "true")
                    for scale in scales
                )
                terms.append({
                    "code": candidate_code,
                    "title": candidate_title,
                    "uri": candidate.get("@id") or "",
                    "requires_postcoordination": required,
                })
                if len(terms) >= _MAX_OPTIONS:
                    truncated = True
                    break
        if len(terms) >= _MAX_OPTIONS:
            break
    return {
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "selected": selected,
        "chapter": chapter,
        "terms": terms,
        "truncated": truncated,
    }


def _stem_code(code: str) -> str:
    if isinstance(code, str) and ("&" in code or "/" in code):
        if not _CODE_RE.fullmatch(code):
            raise PostcoordinationError("INVALID_INPUT", "Select a valid ICD-11 expression.")
        _check_budget()
        info = get_icd11_codeinfo(code)
        return info.get("stemCode") if isinstance(info, dict) else None
    return code


def code_details(code: str) -> dict:
    """Bounded WHO code details for a selected search result."""
    selected, entity = _stem(_stem_code(code))
    raw_terms = entity.get("indexTerm") or []
    raw_exclusions = entity.get("exclusion") or []
    raw_inclusions = entity.get("inclusion") or []
    if not all(isinstance(values, list) for values in (raw_terms, raw_exclusions, raw_inclusions)):
        raise WhoIcdApiUnavailable("WHO code details were malformed")
    exclusions = []
    for exclusion in raw_exclusions[:_MAX_OPTIONS]:
        if not isinstance(exclusion, dict):
            continue
        uri = exclusion.get("linearizationReference")
        if not isinstance(uri, str):
            continue
        excluded = _entity(uri)
        exclusions.append({
            "code": excluded.get("code") or "",
            "title": _plain(exclusion.get("label")) or _plain(excluded.get("title")),
        })
    return {
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "selected": selected,
        "definition": _plain(entity.get("definition"), 2000),
        "coding_note": _plain(entity.get("codingNote"), 2000),
        "fully_specified_name": _plain(entity.get("fullySpecifiedName")),
        "inclusions": [
            term for term in (_plain(item.get("label")) for item in raw_inclusions[:20]
                              if isinstance(item, dict)) if term
        ],
        "matching_terms": [
            term for term in (_plain(item.get("label")) for item in raw_terms[:20]
                              if isinstance(item, dict)) if term
        ],
        "exclusions": exclusions,
        "truncated": len(raw_terms) > 20 or len(raw_exclusions) > _MAX_OPTIONS or len(raw_inclusions) > 20,
    }


def postcoordination_availability(value: object) -> tuple[bool, int | None]:
    """Return WHO's search flag without guessing from isLeaf or code syntax."""
    flag = value if type(value) is int and value in {0, 1, 2} else None
    return bool(flag), flag


def search_context_from_entity(entity: dict) -> dict:
    """Derive search badges when a coder enters a code directly."""
    scales = entity.get("postcoordinationScale") or []
    if not isinstance(scales, list):
        raise WhoIcdApiUnavailable("WHO postcoordination scale was malformed")
    required = any(
        isinstance(scale, dict)
        and scale.get("requiredPostcoordination") in (True, "true")
        for scale in scales
    )
    return {
        "postcoordination": bool(scales),
        "postcoordination_availability": 2 if required else 1 if scales else 0,
        "related_maternal": bool(entity.get("relatedEntitiesInMaternalChapter")),
        "related_perinatal": bool(entity.get("relatedEntitiesInPerinatalChapter")),
        "has_coding_note": bool(entity.get("codingNote")),
    }
