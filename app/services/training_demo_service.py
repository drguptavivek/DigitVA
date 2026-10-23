"""Training & demo project (TRN01): training sessions, participants and onboarding.

Policy: docs/policy/training-demo-project.md. The project is permanent and
signed-in only. A trainer (admin) creates a training session with a chosen
number of coder slots, which copies ten consented cases per slot from a real
ODK form with names, addresses and phone-like
identifiers replaced (``training_pseudonymiser``), and then adds existing users
to it in a role. Sessions are retained; closing one only deactivates its
participants' grants. Every function here is a service call: callers check that
the actor is an admin (``_require_admin`` also does), and no function creates a
user, a password or an account expiry.

Failures raise ``TrainingDemoError`` with a fixed code (``MESSAGES``); nothing
in a message or a log line carries case content or a person's details.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    MapProjectOdk,
    MapProjectSiteOdk,
    MapTrainingCase,
    MapTrainingParticipant,
    MasCadre,
    MasOrgUnit,
    MasTrainingSession,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.mas_training import (
    CASES_PER_SLOT,
    CODER_SLOTS,
    MAX_CODER_SLOTS,
    PARTICIPANT_ROLES,
)
from app.services import authz
from app.services import organization_service as org
from app.services.org_grant_service import validate_org_unit_grant
from app.services.organization_service import OrganizationError, _spreadsheet_safe
from app.services.training_pseudonymiser import (
    COUNT_KEYS,
    pseudonymise_payload,
    residual_categories,
)
from app.services.user_account_service import mask_mobile

log = logging.getLogger(__name__)

TRAINING_PROJECT_ID = "TRN01"
TRAINING_PROJECT_NAME = "Training & demo (WHO 2022, ICD-11)"
#: The real ODK form the case copies come from (project UNSW01, site NC01).
DEFAULT_SOURCE_FORM_ID = "UNSW01NC0101"
TRAINEE_CADRE_CODE = "TRAINEE"
#: The source narratives are mostly Hindi; form locales stay English only.
NARRATION_LANGUAGES = ("english", "hindi")
#: Owner 2026-10-22: a trainee's coded case reaches review within the training.
TRAINING_RECODE_WINDOW_MINUTES = 60
#: Fixed ancestors of every session root: the tree needs a district and a CHC
#: above the PHC-level root, because only optional levels may be skipped.
DISTRICT_UNIT_CODE = "TRNDH"
CHC_UNIT_CODE = "TRNCHC"
NAME_MAX = 200
#: Source cases read when the form has no frozen corpus list.
SOURCE_ROWS_DEFAULT = 200

MESSAGES = {
    "target_not_configured": "Set DIGITVA_TRAINING_PROJECT_ID=TRN01 to enable the training project.",
    "project_missing": "The training project does not exist; run setup first.",
    "project_collision": "A research project TRN01 already exists without a training project.",
    "invalid_target": "TRN01 is not an organization, web-only project; it was not adopted.",
    "odk_mapping_present": "TRN01 has ODK mappings or an ODK form; it was not adopted.",
    "project_closed": "The training project is not active.",
    "form_missing": "The training project has no active web form; run setup first.",
    "source_form_missing": "The source form does not exist.",
    "source_is_training": "The source form belongs to the training project.",
    "not_enough_source_cases": "The source form does not have enough eligible cases.",
    "invalid_coder_slots": "Give the session 1 to 100 coder slots.",
    "invalid_name": "Give the session a name of 1 to 200 characters.",
    "admin_required": "Only an administrator may do this.",
    "session_not_found": "Training session not found.",
    "session_closed": "The training session is closed; reopen it first.",
    "invalid_role": "Unknown participant role.",
    "roles_empty": "Select at least one role.",
    "unknown_user": "No DigitVA user has that email address.",
    "user_inactive": "That user's account is not active.",
    "already_participant": "That user already has this role in the session.",
    "participant_not_found": "That user does not have this role in the session.",
    "no_free_coder_slot": "All coder slots of this session are taken.",
    "grant_not_allowed": "The access rules refused the training grant.",
    "coder_language_missing": "Add {languages} to this user's coding languages first.",
    "session_unit_conflict": "A unit with this session's code already exists in the training project.",
    "report_forbidden": "You may not view this training report.",
    "bulk_refused": "Some users cannot be added; nothing was changed. Remove them from the selection and retry.",
    "bulk_too_many": "Select at most 200 users at a time.",
    "bulk_empty": "Select at least one user.",
    "invalid_filter": "A filter value is not valid.",
}
BULK_MAX = 200
CANDIDATES_MAX = 200


class TrainingDemoError(ValueError):
    """A fixed, safe error code (see ``MESSAGES``); never case content."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params  # language names for coder_language_missing; never case content

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, self.code).format(**self.params)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# Participant role -> the unit-scoped grant roles written for it, and where.
_GRANT_ROLES = {
    "death_reporter": (VaAccessRoles.death_reporter,),
    "interview_supervisor": (VaAccessRoles.interview_supervisor,),
    "interviewer": (VaAccessRoles.interviewer,),
    "coder": (VaAccessRoles.coder,),
    "reviewer_data_manager": (VaAccessRoles.reviewer, VaAccessRoles.data_manager),
}


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def training_configured() -> bool:
    return current_app.config.get("DIGITVA_TRAINING_PROJECT_ID") == TRAINING_PROJECT_ID


def _require_configured() -> None:
    if not training_configured():
        raise TrainingDemoError("target_not_configured")


def _require_admin(user) -> VaUsers:
    if isinstance(user, uuid.UUID):
        user = db.session.get(VaUsers, user)
    if user is None or not user.is_active or not user.is_admin():
        raise TrainingDemoError("admin_required")
    return user


def _require_target(*, lock: bool = False) -> VaProjectMaster:
    """The TRN01 project, checked to be what this feature may operate on."""
    stmt = sa.select(VaProjectMaster).where(VaProjectMaster.project_id == TRAINING_PROJECT_ID)
    if lock:
        stmt = stmt.with_for_update()
    project = db.session.scalar(stmt)
    if project is None:
        raise TrainingDemoError("project_missing")
    if (
        project.project_structure_mode != "organization"
        or project.web_intake_mode == "off"
        or project.demo_training_enabled
        or project.synthetic_demo_reset_enabled
    ):
        raise TrainingDemoError("invalid_target")
    for model in (MapProjectOdk, MapProjectSiteOdk):
        if db.session.scalar(
            sa.select(model.project_id).where(model.project_id == TRAINING_PROJECT_ID).limit(1)
        ):
            raise TrainingDemoError("odk_mapping_present")
    if db.session.scalar(
        sa.select(VaForms.form_id)
        .where(VaForms.project_id == TRAINING_PROJECT_ID, VaForms.form_source != "web")
        .limit(1)
    ):
        raise TrainingDemoError("odk_mapping_present")
    return project


def _web_form() -> VaForms:
    form = db.session.scalar(
        sa.select(VaForms)
        .where(
            VaForms.project_id == TRAINING_PROJECT_ID,
            VaForms.form_source == "web",
            VaForms.form_status == VaStatuses.active,
        )
        .order_by(VaForms.form_id)
        .limit(1)
    )
    if form is None:
        raise TrainingDemoError("form_missing")
    return form


# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------

