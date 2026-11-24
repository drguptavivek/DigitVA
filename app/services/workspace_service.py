"""The ``/va/<sid>/workspace`` body: the coding, reviewing and view shell of one case.

Moved out of ``app/routes/api/va_case.py`` unchanged (digitva-r8nh.11). The
route keeps request parsing, authorization and the response; this module reads
the case's assessments, SmartVA, DORIS seed and timeline and returns the JSON
body. Behaviour is pinned by ``tests/routes/test_va_case_workspace_characterization.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models.mas_icd10_2019_2 import MasIcd1020192
from app.models import (
    VaDeathRegister,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services import smartva_service
from app.services.case_content_service import (
    coding_step,
    final_blockers,
    get_active_smartva,
    get_case_artifacts,
    get_step1_prefill,
    reviewing_step,
    smartva_summary,
    social_autopsy_enabled,
    viewer_source_payload,
)
from app.services.case_list_service import coding_names
from app.services.category_rendering_service import (
    get_category_rendering_service,
)
from app.services.cod_entry_mode import is_masked
from app.services.coder_cod_service import (
    other_conditions_choices,
)
from app.services.authz.grants import has_tree_condition
from app.services.cod_certificate_service import is_coded_tree_case
from app.services.doris_context_service import doris_initial, workspace_doris
from app.services.icd11_titles import stored_cod_label
from app.services.icd_coding_value import DEFAULT_ICD_CLASSIFICATION
from app.services.narrative_qa_service import NARRATIVE_QA_FIELDS, NARRATIVE_QA_MAX_SCORE
from app.services.payload_bound_coding_artifact_service import (
    get_current_payload_narrative_assessment,
    get_current_payload_social_autopsy_analysis,
)
from app.services.reviewer_final_assessment_service import (
    get_latest_active_reviewer_final_assessment,
)
from app.services.social_autopsy_analysis_service import SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
from app.services.workflow_timeline_service import (
    CODING_TIMELINE_EVENTS,
    WorkflowTimelineError,
    parse_timeline,
    server_event,
)

@dataclass
class _Case:
    mode: str
    va_action: str
    submission: VaSubmissions
    project: object
    project_code: str | None
    site_code: str | None
    is_demo_project: bool
    project_mode: str
    form_type_code: str
    active_version: object
    visible_category_codes: list[str]
    recode_active: bool = False
    intake_only: bool = False

    @property
    def project_id(self) -> str | None:
        """The case's project, for per-project PII (digitva-ssg7.3); None redacts."""
        return getattr(self.project, "project_id", None)


def _reported_date_of_death(va_sid: str) -> str | None:
    """The date of death on the death report this interview was started from (ISO), else None."""
    found = db.session.scalar(
        sa.select(VaDeathRegister.date_of_death)
        .where(VaDeathRegister.va_sid == va_sid, VaDeathRegister.date_of_death.is_not(None))
        .limit(1)
    )
    return found.isoformat() if found else None


