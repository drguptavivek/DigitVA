"""Case content for the coding and review workspace, shared by web and API.

What ``va_form.renderpartial`` used to read inline on GET: the section data
of a category (PII redaction and the Redis section cache included), the
coder's and reviewer's saved artifacts that decide which step the workspace
shows, and the Step 1 prefill. The web partials and ``/api/v1/va/<sid>/...``
both call these, so the two cannot drift (digitva-xl43 phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from flask import current_app

from app import cache as flask_cache
from app import db
from app.models import (
    VaCoderReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
)
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.data_management_service import CSV_EXPORT_OMIT_PAYLOAD_FIELDS
from app.services.field_mapping_service import get_mapping_service
from app.services.final_cod_authority_service import (
    get_active_recode_episode,
    get_authoritative_final_assessment,
    get_authoritative_final_cod_record,
)
from app.services.payload_bound_coding_artifact_service import (
    get_current_payload_narrative_assessment,
    get_current_payload_reviewer_review,
    get_current_payload_social_autopsy_analysis,
)
from app.services.reviewer_final_assessment_service import (
    get_latest_active_reviewer_final_assessment,
    get_latest_active_reviewer_initial_assessment,
)
from app.services.smartva_icd11 import smartva_icd11_mapping
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.submission_summary_service import build_submission_summary
from app.services.viewer_pii_service import should_redact_pii
from app.utils import va_render_processcategorydata
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel

SECTION_CACHE_TIMEOUT = 1800  # 30 minutes

#: ``actiontype`` values of an open coding or reviewing session; the
#: completion block only applies inside one.
ACTIVE_SESSION_ACTIONTYPES = frozenset({
    "vastartcoding",
    "vapickcoding",
    "varesumecoding",
    "vademo_start_coding",
    "vastartreviewing",
    "varesumereviewing",
})

#: ``blocked_by`` codes, and the message the web shows for each when the
#: category holding the form is left unsaved.
BLOCK_NARRATIVE_QA = "narrative_qa"
BLOCK_SOCIAL_AUTOPSY = "social_autopsy"
_COMPLETION_BLOCK_MESSAGES = {
    BLOCK_SOCIAL_AUTOPSY: "Save the Social Autopsy Analysis before proceeding to the next category.",
    BLOCK_NARRATIVE_QA: "Complete the Narrative Quality Assessment before proceeding.",
}

def response_contains_user_specific_artifacts(va_partial: str, va_action: str) -> bool:
    """Return whether a rendered partial includes user-specific coding artifacts."""
    if va_action not in {"vacode", "vareview"}:
        return False
    # vacodassessment picks Step 1 or Step 2 from the user's own saved
    # assessment; a cached copy reopens Step 1 after it was saved.
    return va_partial in {"vanarrationanddocuments", "social_autopsy", "vacodassessment"}


# --- section data ----------------------------------------------------------


def section_data_cache_key(
    va_sid: str,
    payload_version_id,
    role: str,
    va_partial: str,
    *,
    redacted: bool = False,
) -> str:
    """Cache key of a category's rendered data.

    ``role`` is the category role bucket: ``va_get_render_datalevel`` maps
    coder and reviewer views through the legacy coder mapping and everyone
    else through the DB mapping, so roles must not share an entry. The
    payload version keeps an interviewer revision (or another interview
    chosen by a supervisor) from being served the old answers. ``redacted``
    is the no-PII variant (docs/policy/access-control-model.md,
    "collaborator").
    """
    key = f"form_data2:{va_sid}:{payload_version_id or 'none'}:{role}:{va_partial}"
    return f"{key}:nopii" if redacted else key


def invalidate_section_data_cache(va_sid: str) -> None:
    """Drop every cached category entry of the submission's current payload.

    Every role and PII variant: the keys differ by both, and the workflow
    panels are not among the visible data categories.
    """
    sub = db.session.get(VaSubmissions, va_sid)
    if not sub:
        return
    version = get_active_payload_version(va_sid)
    version_id = version.payload_version_id if version else None
    payload = version.payload_data if version else None
    service = get_category_rendering_service()
    partials = set(get_visible_category_codes(payload, sub.va_form_id))
    for items in service.WORKFLOW_NAV_ITEMS.values():
        partials.update(item.category_code for item in items)
    for role in set(service.ROLE_BY_ACTION.values()):
        for partial in partials:
            for redacted in (False, True):
                flask_cache.delete(
                    section_data_cache_key(va_sid, version_id, role, partial, redacted=redacted)
                )


def get_active_smartva(va_sid: str):
    """The submission's active SmartVA row, read live (never cached)."""
    return db.session.scalar(
        sa.select(VaSmartvaResults).where(
            (VaSmartvaResults.va_sid == va_sid)
            & (VaSmartvaResults.va_smartva_status == VaStatuses.active)
        )
    )


