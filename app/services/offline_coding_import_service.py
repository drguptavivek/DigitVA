"""Collect Plus standalone push: the ``standalone`` and ``offline_coding``
objects of ``POST /api/v1/intake/submissions`` (Path C).

Contract: docs/policy/offline-api-contract.md section 17. Policy:
docs/policy/doris-cod-workflow.md "Collect Plus offline parity",
docs/policy/coding-workflow-state-machine.md "Imported offline final".

The interview is stored by the ordinary device upload. Offline coding is never
re-run through DORIS or the WHO service: it is held server-side
(``va_bundle_pending_coding``, ``result.origin = collect_plus_offline``) until
the case leaves the attachment and SmartVA states, then the bundle applier
(``bundle_ingest_service.apply_pending_coding``) calls ``apply_held``, which
takes the pushing coder's allocation and saves the result as their final with
the server's own ICD-11 allowability re-check recorded beside it. A
disagreement is flagged on the provenance and sends the case to the reviewer
pool at once instead of after the recode window.

The device UUID is a claim checked against the bearer session's own device;
the process token and local digests are opaque provenance, never verified.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    MasIcd11Mms,
    MasOrgUnit,
    VaAccessRoles,
    VaBundlePendingCoding,
    VaFinalAssessments,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import coder_cod_service as coder_cod
from app.services import coder_workflow_service as coder_workflow
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.authz import resolve_grants
from app.services.cod_entry_mode import cod_entry_mode_snapshot, project_mode
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.services.demo_project_service import (
    get_demo_expiry_for_submission,
    is_demo_training_submission,
)
from app.services.final_cod_authority_service import upsert_final_cod_authority
from app.services.icd11_mms_service import POLICY_EDITABLE_CLASS_KINDS
from app.services.icd_coding_policy import coding_context_for_submission, policy_ok_columns
from app.services.icd_coding_value import extract_icd11_code_expression, extract_icd_code
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.who_icd_api import DEFAULT_ICD11_RELEASE
from app.services.workflow.transitions import (
    WorkflowTransitionError,
    coder_actor,
    mark_coder_finalized,
    mark_reviewer_eligible_after_recode_window,
    system_actor,
)

log = logging.getLogger(__name__)

ORIGIN = "collect_plus_offline"
#: The transition reasons of an imported final (state machine "Imported offline final").
IMPORTED_REASON = "offline_coding_imported"
FORCED_REVIEW_REASON = "offline_coding_disagreement_review"

STANDALONE_KEYS = frozenset({"client_device_uuid", "profile_snapshot", "org_code", "consent"})
PROFILE_KEYS = frozenset({"name", "designation", "facility", "country"})
CODING_KEYS = frozenset({
    "coded_answers_sha256", "device_uuid", "process_token", "conclusive_cod", "remark", "certificate",
    "result", "codedit_result", "certificate_digest", "result_digest", "provenance", "pack_versions",
})
_REQUIRED_CODING = ("coded_answers_sha256", "device_uuid", "process_token", "conclusive_cod", "certificate",
                    "provenance")
_CONFIRMATION_KEYS = frozenset({"confirmed_by", "confirmed_at", "code", "age_group_selectable",
                                "restriction_note", "doris_warning"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PROCESS_TOKEN = re.compile(r"local-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ORG_CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TEXT_MAX = 200
_COD_MAX = 512
_REMARK_MAX = 2000
_PACK_MAX = 20

#: Reply statuses of the coding (the held row's status, as the phone sees it).
_REPLY_STATUS = {"pending": "pending", "applied": "applied", "rejected": "refused"}
#: Allocation refusals that leave a held result pending (as the bundle applier).
_STILL_PENDING = frozenset({"not_ready", "allocation_exists"})


class OfflineCodingError(Exception):
    """A malformed ``standalone`` or ``offline_coding`` object: the whole
    upload is refused (the phone keeps both), never half stored."""

    def __init__(self, message: str, code: str = "offline_coding_invalid", status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Parsing (no database read)
# ---------------------------------------------------------------------------


def _short_text(value, name: str, limit: int = _TEXT_MAX) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise OfflineCodingError(f"{name} must be text of at most {limit} characters.", "standalone_invalid")
    return value.strip() or None


def parse_standalone(value) -> dict:
    """The ``standalone`` object checked for shape: ``client_device_uuid``
    (required), ``profile_snapshot`` (name, designation, facility, country),
    ``org_code`` (a unit code of the project, or null) and ``consent`` (the
    standalone consent record, or null; checked by ``consent_service``).
    422 ``standalone_invalid``."""
    if not isinstance(value, dict) or not set(value) <= STANDALONE_KEYS:
        raise OfflineCodingError(
            "standalone must be {client_device_uuid, profile_snapshot, org_code, consent}.", "standalone_invalid")
    try:
        client_uuid = devices.parse_client_device_uuid(value.get("client_device_uuid"))
    except devices.DeviceAuthError:
        client_uuid = None
    if client_uuid is None:
        raise OfflineCodingError("standalone.client_device_uuid must be a UUID.", "standalone_invalid")
    profile = value.get("profile_snapshot") or {}
    if not isinstance(profile, dict) or not set(profile) <= PROFILE_KEYS:
        raise OfflineCodingError("standalone.profile_snapshot has only name, designation, facility and country.",
                                 "standalone_invalid")
    org_code = value.get("org_code")
    if org_code is not None and (not isinstance(org_code, str) or not _ORG_CODE.fullmatch(org_code.strip())):
        raise OfflineCodingError("standalone.org_code must be a unit code or null.", "standalone_invalid")
    return {
        "client_device_uuid": client_uuid,
        "profile_snapshot": {k: _short_text(profile.get(k), f"profile_snapshot.{k}") for k in sorted(PROFILE_KEYS)},
        "org_code": org_code.strip().upper() if org_code else None,
        "consent": value.get("consent"),
    }


def _bad(message: str):
    raise OfflineCodingError(message)


def _optional_hex(value, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _HEX64.fullmatch(value.lower()):
        _bad(f"offline_coding.{name} must be 64 hex characters or null.")
    return value.lower()


def _optional_object(value, name: str) -> dict | None:
    if value is not None and not isinstance(value, dict):
        _bad(f"offline_coding.{name} must be an object or null.")
    return value


def _confirmation(value) -> dict | None:
    """The device's age-restriction confirmation (``record_final_cod_flags``'s
    shape): its six keys, each text or null."""
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != _CONFIRMATION_KEYS
            or not all(v is None or (isinstance(v, str) and len(v) <= _COD_MAX) for v in value.values())
            or not isinstance(value.get("code"), str)):
        _bad("provenance.antecedent.age_restriction_confirmation must be the confirmation record.")
    return dict(value)


def _provenance(value) -> dict:
    """``{allowability: {rules, release}, antecedent: {code, primary_stem,
    release, causing_condition_unknown?, age_restriction_confirmation?}}``."""
    if not isinstance(value, dict) or set(value) != {"allowability", "antecedent"}:
        _bad("offline_coding.provenance must be {allowability, antecedent}.")
    allowability, antecedent = value["allowability"], value["antecedent"]
    if (not isinstance(allowability, dict) or set(allowability) != {"rules", "release"}
            or not all(isinstance(v, str) and 0 < len(v) <= _TEXT_MAX for v in allowability.values())):
        _bad("provenance.allowability must be {rules, release}.")
    allowed = {"code", "primary_stem", "release", "causing_condition_unknown", "age_restriction_confirmation"}
    if not isinstance(antecedent, dict) or not {"code", "primary_stem", "release"} <= set(antecedent) <= allowed:
        _bad("provenance.antecedent must be {code, primary_stem, release, ...}.")
    code = extract_icd11_code_expression(antecedent.get("code") if isinstance(antecedent.get("code"), str) else None)
    stem = antecedent.get("primary_stem")
    if code is None or code != antecedent["code"].upper() or not isinstance(stem, str) or \
            extract_icd_code(stem, "icd11") != stem.upper():
        _bad("provenance.antecedent.code and primary_stem must be ICD-11 codes.")
    if not isinstance(antecedent["release"], str) or not 0 < len(antecedent["release"]) <= 16:
        _bad("provenance.antecedent.release is required.")
    unknown = antecedent.get("causing_condition_unknown", False)
    if not isinstance(unknown, bool):
        _bad("provenance.antecedent.causing_condition_unknown must be true or false.")
    return {
        "allowability": dict(allowability),
        "antecedent": {
            "code": code, "primary_stem": stem.upper(), "release": antecedent["release"],
            "causing_condition_unknown": unknown,
            "age_restriction_confirmation": _confirmation(antecedent.get("age_restriction_confirmation")),
        },
    }


def _pack_versions(value) -> dict:
    if value is None:
        return {}
    if (not isinstance(value, dict) or len(value) > _PACK_MAX
            or not all(isinstance(k, str) and len(k) <= 64 and isinstance(v, str) and len(v) <= 128
                       for k, v in value.items())):
        _bad(f"offline_coding.pack_versions must map at most {_PACK_MAX} names to version text.")
    return dict(value)


def parse_offline_coding(value) -> dict:
    """The ``offline_coding`` object checked for shape. 422
    ``offline_coding_invalid`` names the first problem, never echoing a
    value. ``conclusive_cod`` (``"<code> <title>"``) must lead with the
    provenance's antecedent code."""
    if not isinstance(value, dict) or not set(value) <= CODING_KEYS:
        _bad("offline_coding has unknown keys.")
    missing = [k for k in _REQUIRED_CODING if value.get(k) in (None, "")]
    if missing:
        _bad(f"offline_coding.{missing[0]} is required.")
    sha = _optional_hex(value["coded_answers_sha256"], "coded_answers_sha256")
    try:
        device_uuid = devices.parse_client_device_uuid(value["device_uuid"])
    except devices.DeviceAuthError:
        _bad("offline_coding.device_uuid must be a UUID.")
    token = value["process_token"]
    if not isinstance(token, str) or not _PROCESS_TOKEN.fullmatch(token):
        _bad("offline_coding.process_token must be local-<uuid>.")
    cod = value["conclusive_cod"]
    if not isinstance(cod, str) or len(cod) > _COD_MAX or "\x00" in cod:
        _bad(f"offline_coding.conclusive_cod must be text of at most {_COD_MAX} characters.")
    remark = value.get("remark")
    if remark is not None and (not isinstance(remark, str) or len(remark) > _REMARK_MAX or "\x00" in remark):
        _bad(f"offline_coding.remark must be text of at most {_REMARK_MAX} characters or null.")
    certificate = _optional_object(value["certificate"], "certificate")
    provenance = _provenance(value["provenance"])
    if extract_icd11_code_expression(cod) != provenance["antecedent"]["code"]:
        _bad("offline_coding.conclusive_cod must lead with provenance.antecedent.code.")
    return {
        "coded_answers_sha256": sha,
        "device_uuid": str(device_uuid),
        "process_token": token,
        "conclusive_cod": cod.strip(),
        "remark": (remark or "").strip() or None,
        "certificate": certificate,
        "result": _optional_object(value.get("result"), "result"),
        "codedit_result": _optional_object(value.get("codedit_result"), "codedit_result"),
        "certificate_digest": _optional_hex(value.get("certificate_digest"), "certificate_digest"),
        "result_digest": _optional_hex(value.get("result_digest"), "result_digest"),
        "provenance": provenance,
        "pack_versions": _pack_versions(value.get("pack_versions")),
    }