def _draft_context(case: _Case, user) -> str | None:
    """Opaque per-actor/allocation/payload discriminator, after normal authorization.

    It is only compared by the client for reload recovery, never accepted as proof.
    """
    if case.mode == "view" or case.active_version is None:
        return None
    allocation_id = db.session.scalar(sa.select(VaAllocations.va_allocation_id).where(
        VaAllocations.va_sid == case.submission.va_sid,
        VaAllocations.va_allocated_to == user.user_id,
        VaAllocations.va_allocation_for == (VaAllocation.coding if case.mode == "coding" else VaAllocation.reviewing),
        VaAllocations.va_allocation_status == VaStatuses.active,
    ).limit(1))
    if allocation_id is None:
        return None
    values = [str(user.user_id), str(allocation_id), case.submission.va_sid,
              str(case.active_version.payload_version_id), case.mode, case.project_mode]
    return hmac.new(
        str(current_app.config["SECRET_KEY"]).encode(),
        json.dumps(values, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def _conditions(text) -> list[str]:
    return text.split(" | ") if text else []


def _iso(moment):
    """ISO 8601 with an explicit offset. The columns are naive and written in
    UTC (the web's ``user_timezone`` filter reads them the same way), so a
    client must not take them for local time."""
    if not moment:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def _coding_timeline(
    va_sid: str, user_id, initial_row, final_row, *, active_allocation: bool
) -> list[dict]:
    """Return bounded saved coding milestones for the coder's latest run.

    The allocation timestamp is the durable coding start; an online editor
    open is not persisted. Only allocation-linked DORIS audit and assessment
    rows contribute the remaining server-recorded milestones.
    """
    coder_id = user_id
    if final_row is not None:
        coder_id = final_row.va_finassess_by
    elif initial_row is not None:
        coder_id = initial_row.va_iniassess_by

    allocation_query = sa.select(VaAllocations).where(
        VaAllocations.va_sid == va_sid,
        VaAllocations.va_allocated_to == coder_id,
        VaAllocations.va_allocation_for == VaAllocation.coding,
    )
    if active_allocation:
        allocation_query = allocation_query.where(
            VaAllocations.va_allocation_status == VaStatuses.active
        )
    allocation = db.session.scalar(
        allocation_query.order_by(VaAllocations.va_allocation_createdat.desc()).limit(1)
    )
    if allocation is None:
        return []

    def stored_event(event: str, moment):
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return server_event(event, at=moment)

    try:
        events = [stored_event("coding_allocated", allocation.va_allocation_createdat)]
        processed_at = db.session.scalar(
            sa.select(VaSubmissionsAuditlog.va_audit_createdat)
            .where(
                VaSubmissionsAuditlog.va_sid == va_sid,
                VaSubmissionsAuditlog.va_audit_action == "DORIS processing completed",
                VaSubmissionsAuditlog.va_audit_entityid == allocation.va_allocation_id,
            )
            .order_by(VaSubmissionsAuditlog.va_audit_createdat)
            .limit(1)
        )
        if processed_at is not None:
            events.append(stored_event("doris_processed", processed_at))
        if initial_row is not None and initial_row.va_iniassess_by == coder_id:
            events.append(stored_event("initial_saved", initial_row.va_iniassess_createdat))
        if final_row is not None and final_row.va_finassess_by == coder_id:
            events.append(stored_event("final_saved", final_row.va_finassess_createdat))
        return parse_timeline(events, CODING_TIMELINE_EVENTS)
    except WorkflowTimelineError:
        # A malformed historical timestamp must not break an authorized workspace.
        current_app.logger.warning("invalid stored coding timeline")
        return []


_COD_FIELDS = ("immediate_cod", "antecedent_cod", "conclusive_cod")


def _icd10_code_titles(assessments: dict) -> dict[str, str]:
    """Title of every ICD-10 code in the assessments, so a phone can show code and title.

    ICD-10 assessments store the bare code; one query reads all titles. ICD-11
    values are stored with their title already and are left out.
    """
    codes = {
        value.strip()
        for row in assessments.values()
        if isinstance(row, dict)
        for field in _COD_FIELDS
        if isinstance(value := row.get(field), str) and value.strip()
    }
    if not codes:
        return {}
    rows = db.session.execute(
        sa.select(MasIcd1020192.code, MasIcd1020192.title).where(MasIcd1020192.code.in_(codes))
    )
    return {code: title for code, title in rows}


def _initial_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_iniassess_id),
        "immediate_cod": row.va_immediate_cod,
        "antecedent_cod": row.va_antecedent_cod,
        # The Step 1 cause with its WHO title, for the Step 2 quick-use label.
        "antecedent_cod_label": stored_cod_label(row.va_antecedent_cod),
        "other_conditions": _conditions(row.va_other_conditions),
        "created_at": _iso(row.va_iniassess_createdat),
    }


def _coder_final_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_finassess_id),
        "conclusive_cod": row.va_conclusive_cod,
        "immediate_cod": row.va_immediate_cod,
        "other_conditions": _conditions(row.va_other_conditions),
        "remark": row.va_finassess_remark,
        "created_at": _iso(row.va_finassess_createdat),
    }


def _doris_summary_json(doris_result) -> dict:
    """Codes only from a saved ``doris_result``: ``{doris_status, doris_code}``, each ``None`` when absent."""
    doris = doris_result if isinstance(doris_result, dict) else {}
    output = doris.get("result") if isinstance(doris.get("result"), dict) else {}
    status, code = doris.get("status"), output.get("code")
    return {
        "doris_status": status if isinstance(status, str) else None,
        "doris_code": code if isinstance(code, str) else None,
    }


def _reviewer_initial_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_riniassess_id),
        "immediate_cod": row.va_immediate_cod,
        "antecedent_cod": row.va_antecedent_cod,
        "antecedent_cod_label": stored_cod_label(row.va_antecedent_cod),
        "other_conditions": _conditions(row.va_other_conditions),
        "created_at": _iso(row.va_riniassess_createdat),
    }


