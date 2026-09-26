"""Short-lived signed proof binding clinical DORIS input and processor results."""

from __future__ import annotations

import hmac

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.services.doris_certificate import normalize_certificate
from app.services.doris_processing import (
    certificate_digest as calculate_certificate_digest,
)
from app.services.doris_processing import (
    processor_result_digest,
    validate_processor_envelope,
)

_SALT = "digitva-doris-clinical-process-v1"
_DEFAULT_MAX_AGE_SECONDS = 15 * 60


class ProcessProofError(ValueError):
    """Base class for a process proof that final save cannot accept."""


class ProcessProofExpired(ProcessProofError):
    pass


class ProcessProofInvalid(ProcessProofError):
    pass


class ProcessProofContextMismatch(ProcessProofError):
    pass


class ProcessProofCertificateChanged(ProcessProofError):
    pass


class ProcessProofResultMismatch(ProcessProofError):
    pass


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT)


def _context(
    *,
    va_sid: str,
    role: str,
    user_id,
    allocation_id,
    payload_version_id,
    icd_release: str,
    who_image_digest: str,
) -> dict[str, str]:
    return {
        "va_sid": str(va_sid),
        "role": str(role),
        "user_id": str(user_id),
        "allocation_id": str(allocation_id),
        "payload_version_id": str(payload_version_id),
        "icd_release": str(icd_release),
        "who_image_digest": str(who_image_digest),
    }


def generate_process_proof(
    *,
    certificate_digest: str,
    result_digest: str,
    va_sid: str,
    role: str,
    user_id,
    allocation_id,
    payload_version_id,
    icd_release: str,
    who_image_digest: str,
) -> str:
    claims = {
        "proof_version": 1,
        "certificate_digest": certificate_digest,
        "result_digest": result_digest,
        **_context(
            va_sid=va_sid,
            role=role,
            user_id=user_id,
            allocation_id=allocation_id,
            payload_version_id=payload_version_id,
            icd_release=icd_release,
            who_image_digest=who_image_digest,
        ),
    }
    return _serializer().dumps(claims)


def verify_process_proof(
    token: str,
    *,
    certificate_digest: str,
    result_digest: str,
    va_sid: str,
    role: str,
    user_id,
    allocation_id,
    payload_version_id,
    icd_release: str,
    who_image_digest: str,
    max_age_seconds: int | None = None,
) -> dict[str, str | int]:
    """Verify proof context and hashes, with distinct final-save failure modes."""

    if not isinstance(token, str) or not token:
        raise ProcessProofInvalid("DORIS process proof is missing.")
    max_age = max_age_seconds
    if max_age is None:
        max_age = int(
            current_app.config.get(
                "DORIS_PROCESS_TOKEN_MAX_AGE_SECONDS", _DEFAULT_MAX_AGE_SECONDS
            )
        )
    try:
        claims = _serializer().loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise ProcessProofExpired("DORIS process proof has expired.") from exc
    except BadSignature as exc:
        raise ProcessProofInvalid("DORIS process proof is invalid.") from exc
    if not isinstance(claims, dict) or claims.get("proof_version") != 1:
        raise ProcessProofInvalid("DORIS process proof is invalid.")

    expected_context = _context(
        va_sid=va_sid,
        role=role,
        user_id=user_id,
        allocation_id=allocation_id,
        payload_version_id=payload_version_id,
        icd_release=icd_release,
        who_image_digest=who_image_digest,
    )
    if any(
        not hmac.compare_digest(str(claims.get(key, "")), value)
        for key, value in expected_context.items()
    ):
        raise ProcessProofContextMismatch("DORIS process context has changed.")
    if not hmac.compare_digest(
        str(claims.get("certificate_digest", "")), certificate_digest
    ):
        raise ProcessProofCertificateChanged("DORIS certificate has changed.")
    if not hmac.compare_digest(str(claims.get("result_digest", "")), result_digest):
        raise ProcessProofResultMismatch("DORIS processor results have changed.")
    return claims


def verify_process_submission(
    token: str,
    *,
    certificate: dict,
    doris_result: dict,
    codedit_result: dict,
    submitted_result_digest: str,
    va_sid: str,
    role: str,
    user_id,
    allocation_id,
    payload_version_id,
    icd_release: str,
    who_image_digest: str,
    max_age_seconds: int | None = None,
) -> dict:
    """Verify final-save certificate and engine envelopes without another WHO call."""

    normalized = normalize_certificate(certificate, release=icd_release)
    cert_digest = calculate_certificate_digest(normalized)
    claims = verify_process_proof(
        token,
        certificate_digest=cert_digest,
        result_digest=str(submitted_result_digest),
        va_sid=va_sid,
        role=role,
        user_id=user_id,
        allocation_id=allocation_id,
        payload_version_id=payload_version_id,
        icd_release=icd_release,
        who_image_digest=who_image_digest,
        max_age_seconds=max_age_seconds,
    )
    doris = validate_processor_envelope("doris", doris_result)
    codedit = validate_processor_envelope("codedit", codedit_result)
    result_digest = processor_result_digest(
        doris,
        codedit,
        release=icd_release,
        who_image_digest=who_image_digest,
    )
    if not hmac.compare_digest(result_digest, str(submitted_result_digest)):
        raise ProcessProofResultMismatch("DORIS processor results have changed.")
    return {
        "certificate": normalized,
        "certificate_digest": cert_digest,
        "result_digest": result_digest,
        "doris": doris,
        "codedit": codedit,
        "claims": claims,
    }
