"""Device uploads (Path B) and device cases (Path B phase 3, digitva-kmk.4).

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseContactAttempt,
    VaDeathRegister,
    VaUsers,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services import case_transition_service as cases
from app.services.case_transition_service import WebIntakeError
from app.services.runtime_form_sync_service import ensure_web_runtime_form
from app.services.web_form_instruments import DEFAULT_LOCALE
from app.services.web_intake import facade
from app.services.web_intake.common import (
    INSTRUMENT_ID,
    _clock_meta,
    _completion_time,
    _device_time,
    log,
)
from app.services.web_intake.drafts import (
    _DEVICE_TIME_KEYS,
    _ENVELOPE_META_KEYS,
    _SUPERSEDED_CASE_STATES,
    DEVICE_SECTION,
    _answers_of,
    _locked_answers,
    _prefill_from_death,
    answers_of,
    check_definition_identity,
    check_device_answers,
    check_refusal_resume,
    is_new_refusal,
    load_draft_envelope,
    refusal_stale,
    release_who_refusal_hold,
    save_draft_sections,
    scrub_refused_draft,
    start_draft,
    stored_answers,
)
from app.services.web_intake.register import (
    _reporter_reaches,
    get_death,
    interviewer_reaches,
)
from app.services.web_intake.revision import (
    RESUBMITTED_REASON,
    _keep_history,
    _keep_losing_version,
    revise_submission,
)
from app.services.web_intake.scope import (
    _require_scope,
)
from app.services.web_intake.serializers import (
    serialize_draft,
)
from app.services.web_intake.submission import (
    _interview_outcome,
    _set_final_section,
    submit_draft,
)
from app.services.web_intake.worklist import (
    _worklist_select,
)


def check_device_times(envelope: dict) -> None:
    """Refuse (422) an envelope whose ``startedAt``, ``completedAt`` or
    ``deviceClockAt`` is present but not an ISO 8601 time with a UTC offset, or
    whose definition identity is malformed (``check_definition_identity``).
    Absent is fine (an older app)."""
    check_definition_identity(envelope)
    for field in ("startedAt", "completedAt", "deviceClockAt"):
        if field in envelope and _device_time(envelope[field]) is None:
            raise WebIntakeError(f"draft.{field} must be an ISO 8601 time with a UTC offset.", 422)
    offset = envelope.get("clockOffsetSeconds")
    if offset is not None and (not isinstance(offset, int) or isinstance(offset, bool)):
        raise WebIntakeError("draft.clockOffsetSeconds must be an integer number of seconds.", 422)


def find_device_upload(user: VaUsers, client_draft_id: uuid.UUID) -> VaWebIntakeDraft | None:
    """The draft an earlier upload of *client_draft_id* created, if any.
    Another interviewer's id is a 409, never their result."""
    draft = db.session.scalar(
        sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.client_draft_id == client_draft_id)
    )
    if draft is not None and draft.user_id != user.user_id:
        raise WebIntakeError("That client_draft_id is already in use.", 409)
    return draft


def is_attachment_draft(draft: VaWebIntakeDraft) -> bool:
    """True for the open draft ``start_attachment_draft`` made: it has a
    ``client_draft_id`` but no upload yet (an upload sets ``answers_sha256``
    and closes the draft)."""
    return draft.status == "draft" and draft.answers_sha256 is None


def start_attachment_draft(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None, client_draft_id: uuid.UUID) -> tuple[VaWebIntakeDraft, bool]:
    """The server draft a phone's direct start (no case) uploads its files to,
    identified by the phone's *client_draft_id*; returns ``(draft, created)``.

    ``submit_device_interview`` resolves the same draft by that id instead of
    starting another, so the files are on the submission. A repeat with the
    same id and the same project/site/unit is the same draft (idempotent). The
    id of another interviewer's draft is 409 (``find_device_upload``); of an
    already uploaded interview, or with another project, site or unit, 409.
    The draft is an ordinary open draft: an unsubmitted one follows the
    existing open-draft rules. A new one runs every ``start_draft`` check.
    """
    existing = facade().find_device_upload(user, client_draft_id)
    if existing is not None:
        if not is_attachment_draft(existing):
            raise WebIntakeError("That client_draft_id is already in use.", 409)
        _check_attachment_draft_matches(existing, project_id, site_id, org_unit_id)
        return existing, False
    draft = start_draft(user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id)
    draft.client_draft_id = client_draft_id
    db.session.flush()
    return draft, True


def _check_attachment_draft_matches(draft: VaWebIntakeDraft, project_id: str, site_id: str, org_unit_id: object | None) -> None:
    if draft.project_id != project_id or draft.site_id != site_id:
        raise WebIntakeError("That client_draft_id belongs to another project or site.", 409)
    if org_unit_id and str(draft.org_unit_id) != str(org_unit_id):
        raise WebIntakeError("That client_draft_id belongs to another unit.", 409)