# ---------------------------------------------------------------------------
# Push time (inside the upload's transaction; the route commits)
# ---------------------------------------------------------------------------


def require_session_device(session, client_device_uuid: uuid.UUID, coding: dict | None):
    """The bearer session's device, when it was enrolled with
    *client_device_uuid* (S3, ``device_for_client_uuid``) and the coding names
    the same UUID; else 403 ``device_mismatch``. A cookie request has no
    device and is refused the same way."""
    device = devices.device_for_client_uuid(session, str(client_device_uuid)) if session is not None else None
    if device is None or (coding is not None and coding["device_uuid"] != str(client_device_uuid)):
        raise OfflineCodingError("This phone is not the device this account enrolled.", "device_mismatch", 403)
    return device


def resolve_org_unit(user: VaUsers, project_id: str, site_id: str, org_code: str | None) -> uuid.UUID | None:
    """The live unit of *project_id* the standalone ``org_code`` names, when
    the pushing interviewer may name it (``reachable_unit_ids``); else None,
    and the upload starts without a unit (routing: the mapping fallback, else
    the unrouted queue). Never a guess from free text."""
    if not org_code:
        return None
    unit = db.session.scalar(sa.select(MasOrgUnit).where(
        MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code == org_code, MasOrgUnit.is_active.is_(True)))
    if unit is None:
        return None
    reachable = intake_svc.reachable_unit_ids(user, project_id, site_id)
    if reachable is not None and unit.org_unit_id not in reachable:
        return None
    return unit.org_unit_id