def get_section_data(
    *,
    va_submission,
    active_version,
    form_type_code: str,
    va_action: str,
    va_partial: str,
    category_config,
    visible_category_codes,
    user,
) -> dict:
    """A category's payload-derived data for the viewer, from the section cache.

    Returns the cached dict: ``summary_items``, ``va_processedcategorydata``,
    the ``cod_attachments_*`` and ``cod_health_history_*`` of the workflow
    panel, and ``smartva`` (cached with the section, as the web always did).

    A no-PII viewer is served the redacted variant. An unconfirmed PII set
    means nobody has said which of this form type's fields are personal data,
    so the whole payload is withheld rather than redacted by an answer that
    was never given (docs/policy/access-control-model.md, "The PII set must
    be confirmed per form type"). The confirmed set plus what the submissions
    export omits for every role (``CSV_EXPORT_OMIT_PAYLOAD_FIELDS``: staff
    identity, instance identifiers, narration image and audio tokens) is
    stripped before rendering, as ``_filter_export_payload``.
    """
    va_sid = va_submission.va_sid
    redact_pii = should_redact_pii(user)
    role = get_category_rendering_service().get_role_for_action(va_action)
    cache_key = section_data_cache_key(
        va_sid,
        active_version.payload_version_id if active_version else None,
        role,
        va_partial,
        redacted=redact_pii,
    )
    cached = flask_cache.get(cache_key)
    if cached is not None:
        return cached

    mapping_svc = get_mapping_service()
    payload_data = active_version.payload_data if active_version else None
    render_payload = payload_data
    if redact_pii and payload_data:
        pii_status = mapping_svc.get_pii_set_status(form_type_code)
        if not pii_status.confirmed:
            current_app.logger.warning(
                "pii set unconfirmed | %s | payload withheld", form_type_code
            )
            render_payload = {}
        else:
            withheld = pii_status.field_ids | CSV_EXPORT_OMIT_PAYLOAD_FIELDS
            render_payload = {
                field_id: value
                for field_id, value in payload_data.items()
                if field_id not in withheld
            }
    choices = mapping_svc.get_choices(form_type_code)
    datalevel = va_get_render_datalevel(va_action, form_type_code, visible_category_codes)
    form_id = va_submission.va_form_id

    def render(partial):
        return va_render_processcategorydata(
            render_payload, form_id, datalevel, choices, partial, va_sid=va_sid
        )

    data = {
        "summary_items": build_submission_summary(form_type_code, render_payload),
        "va_processedcategorydata": render(va_partial),
        "cod_attachments_data": {},
        "cod_attachments_labels": {},
        "cod_attachments_render_modes": {},
        "cod_health_history_data": {},
        "cod_health_history_labels": {},
    }
    if category_config and category_config.render_mode == "workflow_panel":
        data["cod_attachments_data"] = render("vanarrationanddocuments")
        data["cod_attachments_labels"] = mapping_svc.get_subcategory_labels(
            form_type_code, "vanarrationanddocuments"
        )
        data["cod_attachments_render_modes"] = mapping_svc.get_subcategory_render_modes(
            form_type_code, "vanarrationanddocuments"
        )
        data["cod_health_history_data"] = render("vahealthhistorydetails")
        data["cod_health_history_labels"] = mapping_svc.get_subcategory_labels(
            form_type_code, "vahealthhistorydetails"
        )
    data["smartva"] = get_active_smartva(va_sid)
    flask_cache.set(cache_key, data, timeout=SECTION_CACHE_TIMEOUT)
    return data


# --- helpers shared with the POST branches -----------------------------------