def _reviewer_final_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_rfinassess_id),
        "conclusive_cod": row.va_conclusive_cod,
        "immediate_cod": row.va_immediate_cod,
        "other_conditions": _conditions(row.va_other_conditions),
        "remark": row.va_rfinassess_remark,
        "created_at": _iso(row.va_rfinassess_createdat),
    }


def _not_codeable_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "reason": row.va_creview_reason,
        "other": row.va_creview_other,
        "created_at": _iso(row.va_creview_createdat),
    }


def _narrative_qa_json(case: _Case, va_sid: str, user_id) -> dict | None:
    """The NQA form and the caller's own answers on the current payload, or
    ``None`` when the project has Narrative QA off (the save then 400s).

    A cannot-grade save stores zeros; they are returned as stored."""
    if not (case.project and case.project.narrative_qa_enabled):
        return None
    row = get_current_payload_narrative_assessment(va_sid, user_id)
    saved = None
    if row is not None:
        saved = {
            "cannot_grade": bool(row.va_nqa_cannot_grade),
            "values": {
                field["key"]: getattr(row, f"va_nqa_{field['key']}") for field in NARRATIVE_QA_FIELDS
            },
            "score": row.va_nqa_score,
            "rating": row.rating,
        }
    return {"fields": NARRATIVE_QA_FIELDS, "max_score": NARRATIVE_QA_MAX_SCORE, "saved": saved}


def _social_autopsy_json(case: _Case, va_sid: str, user_id) -> dict | None:
    """The SA questions and the caller's own answers on the current payload,
    or ``None`` when this role's SA switch is off (the save then 403s)."""
    if not social_autopsy_enabled(case.project, case.va_action):
        return None
    row = get_current_payload_social_autopsy_analysis(va_sid, user_id)
    saved = None
    if row is not None:
        # One SELECT for the row's options; sorted as the save normalizes them.
        pairs = sorted((option.delay_level, option.option_code) for option in row.selected_options)
        saved = {
            "selected_options": [
                {"delay_level": delay_level, "option_code": option_code}
                for delay_level, option_code in pairs
            ],
            "remark": row.va_saa_remark,
        }
    return {"questions": SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS, "saved": saved}


def _category_counts(catcount, nav) -> dict[str, int]:
    """Return the non-negative notification counts used by the web nav."""
    if not isinstance(catcount, dict):
        return {item.category_code: 0 for item in nav}
    counts = {}
    for item in nav:
        entry = catcount.get(item.category_code)
        count = entry.get("count") if isinstance(entry, dict) else 0
        counts[item.category_code] = count if type(count) is int and count >= 0 else 0
    return counts


#: The open-session ``actiontype`` of each mode (a workspace is a resume of
#: the held allocation); it is what makes a category's required form block.
#: A view is the read-only opening, which never blocks.
SESSION_ACTIONTYPE = {
    "coding": "varesumecoding",
    "reviewing": "varesumereviewing",
    "view": "vaview",
}