def interview_provenance(standalone: dict, coding: dict | None, org_unit_id) -> dict:
    """What the interview's draft meta keeps of a standalone push (as
    ``standalone``): the device UUID claim, the coder profile snapshot, the
    org code and whether it named a unit, and the coding's process token and
    pack versions. Opaque provenance; never used for access."""
    return {
        "origin": ORIGIN,
        "clientDeviceUuid": str(standalone["client_device_uuid"]),
        "profile": standalone["profile_snapshot"],
        "orgCode": standalone["org_code"],
        "orgCodeMatched": org_unit_id is not None,
        "processToken": coding["process_token"] if coding else None,
        "packVersions": coding["pack_versions"] if coding else {},
    }


def has_coding_grant(user: VaUsers, project_id: str) -> bool:
    """A ``coder`` grant on *project_id* that codes (gate open, coding scope
    level met); in a self-coding project that is the self-coding grant."""
    resolved = resolve_grants(user)
    return any(g.project_id == project_id and g.opens_gate and resolved.codes(g)
               for g in resolved.of({VaAccessRoles.coder}, virtual=False))


def _push_refusal(user: VaUsers, project: VaProjectMaster, draft: VaWebIntakeDraft, coding: dict) -> str | None:
    """Why this coding is not taken (the interview is, either way), or None."""
    if draft.va_sid is None or draft.status != "submitted":
        return "not_available"
    if not has_coding_grant(user, project.project_id):
        return "coding_grant_required"
    if project_mode(project) != "unmasked_doris" or project.icd_classification != "icd11":
        return "coding_mode_mismatch"
    if not hmac.compare_digest(draft.answers_sha256 or "", coding["coded_answers_sha256"]):
        return "coded_version_superseded"
    return None


