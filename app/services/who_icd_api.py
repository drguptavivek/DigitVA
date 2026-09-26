"""Small, fixed-target client for the locally deployed WHO ICD-11 API.

The browser-facing proxy in :mod:`app.routes.api.icd11` uses this module so
that the WHO API host never comes from a request.  The same client is used by
ICD-11 code-expression validation; keeping both calls here makes the timeout,
headers and failure behaviour consistent.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlsplit

import requests
from flask import current_app
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

DEFAULT_ICD11_RELEASE = "2026-01"

_MAX_RESOURCE_LENGTH = 1024
_MAX_QUERY_LENGTH = 4096
_MAX_BODY_LENGTH = 128 * 1024
_MAX_RESPONSE_LENGTH = 2 * 1024 * 1024
_RELEASE_RE = re.compile(r"^\d{4}-\d{2}$")
_SAFE_RESOURCE_RE = re.compile(r"^[A-Za-z0-9._~%+:/&=\- ]+$")


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