def setup_training_project() -> dict:
    """Create TRN01 and its fixed structure, or confirm an existing one. Idempotent.

    Needs ``DIGITVA_TRAINING_PROJECT_ID=TRN01``. An existing TRN01 is adopted
    only when it is an organization, web-only project without ODK mappings;
    its settings are then left as they are, except the narration languages
    (English and Hindi), which are set to the fixed pair, and the recode
    window, which is set to 60 minutes. Created: the project and its web
    form, the template levels and cadres, a "Trainee" cadre allowed to do
    every training task at the PHC and sub-centre levels, and the fixed
    district and CHC units above the session roots. Commits.
    """
    _require_configured()
    created = {"project": False, "cadre": False, "units": 0}
    try:
        project = db.session.get(VaProjectMaster, TRAINING_PROJECT_ID)
        if project is None:
            if db.session.get(VaResearchProjects, TRAINING_PROJECT_ID):
                raise TrainingDemoError("project_collision")
            project = VaProjectMaster(
                project_id=TRAINING_PROJECT_ID,
                project_code=TRAINING_PROJECT_ID,
                project_name=TRAINING_PROJECT_NAME,
                project_nickname="Training & demo",
                project_structure_mode="organization",
                web_intake_mode="both",
                coding_intake_mode="pick_and_choose",
                icd_classification="icd11",
                cod_entry_mode="doris",
                masked_cod_required=False,
                narrative_qa_enabled=False,
                social_autopsy_enabled=False,
                reviewer_social_autopsy_enabled=False,
                web_intake_default_locale="en",
                web_intake_available_locales=["en"],
                web_intake_narration_languages=list(NARRATION_LANGUAGES),
                web_intake_intake_note="",
                web_intake_death_summary_enabled=True,
                web_intake_medical_records_enabled=True,
                recode_window_minutes=TRAINING_RECODE_WINDOW_MINUTES,
            )
            db.session.add(project)
            db.session.flush()
            created["project"] = True
        else:
            _require_target()
            if list(project.web_intake_narration_languages or []) != list(NARRATION_LANGUAGES):
                project.web_intake_narration_languages = list(NARRATION_LANGUAGES)
            if project.recode_window_minutes != TRAINING_RECODE_WINDOW_MINUTES:
                project.recode_window_minutes = TRAINING_RECODE_WINDOW_MINUTES
        org.ensure_organization_site(TRAINING_PROJECT_ID)
        org.seed_default_organization(TRAINING_PROJECT_ID)
        levels = {level.level_code: level for level in org.list_levels(TRAINING_PROJECT_ID)}
        created["cadre"] = _ensure_trainee_cadre(levels)
        created["units"] = _ensure_chain(levels)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return created


def _ensure_trainee_cadre(levels: dict) -> bool:
    cadre = db.session.scalar(
        sa.select(MasCadre).where(
            MasCadre.project_id == TRAINING_PROJECT_ID, MasCadre.cadre_code == TRAINEE_CADRE_CODE
        )
    )
    made = cadre is None
    if made:
        cadre = org.create_cadre(TRAINING_PROJECT_ID, cadre_code=TRAINEE_CADRE_CODE, cadre_name="Trainee")
    for level_code in ("phc", "subcentre"):
        if org.get_level_cadre_permission(levels[level_code].org_level_id, cadre.cadre_id) is None:
            org.upsert_level_cadre(
                TRAINING_PROJECT_ID,
                org_level_id=levels[level_code].org_level_id,
                cadre_id=cadre.cadre_id,
                can_fill_va_form=True,
                can_code_va_form=True,
                can_supervise_interviews=True,
                can_report_deaths=True,
            )
    return made


def _ensure_chain(levels: dict) -> int:
    made = 0
    parent = None
    for code, level_code, name in (
        (DISTRICT_UNIT_CODE, "district", "Training district"),
        (CHC_UNIT_CODE, "chc", "Training CHC"),
    ):
        unit = org.find_unit_by_code(TRAINING_PROJECT_ID, code)
        if unit is None:
            unit = org.create_unit(
                TRAINING_PROJECT_ID,
                org_level_id=levels[level_code].org_level_id,
                unit_code=code,
                unit_name=name,
                parent_org_unit_id=parent.org_unit_id if parent else None,
            )
            made += 1
        parent = unit
    return made


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

def _clean_name(name) -> str:
    text = " ".join(str(name or "").split())
    if not 1 <= len(text) <= NAME_MAX:
        raise TrainingDemoError("invalid_name")
    return text


def _slot_of(case_number: int) -> int:
    return (case_number - 1) // CASES_PER_SLOT + 1