def get_display_initial_assessment(va_sid: str):
    """Return the initial COD to display for view/history contexts.

    Prefer the current active initial assessment. If the active draft was
    superseded during final COD submission, fall back to the source initial
    assessment linked from the authoritative coder final assessment.
    """
    initial_assessment = db.session.scalar(
        sa.select(VaInitialAssessments).where(
            (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
            & (VaInitialAssessments.va_sid == va_sid)
        )
    )
    if initial_assessment is not None:
        return initial_assessment

    authoritative_coder_final = get_authoritative_final_assessment(va_sid)
    if (
        authoritative_coder_final is None
        or authoritative_coder_final.source_initial_assessment_id is None
    ):
        return None

    return db.session.get(
        VaInitialAssessments,
        authoritative_coder_final.source_initial_assessment_id,
    )


def social_autopsy_enabled(project, va_action: str = "vacode") -> bool:
    """Return whether the app-owned Social Autopsy analysis form is enabled."""
    if project is None:
        return True
    if va_action == "vareview":
        return bool(project.reviewer_social_autopsy_enabled)
    return bool(project.social_autopsy_enabled)


def social_autopsy_required(project, va_action, form_type_code, visible_category_codes) -> bool:
    """Whether the Social Autopsy analysis gates the final COD for this role.

    The project switch and the category being visible to the role, as
    ``coder_cod_service._social_autopsy_required`` and the reviewer's
    equivalent decide at save time, from codes the caller already computed.
    """
    return bool(
        project is not None
        and social_autopsy_enabled(project, va_action)
        and get_category_rendering_service().is_category_enabled(
            form_type_code, va_action, visible_category_codes, "social_autopsy"
        )
    )


def nqa_blocks_final(va_sid, va_action, project, user_id) -> bool:
    """True when this coder must save the NQA before the final COD form.

    Saving the NQA reloads the page, so a final assessment typed before it
    would be lost; callers show ``_nqa_required_notice.html`` instead.
    """
    return bool(
        va_action == "vacode"
        and project
        and project.narrative_qa_enabled
        and not get_current_payload_narrative_assessment(va_sid, user_id)
    )


def get_step1_prefill(
    va_sid: str,
    user_id,
    va_action: str,
    *,
    recode_resume: bool,
    recode_active: bool | None = None,
):
    """The Step 1 row the form opens with, or None.

    The caller's own active initial. A recode session without one (another
    coder's recode, or a release cleared it) falls back to the coder's latest
    prior initial draft when ``recode_resume`` (the web's ``varesumecoding``).
    Only a row with ``va_iniassess_status == active`` is a saved Step 1.
    ``recode_active`` passes on a caller's own answer to "is a recode episode
    active" so it is read once per request; None reads it here when needed.
    """
    existing = db.session.scalar(
        sa.select(VaInitialAssessments)
        .where(
            VaInitialAssessments.va_sid == va_sid,
            VaInitialAssessments.va_iniassess_by == user_id,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
        .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
    )
    if (
        existing is None
        and va_action == "vacode"
        and recode_resume
        and (get_active_recode_episode(va_sid) is not None if recode_active is None else recode_active)
    ):
        existing = db.session.scalar(
            sa.select(VaInitialAssessments)
            .where(
                VaInitialAssessments.va_sid == va_sid,
                VaInitialAssessments.va_iniassess_by == user_id,
            )
            .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
        )
    return existing


# --- step state and saved artifacts --------------------------------------------


@dataclass
class CaseArtifacts:
    """What the COD workflow panel reads after the section data."""

    next_block_message: str | None = None
    next_block_code: str | None = None
    reviewobject: object = None
    vafinexists: object = None
    vaerrexists: object = None
    vainiexists: object = None
    va_final_assess: object = None
    va_initial_assess: object = None
    va_reviewer_initial_assess: object = None
    va_reviewer_final_assess: object = None
    va_coder_review: object = None
    da_va_final_assess: object = None
    da_va_initial_assess: object = None
    da_va_coder_review: object = None
    narrative_qa_enabled: bool = False
    social_autopsy_enabled: bool = False
    va_narrative_assessment: object = None
    va_social_autopsy_analysis: object = None
    social_autopsy_selected_pairs: set = field(default_factory=set)


def get_case_artifacts(
    *,
    va_sid,
    va_partial,
    va_action,
    va_actiontype,
    project,
    user_id,
    own_reviewer_final: bool = False,
) -> CaseArtifacts:
    """The saved artifacts a workspace partial reads, scoped to *user_id*.

    ``vainiexists`` is the caller's own for coding (a previous coder's active
    Step 1 must not send this coder to Step 2) and unscoped for review and
    view contexts. NQA and Social Autopsy are read only for the partial that
    holds their form, and the completion block derives from those reads.
    ``va_reviewer_final_assess`` is the latest of any reviewer, as the web
    panel shows it, unless ``own_reviewer_final`` (the API) scopes it to
    *user_id*.
    """
    out = CaseArtifacts()
    if va_action == "vareview":
        out.reviewobject = get_current_payload_reviewer_review(va_sid, user_id)
    elif va_action == "vacode":
        out.reviewobject = db.session.scalar(
            sa.select(VaReviewerReview).where(
                (VaReviewerReview.va_rreview_status == VaStatuses.active)
                & (VaReviewerReview.va_sid == va_sid)
            )
        )
    out.va_final_assess = get_authoritative_final_cod_record(va_sid)
    out.vafinexists = out.va_final_assess.va_sid if out.va_final_assess else None
    out.vaerrexists = db.session.scalar(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_creview_status == VaStatuses.active)
            & (VaCoderReview.va_sid == va_sid)
        )
    )
    ini_filter = [
        VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        VaInitialAssessments.va_sid == va_sid,
    ]
    if va_action == "vacode":
        ini_filter.append(VaInitialAssessments.va_iniassess_by == user_id)
    out.vainiexists = db.session.scalar(sa.select(VaInitialAssessments.va_sid).where(*ini_filter))
    out.va_initial_assess = get_display_initial_assessment(va_sid)
    if va_action == "vareview":
        out.va_reviewer_initial_assess = get_latest_active_reviewer_initial_assessment(
            va_sid, user_id
        )
        out.va_reviewer_final_assess = get_latest_active_reviewer_final_assessment(
            va_sid, user_id if own_reviewer_final else None
        )
    out.va_coder_review = db.session.scalar(
        sa.select(VaCoderReview).where(
            (VaCoderReview.va_creview_status == VaStatuses.active)
            & (VaCoderReview.va_sid == va_sid)
        )
    )
    out.da_va_final_assess = db.session.scalar(
        sa.select(VaFinalAssessments).where(
            (VaFinalAssessments.va_finassess_status == VaStatuses.deactive)
            & (VaFinalAssessments.va_sid == va_sid)
            & (VaFinalAssessments.va_finassess_by == user_id)
        )
    )
    out.da_va_coder_review = db.session.scalar(
        sa.select(VaCoderReview).where(
            (VaCoderReview.va_creview_status == VaStatuses.deactive)
            & (VaCoderReview.va_sid == va_sid)
            & (VaCoderReview.va_creview_by == user_id)
        )
    )
    in_workflow = va_action in {"vacode", "vareview"}
    if va_partial == "vanarrationanddocuments":
        out.narrative_qa_enabled = bool(project and project.narrative_qa_enabled)
    if va_partial == "social_autopsy":
        out.social_autopsy_enabled = social_autopsy_enabled(project, va_action)
    if out.narrative_qa_enabled and in_workflow:
        out.va_narrative_assessment = get_current_payload_narrative_assessment(va_sid, user_id)
    if va_partial == "social_autopsy" and in_workflow and out.social_autopsy_enabled:
        out.va_social_autopsy_analysis = get_current_payload_social_autopsy_analysis(
            va_sid, user_id
        )
    if out.va_social_autopsy_analysis:
        out.social_autopsy_selected_pairs = {
            f"{item.delay_level}::{item.option_code}"
            for item in out.va_social_autopsy_analysis.selected_options
        }
    out.next_block_code = _completion_block_code(
        va_partial,
        va_action,
        va_actiontype,
        narrative_qa_enabled=out.narrative_qa_enabled,
        narrative_saved=bool(out.va_narrative_assessment),
        social_autopsy_enabled=out.social_autopsy_enabled,
        social_autopsy_saved=bool(out.va_social_autopsy_analysis),
    )
    out.next_block_message = _COMPLETION_BLOCK_MESSAGES.get(out.next_block_code)
    return out


