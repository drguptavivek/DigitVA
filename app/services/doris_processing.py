"""Run a validated death certificate through local WHO DORIS and CoDEdit."""

from __future__ import annotations

import hashlib
import json

from app.services.doris_certificate import (
    canonical_json_bytes,
    normalize_certificate,
    verify_certificate_codes,
)
from app.services.who_icd_api import (
    DEFAULT_ICD11_RELEASE,
    WhoIcdApiTimeout,
    WhoIcdApiUnavailable,
    post_mortality_processor,
)

_DORIS_KEYS = {
    "code",
    "stemCode",
    "uri",
    "stemURI",
    "report",
    "tabularReport",
    "reject",
    "error",
    "warning",
}
_CODEDIT_KEYS = {"report", "tabularReport", "issueIds"}


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def certificate_digest(certificate: dict) -> str:
    return canonical_digest(certificate)


def processor_result_digest(
    doris: dict,
    codedit: dict,
    *,
    release: str,
    who_image_digest: str,
) -> str:
    return canonical_digest(
        {
            "icd_release": release,
            "who_image_digest": who_image_digest,
            "doris": doris,
            "codedit": codedit,
        }
    )


def validate_processor_envelope(name: str, envelope: object) -> dict:
    """Validate a client-resubmitted engine envelope without calling WHO."""

    if name not in {"doris", "codedit"} or not isinstance(envelope, dict):
        raise ValueError("Invalid DORIS processor result.")
    if set(envelope) != {"status", "result"}:
        raise ValueError("Invalid DORIS processor result.")
    status = envelope["status"]
    if status not in {
        "completed",
        "rejected",
        "timeout",
        "malformed_response",
        "unavailable",
    }:
        raise ValueError("Invalid DORIS processor status.")
    result = envelope["result"]
    if status in {"timeout", "malformed_response", "unavailable"}:
        if result is not None:
            raise ValueError("Failed DORIS processor results must be empty.")
        return envelope
    expected_keys = _DORIS_KEYS if name == "doris" else _CODEDIT_KEYS
    if not isinstance(result, dict) or not expected_keys.issubset(result):
        raise ValueError("Invalid DORIS processor result.")
    if name == "doris":
        reject = result.get("reject")
        if not isinstance(reject, bool) or (status == "rejected") != reject:
            raise ValueError("DORIS rejection status does not match its result.")
    elif status != "completed":
        raise ValueError("CoDEdit cannot have a rejected status.")
    return envelope


def _run_engine(name: str, certificate: dict, release: str) -> dict:
    try:
        status_code, content = post_mortality_processor(name, certificate, release=release)
    except WhoIcdApiTimeout:
        return {"status": "timeout", "result": None}
    except WhoIcdApiUnavailable:
        return {"status": "unavailable", "result": None}
    if status_code < 200 or status_code >= 300:
        return {"status": "unavailable", "result": None}
    try:
        result = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "malformed_response", "result": None}
    expected_keys = _DORIS_KEYS if name == "doris" else _CODEDIT_KEYS
    if not isinstance(result, dict) or not expected_keys.issubset(result):
        return {"status": "malformed_response", "result": None}
    if name == "doris" and not isinstance(result["reject"], bool):
        return {"status": "malformed_response", "result": None}
    status = "rejected" if name == "doris" and result["reject"] else "completed"
    return {"status": status, "result": result}


def process_certificate(
    payload: dict,
    *,
    release: str = DEFAULT_ICD11_RELEASE,
    who_image_digest: str = "",
) -> dict:
    """Validate a phase-0 process payload and return both independent results."""

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported DORIS process schema version.")
    if set(payload) != {"schema_version", "client_revision", "certificate"}:
        raise ValueError("DORIS process payload contains unsupported fields.")
    revision = payload.get("client_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("client_revision must be a non-negative integer.")
    certificate = normalize_certificate(payload.get("certificate"), release=release)
    verify_certificate_codes(certificate, release=release)

    doris = _run_engine("doris", certificate, release)
    codedit = _run_engine("codedit", certificate, release)
    return {
        "schema_version": 1,
        "client_revision": revision,
        "icd_release": release,
        "certificate": certificate,
        "certificate_digest": certificate_digest(certificate),
        "result_digest": processor_result_digest(
            doris,
            codedit,
            release=release,
            who_image_digest=who_image_digest,
        ),
        "doris": doris,
        "codedit": codedit,
    }