def _clean_coder_slots(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CODER_SLOTS:
        raise TrainingDemoError("invalid_coder_slots")
    return value


def _source_order(coder_slots: int, available: int) -> list[int]:
    """Source row index of each case copy, in case-number order.

    Slot ``k`` takes ten consecutive source rows, wrapping around the
    *available* rows (at least ``CASES_PER_SLOT``), so a slot never holds one
    source case twice. Each further pass over the sources starts three rows
    later, so a slot of a later pass is not a copy of an earlier slot.
    """
    order = []
    for slot in range(coder_slots):
        first = slot * CASES_PER_SLOT
        start = (first + 3 * (first // available)) % available
        order.extend((start + i) % available for i in range(CASES_PER_SLOT))
    return order


def slot_unit_code(session_code: str, slot: int) -> str:
    return f"{session_code}_C{slot:02d}"


CORPUS_DIR = Path(__file__).parent / "training_corpus"


def _corpus_sids(source_form_id: str) -> list[str] | None:
    """The owner's frozen case list for *source_form_id* (one va_sid per line, in
    case-number order), or None when the form has no list."""
    path = CORPUS_DIR / f"{source_form_id}.txt"
    if not path.is_file():
        return None
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _load_source_rows(source_form_id: str, limit: int | None = None, *, strict: bool = True) -> list:
    """Eligible source cases, in one query: active payload version, consent
    given. A frozen corpus list fixes which cases and their order (all of it,
    or its first *limit*); otherwise the first *limit* (default
    ``SOURCE_ROWS_DEFAULT``) by va_sid. *strict* refuses a listed case that is
    not eligible, and fewer than ``CASES_PER_SLOT`` cases."""
    corpus = _corpus_sids(source_form_id)
    query = (
        sa.select(VaSubmissions, VaSubmissionPayloadVersion)
        .join(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .where(
            VaSubmissions.va_form_id == source_form_id,
            VaSubmissionPayloadVersion.version_status == "active",
            VaSubmissions.va_consent != "",
            sa.func.lower(VaSubmissions.va_consent) != "no",
        )
    )
    if corpus is not None:
        listed = corpus[:limit] if limit else corpus
        rows = db.session.execute(query.where(VaSubmissions.va_sid.in_(listed))).all()
        order = {sid: number for number, sid in enumerate(corpus)}
        rows.sort(key=lambda row: order[row[0].va_sid])
        if strict and len(rows) < max(len(listed), CASES_PER_SLOT):
            raise TrainingDemoError("not_enough_source_cases")
        return rows
    rows = db.session.execute(query.order_by(VaSubmissions.va_sid).limit(limit or SOURCE_ROWS_DEFAULT)).all()
    if strict and len(rows) < CASES_PER_SLOT:
        raise TrainingDemoError("not_enough_source_cases")
    return rows


def _full_payloads(versions) -> dict:
    """``{payload_version_id: full payload}``; sealed fields joined back when the split is on."""
    from app.services.payload_pii_accessor import get_pii_many, split_enabled
    from app.services.payload_pii_split import join_payload

    sealed = get_pii_many([v.payload_version_id for v in versions]) if split_enabled() else {}
    return {v.payload_version_id: join_payload(v.payload_data, sealed.get(v.payload_version_id)) for v in versions}


def _source_final_causes(sids: list[str]) -> dict[str, str | None]:
    """The authoritative final cause of each source case, one query."""
    rows = db.session.execute(
        sa.select(
            VaFinalCodAuthority.va_sid,
            VaReviewerFinalAssessments.va_conclusive_cod,
            VaFinalAssessments.va_conclusive_cod,
        )
        .outerjoin(
            VaFinalAssessments,
            VaFinalAssessments.va_finassess_id == VaFinalCodAuthority.authoritative_final_assessment_id,
        )
        .outerjoin(
            VaReviewerFinalAssessments,
            VaReviewerFinalAssessments.va_rfinassess_id
            == VaFinalCodAuthority.authoritative_reviewer_final_assessment_id,
        )
        .where(VaFinalCodAuthority.va_sid.in_(sids))
    ).all()
    return {sid: reviewer or coder for sid, reviewer, coder in rows}


def _new_payload(source: dict, *, sid: str, form_id: str, code: str, number: int, seed: str):
    """The pseudonymised payload of one copy, with its identity keys replaced."""
    payload, counts = pseudonymise_payload(source, seed)
    masked = f"T-{code}-{number:03d}"
    for key in [k for k in payload if k.startswith("org_") and k.endswith("_code")]:
        del payload[key]  # routing keys of the source project's tree
    payload.update(
        sid=sid,
        form_def=form_id,
        instanceID=f"uuid:{uuid.uuid5(uuid.NAMESPACE_URL, sid)}",
        unique_id=f"{code}-{number:03d}",
        unique_id2=masked,
        instanceName=masked,
        ReviewState=None,
        OdkReviewComments=None,
    )
    if "SubmitterName" in payload:
        payload["SubmitterName"] = "Training interviewer"
    for key, fake in (("SubmitterID", "training-submitter"), ("DeviceID", "training-device")):
        if key in payload:
            payload[key] = fake
    payload.pop("death_register_id", None)
    payload.pop("KEY", None)
    return payload, counts


def _copy_attachments(source_form_id: str, form_id: str, sid_pairs: dict, created: list):
    """New attachment rows (and stored objects) for the copies; same bytes.

    ``sid_pairs`` is ``{source_sid: [new_sid, ...]}``: a source case copied
    into several slots gives each copy its own row and stored object. Every
    object written is appended to *created* so a failed session can remove
    them. A source row whose object is missing is skipped and counted once per
    copy; a row with no stored object in DigitVA (never downloaded, or gone
    from ODK) is not copied and is counted once per copy as not stored.
    Returns ``(rows, skipped, not_stored)``.
    """
    from app.services.attachment_service import generate_storage_name
    from app.services.attachment_store import StoreTarget, get_attachment_store
    from config import ATTACHMENT_STORE_S3

    store = get_attachment_store()
    is_s3 = store.name == ATTACHMENT_STORE_S3
    every = db.session.scalars(
        sa.select(VaSubmissionAttachments).where(VaSubmissionAttachments.va_sid.in_(list(sid_pairs)))
    ).all()
    sources = [a for a in every if a.exists_on_odk and a.storage_name is not None]
    not_stored = sum(len(sid_pairs[a.va_sid]) for a in every) - sum(len(sid_pairs[a.va_sid]) for a in sources)
    rows, skipped = [], 0
    for src in sources:
        new_sids = sid_pairs[src.va_sid]
        source_target = StoreTarget(source_form_id, src.storage_name, src.local_path)
        content_type = src.mime_type or src.source_mime_type
        tmp = None
        try:
            if is_s3:
                if not store.exists(source_target):
                    skipped += len(new_sids)
                    continue
                fd, tmp = tempfile.mkstemp(prefix="digitva_trn_")
                os.close(fd)
                store.get_key(f"{source_form_id}/media/{src.storage_name}", tmp)  # once for every copy
                path = tmp
            else:
                path = store.open_local_path(source_target)
                if path is None:
                    skipped += len(new_sids)
                    continue
            for new_sid in new_sids:
                name = generate_storage_name(src.filename)
                target = StoreTarget(form_id, name)
                stored = store.put(target, path, content_type=content_type)
                created.append(target)
                rows.append(_attachment_copy(src, new_sid, name, None if is_s3 else stored, is_s3))
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
    return rows, skipped, not_stored


def _attachment_copy(src, new_sid: str, name: str, local_path, is_s3: bool) -> VaSubmissionAttachments:
    return VaSubmissionAttachments(
        va_sid=new_sid,
        filename=src.filename,
        local_path=local_path,
        mime_type=src.mime_type,
        etag=None,
        exists_on_odk=True,
        last_downloaded_at=src.last_downloaded_at,
        storage_name=name,
        source_state=src.source_state,
        source_verified_at=src.source_verified_at,
        source_mime_type=src.source_mime_type,
        derivative_state=src.derivative_state,
        derivative_mime_type=src.derivative_mime_type,
        derivative_source_validator=src.derivative_source_validator,
        derivative_verified_at=src.derivative_verified_at,
        store_state="s3" if is_s3 else "local",
        local_fallback_state="absent" if is_s3 else "present",
    )


def create_training_session(
    name, created_by, *, source_form_id: str | None = None, coder_slots: int = CODER_SLOTS
) -> dict:
    """Create a training session with *coder_slots* (1..100) slots of ten
    pseudonymised case copies each. One transaction.

    Builds the session root unit (named after the session) with one unit per
    coder slot, copies ten eligible cases of *source_form_id* (default the
    UNSW01 NC01 form; its frozen list in ``training_corpus/`` when one exists)
    into each slot as ``trn-<code>-<n>`` under the TRN01 web form, case ``n``
    routed to slot ``((n-1)//10)+1``, state ``ready_for_coding``, and records
    the source case's authoritative final cause as the answer key. With more
    slots than the sources fill, a source case is copied into more than one
    slot (``_source_order``); every copy is its own case. Source rows are
    never changed. Returns ``get_training_session(...)`` plus
    ``replacements`` (counts of names, addresses, identifiers and text
    occurrences replaced), ``attachments_copied``, ``attachments_skipped``
    (stored object missing) and ``attachments_not_stored`` (no stored object in
    DigitVA, not copied). Raises
    ``TrainingDemoError``; nothing is kept on failure, and objects already
    copied are removed.
    """
    _require_configured()
    name = _clean_name(name)
    coder_slots = _clean_coder_slots(coder_slots)
    actor = _require_admin(created_by)
    source_form_id = source_form_id or DEFAULT_SOURCE_FORM_ID
    created_objects: list = []
    try:
        project = _require_target(lock=True)
        if project.project_status != VaStatuses.active:
            raise TrainingDemoError("project_closed")
        form = _web_form()
        source_form = db.session.get(VaForms, source_form_id)
        if source_form is None:
            raise TrainingDemoError("source_form_missing")
        if source_form.project_id == TRAINING_PROJECT_ID:
            raise TrainingDemoError("source_is_training")
        rows = _load_source_rows(source_form_id)
        sources = [row[0] for row in rows]
        payloads = _full_payloads([row[1] for row in rows])
        causes = _source_final_causes([s.va_sid for s in sources])

        existing = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasTrainingSession).where(
                MasTrainingSession.project_id == TRAINING_PROJECT_ID
            )
        )
        code = f"S{existing + 1:03d}"
        session_row, slot_units = _create_units_and_session(code, name, actor, coder_slots)

        replacements = dict.fromkeys(COUNT_KEYS, 0)
        new_subs, new_versions, cases, pairs = [], [], [], {}
        from app.services.va_data_sync.va_data_sync_01_odkcentral import build_submission_projection

        for number, index in enumerate(_source_order(coder_slots, len(rows)), start=1):
            source, version = rows[index]
            sid = f"trn-{code}-{number}"
            slot = _slot_of(number)
            payload, counts = _new_payload(
                payloads[version.payload_version_id],
                sid=sid, form_id=form.form_id, code=code, number=number, seed=f"{code}:{number}",
            )
            payload.setdefault("SubmissionDate", _iso(source.va_submission_date))
            for key, value in counts.items():
                replacements[key] += value
            fields = build_submission_projection(form, payload)
            new_subs.append(
                VaSubmissions(
                    **fields,
                    org_unit_id=slot_units[slot].org_unit_id,
                    org_unit_resolution="manual",
                )
            )
            new_versions.append((sid, payload, version))
            cases.append(
                MapTrainingCase(
                    va_sid=sid,
                    training_session_id=session_row.training_session_id,
                    case_number=number,
                    coder_slot=slot,
                    source_va_sid=source.va_sid,
                    source_final_cod=causes.get(source.va_sid),
                )
            )
            pairs.setdefault(source.va_sid, []).append(sid)
        db.session.add_all(new_subs)
        db.session.flush()

        from app.services.submission_payload_version_service import write_payload_version

        now = _utcnow()
        versions = []
        for sid, payload, source_version in new_versions:
            version = VaSubmissionPayloadVersion(
                va_sid=sid,
                version_status="active",
                created_by=actor.user_id,
                created_by_role="admin",
                version_created_at=now,
                version_activated_at=now,
                has_required_metadata=source_version.has_required_metadata,
                attachments_expected=source_version.attachments_expected,
                validation_err=[],
            )
            # The one payload writer: sealed fields go to the side row when the split is on
            # (it then flushes each version itself, to seal under the version's id).
            write_payload_version(version, payload, new=True)
            versions.append(version)
        db.session.add_all(versions)
        db.session.flush()
        for sub, version in zip(new_subs, versions, strict=True):
            sub.active_payload_version_id = version.payload_version_id
        attachment_rows, skipped, not_stored = _copy_attachments(source_form_id, form.form_id, pairs, created_objects)
        db.session.add_all(attachment_rows)
        db.session.add_all(
            VaSubmissionWorkflow(
                va_sid=sub.va_sid, workflow_state="ready_for_coding", workflow_reason="training_session_copy"
            )
            for sub in new_subs
        )
        db.session.add_all(cases)
        db.session.commit()
    except Exception:
        db.session.rollback()
        _remove_objects(created_objects)
        raise
    log.info(
        "training session created code=%s cases=%d names=%d addresses=%d identifiers=%d text=%d skipped_attachments=%d",
        code, len(new_subs), replacements["names"], replacements["addresses"],
        replacements["identifiers"], replacements["text_replacements"], skipped,
    )
    summary = get_training_session(session_row.training_session_id)
    summary["replacements"] = replacements
    summary["attachments_skipped"] = skipped
    summary["attachments_copied"] = len(attachment_rows)
    summary["attachments_not_stored"] = not_stored
    return summary


def check_source(source_form_id: str | None = None, limit: int | None = None) -> dict:
    """Dry run of the pseudonymiser over the real source cases: counts only.

    Loads the same deterministic selection as session creation, each source
    case once (joined sealed payloads; *limit* keeps the first ones),
    pseudonymises each case in memory and reports how many cases
    still hold any original personal value (``residual_cases``, split by kind
    in ``residual_by_type``). Writes nothing and reads no training table, so
    it works before the training migration. Never returns a value.
    """
    rows = _load_source_rows(source_form_id or DEFAULT_SOURCE_FORM_ID, limit, strict=False)
    payloads = _full_payloads([row[1] for row in rows])
    totals = dict.fromkeys(COUNT_KEYS, 0)
    by_type = {"names": 0, "addresses": 0, "identifiers": 0, "phones": 0}
    residual_cases = 0
    for number, (source, version) in enumerate(rows, start=1):
        original = payloads[version.payload_version_id]
        output, counts = _new_payload(
            original, sid="check", form_id="check", code="CHK", number=number, seed=f"CHK:{number}"
        )
        for key, value in counts.items():
            totals[key] += value
        found = residual_categories(original, output)
        residual_cases += bool(found)
        for kind in found:
            by_type[kind] += 1
    return {
        "cases_checked": len(rows),
        "replacements": totals,
        "residual_cases": residual_cases,
        "residual_by_type": by_type,
    }


def _remove_objects(targets: list) -> None:
    from app.services.attachment_store import get_attachment_store

    store = get_attachment_store()
    for target in targets:
        try:
            store.delete(target)
        except Exception:  # noqa: BLE001 - best effort; a stray object holds only pseudonymised bytes' copy
            log.warning("training session: could not remove a copied attachment object")


def _create_units_and_session(code: str, name: str, actor: VaUsers, coder_slots: int):
    levels = {level.level_code: level for level in org.list_levels(TRAINING_PROJECT_ID)}
    chc = org.find_unit_by_code(TRAINING_PROJECT_ID, CHC_UNIT_CODE)
    if chc is None or "phc" not in levels or "subcentre" not in levels:
        raise TrainingDemoError("project_missing")
    try:
        root = org.create_unit(
            TRAINING_PROJECT_ID,
            org_level_id=levels["phc"].org_level_id,
            unit_code=code,
            unit_name=name,
            parent_org_unit_id=chc.org_unit_id,
        )
    except OrganizationError as exc:
        raise TrainingDemoError("session_unit_conflict") from exc
    slot_units = {}
    for slot in range(1, coder_slots + 1):
        unit_code = slot_unit_code(code, slot)
        slot_units[slot] = MasOrgUnit(
            project_id=TRAINING_PROJECT_ID,
            org_level_id=levels["subcentre"].org_level_id,
            parent_org_unit_id=root.org_unit_id,
            unit_code=unit_code,
            unit_name=f"Coder slot {slot:02d}",
            path=f"{root.path}.{unit_code}",
        )
    db.session.add_all(slot_units.values())
    session_row = MasTrainingSession(
        project_id=TRAINING_PROJECT_ID,
        session_code=code,
        name=name,
        created_by=actor.user_id,
        org_unit_id=root.org_unit_id,
        coder_slots=coder_slots,
    )
    db.session.add(session_row)
    db.session.flush()
    return session_row, slot_units


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _find_session(ref, *, lock: bool = False) -> MasTrainingSession:
    """A session of TRN01 by id (UUID or text) or by code (``S001``)."""
    stmt = sa.select(MasTrainingSession).where(MasTrainingSession.project_id == TRAINING_PROJECT_ID)
    text = str(ref or "").strip()
    try:
        stmt = stmt.where(MasTrainingSession.training_session_id == uuid.UUID(text))
    except ValueError:
        stmt = stmt.where(MasTrainingSession.session_code == text.upper())
    if lock:
        stmt = stmt.with_for_update()
    found = db.session.scalar(stmt)
    if found is None:
        raise TrainingDemoError("session_not_found")
    return found


def _session_fields(row: MasTrainingSession) -> dict:
    return {
        "training_session_id": str(row.training_session_id),
        "session_code": row.session_code,
        "name": row.name,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "created_by": str(row.created_by),
        "org_unit_id": str(row.org_unit_id),
    }


def list_training_sessions() -> list[dict]:
    """Every session, newest first, with participants by role, coder slots used
    and cases coded: four queries however many sessions exist."""
    sessions = db.session.scalars(
        sa.select(MasTrainingSession)
        .where(MasTrainingSession.project_id == TRAINING_PROJECT_ID)
        .order_by(MasTrainingSession.created_at.desc(), MasTrainingSession.session_code.desc())
    ).all()
    if not sessions:
        return []
    ids = [s.training_session_id for s in sessions]
    by_role: dict = {}
    slots: dict = {}
    for session_id, role, count in db.session.execute(
        sa.select(
            MapTrainingParticipant.training_session_id, MapTrainingParticipant.role, sa.func.count()
        )
        .where(MapTrainingParticipant.training_session_id.in_(ids), MapTrainingParticipant.status == "active")
        .group_by(MapTrainingParticipant.training_session_id, MapTrainingParticipant.role)
    ):
        by_role.setdefault(session_id, {})[role] = count
    for session_id, used in db.session.execute(
        sa.select(MapTrainingParticipant.training_session_id, sa.func.count())
        .where(MapTrainingParticipant.training_session_id.in_(ids), MapTrainingParticipant.coder_slot.is_not(None))
        .group_by(MapTrainingParticipant.training_session_id)
    ):
        slots[session_id] = used
    coded = dict(db.session.execute(_coded_counts_stmt(ids)).all())
    out = []
    for row in sessions:
        sid = row.training_session_id
        out.append({
            **_session_fields(row),
            "participants_by_role": {role: by_role.get(sid, {}).get(role, 0) for role in PARTICIPANT_ROLES},
            "coder_slots_used": slots.get(sid, 0),
            "coder_slots_total": row.coder_slots,
            "cases_coded": coded.get(sid, 0),
            "cases_total": row.coder_slots * CASES_PER_SLOT,
        })
    return out


def _coded_counts_stmt(session_ids):
    """Cases with an active final assessment, per session."""
    return (
        sa.select(MapTrainingCase.training_session_id, sa.func.count(sa.distinct(MapTrainingCase.va_sid)))
        .join(VaFinalAssessments, VaFinalAssessments.va_sid == MapTrainingCase.va_sid)
        .where(
            MapTrainingCase.training_session_id.in_(session_ids),
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
        .group_by(MapTrainingCase.training_session_id)
    )


def _participant_dict(participant, user) -> dict:
    return {
        "participant_id": str(participant.participant_id),
        "user_id": str(participant.user_id),
        "name": user.name,
        "email": user.email,
        "role": participant.role,
        "coder_slot": participant.coder_slot,
        "status": participant.status,
        "added_at": _iso(participant.added_at),
        "onboarded_at": _iso(participant.onboarded_at),
    }


def get_training_session(ref) -> dict:
    """One session: its fields, every participant, and its coder slots with
    their coder and case counts. Three queries."""
    row = _find_session(ref)
    participants = db.session.execute(
        sa.select(MapTrainingParticipant, VaUsers)
        .join(VaUsers, VaUsers.user_id == MapTrainingParticipant.user_id)
        .where(MapTrainingParticipant.training_session_id == row.training_session_id)
        .order_by(MapTrainingParticipant.role, MapTrainingParticipant.added_at)
    ).all()
    per_slot = {
        slot: [total, coded]
        for slot, total, coded in db.session.execute(
            sa.select(
                MapTrainingCase.coder_slot,
                sa.func.count(),
                sa.func.count().filter(
                    sa.exists().where(
                        VaFinalAssessments.va_sid == MapTrainingCase.va_sid,
                        VaFinalAssessments.va_finassess_status == VaStatuses.active,
                    )
                ),
            )
            .where(MapTrainingCase.training_session_id == row.training_session_id)
            .group_by(MapTrainingCase.coder_slot)
        )
    }
    coder_of = {p.coder_slot: u for p, u in participants if p.role == "coder"}
    slots = []
    for slot in range(1, row.coder_slots + 1):
        user = coder_of.get(slot)
        total, coded = per_slot.get(slot, [0, 0])
        slots.append({
            "slot": slot,
            "unit_code": slot_unit_code(row.session_code, slot),
            "coder_name": user.name if user else None,
            "cases": total,
            "cases_coded": coded,
        })
    by_role = {role: 0 for role in PARTICIPANT_ROLES}
    for p, _u in participants:
        if p.status == "active":
            by_role[p.role] += 1
    return {
        **_session_fields(row),
        "participants": [_participant_dict(p, u) for p, u in participants],
        "participants_by_role": by_role,
        "slots": slots,
        "coder_slots_used": len(coder_of),
        "coder_slots_total": row.coder_slots,
        "cases_total": sum(s["cases"] for s in slots),
        "cases_coded": sum(s["cases_coded"] for s in slots),
    }


def get_session_cases(ref) -> list[dict]:
    """The session's cases with the answer key, for the trainer report.

    Includes ``source_final_cod``: callers are admin-only and must never put
    it on a coder screen. One query, ordered by case number.
    """
    row = _find_session(ref)
    coded = sa.exists().where(
        VaFinalAssessments.va_sid == MapTrainingCase.va_sid,
        VaFinalAssessments.va_finassess_status == VaStatuses.active,
    )
    return [
        {
            "va_sid": sid, "case_number": number, "coder_slot": slot,
            "source_final_cod": cod, "coded": bool(is_coded),
        }
        for sid, number, slot, cod, is_coded in db.session.execute(
            sa.select(
                MapTrainingCase.va_sid, MapTrainingCase.case_number, MapTrainingCase.coder_slot,
                MapTrainingCase.source_final_cod, coded,
            )
            .where(MapTrainingCase.training_session_id == row.training_session_id)
            .order_by(MapTrainingCase.case_number)
        )
    ]


# ---------------------------------------------------------------------------
# Participants and grants
# ---------------------------------------------------------------------------

def _trainee_cadre() -> MasCadre:
    cadre = db.session.scalar(
        sa.select(MasCadre).where(
            MasCadre.project_id == TRAINING_PROJECT_ID, MasCadre.cadre_code == TRAINEE_CADRE_CODE
        )
    )
    if cadre is None:
        raise TrainingDemoError("project_missing")
    return cadre


def _unit_by_code(code: str) -> MasOrgUnit:
    unit = org.find_unit_by_code(TRAINING_PROJECT_ID, code)
    if unit is None:
        raise TrainingDemoError("session_not_found")
    return unit


def _log_grant(action: str, actor: VaUsers, grant: VaUserAccessGrants) -> None:
    from app.logging.va_logger import log_grant_action

    log_grant_action(
        action=action,
        actor_user_id=actor.user_id,
        actor_role="admin",
        target_user_id=grant.user_id,
        grant_id=grant.grant_id,
        role=grant.role.value,
        scope_type=VaAccessScopeTypes.org_unit.value,
        org_unit_id=grant.org_unit_id,
        cadre_id=grant.cadre_id,
    )


def _check_grant(user: VaUsers, role: VaAccessRoles, unit: MasOrgUnit, actor: VaUsers) -> MasCadre:
    """Raise ``grant_not_allowed`` unless the ordinary rules let *actor* give
    *user* this unit-scoped training grant; writes nothing. Returns the cadre."""
    cadre = _trainee_cadre()
    try:
        validate_org_unit_grant(
            role=role, org_unit_id=unit.org_unit_id, cadre_id=cadre.cadre_id, user_id=user.user_id
        )
    except OrganizationError as exc:
        log.warning("training grant refused role=%s", role.value)
        raise TrainingDemoError("grant_not_allowed") from exc
    if not authz.can_grant(
        actor,
        authz.GrantTarget(role=role, scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id),
    ):
        raise TrainingDemoError("grant_not_allowed")
    return cadre


def _activate_grant(user: VaUsers, role: VaAccessRoles, unit: MasOrgUnit, actor: VaUsers) -> VaUserAccessGrants:
    """Create or reactivate one unit-scoped grant through the ordinary rules."""
    cadre = _check_grant(user, role, unit, actor)
    grant = db.session.scalar(
        sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.role == role,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.org_unit_id == unit.org_unit_id,
        )
    )
    if grant is None:
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id,
            cadre_id=cadre.cadre_id,
            grant_status=VaStatuses.active,
            created_by_user_id=actor.user_id,
            notes="Training session",
        )
        db.session.add(grant)
        db.session.flush()
        _log_grant("grant_created", actor, grant)
    elif grant.grant_status != VaStatuses.active:
        grant.grant_status = VaStatuses.active
        grant.cadre_id = cadre.cadre_id
        _log_grant("grant_reactivated", actor, grant)
    authz.invalidate(user.user_id)
    return grant


def _set_grants_status(grant_ids, status: VaStatuses, actor: VaUsers) -> int:
    """Flip the status of training grants; returns how many changed. One query."""
    if not grant_ids:
        return 0
    grants = db.session.scalars(
        sa.select(VaUserAccessGrants).where(VaUserAccessGrants.grant_id.in_(list(grant_ids)))
    ).all()
    changed = 0
    for grant in grants:
        if grant.grant_status == status:
            continue
        grant.grant_status = status
        changed += 1
        _log_grant("grant_reactivated" if status == VaStatuses.active else "grant_revoked", actor, grant)
        authz.invalidate(grant.user_id)
    return changed


def _find_user(email) -> VaUsers:
    text = str(email or "").strip().lower()
    user = db.session.scalar(sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == text)) if text else None
    if user is None:
        raise TrainingDemoError("unknown_user")
    if not user.is_active:
        raise TrainingDemoError("user_inactive")
    return user


