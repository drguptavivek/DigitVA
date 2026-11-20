"""Data for the printable WHO-form cause-of-death certificate of a coded case.

Policy: docs/policy/cod-certificate-export.md. ``certificate_context`` returns
``None`` for every reason the certificate is unavailable (not coded, not a
tree project, no final), so the route answers one 404 and reveals none of
them. Callers authorize ``Action.VIEW`` first. PII follows the one viewer gate
(``viewer_pii_service.should_redact_pii``).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    VaDeathRegister,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaSubmissions,
    VaUsers,
)
from app.services.authz.grants import has_tree_condition
from app.services.coding_service import get_project_for_submission
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.final_cod_authority_service import get_authoritative_final_cod_record
from app.services.register_pii_accessor import open_register_pii
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import CODING_BUCKET_CODED, coding_bucket
from app.services.workflow.state_store import get_submission_workflow_state
from app.utils import pii_crypto

#: WHO form: lines (a) to (d); a certificate may carry a fifth (MAX_PART1_LINES).
_MIN_LINES = 4
_UNITS = (("Y", "year"), ("M", "month"), ("W", "week"), ("D", "day"), ("H", "hour"), ("M", "minute"))
_DURATION = re.compile(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def is_coded_tree_case(va_sid: str, project_id: str | None) -> bool:
    """Coded (coder or reviewer final) in a project with an active org level."""
    if not project_id:
        return False
    if coding_bucket(get_submission_workflow_state(va_sid)) != CODING_BUCKET_CODED:
        return False
    # A confirmed duplicate (or a withdrawn case) gets no certificate.
    return bool(db.session.scalar(sa.select(sa.and_(
        has_tree_condition(project_id),
        not_confirmed_duplicate_condition(sa.literal(va_sid)),
    ))))


def interval_text(value: str | None) -> str:
    """An ISO-8601 duration as "3 days"; anything unparseable is shown as stored."""
    if not value:
        return ""
    match = _DURATION.match(value)
    if not match or not any(match.groups()):
        return value
    parts = []
    for count, (_, unit) in zip(match.groups(), _UNITS):
        if count:
            parts.append(f"{count} {unit}{'' if count == '1' else 's'}")
    return ", ".join(parts)


def _lines(certificate: dict | None) -> tuple[list[dict], list[dict]]:
    """``(Part I lines, Part II conditions)``; Part I padded to the form's four lines."""
    certificate = certificate if isinstance(certificate, dict) else {}
    lines = []
    for line in certificate.get("Part1") or []:
        conditions = [
            {"text": c.get("Text") or "", "code": c.get("Code") or ""}
            for c in (line or {}).get("Conditions") or []
            if isinstance(c, dict)
        ]
        interval = next((c.get("Interval") for c in (line or {}).get("Conditions") or [] if isinstance(c, dict) and c.get("Interval")), "")
        lines.append({"conditions": conditions, "interval": interval_text(interval)})
    lines += [{"conditions": [], "interval": ""}] * max(0, _MIN_LINES - len(lines))
    part2 = [
        {"text": c.get("Text") or "", "code": c.get("Code") or ""}
        for c in ((certificate.get("Part2") or {}).get("Conditions") or [])
        if isinstance(c, dict)
    ]
    return lines, part2


def _register_pii(va_sid: str) -> dict:
    """The sealed register fields of the case's web-intake row, ``{}`` when there is none or it will not open."""
    row = db.session.scalar(
        sa.select(VaDeathRegister).where(VaDeathRegister.va_sid == va_sid).order_by(VaDeathRegister.created_at).limit(1)
    )
    if row is None:
        return {}
    try:
        return open_register_pii(
            [row],
            only=("deceased_name", "informant_name", "place_of_death", "address",
                  "address_house_street", "address_village_ward", "address_landmark"),
        )[row.death_id]
    except pii_crypto.PiiCryptoError:
        current_app.logger.error("cod certificate: register row %s did not open", row.death_id)
        return {}


def _user_name(user_id) -> str | None:
    return db.session.scalar(sa.select(VaUsers.name).where(VaUsers.user_id == user_id)) if user_id else None


def certificate_context(user, va_sid: str) -> dict | None:
    """Template data of the certificate, or ``None`` when it is not available."""
    submission = db.session.get(VaSubmissions, va_sid)
    project = get_project_for_submission(va_sid) if submission else None
    if submission is None or not is_coded_tree_case(va_sid, project.project_id if project else None):
        return None
    record = get_authoritative_final_cod_record(va_sid)
    if record is None:
        return None
    reviewer_final = coder_final = step1 = None
    if record.source_role == "reviewer":
        final = reviewer_final = db.session.get(VaReviewerFinalAssessments, record.reviewer_final_assessment_id)
        if record.coder_final_assessment_id:
            coder_final = db.session.get(VaFinalAssessments, record.coder_final_assessment_id)
        step1_id = final.source_reviewer_initial_assessment_id
        step1 = db.session.get(VaReviewerInitialAssessments, step1_id) if step1_id else None
    else:
        final = coder_final = db.session.get(VaFinalAssessments, record.coder_final_assessment_id)
        step1_id = final.source_initial_assessment_id
        step1 = db.session.get(VaInitialAssessments, step1_id) if step1_id else None
    # A masked DORIS final carries only the cause: its certificate is on Step 1.
    certificate = final.doris_certificate or (step1.doris_certificate if step1 else None)
    part1, part2 = _lines(certificate)

    redact = should_redact_pii(user, project_id=project.project_id)
    pii = {} if redact else _register_pii(va_sid)
    address = ", ".join(
        p for p in (pii.get("address"), pii.get("address_house_street"),
                    pii.get("address_village_ward"), pii.get("address_landmark")) if p
    )
    if reviewer_final is None:
        outcome = "not reviewed"
    elif coder_final is not None and reviewer_final.va_conclusive_cod == coder_final.va_conclusive_cod:
        outcome = "reviewer agreed"
    else:
        outcome = "reviewer changed the cause"
    admin = (certificate or {}).get("AdministrativeData") or {}
    coded_by = coder_final.va_finassess_by if coder_final else None
    return {
        "project_name": project.project_name,
        "case_id": submission.va_uniqueid_masked,
        "age": submission.va_deceased_age,
        "sex": submission.va_deceased_gender,
        "date_of_death": admin.get("DateDeath") or "",
        "part1": part1,
        "part2": part2,
        "underlying_cause": final.va_conclusive_cod,
        "outcome": outcome,
        "coded_at": record.effective_at,
        "coded_by": None if redact else _user_name(coded_by),
        "reviewed_by": None if redact or reviewer_final is None else _user_name(reviewer_final.va_rfinassess_by),
        "redacted": redact,
        "deceased_name": pii.get("deceased_name"),
        "address": address or None,
        "place_of_death": pii.get("place_of_death"),
        "respondent": pii.get("informant_name"),
        "real_id": None if redact else submission.va_uniqueid_real,
        "generated_at": datetime.now(UTC),
    }