def _store_superseded_copy(user: VaUsers, death: VaDeathRegister, *, client_draft_id: uuid.UUID, site_id: str, data: dict, answers_sha256: str, meta: dict, completion: dict) -> VaWebIntakeDraft:
    """Keep a device interview for a closed case as a ``superseded`` draft
    linked to the case: answers stored, no submission, no routing, and the
    case (its identity included) left exactly as it is.

    The uploader's own open draft (on this case, or the phone's attachment
    draft of *client_draft_id*) is closed as ``replaced`` and its uploaded
    files move to the copy: the phone deletes its local copy on the 2xx, so
    the copy must hold them for a supervisor's choice, and the stale-draft
    purge reads open drafts only. Stored objects stay where they are (each row
    carries its own path). Runs under the case lock the submit holds."""
    if death.site_id != site_id:
        raise WebIntakeError("Death entry belongs to another project or site.")
    open_drafts = db.session.scalars(
        sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.status == "draft", VaWebIntakeDraft.user_id == user.user_id,
            sa.or_(VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.client_draft_id == client_draft_id),
        ).with_for_update()
    ).all()
    for old in open_drafts:
        # The copy takes the phone's id (retries of this upload find the copy).
        if old.client_draft_id == client_draft_id:
            old.client_draft_id = None
    db.session.flush()
    try:
        outcome = _interview_outcome(data, completion)
    except WebIntakeError:
        outcome = None
    form = ensure_web_runtime_form(death.project_id, death.site_id)
    # Stored answers get the same locked-answer rule as a submission.
    prefill = _prefill_from_death(death, user, death.org_unit_id)
    data = {**data, **_locked_answers(prefill)}
    now = facade()._utcnow()
    draft = VaWebIntakeDraft(
        project_id=death.project_id,
        site_id=death.site_id,
        org_unit_id=death.org_unit_id,
        death_id=death.death_id,
        form_id=form.form_id,
        user_id=user.user_id,
        unique_id=death.unique_id,
        meta={"instrumentId": INSTRUMENT_ID, "locale": DEFAULT_LOCALE, "translation_version": 0,
              **meta, "interviewOutcome": outcome},
        prefill=prefill,
        status="superseded",
        client_draft_id=client_draft_id,
        answers_sha256=answers_sha256,
        submitted_at=now,
        client_valid=completion.get("valid") is True,
    )
    draft.sections.append(VaWebIntakeDraftSection(section_name=DEVICE_SECTION, data=stored_answers(data)))
    db.session.add(draft)
    db.session.flush()
    moved = 0
    for old in open_drafts:
        moved += db.session.execute(
            sa.update(VaWebIntakeAttachment).where(VaWebIntakeAttachment.draft_id == old.draft_id)
            .values(draft_id=draft.draft_id)
        ).rowcount
        old.status = "replaced"
        old.meta = {**(old.meta or {}), "replacedDraftId": str(draft.draft_id)}
    if moved:
        cases.record_action(death, actor=user, action="draft_files_moved_to_copy")
    db.session.flush()
    log.info("device interview kept as superseded copy | unique_id=%s | case_status=%s | by=%s", death.unique_id, death.status, user.user_id)
    return draft


def _device_completion(completion: dict, data: dict) -> dict:
    """The upload's ``{valid, issues}`` normalised, with the parsed answers as ``data``."""
    return {
        "valid": completion.get("valid") is True,
        "issues": completion.get("issues") if isinstance(completion.get("issues"), list) else [],
        "data": data,
    }


def _own_submitted_draft(user: VaUsers, death: VaDeathRegister) -> VaWebIntakeDraft | None:
    """The caller's submitted draft of *death* that a later upload of the same
    interview corrects (docs/policy/web-intake.md "Parallel interviews"): the
    one that won the case, else their latest. None when they have none, or
    when a teammate's complete submission or a supervisor closed the case and
    theirs is not the winner: that upload stays a superseded copy. One query
    on ``ix_va_web_intake_drafts_death``."""
    own = db.session.scalar(
        sa.select(VaWebIntakeDraft)
        .where(
            VaWebIntakeDraft.death_id == death.death_id,
            VaWebIntakeDraft.user_id == user.user_id,
            VaWebIntakeDraft.status == "submitted",
        )
        .order_by(sa.case((VaWebIntakeDraft.va_sid == death.va_sid, 0), else_=1), VaWebIntakeDraft.submitted_at.desc())
        .limit(1)
    )
    if own is not None and (own.va_sid == death.va_sid or death.status not in _SUPERSEDED_CASE_STATES):
        return own
    return None