def _audit(va_sid: str, user_id, action: str, entity_id=None) -> None:
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid, va_audit_byrole="vacoder", va_audit_by=user_id, va_audit_operation="c",
        va_audit_action=action[:128], va_audit_entityid=entity_id,
    ))


def hold(user: VaUsers, project: VaProjectMaster, draft: VaWebIntakeDraft, coding: dict,
         profile_snapshot: dict) -> dict:
    """Keep *coding* for the applier, or record why it is refused (a held row
    ``rejected`` with the code, so a resend reports the same). Returns the
    reply's ``offline_coding`` object. Idempotent on the upload's
    ``client_draft_id``: a second call returns the first row's status, except
    that a still-pending coding of answers the interview no longer has (a
    later version was pushed) is replaced by this one when it codes the
    current answers, else refused ``coded_version_superseded`` now, so the
    reply never acknowledges a coding that cannot apply."""
    held = db.session.get(VaBundlePendingCoding, draft.client_draft_id)
    digest = hashlib.sha256(json.dumps(coding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if held is not None:
        if held.status == "pending" and held.result["coding"]["coded_answers_sha256"] != draft.answers_sha256:
            refusal = _push_refusal(user, project, draft, coding)
            if refusal is None:
                held.result = {**held.result, "coding": coding}
                held.content_sha256 = digest
            else:
                held.status, held.code, held.resolved_at = "rejected", refusal, datetime.now(UTC)
                _audit(draft.va_sid, user.user_id, f"offline coding refused ({refusal})", draft.draft_id)
        return status_of(held)
    refusal = _push_refusal(user, project, draft, coding)
    if draft.va_sid is None:
        # A superseded copy: no case of its own to hold the coding against.
        return {"status": "refused", "code": refusal}
    held = VaBundlePendingCoding(
        client_id=draft.client_draft_id, bundle_ids=[], project_id=project.project_id, va_sid=draft.va_sid,
        death_id=draft.death_id, actor_user_id=user.user_id, content_sha256=digest,
        result={"origin": ORIGIN, "client_draft_id": str(draft.client_draft_id), "coding": coding,
                "profile_snapshot": profile_snapshot},
        status="rejected" if refusal else "pending", code=refusal or "not_ready",
        resolved_at=datetime.now(UTC) if refusal else None,
    )
    db.session.add(held)
    if refusal:
        _audit(draft.va_sid, user.user_id, f"offline coding refused ({refusal})", draft.draft_id)
    return status_of(held)


def status_of(held: VaBundlePendingCoding | None) -> dict | None:
    """The reply's ``offline_coding``: ``{status, code}``, ``status`` one of
    ``pending`` (held until the case is ready), ``applied`` or ``refused``."""
    if held is None:
        return None
    return {"status": _REPLY_STATUS[held.status], "code": None if held.status == "applied" else held.code}


def coding_status(client_draft_id: uuid.UUID) -> dict | None:
    return status_of(db.session.get(VaBundlePendingCoding, client_draft_id))


# ---------------------------------------------------------------------------
# Apply (the bundle applier's Celery run; commits)
# ---------------------------------------------------------------------------


def is_offline_hold(held: VaBundlePendingCoding) -> bool:
    return (held.result or {}).get("origin") == ORIGIN


def _finish(held: VaBundlePendingCoding, status: str, code: str | None) -> str:
    held.status, held.code, held.resolved_at = status, code, datetime.now(UTC)
    if status == "rejected":
        _audit(held.va_sid, held.actor_user_id, f"offline coding refused ({code})", held.client_id)
    db.session.commit()
    return status


def apply_held(held: VaBundlePendingCoding) -> str:
    """Apply one held standalone coding whose case left the attachment and
    SmartVA states; returns ``applied``, ``rejected`` or ``pending``.
    Re-checks what the push checked (the account's coding grant, the
    project's mode, the coded answers), takes the coder's allocation and
    saves the imported final. Commits."""
    record = held.result
    coding = record["coding"]
    actor = db.session.get(VaUsers, held.actor_user_id)
    draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.client_draft_id == held.client_id, VaWebIntakeDraft.va_sid == held.va_sid))
    project = db.session.get(VaProjectMaster, held.project_id)
    if actor is None or actor.user_status != VaStatuses.active or draft is None:
        return _finish(held, "rejected", "not_available")
    refusal = _push_refusal(actor, project, draft, coding)
    if refusal is not None:
        return _finish(held, "rejected", refusal)
    try:
        coder_workflow.allocate_pick_form(actor, held.va_sid, own_case=True)
    except coder_workflow.AllocationError as exc:
        db.session.rollback()
        if exc.code in _STILL_PENDING:
            return "pending"
        return _finish(held, "rejected", exc.code or "not_available")
    try:
        _save_imported_final(actor, held.va_sid, project, coding, record.get("profile_snapshot") or {})
    except (coder_cod.CoderCodingError, WorkflowTransitionError) as exc:
        db.session.rollback()
        try:
            coder_workflow.release_own_coding_allocation(actor)
            db.session.commit()
        except coder_workflow.AllocationError:
            db.session.rollback()
        return _finish(held, "rejected", getattr(exc, "code", None) or "wrong_state")
    return _finish(held, "applied", None)