def _participant_units(session_row: MasTrainingSession, role: str, slot: int | None) -> list:
    if role == "coder":
        return [_unit_by_code(slot_unit_code(session_row.session_code, slot))]
    return [db.session.get(MasOrgUnit, session_row.org_unit_id)]


def _find_participant(session_row: MasTrainingSession, user_id, role: str):
    return db.session.scalar(
        sa.select(MapTrainingParticipant).where(
            MapTrainingParticipant.training_session_id == session_row.training_session_id,
            MapTrainingParticipant.user_id == user_id,
            MapTrainingParticipant.role == role,
        )
    )


def _write_participant(session_row, user, role, actor, participant, slot) -> MapTrainingParticipant:
    """Create *participant* (with *slot* for a coder) or reactivate it, and write
    its grants through the ordinary rules. The caller holds the session row lock
    and commits."""
    if participant is None:
        participant = MapTrainingParticipant(
            training_session_id=session_row.training_session_id,
            user_id=user.user_id,
            role=role,
            coder_slot=slot,
            grant_ids=[],
            added_by=actor.user_id,
        )
        db.session.add(participant)
    participant.status = "active"
    grants = [
        _activate_grant(user, grant_role, unit, actor)
        for unit in _participant_units(session_row, role, participant.coder_slot)
        for grant_role in _GRANT_ROLES[role]
    ]
    participant.grant_ids = [g.grant_id for g in grants]
    db.session.flush()
    return participant


