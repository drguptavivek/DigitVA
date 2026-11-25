"""Offline upload, revisions, the outstanding-work report and the prefill policy. Part of the intake API package (``__init__``)."""
import hashlib
import hmac
import json
import re
import uuid

from flask import g, jsonify
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app import db
from app.decorators import role_required
from app.models import (
    AuthDevice,
    VaDeathRegister,
    VaProjectMaster,
)
from app.routes.api.intake._common import _consent_channel, _site_id, bp
from app.routes.api.request_helpers import (
    error,
    intake_error,
    parse_body,
    request_project_id,
    require_project,
)
from app.services import consent_service as consent_svc
from app.services import device_auth_service as devices
from app.services import intake_revision_access as revision_access
from app.services import offline_coding_import_service as offline_import
from app.services import training_scope
from app.services import web_intake_attachment_service as attachments_svc
from app.services import web_intake_service as intake_svc
from app.services.interview_intake_gate import check_refusal_transition

# ---------------------------------------------------------------------------
# Offline upload
# ---------------------------------------------------------------------------


_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")


def _parse_upload_answers(p):
    """The upload's answers and their hash, or an error reply.

    ``answers_json`` is the exact text the app hashed; it is hashed as
    received and only then parsed, so the stored hash is of the bytes the
    app meant to send. Returns ``(data, sha256_hex, None)`` or
    ``(None, None, reply)``."""
    answers_json, claimed = p.get("answers_json"), p.get("answers_sha256")
    if not isinstance(answers_json, str) or not isinstance(claimed, str) or not _SHA256_HEX.fullmatch(claimed):
        return None, None, error(
            "answers_json (the answers as JSON text) and answers_sha256 (64 hex characters) are required.",
            "answers_hash_required", 422,
        )
    raw = answers_json.encode("utf-8", "surrogatepass")
    if len(raw) > intake_svc.DEVICE_ANSWERS_MAX_BYTES:
        return None, None, error("answers_json is too large.", "invalid_interview", 422)
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, claimed.lower()):
        return None, None, error("answers_sha256 does not match answers_json.", "answers_hash_invalid", 422)
    try:
        data = json.loads(answers_json)
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return None, None, error("answers_json must be a JSON object of answers.", "invalid_interview", 422)
    try:
        intake_svc.check_device_answers(data)
    except intake_svc.WebIntakeError as exc:
        return None, None, intake_error(exc)
    return data, digest, None


def _upload_reply(draft, *, kept, received_sha256, locked, status, offline_coding=None):
    """The upload result (``serialize_device_upload``, the coder version's
    hash in ``answers_sha256``) with whose answers the coder has (``kept``:
    ``incoming`` or ``server``), the hash the server received (the app deletes
    its copy when it equals what it sent) and whether coding is final or the
    case closed (``locked``), and ``can_code_now`` (a self-coding project's
    coder may code this case now: ``POST /coding/submissions/<va_sid>/code-now``).
    A standalone push with offline coding adds ``offline_coding``
    (``{status, code, coding_sha256}``, contract section 17)."""
    body = {
        **intake_svc.serialize_device_upload(draft), "kept": kept, "received_sha256": received_sha256, "locked": locked,
        "can_code_now": intake_svc.can_code_now(current_user, draft),
    }
    if offline_coding is not None:
        body["offline_coding"] = offline_coding
    return jsonify(body), status