def _stems(expression: str) -> list[str]:
    """The stems of a code expression: each ``/`` part before its ``&``."""
    return [part.split("&", 1)[0] for part in expression.split("/")]


def allowability_disagreements(va_sid: str, provenance: dict) -> tuple[list[str], str]:
    """The server's ICD-11 allowability re-check of an offline final (the
    rules of ``validate_icd11_mms_coding_value_for_submission`` over the
    local ``mas_icd11_mms`` policy columns, no WHO call): returns the
    disagreement codes, sorted, and the primary stem judged. A cluster's
    primary stem is the device's when it is one of the cluster's stems (WHO's
    causing condition, which only WHO codeinfo names), else its first stem.

    Codes: ``primary_stem_mismatch``, ``release_mismatch``, ``not_selectable``
    (chapter 22, not a category, not selectable or unknown), ``sex_conflict``,
    ``age_unconfirmed`` (age conflict with no confirmation of this code),
    ``causing_condition_flag_invalid`` (the flag on a cluster)."""
    antecedent = provenance["antecedent"]
    expression = antecedent["code"]
    stems = _stems(expression)
    flags = set()
    primary = antecedent["primary_stem"]
    if primary not in stems or ("/" not in expression and primary != stems[0]):
        flags.add("primary_stem_mismatch")
        primary = stems[0]
    if antecedent["release"] != DEFAULT_ICD11_RELEASE:
        flags.add("release_mismatch")
    if antecedent["causing_condition_unknown"] and "/" in expression:
        flags.add("causing_condition_flag_invalid")
    context = coding_context_for_submission(va_sid) or {}
    age_ok, sex_ok = policy_ok_columns(MasIcd11Mms, age_group=context.get("age_group"), sex=context.get("sex"))
    row = db.session.execute(
        sa.select(age_ok.label("age_ok"), sex_ok.label("sex_ok")).where(
            MasIcd11Mms.release == DEFAULT_ICD11_RELEASE,
            MasIcd11Mms.code == primary,
            MasIcd11Mms.is_active.is_(True),
            MasIcd11Mms.class_kind.in_(tuple(POLICY_EDITABLE_CLASS_KINDS)),
            MasIcd11Mms.is_coding_selectable.is_(True),
        )
    ).first()
    if row is None:
        flags.add("not_selectable")
    elif not row.sex_ok:
        flags.add("sex_conflict")
    elif not row.age_ok:
        confirmation = antecedent["age_restriction_confirmation"]
        if not confirmation or confirmation.get("code") != primary:
            flags.add("age_unconfirmed")
    return sorted(flags), primary