def resubmit_device_interview(user: VaUsers, draft: VaWebIntakeDraft, *, envelope: dict, data: dict, answers_sha256: str, completion: dict) -> tuple[str, bool]:
    """Apply an upload of *draft*'s interview that is not the first (a resend
    with other answers, or a second upload of the case); returns
    ``(kept, locked)``.

    The last completed version wins: this one becomes the coder's version when
    its completion time is not older than the stored one's
    (``revise_submission`` with ``resubmit``, reason ``RESUBMITTED_REASON``),
    else, or when coding is final or the case closed (*locked*), its answers
    are kept as ``replaced`` history and ``kept`` is ``"server"``. A
    ``superseded`` copy (a closed case's upload) keeps the resend as history
    the same way, locked."""
    completion = _device_completion(completion, data)
    if draft.status != "submitted":
        now = facade()._utcnow()
        _keep_losing_version(draft, data, answers_sha256, meta={
            "source": "resubmission", "effectiveSavedAt": _completion_time(envelope, now).isoformat(),
            "receivedAt": now.isoformat(),
        })
        return "server", True
    reply = revise_submission(
        user, draft.va_sid, reason_code=RESUBMITTED_REASON, data=data, answers_sha256=answers_sha256,
        completion=completion, envelope=envelope, resubmit=True,
    )
    return reply["kept"], reply["locked"]


def resubmit_browser_draft(user: VaUsers, draft: VaWebIntakeDraft, *, completion: dict) -> dict:
    """A browser submit of a draft that is already submitted (a stale tab, a
    second completion): the later completion is a correction of the interview
    (``revise_submission`` with ``resubmit``, completed now). Returns its reply
    (``kept``, ``locked``, ``va_sid``...). Refusals as ``submit_draft``'s for
    the completion (422), 404 when it is not the caller's."""
    if not isinstance(completion, dict) or not isinstance(completion.get("data"), dict):
        raise WebIntakeError("completion.data is required.")
    data = completion["data"]
    check_device_answers(data)
    # A browser draft has no device hash; the correction needs one to tell
    # answers apart, taken over the data in a fixed form.
    sha = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8", "surrogatepass")).hexdigest()
    return revise_submission(
        user, draft.va_sid, reason_code=RESUBMITTED_REASON, data=data, answers_sha256=sha,
        completion={
            "valid": completion.get("valid") is True,
            "issues": completion.get("issues") if isinstance(completion.get("issues"), list) else [],
        },
        envelope={}, resubmit=True,
    )


def fold_into_own_submission(user: VaUsers, draft: VaWebIntakeDraft, *, completion: dict) -> tuple[VaWebIntakeDraft, dict] | None:
    """A browser submit of the open *draft* on a case whose winning submission
    is the caller's own (an earlier draft of theirs: reachable once that one
    regressed and the interviewer then opened a new draft, see "Parallel
    interviews"): the second completion is a correction of that interview, not
    a teammate's competing copy. Returns ``(winning_draft, reply)`` with the
    reply of ``resubmit_browser_draft``, or None when the case's winner is not
    the caller's (``submit_draft`` then decides as before).

    *draft* is closed as ``replaced``: its final answers are kept on it, and
    the same answers are a payload version of the submission, or ``replaced``
    history when coding is final or the version is older (``revise_submission``'s
    resubmit rules). A teammate's draft is never folded."""
    if draft.status != "draft" or not draft.death_id:
        return None
    # Under the case lock, so the winner read here is the one revised below.
    death = cases.lock_case(db.session.get(VaDeathRegister, draft.death_id))
    if death.status != "submitted" or death.va_sid is None:
        return None
    own = db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.va_sid == death.va_sid,
        VaWebIntakeDraft.user_id == user.user_id,
        VaWebIntakeDraft.status == "submitted",
    ))
    if own is None:
        return None
    reply = resubmit_browser_draft(user, own, completion=completion)
    _set_final_section(draft, completion["data"])
    draft.status = "replaced"
    draft.meta = {**(draft.meta or {}), "replacedDraftId": str(own.draft_id)}
    draft.submitted_at = facade()._utcnow()
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])
    db.session.flush()
    log.info("draft folded into own submission | sid=%s | unique_id=%s | by=%s", own.va_sid, draft.unique_id, user.user_id)
    return own, reply