def _normalise_roles(roles) -> list[str]:
    """A role name or a list of them as a de-duplicated, ordered list of valid roles."""
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, (list, tuple)):
        raise TrainingDemoError("roles_empty")
    unique = list(dict.fromkeys(r for r in roles if r != ""))
    if not unique:
        raise TrainingDemoError("roles_empty")
    if any(r not in PARTICIPANT_ROLES for r in unique):
        raise TrainingDemoError("invalid_role")
    return unique


def add_participant(session_ref, email, roles, added_by) -> dict:
    """Add an existing user to a session in one or more *roles*, or reactivate them.

    *roles* is a role name or a list; each (user, role) is its own participation.
    All or nothing: one transaction, and any refusal (already active, no free
    slot, missing coder language, grant rules) rolls back every role. Unknown or
    inactive users are refused; no user is ever created. A coder takes the next
    free coder slot (kept for the life of the session) and a coder grant on that
    slot's unit; the other roles get grants on the session root
    (reviewer_data_manager gets both reviewer and data_manager). Returns the
    first participation as a dict, with all of them under ``participants``.
    Commits.
    """
    _require_configured()
    roles = _normalise_roles(roles)
    actor = _require_admin(added_by)
    try:
        session_row = _find_session(session_ref, lock=True)
        if session_row.status != "active":
            raise TrainingDemoError("session_closed")
        user = _find_user(email)
        written = []
        for role in roles:
            participant = _find_participant(session_row, user.user_id, role)
            if participant is not None and participant.status == "active":
                raise TrainingDemoError("already_participant")
            slot = None
            if participant is None and role == "coder":
                slot = _next_free_slot(session_row)
                _require_coder_languages(session_row, slot, user)
            written.append(_write_participant(session_row, user, role, actor, participant, slot))
        participants = [_participant_dict(p, user) for p in written]
        result = {**participants[0], "participants": participants}
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return result