def _conclusive_provenance(conclusive_cod: str, provenance: dict, primary: str, flags: list[str]) -> dict:
    """The ``icd11_provenance`` of an imported final, in the server's shape
    (``build_icd11_provenance`` plus ``record_final_cod_flags``) from the
    local MMS row of the expression's first stem; WHO's ``codeinfo_uri`` is
    null (never fetched). The device's age confirmation and causing-condition
    flag are kept as sent; ``allowability_disagreement`` lists the server's
    re-check codes."""
    antecedent = provenance["antecedent"]
    expression = antecedent["code"]
    row = db.session.scalar(sa.select(MasIcd11Mms).where(
        MasIcd11Mms.release == DEFAULT_ICD11_RELEASE, MasIcd11Mms.code == _stems(expression)[0],
        MasIcd11Mms.is_active.is_(True)))
    selected = conclusive_cod.split(None, 1)
    item = {
        "code": expression,
        "title": row.title if row else None,
        "selected_text": selected[1].strip() if len(selected) > 1 else "",
        "release": DEFAULT_ICD11_RELEASE,
        "linearization_uri": row.linearization_uri if row else None,
        "foundation_uri": row.foundation_uri if row else None,
        "codeinfo_uri": None,
        "primary_stem": primary,
        "coding_origin": ORIGIN,
    }
    if antecedent["causing_condition_unknown"]:
        item["causing_condition_unknown"] = True
    if antecedent["age_restriction_confirmation"]:
        item["age_restriction_confirmation"] = antecedent["age_restriction_confirmation"]
    if flags:
        item["allowability_disagreement"] = flags
    return {"conclusive": item}