def submit_device_interview(user: VaUsers, *, project_id: str, client_draft_id: uuid.UUID, site_id: str, org_unit_id: object | None, death_id: object | None, envelope: dict, data: dict, answers_sha256: str, completion: dict, device_id: uuid.UUID | None = None, unrouted_ok: bool = False, refusal_override: bool | None = None, resume_refused: bool = False, base_updated_at: object | None = None, incoming_consent=None) -> tuple[VaWebIntakeDraft, str, bool]:
    """Store and submit one completed device interview; returns
    ``(draft, kept, locked)`` (``"incoming"``/``"server"``: whose answers are
    the coder's version; *locked*: coding is final or the case closed).

    The same path as a web submit: ``start_draft`` (scope, case, prefill) in
    *project_id* only, which returns the interviewer's own open draft on the
    case when there is one (the upload completes it), the answers saved
    through ``save_draft_sections``, then ``submit_draft`` with
    ``intake_source = device``. When the caller already submitted an interview
    of the case, the upload is a later version of it
    (``resubmit_device_interview``) and no new draft is made. A case already
    closed is kept as a superseded copy instead (``_store_superseded_copy``).
    An open draft with browser saves newer than this completion keeps its
    content as ``replaced`` history first: the completion is the version
    submitted. *completion* is ``{valid, issues}`` from the app's form engine;
    without ``valid: true`` the upload needs an incomplete ``interview_outcome``
    pick, exactly as on the web. Idempotency is the caller's
    (``find_device_upload`` first; ``client_draft_id`` is unique).
    *device_id* is the uploading device's id, None for a browser-cookie request.
    *unrouted_ok*: a standalone push may start without a unit (``_require_scope``).
    *envelope* supplies only the meta keys; *data* is the parsed answers and
    *answers_sha256* the hash of their exact JSON text, both already checked
    by the caller (``check_device_answers``) and stored with the upload.
    """
    meta = {k: envelope[k] for k in _ENVELOPE_META_KEYS if k in envelope}
    # Stored beside the draft's meta, never through the client keep-list.
    stored = {k: envelope[k] for k in _DEVICE_TIME_KEYS if k in envelope}
    if device_id is not None:
        stored["deviceId"] = str(device_id)
    now = facade()._utcnow()
    stored.update(_clock_meta(envelope, now))
    device_clock = _device_time(envelope.get("deviceClockAt"))
    if device_clock is not None:
        # Positive = the device clock is behind the server. Audit only: the
        # interview times above are never corrected by it.
        stored["clockSkewSeconds"] = round((now - device_clock).total_seconds())
    completed_at = _completion_time(envelope, now)
    completion = _device_completion(completion, data)
    entries = facade().interviewer_context(user)
    death = None
    case_hold = None
    if death_id:
        death = cases.lock_case(get_death(user, death_id, entries=entries))
        if death.project_id != project_id:
            raise WebIntakeError("Death entry not found.", 404)
        from app.services import consent_service
        case_hold = consent_service.case_refusal_hold(death)
        refusal_override = consent_service.interview_refused(
            death=death, client_draft_id=client_draft_id, answers=data, consent=incoming_consent, known_case_hold=case_hold,
        )
        attempting_resume = (resume_refused and data.get("Id10013") == "yes"
                              and case_hold)
        if refusal_override and not attempting_resume:
            consent_service.check_refusal_answers(data)
        own = _own_submitted_draft(user, death)
        if own is not None:
            if refusal_override:
                raise WebIntakeError("Another interview holds this case after a refusal.", 409, "consent_refused")
            kept, locked = resubmit_device_interview(
                user, own, envelope=envelope, data=data, answers_sha256=answers_sha256, completion=completion,
            )
            return own, kept, locked
        if death.status in _SUPERSEDED_CASE_STATES:
            copy = _store_superseded_copy(
                user, death, client_draft_id=client_draft_id, site_id=site_id,
                data=data, answers_sha256=answers_sha256, meta={**meta, **stored}, completion=completion,
            )
            return copy, "server", True
    pending = facade().find_device_upload(user, client_draft_id)
    if pending is not None and is_attachment_draft(pending):
        # The phone's direct start made this draft for its files: the upload
        # completes it. It is a direct draft, so a request naming a case is
        # not for it.
        if death_id:
            raise WebIntakeError("That client_draft_id is already in use.", 409)
        if pending.death_id:
            death = cases.lock_case(db.session.get(VaDeathRegister, pending.death_id))
        pending = db.session.get(VaWebIntakeDraft, pending.draft_id, with_for_update=True, populate_existing=True)
        if not is_attachment_draft(pending):
            raise WebIntakeError("This draft is no longer editable.", 409)
        _check_attachment_draft_matches(pending, project_id, site_id, org_unit_id)
        _require_scope(user, project_id, site_id, pending.org_unit_id, entries=entries)
        draft = pending
    else:
        draft = start_draft(
            user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id,
            death_id=death_id, entries=entries, locked_death=death, unrouted_ok=unrouted_ok,
        )
    from app.services import consent_service
    if draft.death_id and case_hold is None:
        case_hold = consent_service.case_refusal_hold(db.session.get(VaDeathRegister, draft.death_id))
    if case_hold and not (draft.meta or {}).get("caseRefusalHold"):
        raise WebIntakeError("Another interview holds this case after a refusal.", 409, "consent_refused")
    released = release_who_refusal_hold(draft, answers=data, base_updated_at=base_updated_at,
                                        resume_refused=resume_refused, consent=incoming_consent)
    if released:
        case_hold = False
    if not death_id or released:
        refusal_override = consent_service.interview_refused(
            death=db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None,
            client_draft_id=client_draft_id, answers=data, consent=incoming_consent, known_case_hold=case_hold,
        )
    if refusal_override:
        consent_service.check_refusal_answers(data)
    if (not released and str(_answers_of(draft).get("Id10013") or "").lower() == "no"
            and str(data.get("Id10013") or "").lower() != "no"):
        if not (resume_refused and data.get("Id10013") == "yes"
                and _device_time(base_updated_at) == draft.updated_at):
            raise refusal_stale(draft, "Reload the draft and record the new consent decision.")
    if not refusal_override and not released:
        check_refusal_resume(draft, base_updated_at=base_updated_at, resume_refused=resume_refused)
    if draft.sections:
        # An open draft with content: the phone's own earlier sync is the same
        # draft continuing; a newer browser save is unfinished work that must
        # not be lost to the completion (the last completed version wins).
        draft_meta = draft.meta or {}
        from_phone = draft.answers_sha256 is not None
        edited = datetime.fromisoformat(draft_meta["effectiveSavedAt"]) if from_phone and draft_meta.get("effectiveSavedAt") else draft.updated_at
        own_sync = from_phone and (draft_meta.get("lastSync") or {}).get("clientDraftId") == str(client_draft_id)
        if edited > completed_at and not own_sync:
            _keep_history(draft, _merged_answers(draft), sha256=draft.answers_sha256, meta={
                "source": "device" if from_phone else "web", "effectiveSavedAt": edited.isoformat(),
                "receivedAt": now.isoformat(),
            })
    draft.client_draft_id = client_draft_id
    draft.answers_sha256 = answers_sha256
    draft.meta = {**(draft.meta or {}), **stored}
    # The incoming consent is recorded after this call, so it is passed in;
    # the save clears the teammates, so the submit (same request) does not.
    new = refusal_override is not False and is_new_refusal(draft, data, incoming_consent, client_draft_id)
    save_draft_sections(draft, sections={DEVICE_SECTION: data}, meta=meta or None, actor=user,
                        refusal_override=refusal_override, resume_refused=resume_refused, new_refusal=new,
                        channel="device")
    if submit_draft(draft, user, completion=completion, intake_source="device", completed_at=completed_at, locked_death=death, refusal_override=refusal_override, new_refusal=False) is None:
        return draft, "server", True
    return draft, "incoming", False