def _slot_languages(session_row: MasTrainingSession, slot: int | None = None) -> dict[int, set[str]]:
    """Narration languages of each coder slot's cases (of one slot when given). One query."""
    stmt = (
        sa.select(MapTrainingCase.coder_slot, VaSubmissions.va_narration_language)
        .join(VaSubmissions, VaSubmissions.va_sid == MapTrainingCase.va_sid)
        .where(MapTrainingCase.training_session_id == session_row.training_session_id)
        .distinct()
    )
    if slot is not None:
        stmt = stmt.where(MapTrainingCase.coder_slot == slot)
    needed: dict[int, set[str]] = {}
    for case_slot, language in db.session.execute(stmt):
        if (language or "").strip():
            needed.setdefault(case_slot, set()).add(language.strip().lower())
    return needed


def _missing_languages(needed: set[str], user: VaUsers) -> list[str]:
    have = {str(lang).strip().lower() for lang in (user.vacode_language or [])}
    return sorted(needed - have)


def _require_coder_languages(session_row: MasTrainingSession, slot: int, user: VaUsers) -> None:
    """Refuse a coder who lacks a narration language of the slot's cases. One query."""
    missing = _missing_languages(_slot_languages(session_row, slot).get(slot, set()), user)
    if missing:
        raise TrainingDemoError("coder_language_missing", languages=", ".join(m.title() for m in missing))


def _used_slots(session_row: MasTrainingSession) -> set[int]:
    return set(
        db.session.scalars(
            sa.select(MapTrainingParticipant.coder_slot).where(
                MapTrainingParticipant.training_session_id == session_row.training_session_id,
                MapTrainingParticipant.coder_slot.is_not(None),
            )
        )
    )


def _next_free_slot(session_row: MasTrainingSession) -> int:
    used = _used_slots(session_row)
    free = [slot for slot in range(1, session_row.coder_slots + 1) if slot not in used]
    if not free:
        raise TrainingDemoError("no_free_coder_slot")
    return free[0]


def _contact(user: VaUsers | None) -> str | None:
    """Email, or the masked mobile of a mobile-only account; never the whole number."""
    if user is None:
        return None
    return user.email or mask_mobile(user.mobile_login)


def _bulk_row(user, user_id, role, action, slot=None, reason="") -> dict:
    scope = f"Coder slot {slot:02d}" if slot else ("Whole session" if action != "refuse" else "")
    return {
        "user_id": str(user_id), "name": user.name if user else None, "email": _contact(user),
        "role": role, "slot_or_scope": scope, "action": action, "reason": reason,
    }


