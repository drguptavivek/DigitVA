"""ICD-11 titles for the codes the coding screens offer as one-click choices.

Titles come from the local WHO ICD-11 API (``get_icd11_codeinfo``, the same
call DORIS and the code-info route use), never from ``mas_icd11_mms``. A
postcoordinated expression is titled part by part, stem first, as DORIS does.
When the API is unavailable the label is the code alone and the page still
works; one outage costs one timeout per request, not one per code.
"""

from __future__ import annotations

import html
import logging
import re

from flask import current_app, g

from app import cache
from app.services.icd_coding_value import extract_icd11_code_expression
from app.services.who_icd_api import (
    DEFAULT_ICD11_RELEASE,
    WhoIcdApiUnavailable,
    get_icd11_codeinfo,
    proxy_who_icd_request,
)

log = logging.getLogger(__name__)

# The separators DORIS uses inside an expression; the capture keeps them in the split.
_EXPRESSION_PARTS = re.compile(r"\s*([&/])\s*")
_TAG_RE = re.compile(r"<[^>]+>")
_CACHE_PREFIX = "icd11_title:"
# codeinfo carries no title of its own; the stem entity behind its stemId does.
_WHO_PREFIX = "http://id.who.int/"
_MAX_CODE_LENGTH = 256
_DOWN_FLAG = "_icd11_title_api_down"
# Shared across requests and workers: after an outage, page renders skip the
# API for this long instead of each paying a timeout.
_DOWN_KEY = f"{_CACHE_PREFIX}api_down"
_DOWN_SECONDS = 60


def _plain_text(value) -> str:
    if isinstance(value, dict):
        value = value.get("@value") or value.get("label") or ""
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAG_RE.sub("", value)).strip()


def _who_title(token: str) -> str:
    """WHO's title for one code, read as routes/api/doris_clinical.py _codeinfo_item reads it.

    codeinfo's own title when it has one, else the title of the stem entity its
    stemId points at. "" when WHO has no such code.
    """
    info = get_icd11_codeinfo(token, release=DEFAULT_ICD11_RELEASE)
    if not isinstance(info, dict) or info.get("code") != token:
        return ""
    title = _plain_text(info.get("title") or info.get("label"))
    if title:
        return title
    stem_uri = info.get("stemId")
    if not isinstance(stem_uri, str) or not stem_uri.startswith(_WHO_PREFIX):
        return ""
    response = proxy_who_icd_request(stem_uri.removeprefix(_WHO_PREFIX))
    if response.status_code == 404:
        return ""
    if response.status_code != 200:
        # Not an answer about the code: never cached as "no such code".
        raise WhoIcdApiUnavailable(f"WHO ICD API entity request returned {response.status_code}")
    entity = response.json()
    if not isinstance(entity, dict):
        return ""
    return _plain_text(entity.get("title") or entity.get("label"))


def _token_title(token: str) -> str | None:
    """Title of one stem or extension code; None when WHO has no such code.

    The WHO answer (including "no such code", stored as "") is cached as the
    ICD search results are. An unavailable API is not cached.
    """
    key = f"{_CACHE_PREFIX}{DEFAULT_ICD11_RELEASE}:{token}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    title = _who_title(token)
    cache.set(
        key,
        title,
        timeout=current_app.config.get("ICD_SEARCH_CACHE_TIMEOUT", 60 * 60 * 24 * 7),
    )
    return title or None


def icd11_title(expression: str | None) -> str | None:
    """Title of a code or postcoordinated expression, or None when unknown.

    An expression with several parts gives every part's title joined with
    `` + `` (stem first). Any part without a title makes the whole title None,
    so a half-titled expression is never shown.
    """
    text = expression.strip() if isinstance(expression, str) else ""
    if not text or len(text) > _MAX_CODE_LENGTH or getattr(g, _DOWN_FLAG, False):
        return None
    if cache.get(_DOWN_KEY):
        setattr(g, _DOWN_FLAG, True)
        return None
    tokens = [token for token in _EXPRESSION_PARTS.split(text)[::2] if token]
    try:
        titles = [_token_title(token) for token in tokens]
    except (WhoIcdApiUnavailable, ValueError):
        setattr(g, _DOWN_FLAG, True)
        cache.set(_DOWN_KEY, 1, timeout=_DOWN_SECONDS)
        log.warning("ICD-11 titles unavailable from the WHO API; showing codes only")
        return None
    if not titles or any(title is None for title in titles):
        return None
    return " + ".join(titles)


def icd11_label(expression: str | None) -> str:
    """``CODE — Title`` for one code or expression, the code alone when untitled, '' for none."""
    text = expression.strip() if isinstance(expression, str) else ""
    if not text:
        return ""
    title = icd11_title(text)
    return f"{text} — {title}" if title else text


def icd11_alternatives_label(mapping: str | None) -> str | None:
    """Label for a WHO target that may list alternatives split on ``/``, or None for no target.

    ``/`` separates alternative targets here (as in ``smartva_icd11_alternatives``),
    so each alternative is labelled on its own.
    """
    if not mapping or not isinstance(mapping, str):
        return None
    labels = [icd11_label(part) for part in mapping.split("/") if part.strip()]
    return " / ".join(label for label in labels if label) or None


def stored_cod_label(stored: str | None) -> str:
    """Label for a stored COD value (``"<CODE> <title>"``): the leading code with WHO's title.

    The stored text is kept when WHO gives no title (or the API is down), since
    it already carries the title the coder saw; text without a code is kept too.
    """
    code = extract_icd11_code_expression(stored)
    title = icd11_title(code) if code else None
    if title:
        return f"{code} — {title}"
    return stored or ""