SYNC_MESSAGE = "This interview was also edited on another device; the newer version was kept."


def lock_draft_for_browser_write(draft: VaWebIntakeDraft) -> VaWebIntakeDraft:
    """Take the case lock a phone sync takes (``start_draft``), then re-read
    the draft, so a browser save or submit and a concurrent sync serialise and
    the stale check below sees the committed version."""
    if draft.death_id:
        cases.lock_case(db.session.get(VaDeathRegister, draft.death_id))
        db.session.refresh(draft)
        if draft.status != "draft":
            raise WebIntakeError("This draft is no longer editable.", 409)
    return draft


def _merged_answers(draft: VaWebIntakeDraft) -> dict:
    merged: dict = {}
    for row in draft.sections:
        merged.update(row.data or {})
    return merged


def prepare_browser_overwrite(draft: VaWebIntakeDraft, sections: dict) -> dict:
    """A deliberate browser "Use my answers" (``PATCH ... overwrite``): keep
    the version it replaces as a ``replaced`` row (the trail, and a way back)
    and return *sections* plus every other saved section emptied, the phone's
    included, so the browser's answers replace the draft whole."""
    if draft.sections:
        _keep_history(draft, _merged_answers(draft), sha256=draft.answers_sha256, meta={
            "source": "device" if draft.answers_sha256 else "web",
            "receivedAt": facade()._utcnow().isoformat(), "overwrittenBy": "web",
        })
    return {**{row.section_name: {} for row in draft.sections}, **sections}