def bulk_add_participants(session_ref, user_ids, roles, added_by, *, dry_run: bool = True) -> dict:
    """Add (or reactivate) many existing users in one or more *roles*, all or nothing.

    One plan row per user and role; coder slots go out in user order.

    The plan is computed first with read-only checks (user active, coder
    language, free slot, grant rules), coder slots handed out in the order given.
    ``dry_run`` returns the plan (``rows``) and writes nothing. Without it the
    plan is applied only when no row is refused; otherwise nothing is written
    and ``applied`` is False, so a preview and its apply never disagree. Commits
    on apply. ponytail: grant checks and writes run per user (at most 200), not
    batched; batch them if a session ever takes thousands.
    """
    _require_configured()
    roles = _normalise_roles(roles)
    actor = _require_admin(added_by)
    ids = list(dict.fromkeys(i.strip()[:64] for i in (user_ids or []) if isinstance(i, str)))
    if not ids:
        raise TrainingDemoError("bulk_empty")
    if len(ids) > BULK_MAX:
        raise TrainingDemoError("bulk_too_many")
    try:
        session_row = _find_session(session_ref, lock=not dry_run)
        if session_row.status != "active":
            raise TrainingDemoError("session_closed")
        parsed = {}
        for text in ids:
            try:
                parsed[text] = uuid.UUID(text)
            except ValueError:
                parsed[text] = None
        known = {u.user_id: u for u in db.session.scalars(
            sa.select(VaUsers).where(VaUsers.user_id.in_([v for v in parsed.values() if v]))
        )}
        existing = {(p.user_id, p.role): p for p in db.session.scalars(
            sa.select(MapTrainingParticipant).where(
                MapTrainingParticipant.training_session_id == session_row.training_session_id,
                MapTrainingParticipant.role.in_(roles),
            )
        )}
        free = []
        languages: dict = {}
        if "coder" in roles:
            used = _used_slots(session_row)
            free = [slot for slot in range(1, session_row.coder_slots + 1) if slot not in used]
            languages = _slot_languages(session_row)
        plan, rows = [], []
        for text, uid in parsed.items():
            user = known.get(uid) if uid else None
            if user is None:
                rows.append(_bulk_row(None, text, roles[0], "refuse", reason=MESSAGES["unknown_user"]))
                continue
            if not user.is_active:
                rows.append(_bulk_row(user, uid, roles[0], "refuse", reason=MESSAGES["user_inactive"]))
                continue
            for role in roles:
                participant = existing.get((uid, role))
                if participant is not None and participant.status == "active":
                    rows.append(_bulk_row(user, uid, role, "already", participant.coder_slot,
                                          MESSAGES["already_participant"]))
                    continue
                slot = participant.coder_slot if participant is not None else None
                try:
                    if participant is None and role == "coder":
                        if not free:
                            raise TrainingDemoError("no_free_coder_slot")
                        slot = free[0]
                        missing = _missing_languages(languages.get(slot, set()), user)
                        if missing:
                            raise TrainingDemoError(
                                "coder_language_missing", languages=", ".join(m.title() for m in missing)
                            )
                    for unit in _participant_units(session_row, role, slot):
                        for grant_role in _GRANT_ROLES[role]:
                            _check_grant(user, grant_role, unit, actor)
                except TrainingDemoError as exc:
                    rows.append(_bulk_row(user, uid, role, "refuse", slot if participant else None, exc.message))
                    continue
                if participant is None and role == "coder":
                    free.pop(0)
                action = "reactivate" if participant is not None else "add"
                rows.append(_bulk_row(user, uid, role, action, slot))
                plan.append((user, role, participant, slot))
        refused = [r for r in rows if r["action"] == "refuse"]
        if dry_run:
            return {"dry_run": True, "rows": rows}
        if refused:
            db.session.commit()  # writes nothing; ends the transaction, releasing the session row lock
            return {"dry_run": False, "applied": False, "rows": rows, "refused": refused,
                    "added": 0, "reactivated": 0, "already": 0}
        for user, role, participant, slot in plan:
            _write_participant(session_row, user, role, actor, participant, slot)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {
        "dry_run": False, "applied": True, "rows": rows, "refused": [],
        "added": sum(r["action"] == "add" for r in rows),
        "reactivated": sum(r["action"] == "reactivate" for r in rows),
        "already": sum(r["action"] == "already" for r in rows),
    }


