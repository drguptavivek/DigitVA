"""Interviewer revisions (digitva-bhpl part A, docs/policy/interview-revisions.md) and the history a losing version keeps.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaDeathRegister,
    VaForms,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsers,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services import case_transition_service as cases
from app.services import (
    register_pii_accessor,
    smartva_service,
    training_scope,
)
from app.services import web_intake_attachment_service as attachments
from app.services.authz import Action, can
from app.services.case_transition_service import WebIntakeError
from app.services.coding_release_service import (
    SOURCE_INTERVIEWER_REVISION,
    SOURCE_SUPERVISOR_REVISION,
    release_coding_for_changed_payload,
    reopen_coding_after_revision,
)
from app.services.duplicate_exclusion import is_withdrawn
from app.services.intake_revision_access import (
    EDITOR_OWNER,
    EDITOR_SUPERVISOR,
    find_revisable_submission,
)
from app.services.submission_payload_version_service import (
    ensure_active_payload_version,
    get_active_payload_version,
    get_latest_pending_upstream_payload_version,
    opened_payload,
    payload_matches,
    reject_pending_upstream_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    apply_submission_projection,
    build_submission_projection,
    consent_is_valid,
    normalize_consent,
)
from app.services.web_intake import facade
from app.services.web_intake.common import (
    AUDIT_ROLE,
    PAYLOAD_ROLE,
    _clock_meta,
    _completion_time,
    _device_time,
    _expression_now,
    log,
)
from app.services.web_intake.drafts import (
    _DEFINITION_IDENTITY_KEYS,
    _DEVICE_TIME_KEYS,
    _STARTABLE_STATES,
    FINAL_SECTION,
    _answers_of,
    _approximate_date_of_death,
    _begin_interview,
    _draft_locked_answers,
    _identity_from_answers,
    _missing_identity_error,
    _sync_case_identity,
    merge_incoming_timeline_meta,
    stored_answers,
)
from app.services.web_intake.scope import (
    _require_scope,
)
from app.services.web_intake.submission import (
    OUTCOME_CASE_STATES,
    _interview_outcome,
    _set_final_section,
    build_final_payload,
)
from app.services.workflow.definition import (
    PROTECTED_WORKFLOW_STATES,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    WorkflowTransitionError,
    interview_supervisor_actor,
    mark_attachment_sync_completed,
    system_actor,
)
from app.services.workflow.upstream_changes import (
    UPSTREAM_CHANGE_STATUS_REJECTED,
    get_open_revision_request,
    resolve_pending_upstream_change,
)

#: The fixed reasons for a revision. No free text: a reason carries no
#: personal data.
REVISION_REASONS = ("interviewer_correction", "respondent_correction", "more_information", "finish_partial")


#: The reason of a correction the server itself makes when a later version of
#: an interviewer's own interview arrives (an upload resent with other answers,
#: a second upload, a browser submit of an already submitted draft). Internal:
#: never accepted from a client (``REVISION_REASONS`` is the public list).
RESUBMITTED_REASON = "resubmitted"


#: The reason of a supervisor's correction (docs/policy/interview-revisions.md
#: "Supervisor correction"). Set by the server whenever the caller revises as
#: a supervisor; never accepted from a client (not in ``REVISION_REASONS``).
SUPERVISOR_CORRECTION_REASON = "supervisor_correction"


#: The reason a supervisor's correction rejects a pending upstream version.
SUPERSEDED_BY_SUPERVISOR_REVISION = "superseded_by_supervisor_revision"


def revision_unlocked(submission: VaSubmissions) -> bool:
    """True while a coder's or reviewer's send-back, or a supervisor's reopen
    (``interview_send_back_service``), holds *submission* open for its
    interviewer: it is in ``finalized_upstream_changed`` and the latest
    workflow event that put it there was one of those two requests. An ODK
    upstream change leaves it locked: that case is the data manager's to
    accept or reject. One indexed lookup (``get_open_revision_request``)."""
    return get_open_revision_request(submission.va_sid) is not None


def find_own_submission(user: VaUsers, va_sid: str) -> VaWebIntakeDraft | None:
    """*user*'s submitted draft that holds submission *va_sid*, or None.

    Unlike an unsent draft (digitva-9xn9.22), a submitted case is revised and
    read only under a live interviewer grant on its unit, and a training case
    only in training mode (``?training=1``) under an active session's grant
    (digitva-l9dp.6); otherwise None."""
    draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.va_sid == va_sid,
        VaWebIntakeDraft.user_id == user.user_id,
        VaWebIntakeDraft.status == "submitted",
    ))
    if draft is None or not training_scope.keeps_project(draft.project_id):
        return None
    try:
        _require_scope(user, draft.project_id, draft.site_id, draft.org_unit_id)
    except WebIntakeError as exc:
        if exc.status_code == 403:  # no live grant; other refusals (e.g. an inactive unit) are not grant loss
            return None
    return draft


def may_read_submitted_answers(user: VaUsers, va_sid: str) -> bool:
    """Whether *user* may read submission *va_sid*'s answers through intake:
    the interviewer whose draft became it (``find_own_submission``) or a
    supervisor of its case (``is_interview_supervisor_for``). The read-only
    workspace view's intake gate and the case detail's ``can_view_answers``;
    coding access (``Action.VIEW``) is decided separately. A consent-withdrawn
    case is sealed: admin only. At most three indexed reads."""
    if not user.is_admin() and is_withdrawn(va_sid):
        return False
    if find_own_submission(user, va_sid) is not None:
        return True
    death = db.session.scalar(sa.select(VaDeathRegister).where(VaDeathRegister.va_sid == va_sid).limit(1))
    return death is not None and cases.is_interview_supervisor_for(user, death)


def _revisable_now(death: VaDeathRegister) -> bool:
    """Whether ``revise_submission`` would take a revision of *death*'s
    submission now: the case is not closed or consent-withdrawn, and its
    workflow is not in a protected state unless sent back or reopened
    (docs/policy/interview-revisions.md "Where the lock starts")."""
    if death.status in ("duplicate", "cancelled") or death.consent_withdrawn_at is not None:
        return False
    state = get_submission_workflow_state(death.va_sid)
    if state not in PROTECTED_WORKFLOW_STATES:
        return True
    submission = db.session.get(VaSubmissions, death.va_sid)
    return state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED and submission is not None and facade().revision_unlocked(submission)


def case_submission_view(user: VaUsers, death: VaDeathRegister, my_submission: bool) -> dict:
    """The case detail's submitted interview (docs/policy/interview-revisions.md).

    ``submission`` ``{va_sid, submitted_at, interview_outcome}`` (plus the
    caller's ``draft_id``, which a revision opens) for the interviewer whose
    draft became the case's submission (*my_submission*), a supervisor of
    the case, or a caller with coding access to it (``Action.VIEW``, who
    already reads it in the workspace); None otherwise or without a submission. ``can_view_answers``
    follows it. ``can_revise``: only the submitter, while ``revise_submission``
    would take a revision (case not ``duplicate``/``cancelled``; workflow not
    in a protected state unless sent back or reopened). Revision stays open
    during active coding (rule 2). ``revise_reason_required`` is always True:
    a client revision needs one of ``REVISION_REASONS``.
    """
    view = {"submission": None, "can_view_answers": False, "can_revise": False, "revise_reason_required": True}
    if not death.va_sid:
        return view
    draft = find_own_submission(user, death.va_sid) if my_submission else None
    if draft is None:
        if not (cases.is_interview_supervisor_for(user, death) or can(user, Action.VIEW, death.va_sid)):
            return view
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.va_sid == death.va_sid, VaWebIntakeDraft.status == "submitted",
        ).limit(1))
        mine = False
    else:
        mine = True
    view["submission"] = {
        "va_sid": death.va_sid,
        "submitted_at": draft.submitted_at.isoformat() if draft is not None and draft.submitted_at else None,
        "interview_outcome": (draft.meta or {}).get("interviewOutcome") if draft is not None else None,
        **({"draft_id": str(draft.draft_id)} if mine else {}),
    }
    view["can_view_answers"] = True
    # Mirrors revise_submission's lock check.
    view["can_revise"] = mine and _revisable_now(death)
    return view


def revise_submission(user: VaUsers, va_sid: str, *, reason_code: str, data: dict, answers_sha256: str | None, completion: dict, envelope: dict, resubmit: bool = False, found: tuple | None = None) -> dict:
    """Revise the submitted interview *va_sid* as its interviewer, or as a
    supervisor who may correct it; returns the reply ``{changed, va_sid,
    payload_version_id, answers_sha256, outcome, workflow_state}`` (plus
    ``kept`` and ``locked`` with *resubmit*).

    Only the user whose draft became the submission (``find_own_submission``)
    or a supervisor whose cadre may edit interviews and whose reach covers
    the case (``find_supervised_submission``: the case's completed current
    submission, in a project where they see personal data) may; *found*:
    the caller's ``find_revisable_submission`` result, when it already looked; else 404, never revealing it exists. The owner wins when
    both apply. A supervisor's *reason_code* is ignored: the server records
    ``SUPERVISOR_CORRECTION_REASON``, audits ``supervisor_revision`` and
    refuses turning the completed interview incomplete (409
    ``case_state_conflict``; that move is its interviewer's). The interviewer
    stays the interview's: the payload is built as the draft owner's
    (``SubmitterID``, so ``va_data_collector``, and the timezone), and the
    caller is only the version's ``created_by`` and the audit actor.

    Done under the case lock with a lock on the
    submission, so a concurrent submit, revision or sync serialises with it.
    The payload is rebuilt from the new raw answers exactly as ``submit_draft``
    builds it, on the original submit time, ``intake_source`` and
    non-answer values (``build_web_payload``'s *carry*), so only a real
    change in the answers or times changes the fingerprint.

    An equal fingerprint is the ODK no-change rule, which is about coding: no
    payload version, no release, no SmartVA rerun, no routing, no case move.
    Raw answers that differ only in answers stripped as irrelevant are still
    kept (the previous ones as a ``replaced`` draft row, the new ones as the
    draft's ``final`` section, ``answers_sha256`` set to the sent hash), so
    nothing typed is lost and the phone's acknowledgement matches; raw answers
    with the stored hash write nothing. Otherwise the previous raw answers are
    kept as a ``replaced`` draft row, the draft takes the new ones, a new
    active payload version records reason and hash, the coding artifacts and
    allocations are dropped as an ODK edit drops them, and the submission is
    re-routed. An incomplete outcome revised to ``completed`` also runs
    ``submit_draft``'s completion branch (case to ``submitted``); one revised
    to another incomplete outcome moves the case to that outcome's state
    (``OUTCOME_CASE_STATES``) the way a submit does. A completed interview
    revised to refused or incomplete is allowed (the latest completed version
    wins, docs/policy/interview-revisions.md): coding is released first, the
    submission routes to ``consent_refused``, and the case it won leaves
    ``submitted`` for that outcome's state and loses its ``va_sid``. A
    completed-to-completed revision syncs the form's identity answers onto the
    case again: the winning submission is the one corrected.

    A protected case is locked, except one a coder, reviewer or supervisor
    sent back or reopened (``revision_unlocked``): its changed revision
    restarts coding at once (``reopen_coding_after_revision``, the data
    manager's accept block under a system actor), rejects any lingering
    pending upstream payload, and keeps the earlier COD as inactive history.
    An unchanged revision leaves that case sent back.

    The draft's ``meta["effectiveSavedAt"]`` becomes this version's completion
    time (``_completion_time`` of *envelope*). The interview start
    (``startedAt``, payload ``start``) is never moved: the stored one stays
    whatever *envelope* sends, so a revision differing only in its start is
    no change.

    *resubmit* is the server's own correction of the interviewer's latest
    version (reason ``RESUBMITTED_REASON``) and never refuses for a reason the
    caller cannot act on: the version is applied only when it is not older than
    the stored one (a tie goes to the later received) and the case still takes
    it. Otherwise (coding finished, case closed or won by a teammate, or an
    older version) nothing in the case changes and the answers are kept as a
    ``replaced`` row, once per answers (``kept: "server"``; ``locked: true``
    when coding or the case no longer takes any version).

    Every other refusal is decided before anything is written, except the
    workflow race ``revision_locked`` (a coder finalised after the check) and a
    case transition ``cases.transition`` refuses; those raise after writes, and
    the route's error handler rolls the whole transaction back. Refusals: 404
    unknown or not the caller's, 409 ``revision_locked`` (protected workflow
    state not sent back or reopened), ``case_already_submitted`` (a teammate's
    complete submission won), ``case_closed`` (duplicate or cancelled),
    ``case_state_conflict`` (an outcome change a teammate's winning case state
    does not allow), the live-org-unit refusals when finishing a partial, 422
    ``invalid_reason``, the missing identity of a finished partial and
    ``_interview_outcome``'s own.
    """
    # *found*: the route's one lookup. A resubmit is always the owner's.
    if found is None:
        found = (find_own_submission(user, va_sid), EDITOR_OWNER) if resubmit else find_revisable_submission(user, va_sid)
    draft, editor = found
    by_supervisor = editor == EDITOR_SUPERVISOR
    if by_supervisor:
        # The interview stays its interviewer's whoever corrects it.
        interviewer = db.session.get(VaUsers, draft.user_id)
        reason_code = SUPERVISOR_CORRECTION_REASON
        audit_role = interview_supervisor_actor(user.user_id).audit_role
        audit_action = "va_submission_revised_by_supervisor"
        source = SOURCE_SUPERVISOR_REVISION
        superseded_reason = SUPERSEDED_BY_SUPERVISOR_REVISION
        smartva_reason = SOURCE_SUPERVISOR_REVISION
    else:
        if not resubmit and reason_code not in REVISION_REASONS:
            raise WebIntakeError("reason_code must be one of: " + ", ".join(REVISION_REASONS) + ".", 422, "invalid_reason")
        interviewer = user
        audit_role = AUDIT_ROLE
        audit_action = "va_submission_revised_by_interviewer"
        source = SOURCE_INTERVIEWER_REVISION
        superseded_reason = "superseded_by_interviewer_revision"
        smartva_reason = "interview_revision"
    if draft is None:
        raise WebIntakeError("Submission not found.", 404)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    if death is not None:
        death = cases.lock_case(death)
    submission = db.session.get(VaSubmissions, va_sid, with_for_update=True)
    # Re-read under the locks: a revision that won meanwhile is the version
    # this one compares against.
    db.session.refresh(draft)
    if submission is None or draft.status != "submitted":
        raise WebIntakeError("Submission not found.", 404)
    # Under the lock: the owner's regression may have taken the case's submission meanwhile.
    if by_supervisor and (death is None or death.va_sid != va_sid):
        raise WebIntakeError("Submission not found.", 404)
    if ((draft.meta or {}).get("interviewOutcome") == "refused" or
            str(data.get("Id10013") or "").strip().lower() == "no"):
        raise WebIntakeError("A submitted interview cannot be changed to or from a refusal here.", 422, "consent_refused")
    state = get_submission_workflow_state(va_sid)
    # A sent-back or reopened case takes the revision and restarts coding at
    # once; every other protected state is locked, an ODK upstream change
    # included (the data manager resolves that one).
    reopening = state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED and facade().revision_unlocked(submission)
    locked = state in PROTECTED_WORKFLOW_STATES and not reopening
    if locked and not resubmit:
        raise WebIntakeError("Coding has finished on this interview; it can no longer be revised.", 409, "revision_locked")

    active = get_active_payload_version(va_sid)
    # The opened prior (sealed fields joined back with the payload split on):
    # it is the revision's carry, so ABHA and the identity answers survive.
    prior = opened_payload(active)
    previous = (draft.meta or {}).get("interviewOutcome") or prior.get("interview_outcome")
    now = facade()._utcnow()
    completed_at = _completion_time(envelope, now)

    def kept_apart(*, closed: bool) -> dict:
        """The resubmitted answers stay history; the coder's version stands."""
        _keep_losing_version(draft, data, answers_sha256, meta={
            "source": "resubmission", "effectiveSavedAt": completed_at.isoformat(), "receivedAt": now.isoformat(),
        })
        return {**_revision_reply(draft, active, False, previous), "kept": "server", "locked": closed}

    if resubmit:
        # Every submit and correction records it (no pre-release rows exist).
        stored_at = datetime.fromisoformat(draft.meta["effectiveSavedAt"])
        if locked:
            return kept_apart(closed=True)
        if completed_at < stored_at:
            return kept_apart(closed=False)
    # Only consent = no stores ``refused``, and the server writes it, so a
    # revision that corrects consent to yes may send it back unchanged. It
    # was never the interviewer's pick: not a conflict with consent.
    picked = data
    if previous == "refused" and data.get("interview_outcome") == "refused":
        picked = {name: value for name, value in data.items() if name != "interview_outcome"}
    outcome = _interview_outcome(picked, completion)
    regressing = previous == "completed" and outcome != "completed"
    completing = outcome == "completed" and previous != "completed"
    if by_supervisor and outcome != previous:
        raise WebIntakeError(
            "A supervisor correction keeps the interview's outcome; its interviewer changes that.",
            409, "case_state_conflict",
        )
    # Locked answers keep the value the interview was submitted with; one the
    # submit never held is filled from the case and the interviewer, as on a
    # submit. Recomputing them all would turn a renamed interviewer or a
    # corrected registration into a change to answers nobody edited.
    stored = _answers_of(draft)
    locked_answers = {name: stored.get(name, value) for name, value in _draft_locked_answers(draft).items()}
    raw = {**data, **locked_answers, "interview_outcome": outcome}
    if death is not None:
        refusal = None
        # A consent-withdrawn case is closed to every interview change too.
        if death.status in ("duplicate", "cancelled") or death.consent_withdrawn_at is not None:
            refusal = WebIntakeError("This case is closed.", 409, "case_closed")
        elif completing:
            if death.status == "submitted" and death.va_sid != va_sid:
                refusal = WebIntakeError("A complete interview of this case was already submitted.", 409, "case_already_submitted")
            else:
                facade()._require_live_org_unit(draft)
                # What the identity sync below will leave on the case.
                identity = {
                    "deceased_name": register_pii_accessor.current_values(death, ("deceased_name",))["deceased_name"],
                    "date_of_death": death.date_of_death,
                    "deceased_sex": death.deceased_sex, **_identity_from_answers(raw),
                }
                if not identity["date_of_death"]:
                    identity["date_of_death"] = _approximate_date_of_death(raw)
                if not all(identity.values()):
                    raise _missing_identity_error(
                        raw, name=bool(identity["deceased_name"]), sex=bool(identity["deceased_sex"]),
                        date_of_death=bool(identity["date_of_death"]),
                    )
        elif outcome != previous and death.status != OUTCOME_CASE_STATES[outcome] and death.va_sid != va_sid:
            # Incomplete to another incomplete outcome: the case follows it as
            # on a submit (via in_progress), or the revision is refused rather
            # than leave the case and the submission disagreeing. The case's
            # own winning submission always moves it (a regression included).
            if death.status not in _STARTABLE_STATES and death.status != "in_progress":
                refusal = WebIntakeError(
                    f"The case is {death.status}, so this interview's outcome can no longer be changed.",
                    409, "case_state_conflict",
                )
        if refusal is not None:
            if not resubmit:
                raise refusal
            return kept_apart(closed=True)

    # The interview start is when the family was interviewed: a revision never
    # moves it (docs/policy/interview-revisions.md, digitva-7amd.4), so the
    # stored start wins whatever the client sends, and a draft that has none
    # stays without one (the payload then falls back to the open time).
    meta = {
        **(draft.meta or {}),
        **{k: envelope[k] for k in (*_DEVICE_TIME_KEYS, *_DEFINITION_IDENTITY_KEYS) if k in envelope},
        **_clock_meta({k: v for k, v in envelope.items() if k != "startedAt"}, facade()._utcnow()),
    }
    if "startedAt" in (draft.meta or {}):
        meta["startedAt"] = draft.meta["startedAt"]
    else:
        meta.pop("startedAt", None)
    # Revisions and idempotent device resends rebuild the envelope from the
    # stored draft.  Merge the small client timeline streams before that
    # rebuild, retaining server-owned submitted/final_saved receipts.
    meta.update(merge_incoming_timeline_meta(draft, envelope, allow_server_receipts=True))
    # The original submit time and source: SubmissionDate, the masked id and
    # the default end time stay as they were, so they never read as a change.
    submitted_at = datetime.fromisoformat(prior["SubmissionDate"]) if prior.get("SubmissionDate") else draft.submitted_at
    expression_now = _device_time(meta.get("completedAt")) or _expression_now(interviewer, submitted_at)
    payload, references, validation_err = build_final_payload(
        draft, interviewer, raw, submitted_at=submitted_at, expression_now=expression_now, visit_note={},
        intake_source=prior.get("intake_source") or "web", meta=meta, carry=prior if active is not None else None,
    )
    # The form's own start answer (Id10011) is pinned the same way. A revision
    # session can stamp a new one, so the coded payload keeps the stored value;
    # the raw answers keep what was sent, so the acknowledged hash still holds.
    if prior.get("Id10011") is not None:
        payload["Id10011"] = prior["Id10011"]
    # Recomputed from the stored payload, as ensure_active_payload_version and
    # ODK sync decide "same payload" (payload_matches, both sides one rule):
    # a stored column from an older normalisation must not turn a no-op into
    # a release.
    if active is not None and payload_matches(active, payload):
        if answers_sha256 != draft.answers_sha256:
            _replace_raw_answers(draft, raw, answers_sha256, completion, at=now, version_id=active.payload_version_id)
        reply = _revision_reply(draft, active, False, outcome)
        draft.meta = {
            **meta,
            **({"effectiveSavedAt": completed_at.isoformat()} if resubmit else {}),
        }
        if resubmit:
            reply.update(kept="incoming", locked=False)
        return reply

    payload["updatedAt"] = now.isoformat()
    form = db.session.get(VaForms, draft.form_id)
    fields = build_submission_projection(form, payload)
    if fields["va_sid"] != va_sid:
        if resubmit:
            return kept_apart(closed=True)
        raise WebIntakeError("This interview's form changed; it cannot be revised.", 409)
    # All refusals above are decided; writes start here.
    if death is not None and outcome == "completed":
        _sync_case_identity(death, raw, user)
    apply_submission_projection(submission, fields, payload)
    version = ensure_active_payload_version(
        submission,
        payload_data=payload,
        source_updated_at=fields["va_odk_updatedat"],
        created_by_role=PAYLOAD_ROLE,
        created_by=user.user_id,
        validation_err=validation_err,
        revision_reason_code=reason_code,
        answers_sha256=answers_sha256,
    )
    attachments.link_to_submission(va_sid, draft.draft_id, payload)
    _replace_raw_answers(draft, raw, answers_sha256, completion, at=now, version_id=version.payload_version_id)
    draft.meta = {**meta, "attachmentReferences": references, "interviewOutcome": outcome, "effectiveSavedAt": completed_at.isoformat()}

    enters_coding = outcome == "completed" and consent_is_valid(normalize_consent(raw.get("Id10013")))
    # *source* is also the workflow reason ("interviewer_revision" / "supervisor_revision").
    try:
        if reopening:
            # The revision is the new payload: no pending upstream version may
            # linger beside it. Coding restarts at smartva_pending, then the
            # routing below puts the case where any revision would be.
            pending = get_latest_pending_upstream_payload_version(va_sid)
            if pending is not None:
                reject_pending_upstream_payload_version(pending, reason=superseded_reason)
            resolve_pending_upstream_change(
                va_sid, resolution_status=UPSTREAM_CHANGE_STATUS_REJECTED, resolved_by=user.user_id, resolved_by_role=audit_role,
            )
            reopen_coding_after_revision(va_sid, audit_by=user.user_id, source=source)
        else:
            release_coding_for_changed_payload(va_sid, source=source, audit_by=user.user_id)
        facade().route_synced_submission(va_sid, consent_valid=enters_coding, reason=source, actor=system_actor())
    except WorkflowTransitionError as exc:
        # A coder finalised between the check above and here; the route rolls back.
        raise WebIntakeError("Coding has finished on this interview; it can no longer be revised.", 409, "revision_locked") from exc
    if enters_coding and not references:
        mark_attachment_sync_completed(va_sid, reason="web_intake_no_attachments", actor=system_actor())
        smartva_service.queue_smartva_after_commit(va_sid, smartva_reason)
    if death is not None and outcome != previous:
        target = OUTCOME_CASE_STATES[outcome]
        if completing or death.status != target:
            _begin_interview(death, user)
            cases.transition(
                death, target, actor=user, action="submitted" if completing else f"submitted_{outcome}", reason=reason_code,
            )
        if completing:
            death.va_sid = va_sid
        elif regressing and death.va_sid == va_sid:
            # The case waits for a new complete interview; the regressed
            # submission stays linked through its draft only.
            death.va_sid = None
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole=audit_role,
        va_audit_by=user.user_id,
        va_audit_operation="u",
        va_audit_action=audit_action,
        va_audit_entityid=version.payload_version_id,
    ))
    db.session.flush()
    log.info("interview revised | sid=%s | by=%s | reason=%s | outcome=%s", va_sid, user.user_id, reason_code, outcome)
    reply = _revision_reply(draft, version, True, outcome)
    if resubmit:
        reply.update(kept="incoming", locked=False)
    return reply


def _replace_raw_answers(draft: VaWebIntakeDraft, raw: dict, answers_sha256: str, completion: dict, *, at: datetime, version_id: uuid.UUID) -> None:
    """Keep the draft's current raw answers as a ``replaced`` history row and
    make *raw* its only (``final``) section, with the sent hash and the
    completion that came with it. *version_id* is the payload version that was
    current when the answers were replaced."""
    _keep_history(draft, _answers_of(draft), sha256=draft.answers_sha256, meta={
        "source": "revision", "revisedAt": at.isoformat(), "payloadVersionId": str(version_id),
    })
    _set_final_section(draft, raw)
    for row in [r for r in draft.sections if r.section_name != FINAL_SECTION]:
        draft.sections.remove(row)
    draft.answers_sha256 = answers_sha256
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])