def prepare_browser_save(draft: VaWebIntakeDraft, sections: dict, *, base_updated_at: object,
                         resume_refused: bool) -> dict:
    """The browser autosave's pre-step (``PATCH /drafts/<id>``), on the draft
    ``lock_draft_for_browser_write`` returned and after the route's stale
    checks: returns *sections* without the covered answers no consent on file
    takes (``strip_unconsented_answers``, judged on every section's answers,
    an empty later value never hiding a filled earlier one), then applies the
    refusal rules to the draft's answers with these merged in: a teammate's
    case refusal hold, the WHO refusal-hold release and the refusal resume.
    *base_updated_at* is the body's ``if_updated_at``.
    Raises WebIntakeError: 422 ``invalid_interview`` (over 128 sections), 409
    ``consent_refused`` (another interview holds the case), 409
    ``refusal_stale``."""
    from app.services import consent_service  # local: consent_service imports this module
    from app.services.interview_intake_gate import check_refusal_transition

    if len(sections) > 128:
        raise WebIntakeError("Too many draft sections.", 422, "invalid_interview")
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    combined = {}
    for answers in sections.values():
        if isinstance(answers, dict):
            for name, value in answers.items():
                if name not in combined or consent_service.filled(value):
                    combined[name] = value
    allowed, _ = consent_service.strip_unconsented_answers(
        project_id=draft.project_id, death=death, client_draft_id=draft.client_draft_id, answers=combined,
    )
    sections = {
        name: {key: value for key, value in answers.items() if key in allowed}
        if isinstance(answers, dict) else answers
        for name, answers in sections.items()
    }
    combined = answers_of(draft)
    for answers in sections.values():
        if isinstance(answers, dict):
            combined.update(answers)
    if death is not None and consent_service.case_refusal_hold(death) and not (draft.meta or {}).get("caseRefusalHold"):
        raise WebIntakeError("Another interview holds this case after a refusal.", 409, "consent_refused")
    released = release_who_refusal_hold(
        draft, answers=combined, base_updated_at=base_updated_at, resume_refused=resume_refused,
    )
    if not check_refusal_transition(death_id=draft.death_id, client_draft_id=draft.client_draft_id,
                                    answers=combined):
        if not released:
            check_refusal_resume(draft, base_updated_at=base_updated_at, resume_refused=resume_refused)
    return sections


def prepare_browser_submit(user: VaUsers, draft: VaWebIntakeDraft, completion: object) -> None:
    """The browser submit's pre-step (``POST /drafts/<id>/submit``), before
    the route decides between a first submit and a correction: when
    *completion* carries answers, every branch stores them, so the consent on
    file must cover them (``apply_interview_consent``; the browser cannot take
    a consent yet, digitva-athy) and a refusal must carry no interview
    answers (``check_refusal_answers``). Raises ConsentError."""
    from app.services import consent_service  # local: consent_service imports this module
    from app.services.interview_intake_gate import check_refusal_transition

    if not (isinstance(completion, dict) and isinstance(completion.get("data"), dict)):
        return
    consent_service.apply_interview_consent(
        user, project_id=draft.project_id,
        death=db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None,
        client_draft_id=draft.client_draft_id, consent=None, answers=completion["data"], channel="web",
    )
    if check_refusal_transition(death_id=draft.death_id, client_draft_id=draft.client_draft_id,
                                answers=completion["data"]):
        consent_service.check_refusal_answers(completion["data"])


def _sync_reply(draft: VaWebIntakeDraft, kept: str, conflict: bool) -> dict:
    reply = {
        "draft": serialize_draft(draft),
        "kept": kept,
        "conflict": conflict,
        "answers_sha256": draft.answers_sha256,
        "message": SYNC_MESSAGE if conflict else None,
    }
    if kept == "server":
        reply["envelope"] = load_draft_envelope(draft)  # the phone replaces its copy
    return reply