def training_candidates(
    session_ref, actor, *, created_since: str = "", created_by: str = "me", query: str = "",
    limit: int = 50, tz_name: str | None = None,
) -> dict:
    """Active users who could be added to a session, newest account first.

    Lean fields only; users already active in the session (any role) and the
    ODK sync account are left out. ``created_since`` is a date read as midnight
    in *tz_name* (the admin's zone) and compared with the naive-UTC
    ``user_created_at``. ``created_by`` is ``me`` (accounts the admin created or
    imported, ``other.created_by_user_id``) or ``any``. Bounded: ``limit`` is
    clamped to 1..200 and ``truncated`` says more matched. Admin only.
    ponytail: va_users has no created-at or created-by index; it is a small
    table, add one if accounts reach the hundreds of thousands.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from app.services.odk_case_service import ODK_SYNC_USER_ID

    _require_admin(actor)
    if created_by not in ("me", "any"):
        raise TrainingDemoError("invalid_filter")
    session_row = _find_session(session_ref)
    stmt = (
        sa.select(VaUsers.user_id, VaUsers.name, VaUsers.email, VaUsers.mobile_login, VaUsers.user_status)
        .where(
            VaUsers.user_status == VaStatuses.active,
            VaUsers.user_id != ODK_SYNC_USER_ID,
            VaUsers.user_id.not_in(
                sa.select(MapTrainingParticipant.user_id).where(
                    MapTrainingParticipant.training_session_id == session_row.training_session_id,
                    MapTrainingParticipant.status == "active",
                )
            ),
        )
    )
    if created_since:
        try:
            day = datetime.strptime(created_since, "%Y-%m-%d")
            try:
                zone = ZoneInfo(tz_name or "Asia/Kolkata")
            except ZoneInfoNotFoundError:
                zone = ZoneInfo("Asia/Kolkata")
            since = day.replace(tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
        except ValueError as exc:
            raise TrainingDemoError("invalid_filter") from exc
        stmt = stmt.where(VaUsers.user_created_at >= since)
    if created_by == "me":
        stmt = stmt.where(VaUsers.other["created_by_user_id"].astext == str(actor.user_id))
    text = (query or "").strip()[:100]
    if text:
        stmt = stmt.where(sa.or_(
            VaUsers.email.icontains(text, autoescape=True), VaUsers.name.icontains(text, autoescape=True)
        ))
    limit = max(1, min(int(limit), CANDIDATES_MAX))
    rows = db.session.execute(stmt.order_by(VaUsers.user_created_at.desc(), VaUsers.user_id).limit(limit + 1)).all()
    return {
        "users": [
            {"user_id": str(uid), "name": name, "email": email or mask_mobile(mobile),
             "status": status.value}
            for uid, name, email, mobile, status in rows[:limit]
        ],
        "truncated": len(rows) > limit,
    }


#: Training role -> the roles of the main project's organization users import.
_GRADUATION_ROLES = {
    "death_reporter": ("death_reporter",),
    "interview_supervisor": ("interview_supervisor",),
    "interviewer": ("interviewer",),
    "coder": ("coder",),
    "reviewer_data_manager": ("reviewer", "data_manager"),
}
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")


def graduation_csv(session_ref, actor, *, role: str = "", org_unit_code: str = "", cadre_code: str = "") -> str:
    """The session's active participants as a CSV in the columns of the
    organization users import (``project_user_import_service.HEADERS``), to be
    loaded into the participants' real project. ``role`` optionally keeps one
    training role; the unit and cadre columns carry the codes given, else stay
    blank. A reviewer_data_manager gives a reviewer row and a data_manager row;
    a mobile-only user is keyed by phone. Writes nothing; no grant is created here.
    """
    from app.services.project_user_import_service import HEADERS

    _require_admin(actor)
    if role and role not in PARTICIPANT_ROLES:
        raise TrainingDemoError("invalid_role")
    if not (_CODE_RE.match(org_unit_code or "") and _CODE_RE.match(cadre_code or "")):
        raise TrainingDemoError("invalid_filter")
    session_row = _find_session(session_ref)
    stmt = (
        sa.select(VaUsers.email, VaUsers.name, VaUsers.mobile_login, MapTrainingParticipant.role)
        .join(VaUsers, VaUsers.user_id == MapTrainingParticipant.user_id)
        .where(
            MapTrainingParticipant.training_session_id == session_row.training_session_id,
            MapTrainingParticipant.status == "active",
        )
        .order_by(VaUsers.name, VaUsers.user_id, MapTrainingParticipant.role)
    )
    if role:
        stmt = stmt.where(MapTrainingParticipant.role == role)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADERS)
    seen = set()
    for email, name, mobile, participant_role in db.session.execute(stmt):
        for import_role in _GRADUATION_ROLES[participant_role]:
            key = (email or mobile, import_role)
            if key in seen:
                continue
            seen.add(key)
            values = {
                "email": email or "", "name": name, "role": import_role,
                "org_unit_code": org_unit_code.upper(), "cadre_code": cadre_code.upper(),
                "language_codes": "", "phone": "" if email else (mobile or ""),
            }
            writer.writerow([_spreadsheet_safe(values[h]) for h in HEADERS])
    return out.getvalue()


def remove_participant(session_ref, user_id, role, by) -> dict:
    """Deactivate a participant's training grants and mark them removed.

    Only this participation's grants change; the user's other grants and the
    coder's slot stay. Adding them again reactivates the same grants. Commits.
    """
    _require_configured()
    actor = _require_admin(by)
    try:
        session_row = _find_session(session_ref, lock=True)
        try:
            uid = uuid.UUID(str(user_id))
        except ValueError as exc:
            raise TrainingDemoError("participant_not_found") from exc
        participant = db.session.scalar(
            sa.select(MapTrainingParticipant).where(
                MapTrainingParticipant.training_session_id == session_row.training_session_id,
                MapTrainingParticipant.user_id == uid,
                MapTrainingParticipant.role == role,
            )
        )
        if participant is None:
            raise TrainingDemoError("participant_not_found")
        _set_grants_status(participant.grant_ids, VaStatuses.deactive, actor)
        participant.status = "removed"
        db.session.flush()
        result = _participant_dict(participant, db.session.get(VaUsers, uid))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return result


def _set_session_status(session_ref, status: str, by) -> dict:
    _require_configured()
    actor = _require_admin(by)
    try:
        row = _find_session(session_ref, lock=True)
        row.status = status
        grant_ids = [
            gid
            for ids in db.session.scalars(
                sa.select(MapTrainingParticipant.grant_ids).where(
                    MapTrainingParticipant.training_session_id == row.training_session_id,
                    MapTrainingParticipant.status == "active",
                )
            )
            for gid in ids
        ]
        changed = _set_grants_status(
            grant_ids, VaStatuses.active if status == "active" else VaStatuses.deactive, actor
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("training session %s code=%s grants_changed=%d", status, row.session_code, changed)
    summary = get_training_session(row.training_session_id)
    summary["grants_changed"] = changed
    return summary


def close_training_session(session_ref, by) -> dict:
    """Close a session: its active participants' training grants are deactivated.
    Nothing is deleted; reopening restores them. Commits."""
    return _set_session_status(session_ref, "closed", by)


def reopen_training_session(session_ref, by) -> dict:
    """Reopen a closed session: the grants of participants still active are
    reactivated (removed participants stay removed). Commits."""
    return _set_session_status(session_ref, "active", by)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

_PENDING = (
    MapTrainingParticipant.status == "active",
    MapTrainingParticipant.onboarded_at.is_(None),
)


def has_pending_onboarding(user_id) -> bool:
    """Whether *user_id* has an active participation in an active session that
    has not been onboarded: one probe of the partial index."""
    return bool(
        db.session.scalar(
            sa.select(sa.exists().where(
                MapTrainingParticipant.user_id == user_id,
                *_PENDING,
                MapTrainingParticipant.training_session_id.in_(
                    sa.select(MasTrainingSession.training_session_id).where(MasTrainingSession.status == "active")
                ),
            ))
        )
    )


def participations(user_id, *, pending_only: bool = False) -> list[dict]:
    """The user's active participations in active sessions, for the welcome page."""
    stmt = (
        sa.select(MapTrainingParticipant.role, MapTrainingParticipant.coder_slot,
                  MapTrainingParticipant.onboarded_at, MasTrainingSession.session_code,
                  MasTrainingSession.name)
        .join(MasTrainingSession, MasTrainingSession.training_session_id == MapTrainingParticipant.training_session_id)
        .where(
            MapTrainingParticipant.user_id == user_id,
            MapTrainingParticipant.status == "active",
            MasTrainingSession.status == "active",
        )
        .order_by(MasTrainingSession.session_code, MapTrainingParticipant.role)
    )
    if pending_only:
        stmt = stmt.where(MapTrainingParticipant.onboarded_at.is_(None))
    return [
        {"role": role, "coder_slot": slot, "onboarded_at": _iso(done), "session_code": code, "session_name": name}
        for role, slot, done, code, name in db.session.execute(stmt)
    ]


#: Expo Training sub-menus -> the participant roles that open them
#: (docs/policy/training-demo-project.md, "Onboarding and the public page").
AREA_ROLES = {
    "interview": frozenset({"death_reporter", "interviewer", "interview_supervisor"}),
    "coding": frozenset({"coder"}),
    "review": frozenset({"reviewer_data_manager"}),
}


def areas_of(parts: list[dict]) -> list[str]:
    """The Training sub-menus (in menu order) the participations in *parts* open."""
    roles = {part["role"] for part in parts}
    return [area for area, area_roles in AREA_ROLES.items() if roles & area_roles]


def may_use_area(user_id, area: str) -> bool:
    """Whether *user_id* has an active participation, in an active session, with
    a role that opens *area*. The server-side gate of ``training=1``."""
    roles = AREA_ROLES.get(area)
    if not roles:
        return False
    return bool(
        db.session.scalar(
            sa.select(sa.exists().where(
                MapTrainingParticipant.user_id == user_id,
                MapTrainingParticipant.status == "active",
                MapTrainingParticipant.role.in_(sorted(roles)),
                MapTrainingParticipant.training_session_id.in_(
                    sa.select(MasTrainingSession.training_session_id).where(MasTrainingSession.status == "active")
                ),
            ))
        )
    )


def me_summary(user_id) -> dict:
    """The Training menu's data: ``{project_id, areas, pending}``; the same
    shape ``GET /api/v1/me/access`` carries as ``training``, plus the
    participations for the overview screen."""
    parts = participations(user_id) if training_configured() else []
    return {
        "project_id": TRAINING_PROJECT_ID if training_configured() else None,
        "areas": areas_of(parts),
        "pending": any(part["onboarded_at"] is None for part in parts),
        "participations": parts,
    }


def complete_onboarding(user_id) -> list[str]:
    """Record that the user started: sets ``onboarded_at`` on their pending
    participations in active sessions and returns their roles. Commits."""
    roles = list(
        db.session.scalars(
            sa.update(MapTrainingParticipant)
            .where(
                MapTrainingParticipant.user_id == user_id,
                *_PENDING,
                MapTrainingParticipant.training_session_id.in_(
                    sa.select(MasTrainingSession.training_session_id).where(MasTrainingSession.status == "active")
                ),
            )
            .values(onboarded_at=_utcnow())
            .returning(MapTrainingParticipant.role)
        )
    )
    db.session.commit()
    return roles


_ONBOARDING_SESSION_KEY = "training_onboarding_checked"


def remember_onboarding_checked(user_id) -> None:
    """Remember in the login session that the onboarding check is done."""
    from flask import session

    session[_ONBOARDING_SESSION_KEY] = str(user_id)


def should_redirect_to_welcome(user_id) -> bool:
    """Whether this request should send the user to the welcome page.

    At most one indexed query per login session: the answer is remembered in
    the session either way, so a user is redirected once, and a user with
    nothing pending is not asked again. Needs the feature configured.
    """
    from flask import session

    if not training_configured() or session.get(_ONBOARDING_SESSION_KEY) == str(user_id):
        return False
    pending = has_pending_onboarding(user_id)
    remember_onboarding_checked(user_id)
    return pending