def _save_imported_final(actor: VaUsers, va_sid: str, project: VaProjectMaster, coding: dict,
                         profile_snapshot: dict) -> VaFinalAssessments:
    """The coder's final from an offline coding, as ``submit_coder_final_cod``
    stores an unmasked DORIS final (supersede, authority, release, state) but
    with the device's certificate and results as imported, no DORIS
    verification, and the narrative QA and social autopsy gates not asked
    (the phone has neither). Raises ``CoderCodingError`` (no allocation, no
    active payload) or ``WorkflowTransitionError``. Commits."""
    actiontype = coder_cod.derive_actiontype(va_sid)
    allocation = coder_cod.require_coding_session(actor, va_sid, actiontype)
    submission = db.session.scalar(sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid).with_for_update())
    payload = get_active_payload_version(va_sid)
    if submission is None or payload is None:
        raise coder_cod.CoderCodingError("This submission has no active payload version.", 422, code="final_blocked")
    flags, primary = allowability_disagreements(va_sid, coding["provenance"])
    snapshot = cod_entry_mode_snapshot(project, str(current_app.config.get("DORIS_WHO_IMAGE_DIGEST") or "").strip())
    snapshot.update(coding_origin=ORIGIN, offline={
        "device_uuid": coding["device_uuid"], "process_token": coding["process_token"],
        "pack_versions": coding["pack_versions"], "allowability": coding["provenance"]["allowability"],
        "certificate_digest": coding["certificate_digest"], "result_digest": coding["result_digest"],
        "profile_snapshot": profile_snapshot,
    })
    final = VaFinalAssessments(
        va_finassess_id=uuid.uuid4(), va_sid=va_sid, payload_version_id=payload.payload_version_id,
        va_finassess_by=actor.user_id, va_conclusive_cod=coding["conclusive_cod"],
        icd11_provenance=_conclusive_provenance(coding["conclusive_cod"], coding["provenance"], primary, flags),
        doris_certificate=coding["certificate"], doris_result=coding["result"],
        codedit_result=coding["codedit_result"], cod_entry_mode_snapshot=snapshot,
        va_finassess_remark=coding["remark"], demo_expires_at=get_demo_expiry_for_submission(va_sid, actiontype),
        va_finassess_status=VaStatuses.active,
    )
    for earlier in db.session.scalars(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.payload_version_id == payload.payload_version_id,
            VaFinalAssessments.va_finassess_status == VaStatuses.active)):
        earlier.va_finassess_status = VaStatuses.deactive
        _audit(va_sid, actor.user_id, "deactivated superseded final cod", earlier.va_finassess_id)
    db.session.add(final)
    _audit(va_sid, actor.user_id, "final cod imported from collect plus offline", final.va_finassess_id)
    if flags:
        _audit(va_sid, actor.user_id, "offline coding allowability disagreement: " + ",".join(flags),
               final.va_finassess_id)
    allocation.va_allocation_status = VaStatuses.deactive
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid, va_audit_byrole="vacoder", va_audit_by=actor.user_id, va_audit_operation="d",
        va_audit_action="allocated form released from coder", va_audit_entityid=allocation.va_allocation_id,
    ))
    db.session.flush()
    upsert_final_cod_authority(va_sid, final, reason=IMPORTED_REASON, source_role="vacoder",
                               updated_by=actor.user_id)
    mark_coder_finalized(va_sid, reason=IMPORTED_REASON, actor=coder_actor(actor.user_id))
    if flags or is_demo_training_submission(va_sid):
        # Forced review: the reviewer pool at once, the recode window skipped.
        mark_reviewer_eligible_after_recode_window(
            va_sid, reason=FORCED_REVIEW_REASON if flags else "demo_reviewer_eligible_immediately",
            actor=system_actor())
    db.session.commit()
    bust_coder_dashboard_cache(actor.user_id)
    log.info("offline coding imported | sid=%s | by=%s | disagreements=%s", va_sid, actor.user_id, len(flags))
    return final