def _completion_block_code(
    va_partial,
    va_action,
    va_actiontype,
    *,
    narrative_qa_enabled,
    narrative_saved,
    social_autopsy_enabled,
    social_autopsy_saved,
) -> str | None:
    """The ``BLOCK_*`` code when the category holds an unsaved required form.

    Only inside an open coding or reviewing session; the Social Autopsy
    category waits for its analysis, the narrative one for the NQA.
    """
    if va_action not in {"vacode", "vareview"} or va_actiontype not in ACTIVE_SESSION_ACTIONTYPES:
        return None
    if va_partial == "social_autopsy" and social_autopsy_enabled and not social_autopsy_saved:
        return BLOCK_SOCIAL_AUTOPSY
    if va_partial == "vanarrationanddocuments" and narrative_qa_enabled and not narrative_saved:
        return BLOCK_NARRATIVE_QA
    return None


def category_block_code(
    va_sid, va_partial, va_action, va_actiontype, project, user_id
) -> str | None:
    """``_completion_block_code`` for one category, reading only its own form."""
    nqa_on = va_partial == "vanarrationanddocuments" and bool(project and project.narrative_qa_enabled)
    sa_on = va_partial == "social_autopsy" and social_autopsy_enabled(project, va_action)
    return _completion_block_code(
        va_partial,
        va_action,
        va_actiontype,
        narrative_qa_enabled=nqa_on,
        narrative_saved=bool(nqa_on and get_current_payload_narrative_assessment(va_sid, user_id)),
        social_autopsy_enabled=sa_on,
        social_autopsy_saved=bool(
            sa_on and get_current_payload_social_autopsy_analysis(va_sid, user_id)
        ),
    )