@bp.post("/submissions")
@role_required("interviewer")
def submit_interview():
    """One completed interview, idempotent on ``client_draft_id``. The last
    completed version of the interviewer's own interview is the coder's
    (docs/policy/web-intake.md "Parallel interviews"): a resend with the same
    ``answers_sha256`` returns the first result with 200; one with other
    answers, or a second upload of a case the caller already submitted,
    becomes the coder's version when its completion time is not older, else
    it is kept as history. Never a hash conflict. Reply: the upload result
    plus ``kept`` (``incoming`` or ``server``), ``received_sha256`` and
    ``locked`` (coding final or case closed). A bearer request records its
    device on the interview; a cookie request has none. Optional ``consent``
    (contract 5.3, naming this ``client_draft_id``): a consent taken for this
    attempt, stored with the upload; where the project requires consent,
    covered answers need it granted or, without one, a granted registration
    consent on the case (422 ``consent_required`` / ``consent_conflict`` /
    ``consent_invalid``, 409 ``conflict``). A resend of the same answers
    returns the first result unchecked.

    Collect Plus standalone push (contract section 17): ``standalone``
    (``client_device_uuid`` of this bearer's device, else 403
    ``device_mismatch``; profile snapshot; ``org_code`` naming the unit, an
    unmatched one starting without a unit; ``consent``, the standalone
    consent record, in place of ``consent``) and, optionally,
    ``offline_coding``, held for import and reported as ``offline_coding``
    in the reply. The same draft id from another device is 409 ``conflict``."""
    p = parse_body()
    try:
        client_draft_id = uuid.UUID(str(p.get("client_draft_id")))
    except ValueError:
        return error("client_draft_id must be a UUID.", "invalid_request", 400)
    site_id = _site_id(p)
    envelope = p.get("draft")
    completion = p.get("completion")
    if not isinstance(completion, dict):
        # The package's completion result carries valid/issues beside data.
        completion = envelope if isinstance(envelope, dict) else {}
    if not isinstance(envelope, dict):
        return error("draft must be an object.", "invalid_interview", 422)

    project_id = request_project_id(p)
    data, answers_sha256, refusal = _parse_upload_answers(p)
    if refusal is not None:
        return refusal
    standalone = coding = standalone_device = None
    enrolled_context = False
    if p.get("standalone") is not None:
        standalone = offline_import.parse_standalone(p["standalone"])
        if p.get("offline_coding") is not None:
            coding = offline_import.parse_offline_coding(p["offline_coding"])
        if p.get("consent") is not None and standalone["consent"] is not None:
            return error("Send the consent once: standalone.consent or consent.", "invalid_request", 400)
        standalone_device = offline_import.require_session_device(
            g.get("device_session"), standalone["client_device_uuid"], coding)
    elif p.get("offline_coding") is not None:
        coding = offline_import.parse_offline_coding(p["offline_coding"])
        enrolled_context = True
        standalone_device = offline_import.require_session_device(
            g.get("device_session"), uuid.UUID(coding["device_uuid"]), coding)
    coding_sha256 = offline_import.coding_receipt_sha256(p["offline_coding"]) if coding is not None else None
    existing = intake_svc.find_device_upload(current_user, client_draft_id)
    decision = p.get("consent")
    if standalone is not None and standalone["consent"] is not None:
        decision = standalone["consent"].get("envelope") if isinstance(standalone["consent"], dict) else None
    refused = check_refusal_transition(
        death_id=existing.death_id if existing is not None else None, client_draft_id=client_draft_id,
        answers=data, consent=decision,
    )
    same_final = existing is not None and existing.status != "draft" and existing.answers_sha256 == answers_sha256
    if refused and (coding is not None or (not same_final and consent_svc.refusal_answers(data) != data)):
        return error("Consent was refused; remove interview answers, files and coding before sending.", "consent_refused", 422)
    try:
        intake_svc.check_device_times(envelope)
    except intake_svc.WebIntakeError as exc:
        return error(str(exc), "invalid_interview", 422)

    def _apply_interview_consent(draft):
        # On the case the upload landed on, gating the answers as received.
        consent = p.get("consent")
        if standalone is not None and standalone["consent"] is not None:
            consent = consent_svc.standalone_consent(current_user, project_id, standalone["consent"])
        consent_svc.apply_interview_consent(
            current_user, project_id=project_id, death=db.session.get(VaDeathRegister, draft.death_id),
            client_draft_id=client_draft_id, consent=consent, answers=data, channel=_consent_channel(),
        )

    def _hold_coding(draft):
        if coding is None:
            return None
        project = db.session.get(VaProjectMaster, draft.project_id)
        profile_snapshot = standalone["profile_snapshot"] if standalone is not None else {}
        return offline_import.hold(
            current_user, project, draft, coding, profile_snapshot, coding_sha256=coding_sha256,
            enrolled_context=enrolled_context,
        )

    def resend(existing):
        # The same hash is the first result again; other answers are a later
        # version of the interview.
        if existing.project_id != project_id:
            return error("This client draft belongs to another project.", "conflict", 409)
        if standalone_device is not None and (existing.meta or {}).get("deviceId") != str(standalone_device.device_id):
            # A backup restored on a second phone: never a new case.
            return error("This interview was sent from another device.", "conflict", 409)
        if existing.death_id:
            intake_svc.cases.lock_case(db.session.get(VaDeathRegister, existing.death_id))
            db.session.refresh(existing)
        now_refused = check_refusal_transition(
            death_id=existing.death_id, client_draft_id=client_draft_id, answers=data, consent=decision,
        )
        if now_refused and existing.status != "draft" and existing.answers_sha256 != answers_sha256:
            raise consent_svc.ConsentError("A submitted interview cannot be changed to a refusal here.",
                                           "consent_refused", fields=[])
        if ((existing.meta or {}).get("interviewOutcome") == "refused"
                and existing.answers_sha256 != answers_sha256):
            raise consent_svc.ConsentError("A submitted refusal cannot be changed here.", "consent_refused", fields=[])
        if now_refused and (coding is not None or
                            (existing.answers_sha256 != answers_sha256 and consent_svc.refusal_answers(data) != data)):
            raise consent_svc.ConsentError("Consent was refused; remove interview answers, files and coding before sending.",
                                           "consent_refused", fields=[])
        if existing.answers_sha256 == answers_sha256:
            closed = existing.status == "superseded"
            timeline_meta = intake_svc.merge_incoming_timeline_meta(
                existing, envelope, allow_server_receipts=True
            )
            if timeline_meta:
                existing.meta = {**(existing.meta or {}), **timeline_meta}
            held = _hold_coding(existing) if coding is not None else None
            if coding is not None or timeline_meta:
                db.session.commit()
            return _upload_reply(
                existing, kept="server" if closed else "incoming", received_sha256=answers_sha256, locked=closed,
                status=200, offline_coding=held,
            )
        _apply_interview_consent(existing)
        kept, locked = intake_svc.resubmit_device_interview(
            current_user, existing, envelope=envelope, data=data, answers_sha256=answers_sha256, completion=completion,
        )
        held = _hold_coding(existing)
        db.session.commit()
        return _upload_reply(existing, kept=kept, received_sha256=answers_sha256, locked=locked, status=200,
                             offline_coding=held)

    if existing is not None and not intake_svc.is_attachment_draft(existing):
        return resend(existing)
    session = g.get("device_session")
    device = db.session.get(AuthDevice, session.device_id) if session is not None else None
    org_unit_id = p.get("org_unit_id") or None
    if standalone is not None:
        org_unit_id = offline_import.resolve_org_unit(current_user, project_id, site_id, standalone["org_code"])
    try:
        draft, kept, locked = intake_svc.submit_device_interview(
            current_user,
            project_id=project_id,
            client_draft_id=client_draft_id,
            site_id=site_id,
            org_unit_id=org_unit_id,
            death_id=p.get("death_id") or None,
            envelope=envelope,
            data=data,
            answers_sha256=answers_sha256,
            completion=completion,
            device_id=device.device_id if device else None,
            unrouted_ok=standalone is not None,
            resume_refused=p.get("resume_refused") is True,
            base_updated_at=p.get("base_updated_at"),
            incoming_consent=decision,
        )
        if standalone is not None:
            draft.meta = {**(draft.meta or {}), "standalone": offline_import.interview_provenance(
                standalone, coding, org_unit_id)}
        _apply_interview_consent(draft)
        if coding is not None:
            if check_refusal_transition(death_id=draft.death_id, client_draft_id=client_draft_id,
                                        answers=data, consent=decision):
                raise consent_svc.ConsentError("Consent was refused; coding cannot be sent.", "consent_refused", fields=[])
        held = _hold_coding(draft)
        db.session.commit()
        attachments_svc.delete_committed_blobs()
    except IntegrityError:
        # A concurrent resend of the same client_draft_id won the unique index.
        db.session.rollback()
        existing = intake_svc.find_device_upload(current_user, client_draft_id)
        if existing is None or intake_svc.is_attachment_draft(existing):
            raise
        return resend(existing)
    return _upload_reply(draft, kept=kept, received_sha256=answers_sha256, locked=locked, status=201,
                         offline_coding=held)


