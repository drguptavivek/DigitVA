"""Submission: turning a draft into a submission, its payload and its case move.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
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
    collection_hold,
    notification_service,
    public_demo_service,
    register_pii_accessor,
    served_form_service,
    smartva_service,
)
from app.services import org_unit_routing_service as org_routing
from app.services import organization_service as org
from app.services import web_intake_attachment_service as attachments
from app.services.case_transition_service import WebIntakeError
from app.services.project_country_service import project_country
from app.services.submission_payload_version_service import (
    ensure_active_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    build_submission_projection,
    consent_is_valid,
    normalize_consent,
)
from app.services.web_form_instruments import DEFAULT_LOCALE
from app.services.web_form_relevance_service import (
    form_version_of,
)
from app.services.web_intake import facade
from app.services.web_intake.common import (
    AUDIT_ROLE,
    PAYLOAD_ROLE,
    _device_time,
    _expression_now,
    log,
)
from app.services.web_intake.drafts import (
    _SUPERSEDED_CASE_STATES,
    _TIMELINE_META_KEY,
    FINAL_SECTION,
    _begin_interview,
    _draft_locked_answers,
    _is_attachment_reference,
    _missing_identity_error,
    _sync_case_identity,
    check_device_answers,
    clear_direct_identity_for_refusal,
    is_new_refusal,
    scrub_refused_draft,
    stored_answers,
)
from app.services.web_intake.register import (
    _clean,
    _clean_date,
)
from app.services.web_intake.scope import (
    _unit_context,
)
from app.services.who_age_normalization import derive_final_age_in_years
from app.services.workflow.transitions import (
    mark_attachment_sync_completed,
    system_actor,
)
from app.services.workflow_timeline_service import (
    INTERVIEW_TIMELINE_EVENTS,
    WorkflowTimelineError,
    merge_timeline,
    server_event,
)
from app.utils.national_id import redact_national_id_digits, redact_payload_national_ids


def build_web_payload(draft: VaWebIntakeDraft, data: dict, user: VaUsers, *, submitted_at: datetime, intake_source: str = "web", meta: dict | None = None, carry: dict | None = None, attachments_from: VaWebIntakeDraft | None = None) -> tuple[dict, dict]:
    """Return (payload, attachment_references) shaped like a synced ODK record.

    An attachment answer whose file the server holds (uploaded for
    *attachments_from*, default *draft*: ``web_intake_attachment_service``)
    carries that file's filename in the payload, as an ODK answer does, and is
    linked to the submission by ``attachments.link_to_submission``. An answer
    whose file has not reached the server is lifted out of the payload and
    returned in ``attachment_references`` (slot name -> reference): empty means
    every attachment is held. ``AttachmentsExpected`` counts both kinds.

    ``meta`` replaces ``draft.meta`` when given (a revision builds the next
    version before it changes the draft).

    ``carry`` is the payload a revision replaces. Every value that is not an
    answer or an interview time is taken from it instead of today's world
    (the submitter's name, the organization-unit codes and names, the death
    register's ABHA), so renaming the interviewer or a unit after the submit
    does not turn a resend of the same answers into a change. So are the
    identifiers ``sid``, ``KEY`` and ``instanceID``: the submission keeps its
    id when another interviewer's draft supplies the answers (a supervisor's
    choice, ``choose_interview``), where they would otherwise name *draft*.

    ``data`` is expected to already have had ``strip_irrelevant_answers``
    applied (see ``submit_draft``): an attachment reference for a question
    that became irrelevant (e.g. an ``md_im*`` slot after ``md_available``
    flips to "no") must never reach here, or it is counted in
    ``AttachmentsExpected``. A file uploaded for such a slot stays in
    ``va_web_intake_attachments``, unlinked.
    """
    # Server authoritative whatever the client sent (PII slice 1a); the
    # payload version service reduces again before storing.
    data = redact_payload_national_ids(data or {})[0]
    payload: dict = {}
    references: dict = {}
    wanted = {key: attachments.reference_id(value) for key, value in (data or {}).items() if _is_attachment_reference(value)}
    held = attachments.pending_filenames((attachments_from or draft).draft_id, {i for i in wanted.values() if i})
    for key, value in (data or {}).items():
        if key not in wanted:
            payload[key] = value
        elif wanted[key] in held:
            payload[key] = held[wanted[key]]
        else:
            references[key] = value
            payload[key] = None

    form = db.session.get(VaForms, draft.form_id)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    if carry is None:
        unit_context = _unit_context(draft.org_unit_id)
    else:
        unit_context = {k: v for k, v in carry.items() if k.startswith("org_")}
    submitted_iso = submitted_at.isoformat()
    if meta is None:
        meta = draft.meta or {}

    payload.update(unit_context)
    payload.setdefault("Site", draft.site_id)
    payload["unique_id"] = draft.unique_id
    payload["site_individual_id"] = draft.unique_id
    payload.setdefault("survey_state", unit_context.get("org_state_name", ""))
    payload.setdefault("survey_district", unit_context.get("org_district_name", ""))
    payload["narr_language"] = payload.get("narr_language") or "english"
    payload["language"] = payload.get("language") or payload["narr_language"]
    if death is not None:
        if death.source == "register":
            if carry is not None:
                abha = {k: carry[k] for k in ("abha_number", "abha_address") if k in carry}
            else:
                abha = register_pii_accessor.current_values(death, ("abha_number", "abha_address"))
            for key, value in abha.items():
                payload.setdefault(key, value)
        payload["death_register_id"] = str(death.death_id)

    # ODK-shaped metadata so the shared projection and payload-version code
    # see a complete record (see va_odk_06_fetchsubmissions._normalize_odata_record).
    own_ids = {"KEY": f"web:{draft.draft_id}", "instanceID": f"web:{draft.draft_id}",
               "sid": f"web-{draft.draft_id}-{form.form_id.lower()}"}
    payload.update({k: (carry or {}).get(k) or v for k, v in own_ids.items()})
    payload["SubmissionDate"] = submitted_iso
    payload["updatedAt"] = submitted_iso
    payload["SubmitterName"] = carry["SubmitterName"] if carry and "SubmitterName" in carry else user.name
    payload["SubmitterID"] = str(user.user_id)
    payload["DeviceID"] = f"digitva-{intake_source}"
    payload["FormVersion"] = str(meta.get("instrumentVersion") or meta.get("formVersion") or "2022")
    # QA flag, never a refusal: filled on a served form version older than the
    # one this server serves now.
    payload["form_version_outdated"] = _is_outdated_form_version(payload["FormVersion"])
    payload["ReviewState"] = None
    payload["instanceName"] = f"{draft.unique_id}_WHOVA2022"
    payload["form_def"] = form.form_id
    # Device-recorded times when the interview carried them, else the draft's
    # open time and the server submit time (docs/policy/field-data-collection.md
    # "Interview times"). ``today`` is the completion date the server's
    # re-check used; nothing else reads it.
    started_at, completed_at = _device_time(meta.get("startedAt")), _device_time(meta.get("completedAt"))
    payload["start"] = meta["startedAt"] if started_at else meta.get("createdAt") or submitted_iso
    payload["end"] = meta["completedAt"] if completed_at else submitted_iso
    payload["today"] = (completed_at or submitted_at).date().isoformat()
    # Phone-clock audit for coders and supervisors (phone minus server, seconds).
    if "clockOffsetSeconds" in meta:
        payload["device_clock_offset_seconds"] = meta["clockOffsetSeconds"]
    if meta.get("clockSuspect"):
        payload["device_clock_suspect"] = True
    payload["AttachmentsExpected"] = len(wanted)
    payload["AttachmentsPresent"] = len(wanted) - len(references)
    payload["intake_source"] = intake_source
    # What the respondent was shown: the working language and the exact
    # translation version behind it, so the screen is reconstructible.
    payload["intake_locale"] = meta.get("locale") or DEFAULT_LOCALE
    payload["intake_translation_version"] = meta.get("translation_version") or 0
    payload["unique_id2"] = f"{draft.unique_id}_{submitted_at.strftime('%H%M%S')}{int(submitted_at.microsecond / 1000):03}"
    # The ND01 calculate the WHO workbook lacks; coding cards, exports and the
    # age band read it. Never replaces one the payload already carries.
    if payload.get("finalAgeInYears") in (None, ""):
        payload["finalAgeInYears"] = derive_final_age_in_years(payload)
    return payload, references


def _require_live_org_unit(draft: VaWebIntakeDraft) -> None:
    """Refuse a submission whose organization unit is inactive or unplaced.

    A unit can be deactivated, or turn out to be unplaced (imported, parent
    not yet mapped — see ``unplaced_unit_codes``), between starting a draft
    and submitting it. Routing only attributes a submission to a live, placed
    unit, so the case would fall back to the mapping's unit or stay unrouted —
    and since coding eligibility is decided by the routed unit, an unrouted
    case in a project with an organization tree is visible to no coder at
    all. Failing here tells the interviewer while the draft is still safe,
    instead of filing a death nobody can see.
    """
    if not draft.org_unit_id:
        return
    unit = db.session.get(MasOrgUnit, uuid.UUID(str(draft.org_unit_id)))
    if unit is None:
        raise WebIntakeError(
            "The organization unit for this case no longer exists. Ask an "
            "administrator to restore it or move the case before submitting.",
            409,
        )
    if not unit.is_active:
        raise WebIntakeError(
            f"The organization unit for this case ({unit.unit_name}) is no "
            "longer active, so the case could not be attributed to it or "
            "reach a coder. Ask an administrator to reactivate it or move the "
            "case before submitting.",
            409,
        )
    unplaced = org.unplaced_unit_codes(unit.project_id)  # same predicate as the intake unit picker
    if str(unit.path).split(".")[0] in unplaced:
        raise WebIntakeError(
            f"The organization unit for this case ({unit.unit_name}) is not yet placed in the "
            "organization tree, so the case could not be attributed to it or reach a coder. Ask an "
            "administrator to map its parent (Organization → Units → Map parents) before submitting.",
            409,
        )


#: ``interview_outcome`` -> the case state its submission leaves the case in
#: (decision 8 of .tasks/2026-09-28-interviewer-worklist.md). Only
#: ``completed`` enters coding; the rest keep the case open for a later
#: complete submission.
OUTCOME_CASE_STATES = {
    "completed": "submitted",
    "refused": "refused",
    "partially_completed": "paused",
    "respondent_unavailable": "not_reachable",
}


_INCOMPLETE_OUTCOMES = frozenset({"partially_completed", "respondent_unavailable"})


def _interview_outcome(data: dict, completion: dict) -> str:
    """The ``interview_outcome`` a submission is stored with, decided here.

    The form cannot compute it (docs/policy/web-intake.md, "The
    ``interview_outcome`` question"): ``refused`` when consent (Id10013) is
    no; ``completed`` when the form reports every required question answered;
    otherwise the interviewer's own pick, which must be ``partially_completed`` or
    ``respondent_unavailable``. Raises 422 for an invalid form with no such
    pick, or a valid one without consent. Also 422 (``outcome_conflicts_consent``)
    when the pick is ``refused`` while consent is yes, valid form or not.
    """
    consent = normalize_consent(data.get("Id10013"))
    if consent.lower() == "no":
        return "refused"
    if consent.lower() == "yes" and data.get("interview_outcome") == "refused":
        raise WebIntakeError(
            "Consent is recorded as yes, but the interview outcome says refused. Change one of them.",
            422,
            "outcome_conflicts_consent",
            ["Id10013", "interview_outcome"],
        )
    if completion.get("valid") is True:
        if not consent:
            raise WebIntakeError("The consent question (Id10013) must be answered.", 422)
        return "completed"
    picked = data.get("interview_outcome")
    if picked in _INCOMPLETE_OUTCOMES:
        return picked
    raise WebIntakeError(
        "The questionnaire is not valid yet; complete the sections flagged by the form, "
        "or record the interview outcome as partially completed or respondent unavailable.",
        422,
    )


def _visit_note(data: dict) -> dict:
    """The visit note an identity-less refusal carries: address and date of
    the visit required (422), remarks optional. Keyed by the form's answer
    names so it is stored in the payload exactly as the form collects it."""
    try:
        address = _clean(data.get("visit_address"), what="Visit address", required=True, max_len=500)
        visited = _clean_date(data.get("visit_date"), what="Visit date", required=True)
        remarks = _clean(data.get("visit_remarks"), what="Visit remarks", max_len=2000)
    except WebIntakeError as exc:
        raise WebIntakeError(f"A refusal with no identity needs a visit note: {exc}", 422) from exc
    # Also kept in the draft's meta: free text, so digit runs are masked here
    # as in the payload (PII slice 1a).
    note = {"visit_address": redact_national_id_digits(address)[0], "visit_date": visited.isoformat()}
    if remarks:
        note["visit_remarks"] = redact_national_id_digits(remarks)[0]
    return note


def _set_final_section(draft: VaWebIntakeDraft, data: dict) -> None:
    """Store *data* as the draft's ``final`` section: the exact final raw
    answers, locked answers included, before irrelevant ones are stripped. A
    browser section saved under that name is overwritten, not duplicated."""
    data = stored_answers(data)
    for row in draft.sections:
        if row.section_name == FINAL_SECTION:
            row.data = data
            return
    draft.sections.append(VaWebIntakeDraftSection(section_name=FINAL_SECTION, data=data))


def _supersede_draft(draft: VaWebIntakeDraft, data: dict, completion: dict) -> None:
    """Keep a draft whose case was closed meanwhile (a teammate's complete
    submission won): final answers stored, no submission, no routing, the case
    left exactly as it is. The browser's saved sections may lack the last
    edits, which only the submit carries, so they are kept as one more section."""
    _set_final_section(draft, data)
    draft.status = "superseded"
    # ``submit_draft`` has set ``interview_outcome`` in *data*. Read by the
    # candidate rule (``_candidate_condition``): a complete copy can be chosen
    # by a supervisor, an incomplete one never.
    draft.meta = {**(draft.meta or {}), "interviewOutcome": data.get("interview_outcome")}
    draft.submitted_at = facade()._utcnow()
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])
    db.session.flush()
    log.info("draft kept as superseded copy | unique_id=%s | by=%s", draft.unique_id, draft.user_id)


_COMPOSED_VERSION_RE = re.compile(r"^\d+-[0-9a-f]{10}$")


def _is_outdated_form_version(version: str) -> bool:
    """A served (composed) form version other than the current one. The
    browser's bundled version and unknown strings are not composed versions."""
    if not _COMPOSED_VERSION_RE.match(version):
        return False
    try:
        return version != served_form_service.composed_version()
    except served_form_service.ServedFormUnavailable:
        return False


def build_final_payload(draft: VaWebIntakeDraft, user: VaUsers, data: dict, *, submitted_at: datetime, expression_now: datetime, visit_note: dict, intake_source: str, meta: dict | None = None, carry: dict | None = None, attachments_from: VaWebIntakeDraft | None = None) -> tuple[dict, dict, list]:
    """The coding payload for the final raw answers *data*, with its
    attachment references and the server's own validation diagnostic:
    ``(payload, references, validation_err)``. Shared by a first submit and an
    interviewer's revision (which passes the payload it replaces as *carry*, see
    ``build_web_payload``), so both strip and build identically."""
    # Re-derive relevance and constraint over the client's raw answers before
    # anything is stripped: this is the diagnostic the client's own
    # "valid: true" is checked against (beads digitva-cal.2). It does not
    # block the submission -- see derive_validation_errors' docstring.
    # Against the form version the interview was filled on, when the server
    # served that version (field-data-collection.md "Form version"); any other
    # (the browser's bundled form, an unknown version) uses the current rules.
    version = form_version_of(meta if meta is not None else draft.meta)
    validation_err = facade().derive_validation_errors(data, now=expression_now, version=version)
    # Final submit only (never a draft save): remove answers to questions
    # that are not relevant, resolved to a fixed point (beads digitva-aiy.1).
    stripped_data, _removed_answers = facade().strip_irrelevant_answers(data, now=expression_now, version=version)
    # Added after stripping: the form shows the note only while no given name
    # is recorded, so a partial identity would otherwise lose it as irrelevant.
    stripped_data = {**stripped_data, **visit_note}
    payload, references = build_web_payload(
        draft, stripped_data, user, submitted_at=submitted_at, intake_source=intake_source, meta=meta, carry=carry,
        attachments_from=attachments_from,
    )
    return payload, references, validation_err


def submit_draft(draft: VaWebIntakeDraft, user: VaUsers, *, completion: dict, intake_source: str = "web", completed_at: datetime | None = None, locked_death: VaDeathRegister | None = None, refusal_override: bool | None = None, new_refusal: bool | None = None) -> VaSubmissions | None:
    """Turn a draft into a submission; its ``interview_outcome`` decides where it goes.

    Every outcome is stored as a submission. Only ``completed`` enters coding
    and moves the case to ``submitted`` (first complete submission wins);
    ``refused`` and the incomplete outcomes are routed to ``consent_refused``
    (no SmartVA, no allocation) and leave the case waiting
    (``OUTCOME_CASE_STATES``). A draft whose case is already closed
    (``_SUPERSEDED_CASE_STATES``) becomes a ``superseded`` copy and the result
    is None; the browser route first tries ``fold_into_own_submission``, which
    takes a draft on a case the caller's own interview won.

    The submitted draft's ``meta["effectiveSavedAt"]`` is its completion time
    (*completed_at*, a device's skew-corrected ``completedAt``; the submit
    time when None), the clock a later version of the same interview is
    compared against (``revise_submission`` with ``resubmit``).

    *locked_death*: the draft's case when the caller already holds its row
    lock in this transaction (``submit_device_interview``); not locked again.
    *new_refusal* as ``save_draft_sections``.
    """
    if draft.status != "draft":
        raise WebIntakeError("This draft has already been submitted.", 409)
    if not isinstance(completion, dict) or not isinstance(completion.get("data"), dict):
        raise WebIntakeError("completion.data is required.")
    check_device_answers(completion["data"])
    # Web and device submits both pass here (public-demo.md section 8).
    public_demo_service.check_new_submission(user, draft.project_id)
    from app.services import consent_service
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    if death is not None and (locked_death is None or locked_death.death_id != death.death_id):
        death = cases.lock_case(death)
    refused = refusal_override if refusal_override is not None else consent_service.interview_refused(
        death=death, client_draft_id=draft.client_draft_id, answers=completion["data"],
    )
    outcome = "refused" if refused else _interview_outcome(completion["data"], completion)
    # Locked answers (interviewer identity, area presets, ABHA, registered age) are
    # overwritten with the draft's server-computed prefill, added when the
    # client left them out, before relevance is derived or stripped. Overwrite,
    # not refuse: a device interview finished offline may hold a stale locked
    # value (a profile or case edit), and refusing
    # would strand a completed interview the interviewer cannot correct.
    data = (consent_service.refusal_answers(completion["data"]) if refused else
            {**completion["data"], **_draft_locked_answers(draft), "interview_outcome": outcome})
    consent = normalize_consent(data.get("Id10013"))
    facade()._require_live_org_unit(draft)
    visit_note: dict = {}
    if death is not None:
        # Under the case lock, so a teammate's concurrent winning submit is
        # seen here and this one is kept as a superseded copy, and before any
        # identity sync, so a closed case's identity is never rewritten.
        # Re-read under the lock: a double or retried submit of this same
        # draft that won meanwhile must not turn the winner into a copy.
        if db.session.scalar(sa.select(VaWebIntakeDraft.status).where(VaWebIntakeDraft.draft_id == draft.draft_id)) != "draft":
            raise WebIntakeError("This draft has already been submitted.", 409)
        if refused:
            new = new_refusal if new_refusal is not None else is_new_refusal(draft, completion["data"])
            clear_direct_identity_for_refusal(draft, user, hold_others=new)
            scrub_refused_draft(draft)
        if death.status in _SUPERSEDED_CASE_STATES:
            _supersede_draft(draft, data, completion)
            return None
        # Identity comes from a direct start's own (only) draft or from the
        # winning complete submit, never from a refused or partial one on a
        # shared case.
        if outcome != "refused" and (death.status == "draft_identity" or outcome == "completed"):
            _sync_case_identity(death, data, user)
        # A refusal needs no identity: WHO asks it after consent, so a direct
        # start refused at consent never has one. The submission is stored as
        # refused and the nameless case closes as cancelled, the only closed
        # state the identity constraint allows without one (digitva-vzk.12).
        identity_pending = death.status == "draft_identity"
        if identity_pending and outcome != "refused":
            raise _missing_identity_error(
                data, name=bool(death.has_deceased_name or death.deceased_name),
                sex=bool(death.deceased_sex), date_of_death=bool(death.date_of_death),
            )
        _begin_interview(death, user)
        if not (identity_pending or death.status in ("in_progress", "paused")):
            raise WebIntakeError("This case is closed.", 409)
        # A case restarted from such a refusal still has no identity.
        if outcome != "refused" and not cases.identity_complete(death):
            raise _missing_identity_error(
                data, name=bool(death.has_deceased_name or death.deceased_name),
                sex=bool(death.deceased_sex), date_of_death=bool(death.date_of_death),
            )

    elif refused:
        scrub_refused_draft(draft)

    submitted_at = facade()._utcnow()
    try:
        submitted_timeline = merge_timeline(
            (draft.meta or {}).get(_TIMELINE_META_KEY),
            [server_event("submitted", at=submitted_at)],
            INTERVIEW_TIMELINE_EVENTS,
        )
    except WorkflowTimelineError as exc:
        raise WebIntakeError("Invalid workflow timeline.", 400, "invalid_workflow_timeline") from exc
    # The device's completion time in its own offset, else the submit time in
    # the interviewer's timezone (docs/policy/field-data-collection.md).
    expression_now = _device_time((draft.meta or {}).get("completedAt")) or _expression_now(user, submitted_at)
    payload, references, validation_err = build_final_payload(
        draft, user, data, submitted_at=submitted_at, expression_now=expression_now,
        visit_note=visit_note, intake_source=intake_source,
    )
    if refused:
        # Keep system identifiers needed by the submission pipeline, never register prefill.
        keep = {"KEY", "instanceID", "sid", "SubmissionDate", "updatedAt", "SubmitterID",
                "DeviceID", "FormVersion", "ReviewState", "form_def", "intake_source",
                "death_register_id", "AttachmentsExpected", "AttachmentsPresent"}
        payload = {k: v for k, v in payload.items() if k in keep or k in consent_service.REFUSAL_ANSWERS}
        payload.update(consent_service.refusal_answers(data))
        payload["interview_outcome"] = "refused"
        references = {}
        validation_err = []
    if references:
        # Every file the answers name must be on the server first (the page
        # and the phone send them before they submit); a case must not reach
        # coding with a file missing. The phone, told this, marks its files
        # unconfirmed and sends them again (phone-attachments.md).
        raise WebIntakeError(
            f"{len(references)} attached file(s) have not finished uploading; wait for them to be sent, then submit again.",
            409, "attachments_pending",
        )
    form = db.session.get(VaForms, draft.form_id)
    fields = build_submission_projection(form, payload)
    va_sid = fields["va_sid"]
    if db.session.get(VaSubmissions, va_sid) is not None:
        raise WebIntakeError("This questionnaire was already submitted.", 409)

    submission = VaSubmissions(
        va_sid=va_sid,
        va_form_id=fields["va_form_id"],
        va_country_iso3=project_country(form.project_id),
        va_submission_date=fields["va_submission_date"],
        va_odk_updatedat=fields["va_odk_updatedat"],
        va_data_collector=fields["va_data_collector"],
        va_odk_reviewstate=fields["va_odk_reviewstate"],
        va_odk_reviewcomments=fields["va_odk_reviewcomments"],
        va_instance_name=fields["va_instance_name"],
        va_uniqueid_real=fields["va_uniqueid_real"],
        va_uniqueid_masked=fields["va_uniqueid_masked"],
        va_consent=fields["va_consent"],
        va_narration_language=fields["va_narration_language"],
        va_deceased_age=fields["va_deceased_age"],
        va_deceased_age_normalized_days=fields["va_deceased_age_normalized_days"],
        va_deceased_age_normalized_years=fields["va_deceased_age_normalized_years"],
        va_deceased_age_source=fields["va_deceased_age_source"],
        va_deceased_gender=fields["va_deceased_gender"],
        va_summary=fields["va_summary"],
        va_catcount=fields["va_catcount"],
        va_category_list=fields["va_category_list"],
    )
    db.session.add(submission)
    db.session.flush()
    attachments.link_to_submission(va_sid, draft.draft_id, payload)
    # Attribute the death to an organization unit, exactly as ODK sync does:
    # the web questionnaire carries the same org_<level_code>_code fields, and
    # the project-site's ODK mapping supplies the same fallback unit.
    # No-op for a project without an organization tree.
    routing_context = org_routing.context_for_form(form)
    if routing_context.has_tree:
        org_routing.route_submission(
            submission, context=routing_context, payload=payload
        )
    ensure_active_payload_version(
        submission,
        payload_data=payload,
        source_updated_at=fields["va_odk_updatedat"],
        created_by_role=PAYLOAD_ROLE,
        created_by=user.user_id,
        validation_err=validation_err,
        answers_sha256=draft.answers_sha256,
    )
    # A refused or incomplete interview is kept but never coded. consent_refused
    # is the only existing state that is outside coding *and* blocked from
    # SmartVA (SMARTVA_BLOCKED_WORKFLOW_STATES); no new workflow state.
    enters_coding = outcome == "completed" and consent_is_valid(consent)
    # Outside the collection period at this first upload: kept, but held out
    # of coding and reports (collection_hold); SmartVA waits for the release.
    held = enters_coding and collection_hold.hold_at_upload(user, draft, va_sid, submitted_at)
    facade().route_synced_submission(
        va_sid,
        consent_valid=enters_coding,
        reason="web_intake_submitted",
        actor=system_actor(),
    )
    if enters_coding and not references:
        mark_attachment_sync_completed(
            va_sid, reason="web_intake_no_attachments", actor=system_actor()
        )
        if not held:
            smartva_service.queue_smartva_after_commit(va_sid, "web_intake_submit")
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole=AUDIT_ROLE,
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="va_submission_created_from_web_intake",
            va_audit_entityid=draft.draft_id,
        )
    )
    # The complete raw answers, whatever sections the saves held.
    _set_final_section(draft, data)
    draft.status = "submitted"
    draft.va_sid = va_sid
    draft.submitted_at = submitted_at
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])
    draft.meta = {
        **(draft.meta or {}), "attachmentReferences": references, "interviewOutcome": outcome,
        "effectiveSavedAt": (completed_at or submitted_at).isoformat(),
        _TIMELINE_META_KEY: submitted_timeline,
    }
    if visit_note:
        draft.meta = {**draft.meta, "visitNote": visit_note}
    if death is not None:
        action = "submitted" if outcome == "completed" else f"submitted_{outcome}"
        to_state = "cancelled" if identity_pending else OUTCOME_CASE_STATES[outcome]
        cases.transition(death, to_state, actor=user, action=action)
        if outcome == "completed":
            # The case's submission is the complete one; an earlier refused or
            # incomplete one stays linked through its draft only.
            death.va_sid = va_sid
            # The case is closed: interviewers still holding an open draft on it.
            holders = notification_service.open_draft_holders(death.death_id, exclude_user_id=user.user_id)
            notification_service.notify(
                holders, notification_service.CASE_SUBMITTED_BY_OTHER, project_id=draft.project_id,
                death_id=death.death_id, draft_id=holders,
            )
    db.session.flush()
    log.info("web intake submitted | sid=%s | unique_id=%s | by=%s | outcome=%s | attachments=%d", va_sid, draft.unique_id, user.user_id, outcome, len(references))
    return submission
