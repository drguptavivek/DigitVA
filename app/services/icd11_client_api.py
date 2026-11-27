"""Terminology operations behind the ICD-11 client API (digitva-ddpf).

Thin, release-pinned wrappers over the WHO adapter (app/services/who_icd_api.py)
and the guidance service (app/services/icd11_postcoordination.py). Every
result names ``release``. Every operation runs inside ``client_slot()``, the
client API's own 4 guidance slots, so external traffic never takes the
coders' slots. Policy: docs/policy/icd11-client-api.md.
"""

from __future__ import annotations

import re
from threading import BoundedSemaphore
from urllib.parse import urlencode

from app.services.doris_certificate import expected_expression_uri
from app.services.icd11_postcoordination import (
    _CODE_RE,
    _plain,
    guidance_request,
    repeated_part,
    search_context_from_entity,
    selection_refusal,
)
from app.services.icd11_titles import cluster_title
from app.services.who_icd_api import (
    DEFAULT_ICD11_RELEASE,
    WhoIcdApiUnavailable,
    get_icd11_codeinfo,
    proxy_who_icd_request,
)

_client_capacity = BoundedSemaphore(4)
_MAX_WORDS = 20
_MMS_URI_RE = re.compile(
    rf"^http://id\.who\.int/icd/release/11/{re.escape(DEFAULT_ICD11_RELEASE)}"
    r"/mms/(\d+)(/unspecified|/other)?$"
)


def client_slot():
    """A guidance slot from the client API's own capacity (429 GUIDANCE_BUSY when full)."""
    return guidance_request(capacity=_client_capacity)


def valid_code(value: object) -> bool:
    """A stem code or expression in WHO's code alphabet, at most 128 characters."""
    return isinstance(value, str) and bool(_CODE_RE.fullmatch(value))


def browser_url(uri: object) -> str | None:
    """The WHO ICD-11 browser page of a plain MMS linearization URI, else None.

    Postcoordinated expression URIs (spaces and operators) and any other
    release or host get None; the base matches the coder screens' browser link.
    """
    match = _MMS_URI_RE.fullmatch(uri) if isinstance(uri, str) else None
    if not match:
        return None
    entity_id, residual = match.groups()
    fragment = entity_id + (residual.replace("/", "%2F") if residual else "")
    return f"https://icd.who.int/browse/{DEFAULT_ICD11_RELEASE}/mms/en#{fragment}"


def _text(value: object) -> str:
    if isinstance(value, list):
        value = " ".join(item for item in value if isinstance(item, str))
    return _plain(value, 2000)


def codeinfo_item(code: str) -> dict | None:
    """The WHO item for exactly ``code``, or None when WHO does not know it.

    Same rules as the clinical route (doris_clinical._codeinfo_item; the
    copies are to be merged under digitva-zcmg): WHO must answer for this
    exact code, and ``uri`` is the expression URI, never the stem's. Adds
    ``browser_url``, from the first stem's URI so an expression links to it.
    """
    info = get_icd11_codeinfo(code, release=DEFAULT_ICD11_RELEASE)
    if not isinstance(info, dict) or info.get("code") != code:
        return None
    uri = expected_expression_uri(code, DEFAULT_ICD11_RELEASE)
    if not uri:
        return None
    title = _text(info.get("title") or info.get("label"))
    stem_uri = info.get("stemId")
    if not isinstance(stem_uri, str) or not stem_uri.startswith("http://id.who.int/"):
        return None
    entity = proxy_who_icd_request(stem_uri.removeprefix("http://id.who.int/")).json()
    if not isinstance(entity, dict):
        return None
    if not title:
        title = _text(entity.get("title") or entity.get("label"))
    if not title:
        return None
    item = {
        "code": code,
        "title": cluster_title(code, title),
        "uri": uri,
        "release": DEFAULT_ICD11_RELEASE,
        "postcoordination": False,
        # The first stem only: selection_refusal checks any further "/" stems.
        "leaf": not entity.get("child"),
        "extension": code.startswith("X"),
    }
    if "&" not in code and "/" not in code:
        item.update(search_context_from_entity(entity))
    item["browser_url"] = browser_url(stem_uri)
    return item


def search_words(query: str) -> dict:
    """WHO's word suggestions for ``query`` (at most 20, plain text).

    The same bounded MMS search POST as ``search_terms`` with
    ``includeKeywordResult=true``, which is what makes WHO return ``words``.
    ``search_terms`` and its request body stay unchanged: its frozen
    fixtures and cache key depend on them.
    """
    body = urlencode({
        "q": query.strip(),
        "includeKeywordResult": "true",
        "useFlexiSearch": "false",
        "flatResults": "true",
        "medicalCodingMode": "true",
    }).encode()
    upstream = proxy_who_icd_request(
        f"icd/release/11/{DEFAULT_ICD11_RELEASE}/mms/search",
        method="POST",
        body=body,
        content_type="application/x-www-form-urlencoded",
    )
    raw = upstream.json()
    words = raw.get("words") if isinstance(raw, dict) else None
    if words is None:
        words = []
    if not isinstance(words, list):
        raise WhoIcdApiUnavailable("WHO word suggestions were malformed")
    labels = [
        label for label in (
            _plain(word.get("label")) for word in words if isinstance(word, dict)
        ) if label
    ]
    return {
        "words": labels[:_MAX_WORDS],
        "truncated": bool(raw.get("wordSuggestionsChopped")) or len(labels) > _MAX_WORDS,
    }


def validate_expression(code: str) -> dict:
    """Whether WHO accepts ``code``, and whether a certificate could take it.

    ``code`` is already ``valid_code``-checked by the route. A WHO-valid
    expression may still not be a final code for a death certificate:
    ``certificate_refusal`` says why.
    """
    repeated = repeated_part(code)
    if repeated:
        return {
            "valid": False,
            "refusal": {
                "code": "REPEATED_PART",
                "message": f"{repeated} appears more than once in the expression.",
            },
        }
    item = codeinfo_item(code)
    if item is None:
        return {
            "valid": False,
            "refusal": {"code": "CODE_NOT_FOUND", "message": "WHO does not recognise this code."},
        }
    refusal = selection_refusal(item)
    return {
        "valid": True,
        "item": item,
        "certificate_refusal": (
            {"code": "NOT_CERTIFIABLE", "message": refusal} if refusal else None
        ),
    }