@bp.post("/submissions/<va_sid>/revisions")
@role_required("interviewer", "interview_supervisor")
def revise_submission(va_sid):
    """Revise the caller's own submitted interview, or correct one as a
    supervisor whose cadre may edit interviews (docs/policy/interview-revisions.md,
    "Supervisor correction": ``reason_code`` is then ignored and recorded as
    ``supervisor_correction``; the outcome cannot change, 409
    ``case_state_conflict``; a ``consent`` sent is not recorded).

    Body: ``reason_code`` (``interviewer_correction``, ``respondent_correction``,
    ``more_information`` or ``finish_partial``), ``answers_json`` +
    ``answers_sha256`` (the complete answers, as ``/submissions``),
    ``completion`` (``{valid, issues}``), ``draft`` (envelope meta; only
    ``startedAt``/``completedAt`` are taken, checked as on upload; the stored
    ``startedAt`` always stays). Replies 200
    ``{changed, va_sid, payload_version_id, answers_sha256, outcome,
    workflow_state}``; ``changed: false`` when the answers do not change the
    coding payload: no new version, release or routing, but raw answers that
    differ (only irrelevant ones were edited) are kept and ``answers_sha256``
    is the sent hash. 404 ``not_found`` unless the caller's own submitted
    interview; 409 ``revision_locked`` / ``case_already_submitted`` /
    ``case_closed`` / ``case_state_conflict``; 422 ``invalid_reason`` /
    ``answers_hash_*`` / ``invalid_interview``. A completed interview revised
    to a refusal or partial one is allowed: the case leaves coding. The
    server's own reason ``resubmitted`` is not accepted here. Optional
    ``consent`` and the consent gate as ``/submissions``, the attempt being
    the submission's own ``client_draft_id`` (null for a browser interview:
    then the consent is the case's registration consent)."""
    p = parse_body()
    reason_code = p.get("reason_code")
    envelope = p.get("draft")
    completion = p.get("completion")
    if not isinstance(reason_code, str) or not isinstance(envelope, dict) or not isinstance(completion, dict):
        return error("reason_code, draft and completion are required.", "invalid_interview", 422)
    data, answers_sha256, refusal = _parse_upload_answers(p)
    if refusal is not None:
        return refusal
    try:
        intake_svc.check_device_times(envelope)
    except intake_svc.WebIntakeError as exc:
        return error(str(exc), "invalid_interview", 422)
    # Before the revision writes (it queues SmartVA); not the caller's own
    # submission nor one they may correct: the service's 404, never a consent
    # refusal. A supervisor did not interview anyone, so records no consent.
    found = revision_access.find_revisable_submission(current_user, va_sid)
    draft, editor = found
    consent = p.get("consent") if editor == revision_access.EDITOR_OWNER else None
    if draft is not None:
        if (draft.meta or {}).get("interviewOutcome") == "refused":
            return error("A submitted refusal cannot be changed here.", "consent_refused", 422)
        if check_refusal_transition(death_id=draft.death_id, client_draft_id=draft.client_draft_id,
                                    answers=data, consent=consent):
            return error("A submitted interview cannot be changed to a refusal here.", "consent_refused", 422)
        consent_svc.apply_interview_consent(
            current_user, project_id=draft.project_id,
            death=db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None,
            client_draft_id=draft.client_draft_id, consent=consent, answers=data,
            channel=_consent_channel(),
        )
    reply = intake_svc.revise_submission(
        current_user, va_sid, reason_code=reason_code, data=data, answers_sha256=answers_sha256,
        completion={"valid": completion.get("valid") is True,
                    "issues": completion.get("issues") if isinstance(completion.get("issues"), list) else []},
        envelope=envelope, found=found,
    )
    db.session.commit()
    return jsonify(reply)


@bp.post("/outstanding")
@role_required("interviewer")
def report_outstanding():
    """The app's report of unsent work, stored on its device session. A
    browser cookie has no device session: 403 ``device_session_required``."""
    session = g.get("device_session")
    if session is None:
        return error("Only a device session reports outstanding work.", "device_session_required", 403)
    p = parse_body()
    devices.record_outstanding(
        session, p.get("count"), p.get("unique_ids"), p.get("client_draft_ids"), p.get("client_death_ids")
    )
    db.session.commit()
    return "", 204


@bp.get("/projects/<project_id>/prefill-policy")
@role_required("interviewer")
def prefill_policy(project_id):
    """The offline prefill the server applies in the project, for an app that
    builds a draft before it can reach the server. One of the caller's
    projects only (403 ``project_forbidden``)."""
    training_scope.resolve("interview")
    if not training_scope.keeps_project(project_id):
        return error("This project is not available in this area.", "project_forbidden", 403)
    if training_scope.current() != training_scope.ONLY:
        require_project(project_id)
    return jsonify(intake_svc.prefill_policy(current_user, project_id))

