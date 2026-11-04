"""Small, fixed-target client for the locally deployed WHO ICD-11 API.

The browser-facing proxy in :mod:`app.routes.api.icd11` uses this module so
that the WHO API host never comes from a request.  The same client is used by
ICD-11 code-expression validation; keeping both calls here makes the timeout,
headers and failure behaviour consistent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from urllib.parse import quote, urlsplit

import redis
import requests
from flask import current_app
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_ICD11_RELEASE = "2026-01"

_MAX_RESOURCE_LENGTH = 1024
_MAX_QUERY_LENGTH = 4096
_MAX_BODY_LENGTH = 128 * 1024
_MAX_RESPONSE_LENGTH = 2 * 1024 * 1024
_RELEASE_RE = re.compile(r"^\d{4}-\d{2}$")
_SAFE_RESOURCE_RE = re.compile(r"^[A-Za-z0-9._~%+:/&=\- ]+$")
_CACHE_PREFIX = "icd11api:"
_BOUNDARY_RE = re.compile(r";\s*boundary=(\"[^\"]+\"|[^;]+)", re.IGNORECASE)
_CACHED_HEADERS = ("Content-Type", "API-Version", "Vary")
_CACHEABLE_STATUSES = {200, 404}


class WhoIcdApiUnavailable(RuntimeError):
    """The local WHO API could not return a usable response."""


class WhoIcdApiTimeout(WhoIcdApiUnavailable):
    """The local WHO API request exceeded its configured deadline."""


def _base_url() -> str:
    configured = str(current_app.config.get("ICD11_API_BASE_URL") or "").strip()
    parsed = urlsplit(configured)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WhoIcdApiUnavailable("WHO ICD API base URL is not configured")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WhoIcdApiUnavailable("WHO ICD API base URL is invalid")
    return configured.rstrip("/")


def _validate_resource(resource: str) -> str:
    resource = (resource or "").strip()
    if (
        not resource
        or len(resource) > _MAX_RESOURCE_LENGTH
        or resource.startswith("/")
        or "\\" in resource
        or ".." in resource
        or not _SAFE_RESOURCE_RE.fullmatch(resource)
    ):
        raise ValueError("Invalid WHO ICD API resource.")

    # ECT only needs the MMS linearization, entity details and the schema used
    # for post-coordination.  In particular, do not turn this endpoint into a
    # general proxy for Swagger, admin or unrelated services.
    release_prefix = "icd/release/11/"
    if resource.startswith(release_prefix):
        suffix = resource[len(release_prefix) :]
        allowed = (
            suffix == "mms"
            or suffix.startswith("mms/")
            or suffix == f"{DEFAULT_ICD11_RELEASE}/mms"
            or suffix.startswith(f"{DEFAULT_ICD11_RELEASE}/mms/")
        )
        if allowed:
            return resource
    if resource == "icd/release/11/mms" or resource.startswith("icd/release/11/mms/"):
        return resource
    if resource.startswith("icd/entity/") and resource[len("icd/entity/") :].isdigit():
        return resource
    schema_prefix = "icd/schema/otherPostcoordination"
    if resource == schema_prefix or resource.startswith(schema_prefix + "/"):
        return resource
    raise ValueError("WHO ICD API resource is not available through DigitVA.")


def _processor_resource(processor: str, release: str) -> str:
    if processor not in {"doris", "codedit"}:
        raise ValueError("Unknown WHO mortality processor.")
    if not _RELEASE_RE.fullmatch(release):
        raise ValueError("Invalid ICD-11 release.")
    return f"icd/release/11/{release}/{processor}"


def _request_timeout() -> tuple[float, float]:
    timeout = float(current_app.config.get("ICD11_API_TIMEOUT_SECONDS", 5))
    timeout = min(max(timeout, 0.1), 30.0)
    return timeout, timeout


def _cache_timeout() -> int:
    return int(current_app.config.get("ICD11_API_CACHE_TIMEOUT", 0) or 0)


def _is_cacheable_request(method: str, resource: str) -> bool:
    # ECT searches with a POST that only reads; every other POST stays live.
    return method == "GET" or (
        method == "POST" and resource.endswith("/mms/search")
    )


def _cache_key(url: str, method: str, body: bytes, content_type: str | None) -> str:
    # The headers are fixed in proxy_who_icd_request; they are part of the key
    # so changing them there cannot serve answers fetched under the old ones.
    ctype = content_type or ""
    if body:
        # ECT posts multipart/form-data whose random boundary is in the body;
        # drop it so the same search hashes the same.
        match = _BOUNDARY_RE.search(ctype)
        if match:
            boundary = match.group(1).strip('"')
            body = body.replace(boundary.encode(), b"-")
            ctype = _BOUNDARY_RE.sub("", ctype)
    raw = "\n".join((url, method, "en", "v2", ctype, hashlib.sha256(body).hexdigest()))
    return _CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:40]


_cache_clients: dict[str, redis.Redis] = {}


def _cache_client() -> redis.Redis | None:
    """Client for the dedicated ICD cache Redis, or None when it is not set."""
    url = str(current_app.config.get("ICD11_API_CACHE_REDIS_URL") or "").strip()
    if not url:
        return None
    if url not in _cache_clients:
        # Short timeouts: a slow cache must cost less than the API call it saves.
        _cache_clients[url] = redis.Redis.from_url(
            url, socket_timeout=0.5, socket_connect_timeout=0.5
        )
    return _cache_clients[url]


def _cache_get(client: redis.Redis, key: str) -> requests.Response | None:
    # Never log the exception text or URL: the connection URL holds the password.
    try:
        raw = client.get(key)
        if raw is None:
            return None
        stored = json.loads(raw)
        response = requests.Response()
        response.status_code = int(stored["status"])
        response._content = base64.b64decode(stored["body"])
        response._content_consumed = True
        response.headers.update(stored["headers"])
        return response
    except Exception:  # a broken cache must never fail the lookup
        logger.warning("WHO ICD API cache read failed")
        return None


def _cache_set(
    client: redis.Redis, key: str, response: requests.Response, timeout: int
) -> None:
    headers = {
        name: response.headers[name]
        for name in _CACHED_HEADERS
        if response.headers.get(name)
    }
    try:
        client.set(
            key,
            json.dumps(
                {
                    "status": response.status_code,
                    "headers": headers,
                    "body": base64.b64encode(response.content).decode("ascii"),
                }
            ),
            ex=timeout,
        )
    except Exception:
        logger.warning("WHO ICD API cache write failed")


def proxy_who_icd_request(
    resource: str,
    *,
    method: str = "GET",
    query_string: bytes = b"",
    body: bytes = b"",
    content_type: str | None = None,
) -> requests.Response:
    """Make one bounded request to the configured local WHO API.

    ``resource`` is deliberately validated here as well as at the Flask route
    so future callers cannot accidentally bypass the proxy's allow-list.

    Successful (200) and not-found (404) answers to GETs and to the ECT
    ``mms/search`` POST are cached in the dedicated Redis named by
    ``ICD11_API_CACHE_REDIS_URL`` for ``ICD11_API_CACHE_TIMEOUT`` seconds
    (an empty URL or 0 turns it off).  Validation runs before the lookup; other POSTs and
    errors are never cached.
    """

    resource = _validate_resource(resource)
    if len(query_string) > _MAX_QUERY_LENGTH or len(body) > _MAX_BODY_LENGTH:
        raise ValueError("WHO ICD API request is too large.")
    if method not in {"GET", "POST"}:
        raise ValueError("WHO ICD API method is not available through DigitVA.")
    if method == "GET" and body:
        raise ValueError("GET requests cannot contain a body.")

    try:
        query = query_string.decode("ascii") if query_string else ""
    except UnicodeDecodeError as exc:
        raise ValueError("WHO ICD API query is malformed.") from exc
    url = f"{_base_url()}/{resource}"
    if query:
        url += f"?{query}"

    headers = {
        "Accept": "application/json",
        "Accept-Language": "en",
        "API-Version": "v2",
    }
    if body:
        headers["Content-Type"] = content_type or "application/json"

    cache_timeout = _cache_timeout() if _is_cacheable_request(method, resource) else 0
    client = _cache_client() if cache_timeout > 0 else None
    key = _cache_key(url, method, body, content_type) if client else ""
    if key:
        cached = _cache_get(client, key)
        if cached is not None:
            return cached

    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            data=body or None,
            timeout=_request_timeout(),
            allow_redirects=False,
            stream=True,
        )
    except requests.Timeout as exc:
        raise WhoIcdApiTimeout("WHO ICD API request timed out") from exc
    except requests.RequestException as exc:
        raise WhoIcdApiUnavailable("WHO ICD API request failed") from exc

    if 300 <= response.status_code < 400 or response.status_code >= 500:
        response.close()
        raise WhoIcdApiUnavailable("WHO ICD API returned an unusable response")
    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit() and int(content_length) > _MAX_RESPONSE_LENGTH:
        response.close()
        raise WhoIcdApiUnavailable("WHO ICD API response is too large")
    try:
        content = response.raw.read(_MAX_RESPONSE_LENGTH + 1)
    except Urllib3ReadTimeoutError as exc:
        raise WhoIcdApiTimeout("WHO ICD API response timed out") from exc
    except (AttributeError, OSError, requests.RequestException, Urllib3HTTPError) as exc:
        response.close()
        raise WhoIcdApiUnavailable("WHO ICD API response could not be read") from exc
    finally:
        response.close()
    if len(content) > _MAX_RESPONSE_LENGTH:
        raise WhoIcdApiUnavailable("WHO ICD API response is too large")
    response._content = content
    response._content_consumed = True
    if key and response.status_code in _CACHEABLE_STATUSES:
        _cache_set(client, key, response, cache_timeout)
    return response


def post_mortality_processor(
    processor: str,
    certificate: dict,
    *,
    release: str = DEFAULT_ICD11_RELEASE,
    max_response_bytes: int = 512 * 1024,
) -> tuple[int, bytes]:
    """POST one certificate to a fixed local DORIS or CoDEdit endpoint."""

    resource = _processor_resource(processor, release)
    body = json.dumps(
        certificate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(body) > 32 * 1024:
        raise ValueError("DORIS certificate is too large.")

    headers = {
        "Accept": "application/json",
        "Accept-Language": "en",
        "API-Version": "v2",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            f"{_base_url()}/{resource}",
            headers=headers,
            data=body,
            timeout=_request_timeout(),
            allow_redirects=False,
            stream=True,
        )
    except requests.Timeout as exc:
        raise WhoIcdApiTimeout("WHO mortality processor timed out") from exc
    except requests.RequestException as exc:
        raise WhoIcdApiUnavailable("WHO mortality processor request failed") from exc

    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit() and int(content_length) > max_response_bytes:
        response.close()
        raise WhoIcdApiUnavailable("WHO mortality processor response is too large")
    try:
        content = response.raw.read(max_response_bytes + 1)
    except Urllib3ReadTimeoutError as exc:
        raise WhoIcdApiTimeout("WHO mortality processor response timed out") from exc
    except (AttributeError, OSError, requests.RequestException, Urllib3HTTPError) as exc:
        raise WhoIcdApiUnavailable(
            "WHO mortality processor response could not be read"
        ) from exc
    finally:
        response.close()
    if len(content) > max_response_bytes:
        raise WhoIcdApiUnavailable("WHO mortality processor response is too large")
    return response.status_code, content


def get_icd11_codeinfo(
    expression: str,
    release: str = DEFAULT_ICD11_RELEASE,
) -> dict | None:
    """Return WHO ``codeinfo`` for a stem or post-coordinated expression.

    WHO returns 404 for an invalid expression; callers use ``None`` for that
    case.  Network failures, upstream 5xx responses and malformed JSON raise
    :class:`WhoIcdApiUnavailable` so save validation can fail closed.
    """

    expression = (expression or "").strip()
    release = (release or "").strip()
    if not expression or len(expression) > 256:
        return None
    if not _RELEASE_RE.fullmatch(release):
        raise ValueError("Invalid ICD-11 release.")
    encoded_expression = quote(expression, safe="")
    resource = (
        f"icd/release/11/{release}/mms/codeinfo/{encoded_expression}"
    )
    response = proxy_who_icd_request(resource)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise WhoIcdApiUnavailable("WHO ICD API rejected codeinfo request")
    try:
        payload = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise WhoIcdApiUnavailable("WHO ICD API returned malformed codeinfo") from exc
    if not isinstance(payload, dict):
        raise WhoIcdApiUnavailable("WHO ICD API returned malformed codeinfo")
    return payload