def sync_device_draft(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None, death_id: object | None, client_draft_id: uuid.UUID, envelope: dict, data: dict, answers_sha256: str, saved_at: object, device_clock_at: object, base_updated_at: object | None, resume_refused: bool = False) -> dict:
    """Sync a phone's in-progress interview into the interviewer's one open
    draft of the case (web-intake.md "Parallel interviews"); returns the reply.

    The newer save wins, whole (no section merge): the phone's ``saved_at``
    corrected by the device clock's drift (``now - device_clock_at`` is how old
    the save is on the device, so the correction needs no absolute clock),
    against the draft's last save (``updated_at``, or the corrected phone time
    of an earlier phone win nobody has edited since). A tie goes to the phone,
    which is received later. The loser is kept as a ``replaced`` row. A conflict
    is a draft the phone had not seen (``base_updated_at`` is the ``updated_at``
    of its last download or sync reply, None if never); without one the phone
    simply continues the draft and always wins. A resend is a no-op.
    Never sets the draft's ``client_draft_id``: only the final upload does.
    Refusals (all before anything is written): 422 for the times, 400
    without a case, and ``start_draft``'s own (a closed case is 409).
    """
    saved = _device_time(saved_at)
    clock = _device_time(device_clock_at)
    if saved is None or clock is None:
        raise WebIntakeError("savedAt and deviceClockAt must be ISO 8601 times with a UTC offset.", 422)
    base = None
    if base_updated_at is not None:
        base = _device_time(base_updated_at)
        if base is None:
            raise WebIntakeError("base_updated_at must be null or an ISO 8601 time with a UTC offset.", 422)
    check_device_times(envelope)
    if not death_id:
        raise WebIntakeError("death_id is required.")
    now = facade()._utcnow()
    draft = start_draft(user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id, death_id=death_id)
    from app.services import consent_service  # local: consent_service imports this module
    if consent_service.case_refusal_hold(db.session.get(VaDeathRegister, draft.death_id)) and not (draft.meta or {}).get("caseRefusalHold"):
        raise WebIntakeError("Another interview holds this case after a refusal.", 409, "consent_refused")
    resume_refused = resume_refused and base is not None and base == draft.updated_at
    released = release_who_refusal_hold(draft, answers=data, base_updated_at=base_updated_at,
                                        resume_refused=resume_refused)
    if str(_answers_of(draft).get("Id10013") or "").strip().lower() == "no" and not resume_refused:
        data = {**data, "Id10013": "no"}
    # No covered answer is stored without a granted consent on file (the gate of /submissions); the hash
    # stays the phone's, so a resend of the same save is still recognised below.
    data, stripped = consent_service.strip_unconsented_answers(
        project_id=draft.project_id, death=db.session.get(VaDeathRegister, draft.death_id),
        client_draft_id=client_draft_id, answers=data)
    combined = {**_answers_of(draft), **data}
    refused = consent_service.interview_refused(
        death=db.session.get(VaDeathRegister, draft.death_id),
        client_draft_id=client_draft_id, answers=combined,
    )
    if not refused and not released:
        check_refusal_resume(draft, base_updated_at=base_updated_at, resume_refused=resume_refused)
    # Decided before the scrub below marks the draft refused.
    new = refused and is_new_refusal(draft, combined, client_draft_id=client_draft_id)
    if refused:
        cleaned = consent_service.refusal_answers(data)
        stripped = stripped or cleaned != data
        data = cleaned
        scrub_refused_draft(draft)
    meta = draft.meta or {}
    last = meta.get("lastSync") or {}
    cid = str(client_draft_id)
    # The phone's own earlier version, untouched since: the same draft
    # continuing, never a conflict. A stripped earlier sync is not a no-op
    # resend: once consent is on file the same hash stores the full answers.
    from_phone = draft.answers_sha256 is not None and last.get("clientDraftId") == cid
    if from_phone and draft.answers_sha256 == answers_sha256 and refused:
        draft.meta = {**meta, "lastSync": {**last, "refusal": True, "stripped": True}}
        db.session.flush()
        return _sync_reply(draft, "server", bool(last.get("conflict")))
    if from_phone and draft.answers_sha256 == answers_sha256 and last.get("refusal") and not refused:
        return _sync_reply(draft, "server", False)
    if from_phone and draft.answers_sha256 == answers_sha256 and not last.get("stripped"):
        return _sync_reply(draft, "incoming", bool(last.get("conflict")))
    has_content = bool(draft.sections)
    effective = min(now, now - (clock - saved))
    # An untouched phone win is dated by its corrected save time, not by the
    # (later) moment it was received.
    phone_won = draft.answers_sha256 is not None and meta.get("effectiveSavedAt")
    current = datetime.fromisoformat(meta["effectiveSavedAt"]) if phone_won else draft.updated_at
    conflict = has_content and not from_phone and (base is None or base != draft.updated_at)
    redo_stripped = from_phone and draft.answers_sha256 == answers_sha256
    if redo_stripped:
        incoming_wins = True
    elif has_content and (conflict or from_phone):
        incoming_wins = effective >= current
    else:
        incoming_wins = True
    source = "device" if phone_won else "web"
    if not incoming_wins:
        if conflict:
            _keep_losing_version(draft, data, answers_sha256, client_draft_id=cid, meta={
                "source": "device", "clientDraftId": cid, "savedAt": saved.isoformat(),
                "effectiveSavedAt": effective.isoformat(), "receivedAt": now.isoformat(),
            })
        return _sync_reply(draft, "server", conflict)
    if conflict:
        _keep_history(draft, _merged_answers(draft), sha256=draft.answers_sha256, meta={
            "source": source, "effectiveSavedAt": current.isoformat(), "receivedAt": now.isoformat(),
        })
    for row in [r for r in draft.sections if r.section_name != DEVICE_SECTION]:
        draft.sections.remove(row)
    draft.answers_sha256 = answers_sha256
    stored = {k: envelope[k] for k in ("startedAt",) if k in envelope}
    stored.update(_clock_meta(envelope, now))
    draft.meta = {
        **meta, **stored,
        "effectiveSavedAt": effective.isoformat(),
        "clockSkewSeconds": round((now - clock).total_seconds()),
        "lastSync": {"clientDraftId": cid, "conflict": conflict, **({"stripped": True} if stripped else {}),
                     **({"refusal": True} if refused else {})},
    }
    section = envelope.get("currentSection")
    save_draft_sections(
        draft, sections={DEVICE_SECTION: data},
        meta={k: envelope[k] for k in _ENVELOPE_META_KEYS if k in envelope} or None,
        current_section=section if isinstance(section, str) and section else None, actor=user, resume_refused=resume_refused,
        # The draft has no client_draft_id until its upload: the attempt's
        # own consent decided *refused* above, so it is passed on.
        refusal_override=refused, new_refusal=new, channel="device",
    )
    log.info("device draft synced | unique_id=%s | conflict=%s | by=%s", draft.unique_id, conflict, user.user_id)
    return _sync_reply(draft, "server" if refused else "incoming", conflict)