def _revision_reply(draft: VaWebIntakeDraft, version, changed: bool, outcome: str) -> dict:
    return {
        "changed": changed,
        "va_sid": draft.va_sid,
        "payload_version_id": str(version.payload_version_id),
        "answers_sha256": draft.answers_sha256,
        "outcome": outcome,
        "workflow_state": get_submission_workflow_state(draft.va_sid),
    }


#: Section holding the answers of a draft version that lost an edit conflict.
HISTORY_SECTION = "history"


def _keep_history(draft: VaWebIntakeDraft, answers: dict, *, sha256: str | None, meta: dict) -> None:
    """Keep a losing version of *draft* as a ``replaced`` draft row: same case,
    owner and form, answers in one ``history`` section, no client id (the
    unique index on it must not match) and not ``draft`` (so the one-open-draft
    index ignores it)."""
    row = VaWebIntakeDraft(
        project_id=draft.project_id, site_id=draft.site_id, org_unit_id=draft.org_unit_id,
        death_id=draft.death_id, form_id=draft.form_id, user_id=draft.user_id, unique_id=draft.unique_id,
        meta={"replacedDraftId": str(draft.draft_id), **meta}, prefill={},
        status="replaced", answers_sha256=sha256,
    )
    row.sections.append(VaWebIntakeDraftSection(section_name=HISTORY_SECTION, data=stored_answers(answers)))
    db.session.add(row)


def _keep_losing_version(draft: VaWebIntakeDraft, answers: dict, sha256: str | None, *, meta: dict, client_draft_id: str | None = None) -> None:
    """Keep a losing resend of *draft*'s interview as a ``replaced`` row, once:
    a retry of the same answers (same hash, and the same ``clientDraftId``
    when given) stores no second row. One indexed lookup on the case."""
    clauses = [
        VaWebIntakeDraft.death_id == draft.death_id,
        VaWebIntakeDraft.user_id == draft.user_id,
        VaWebIntakeDraft.status == "replaced",
        VaWebIntakeDraft.answers_sha256 == sha256,
    ]
    if client_draft_id is not None:
        clauses.append(VaWebIntakeDraft.meta["clientDraftId"].astext == client_draft_id)
    if not db.session.scalar(sa.select(sa.exists().where(*clauses))):
        _keep_history(draft, answers, sha256=sha256, meta=meta)
        db.session.flush()