def coding_step(*, masked: bool, has_initial: bool, has_not_codeable: bool) -> str:
    """``initial | final | done`` of a coder's workspace, as the COD panel picks it.

    Step 1 only while the coder has neither a Step 1 nor a not-codeable
    review; an unmasked project has no Step 1, so it goes straight to the
    final; a not-codeable review with no Step 1 leaves nothing to do.
    """
    if has_initial:
        return "final"
    if has_not_codeable:
        return "done"
    return "initial" if masked else "final"


def reviewing_step(*, masked: bool, has_initial: bool, has_final: bool) -> str:
    """``initial | final | done`` of a reviewer's workspace.

    An unmasked project has the one final step; a masked one needs the
    reviewer's own Step 1 first. A reviewer final already saved is done.
    """
    if has_final:
        return "done"
    if not masked or has_initial:
        return "final"
    return "initial"


def final_blockers(
    *, va_sid, va_action, user_id, project, form_type_code, visible_category_codes
) -> list[str]:
    """``blocked_by`` of the final COD: Narrative QA and Social Autopsy not saved.

    NQA gates coders only (``nqa_blocks_final``); Social Autopsy gates the
    role it is enabled for.
    """
    blocked = []
    if nqa_blocks_final(va_sid, va_action, project, user_id):
        blocked.append(BLOCK_NARRATIVE_QA)
    if social_autopsy_required(
        project, va_action, form_type_code, visible_category_codes
    ) and not get_current_payload_social_autopsy_analysis(va_sid, user_id):
        blocked.append(BLOCK_SOCIAL_AUTOPSY)
    return blocked


_NAN = "NaN"


def _clean(value):
    return None if value is None or value == _NAN or value == "" else value


def smartva_summary(smartva) -> dict | None:
    """The SmartVA result as the summary table shows it, or None.

    ``NaN`` and empty values are null, as the table skips them; each cause
    carries the ICD-11 mapping of its ICD-10 code (None when unmapped).
    """
    if smartva is None:
        return None
    causes = []
    for rank in (1, 2, 3):
        cause = _clean(getattr(smartva, f"va_smartva_cause{rank}"))
        icd10 = _clean(getattr(smartva, f"va_smartva_cause{rank}icd"))
        causes.append({
            "rank": rank,
            "cause": cause,
            "icd10": icd10,
            "icd11": smartva_icd11_mapping(icd10) if icd10 else None,
            "likelihood": _clean(getattr(smartva, f"va_smartva_likelihood{rank}")),
        })
    symptoms = _clean(smartva.va_smartva_allsymptoms)
    return {
        "age": _clean(smartva.va_smartva_age),
        "gender": _clean(smartva.va_smartva_gender),
        "key_symptoms": [
            s for s in (_clean(getattr(smartva, f"va_smartva_keysymptom{i}")) for i in (1, 2, 3)) if s
        ],
        "causes": causes,
        "symptoms": [s.strip() for s in symptoms.split(";") if s.strip()] if symptoms else [],
    }