def serialize_device_upload(draft: VaWebIntakeDraft) -> dict:
    """The contract's upload result, rebuilt from the stored draft so a
    resend gets the same ``va_sid``, case and outcome as the first upload;
    ``case.status`` is the case's current state."""
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    return {
        "va_sid": draft.va_sid,
        "case": {
            "death_id": str(death.death_id) if death else None,
            "unique_id": draft.unique_id,
            "status": death.status if death else None,
        },
        "outcome": (draft.meta or {}).get("interviewOutcome"),
        "superseded": draft.status == "superseded",
        "answers_sha256": draft.answers_sha256,
    }


def case_prefill(user: VaUsers, death: VaDeathRegister, my_draft_id: uuid.UUID | None) -> dict | None:
    """What the web form page prefills for *death*: the case detail's
    ``prefill``, so an interview started offline opens prefilled. Carries the
    questionnaire's own answers (informant's and parents' names, address,
    ABHA), never a phone number.

    Only for a caller who may start or resume the interview, as
    ``start_draft`` decides: they hold the case's own draft (*my_draft_id*),
    or the case is open (another interviewer's draft does not matter).
    Otherwise None (a closed case): the identifiers are not theirs to read.
    """
    if not interviewer_reaches(user, death):
        return None
    if my_draft_id is None and death.status in _SUPERSEDED_CASE_STATES:
        return None
    return _prefill_from_death(death, user, death.org_unit_id)


def case_row(user: VaUsers, death: VaDeathRegister) -> tuple:
    """A ``_worklist_select`` row for a case the caller already holds in scope
    (an offline registration's reply): the worklist query for that one case,
    without its scope."""
    return tuple(
        db.session.execute(_worklist_select(user).where(VaDeathRegister.death_id == death.death_id)).one()
    )


def get_device_case(user: VaUsers, project_id: str, death_id: object) -> VaDeathRegister:
    """A case in the caller's scope and in *project_id*, else 404."""
    death = get_death(user, death_id)
    if death.project_id != project_id:
        raise WebIntakeError("Death entry not found.", 404)
    return death


def find_device_registration(user: VaUsers, project_id: str, client_death_id: uuid.UUID) -> VaDeathRegister | None:
    """The case an earlier offline registration with *client_death_id*
    created, if any. Another user's id is a 409; a case since moved out of
    the caller's scope or *project_id* is a 404."""
    death = db.session.scalar(
        sa.select(VaDeathRegister).where(VaDeathRegister.client_death_id == client_death_id)
    )
    if death is None:
        return None
    if death.registered_by != user.user_id:
        raise WebIntakeError("That client_death_id is already in use.", 409)
    try:
        return get_device_case(user, project_id, death.death_id)
    except WebIntakeError:
        # A death_reporter registered it: theirs by the reporter's reach.
        if death.project_id == project_id and _reporter_reaches(user, death):
            return death
        raise


def find_device_attempt(user: VaUsers, death_id: object, client_attempt_id: uuid.UUID) -> VaDeathRegister | None:
    """The case of an earlier attempt logged with *client_attempt_id*, if
    any. The id reused by another user or on another case is a 409."""
    attempt = db.session.scalar(
        sa.select(MapCaseContactAttempt).where(MapCaseContactAttempt.client_attempt_id == client_attempt_id)
    )
    if attempt is None:
        return None
    try:
        same_case = attempt.death_id == uuid.UUID(str(death_id))
    except ValueError:
        same_case = False
    if attempt.by_user_id != user.user_id or not same_case:
        raise WebIntakeError("That client_attempt_id is already in use.", 409)
    return get_death(user, attempt.death_id)