def build_workspace(
    case: _Case,
    va_sid: str,
    user,
    *,
    redact_pii,
    count_attachments_per_category,
    viewer_payload_of,
    survey_location,
    may_see_cod_reference,
    read_state,
) -> tuple[dict, str | None]:
    """Return ``(body, wf_state)`` for an already-authorized *case*.

    *user* is the caller (``current_user``). The collaborators that tests patch
    on the route module are passed in as callables, resolved by the route at
    call time: ``redact_pii`` (``should_redact_pii``), ``count_attachments_per_category``,
    ``viewer_payload_of`` (``payload_for_viewer``), ``survey_location`` and
    ``may_see_cod_reference``. ``read_state`` reads the case's coding state; the
    route puts the returned *wf_state* in ``body["case"]`` itself, so this module
    names no coding state (tests/test_duplicate_exclusion_coverage.py exempts the
    route function, one allocated or viewed case, not a coding list).
    ``redact_pii`` is evaluated once per request (it only reads grants), and the
    body is otherwise unchanged.
    """
    uid = user.user_id
    view = case.mode == "view"
    redacted = redact_pii(user, project_id=case.project_id)
    icd_classification = (
        case.project.icd_classification
        if case.project and case.project.icd_classification
        else DEFAULT_ICD_CLASSIFICATION
    )
    category_service = get_category_rendering_service()
    nav = category_service.get_category_nav(
        case.form_type_code, case.va_action, case.visible_category_codes
    )
    category_counts = _category_counts(case.submission.va_catcount, nav)
    attachment_counts = count_attachments_per_category(
        case.form_type_code,
        case.active_version.payload_data if case.active_version else {},
        va_sid,
    )
    artifacts = get_case_artifacts(
        va_sid=va_sid,
        va_partial="vacodassessment",
        va_action=case.va_action,
        va_actiontype=SESSION_ACTIONTYPE[case.mode],
        project=case.project,
        user_id=uid,
        own_reviewer_final=True,
    )
    masked = is_masked(case.project_mode)
    wf_state = read_state(va_sid)
    # ``mode=view`` only: the COD reference and SmartVA unblind coding.
    show_reference = view and not case.intake_only and may_see_cod_reference(va_sid, wf_state, uid)
    # The authoritative record carries the coder final it stands on (or
    # supersedes); one primary-key read, usually already in the session.
    authoritative = artifacts.va_final_assess
    coder_final = (
        db.session.get(VaFinalAssessments, authoritative.coder_final_assessment_id)
        if authoritative is not None and authoritative.coder_final_assessment_id
        else None
    )
    assessments = {
        "initial": None,
        "initial_prefill": None,
        "final": None,
        "not_codeable": None,
        "coder_initial": None,
        "reviewer_initial": None,
        "reviewer_final": None,
    }
    options = None
    if case.mode == "coding":
        prefill = get_step1_prefill(
            va_sid, uid, "vacode", recode_resume=True, recode_active=case.recode_active
        )
        own = prefill if prefill is not None and prefill.va_iniassess_status == VaStatuses.active else None
        assessments["initial"] = _initial_json(own)
        assessments["initial_prefill"] = _initial_json(prefill)
        step = coding_step(
            masked=masked, has_initial=own is not None, has_not_codeable=bool(artifacts.vaerrexists)
        )
        options = other_conditions_choices(case.active_version.payload_data if case.active_version else None)
        # The web's active coding panel shows neither before Step 2: another
        # coder's authoritative final would unblind a masked Step 1, and a
        # not-codeable review counts only as the caller's own.
        if step == "final":
            assessments["final"] = _coder_final_json(coder_final)
        if artifacts.va_coder_review is not None and artifacts.va_coder_review.va_creview_by == uid:
            assessments["not_codeable"] = _not_codeable_json(artifacts.va_coder_review)
    elif view:
        # Read-only reference once coding is finished: the authoritative
        # final's coder row, the latest reviewer final of any reviewer.
        if show_reference:
            assessments["final"] = _coder_final_json(coder_final)
            assessments["not_codeable"] = _not_codeable_json(artifacts.va_coder_review)
            assessments["coder_initial"] = _initial_json(artifacts.va_initial_assess)
            assessments["reviewer_final"] = _reviewer_final_json(
                get_latest_active_reviewer_final_assessment(va_sid, None)
            )
        if redacted:
            # Staff free text can name people; a redacted viewer gets the codes only.
            for key, field in (("final", "remark"), ("reviewer_final", "remark"), ("not_codeable", "other")):
                if assessments[key] is not None:
                    assessments[key][field] = None
        step = "view"
    else:
        # The reviewer sees the coder's Step 1, final and not-codeable review
        # as read-only reference; the reviewer rows are their own.
        assessments["final"] = _coder_final_json(coder_final)
        if assessments["final"] is not None and case.project_mode == "unmasked_doris":
            # As the legacy reviewer panel: the coder's DORIS status and computed code, no reports.
            assessments["final"].update(_doris_summary_json(coder_final.doris_result))
        assessments["not_codeable"] = _not_codeable_json(artifacts.va_coder_review)
        assessments["coder_initial"] = _initial_json(artifacts.va_initial_assess)
        assessments["reviewer_initial"] = _reviewer_initial_json(artifacts.va_reviewer_initial_assess)
        assessments["reviewer_final"] = _reviewer_final_json(artifacts.va_reviewer_final_assess)
        step = reviewing_step(
            masked=masked,
            has_initial=artifacts.va_reviewer_initial_assess is not None,
            has_final=artifacts.va_reviewer_final_assess is not None,
        )
    timeline_initial = own if case.mode == "coding" else artifacts.va_initial_assess
    timeline_final = coder_final
    if case.mode == "coding" and timeline_final is not None and timeline_final.va_finassess_by != uid:
        timeline_final = None
    coding_timeline = (
        []
        if case.intake_only or (view and not show_reference)
        else _coding_timeline(
            va_sid,
            uid,
            timeline_initial,
            timeline_final,
            active_allocation=case.mode == "coding",
        )
    )
    # SmartVA completes asynchronously, so it is read live, and a masked
    # project keeps it from Step 1 as the web does: shown once the caller
    # has their own Step 1.
    has_initial = (
        assessments["initial"] is not None
        if case.mode == "coding"
        else artifacts.va_reviewer_initial_assess is not None
    )
    smartva = None
    if show_reference or (not view and (not masked or has_initial)):
        smartva = smartva_summary(get_active_smartva(va_sid))
    smartva_panel = smartva_service.smartva_panel(va_sid)
    survey = survey_location(
        case,
        nav,
        viewer_payload_of(
            viewer_source_payload(case.active_version, redacted),
            case.form_type_code,
            redacted,
        ),
    )
    body = {
        "case": {
            "va_sid": va_sid,
            "payload_version_id": str(case.active_version.payload_version_id) if case.active_version else None,
            "doris_draft_context": _draft_context(case, user),
            "instance_name": case.submission.va_uniqueid_masked,
            # The coding header only (coding-workflow-state-machine.md,
            # "Names on the coding screens"); None when the caller may not see it.
            "deceased_name": coding_names(user, [va_sid]).get(va_sid) if case.mode == "coding" else None,
            "form_type_code": case.form_type_code,
            "project_code": case.project_code,
            "site_code": case.site_code,
            "age": case.submission.va_deceased_age,
            "gender": case.submission.va_deceased_gender,
            **survey,
            "is_demo_project": case.is_demo_project,
            "project_mode": case.project_mode,
            # get_icd_classification_for_submission's answer from the project
            # already loaded (same submission -> form -> project path).
            "icd_classification": icd_classification,
            "narrative_qa_enabled": not view and bool(case.project and case.project.narrative_qa_enabled),
            "social_autopsy_enabled": not view and social_autopsy_enabled(case.project, case.va_action),
            # False for an intake-only view: its workflow events stay READ_EVENTS's.
            "history_available": not case.intake_only,
            # A coded org-project case in a read-only view has a printable
            # certificate (/coding/area/<sid>/certificate); the page re-checks.
            "certificate_available": bool(view and not case.intake_only and is_coded_tree_case(va_sid, case.project_id)),
            # The date of death on the death report this interview was started from (ISO), for DORIS to compare.
            "reported_date_of_death": _reported_date_of_death(va_sid),
            # An organization project's site code is generated, not a place: the phone shows the project alone.
            "is_org_project": bool(case.project_id and db.session.scalar(sa.select(has_tree_condition(case.project_id)))),
        },
        "categories": [
            {
                "code": item.category_code,
                "label": item.display_label,
                "nav_label": item.nav_label,
                "icon_name": item.icon_name,
                "count": category_counts[item.category_code],
                "attachment_count": attachment_counts.get(item.category_code, 0),
                "render_mode": item.render_mode,
            }
            for item in nav
        ],
        "default_category": category_service.get_default_category_code(
            case.form_type_code, case.va_action, case.visible_category_codes
        ),
        "step": step,
        "blocked_by": []
        if view
        else final_blockers(
            va_sid=va_sid,
            va_action=case.va_action,
            user_id=uid,
            project=case.project,
            form_type_code=case.form_type_code,
            visible_category_codes=case.visible_category_codes,
        ),
        "assessments": assessments,
        # Additive (older apps ignore it): ICD-10 code -> title for the codes above.
        "code_titles": _icd10_code_titles(assessments)
        if icd_classification != "icd11"
        else {},
        "codingTimelineV1": coding_timeline,
        "smartva": smartva,
        "smartva_status": smartva_panel["status"],
        "smartva_can_run": bool(smartva_panel["can_run"]) and not view,
        "other_conditions_options": options,
        "narrative_qa": None if view else _narrative_qa_json(case, va_sid, uid),
        "social_autopsy": None if view else _social_autopsy_json(case, va_sid, uid),
        "doris": None
        if view
        else workspace_doris(
            va_sid=va_sid,
            mode=case.mode,
            project_mode=case.project_mode,
            submission=case.submission,
            active_version=case.active_version,
            redact_pii=redacted,
            step1=prefill if case.mode == "coding" else None,
            reviewer_initial=artifacts.va_reviewer_initial_assess,
            reviewer_final=artifacts.va_reviewer_final_assess,
        ),
    }
    if body["doris"] is not None:
        reset_certificate, reset_provenance = doris_initial(
            None, case.submission, case.project_mode, redacted, case.active_version,
        )
        body["doris"].update(reset_certificate=reset_certificate, reset_prefill_provenance=reset_provenance)
    return body, wf_state
