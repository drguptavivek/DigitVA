"""Public demo: a user's own cause-of-death reports and downloads
(digitva-77v5.3; docs/policy/public-demo.md sections 5 and 6).

One reader, ``own_reports``, feeds the list page, the report page and the CSV
and JSON downloads, so all of them show the same facts. A fixed number of
queries whatever the number of cases (cases; SmartVA; coder finals; reviewer
finals; the authority pointers and the finals they name; and, for a download,
the answers), each ``IN`` the case ids of the first. Which final shows follows
``final_cod_authority_service.get_authoritative_final_cod_record``
(``_apply_authority``). The scope is ``authz.scope_filter(user, VIEW)``, which for a
public-demo account is its own submitted cases (``_own_cases``), ANDed with
the user's own submitted draft on the demo project; any other caller gets
nothing.

Not read here: death-register PII (the download carries the questionnaire
answers the user entered, never the sealed register), SmartVA failure
details, and the coder's remarks. The report page does show the caller's own
case's coder text: the DORIS certificate's condition text and, in the simple
mode, ``va_immediate_cod`` and ``va_other_conditions`` (the user's own
submission, so the user sees what was entered); a cause's title comes from the
stored ICD-11 provenance, never from the text typed after the code.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaReviewerFinalAssessments,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaWebIntakeDraft,
)
from app.services import public_demo_service as demo
from app.services.authz import Action, scope_filter
from app.services.case_export_service import safe_cell
from app.services.icd_coding_value import extract_icd11_code_expression
from app.services.workflow import definition as wf

#: Cases one page or download carries. The per-account submission limit (10
#: by default) keeps a real account far below it; this bounds a raised limit.
LIST_LIMIT = 200
DEFAULT_DOWNLOAD_RATE_LIMIT = "10 per hour"
NOT_A_CERTIFICATE = "Public demo — not a medical certificate"

# pipeline code, label, what it means. Every workflow state is mapped (a test
# holds the keys equal to ``wf.ALL_WORKFLOW_STATES``).
_WAITING = ("waiting_for_smartva", "Waiting for SmartVA",
            "The interview is received and SmartVA is working on it.")
_NOT_ANALYSABLE = ("not_analysable", "Not analysable",
                   "Consent was refused, the interview was incomplete, or it cannot be coded.")
PIPELINE = {
    wf.WORKFLOW_SCREENING_PENDING: _WAITING,
    wf.WORKFLOW_ATTACHMENT_SYNC_PENDING: _WAITING,
    wf.WORKFLOW_SMARTVA_PENDING: _WAITING,
    wf.WORKFLOW_READY_FOR_CODING: (
        "ready_to_code", "Ready to code", "Open VA Coding to assign the cause of death."),
    wf.WORKFLOW_CODING_IN_PROGRESS: ("coding", "Being coded", "Coding has started but is not final."),
    wf.WORKFLOW_CODER_STEP1_SAVED: ("coding", "Being coded", "Coding has started but is not final."),
    wf.WORKFLOW_CODER_FINALIZED: (
        "coded_waiting_review", "Coded, waiting for the review window",
        "The final cause is saved; it can still be recoded for a few minutes before review opens."),
    wf.WORKFLOW_REVIEWER_ELIGIBLE: (
        "ready_to_review", "Coded, ready for review", "Open VA Review to review the coding."),
    wf.WORKFLOW_REVIEWER_CODING_IN_PROGRESS: (
        "reviewing", "Being reviewed", "Review has started but is not final."),
    wf.WORKFLOW_REVIEWER_FINALIZED: ("reviewed", "Reviewed", "The reviewer's final cause is saved."),
    wf.WORKFLOW_FINALIZED_UPSTREAM_CHANGED: (
        "coded", "Coded (answers changed since)", "The answers changed after coding."),
    wf.WORKFLOW_NOT_CODEABLE_BY_CODER: _NOT_ANALYSABLE,
    wf.WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER: _NOT_ANALYSABLE,
    wf.WORKFLOW_CONSENT_REFUSED: (
        "not_analysable", "Not analysable (consent refused or incomplete)",
        "Consent was refused or the interview was incomplete, so it is not coded."),
}
_UNKNOWN = ("unknown", "Processing", "The case is being processed.")


class NotAvailable(LookupError):
    """The caller has no demo reports: the flag is off or the account is not a
    public-demo account. Routes answer 404."""


def download_rate_limit() -> str:
    """The limit on downloads (policy section 8), read per request so a
    deployment can change it; CSV and JSON share one bucket."""
    return current_app.config.get("PUBLIC_DEMO_DOWNLOAD_RATE_LIMIT") or DEFAULT_DOWNLOAD_RATE_LIMIT


def pipeline(state: str | None) -> dict:
    code, label, detail = PIPELINE.get(state, _UNKNOWN)
    return {"code": code, "label": label, "detail": detail}


def _age_label(years, days, raw) -> str:
    """"42 years" / "12 days", from the normalised age when stored."""
    try:
        if years is not None and float(years) >= 1:
            return f"{int(float(years))} years"
        if days is not None:
            return f"{int(float(days))} days"
    except (TypeError, ValueError):
        pass
    return str(raw) if raw is not None else ""


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _condition(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    return {"text": _text(item.get("Text")), "code": _text(item.get("Code")),
            "interval": _text(item.get("Interval"))}


def _chain(final) -> dict:
    """The Part I lines and Part II conditions of a final assessment: from
    the DORIS certificate, else the simple mode's immediate cause and other
    conditions."""
    certificate = final.doris_certificate
    if isinstance(certificate, dict):
        part1 = [
            [c for c in (_condition(x) for x in (line.get("Conditions") or [])) if c]
            for line in certificate.get("Part1") or [] if isinstance(line, dict)
        ]
        part2_raw = certificate.get("Part2")
        part2 = [c for c in (_condition(x) for x in (
            part2_raw.get("Conditions") or [] if isinstance(part2_raw, dict) else [])) if c]
        return {"part1": [line for line in part1 if line], "part2": part2}
    part1, part2 = [], []
    if _text(final.va_immediate_cod):
        part1 = [[{"text": _text(final.va_immediate_cod),
                   "code": extract_icd11_code_expression(final.va_immediate_cod), "interval": None}]]
    if _text(final.va_other_conditions):
        part2 = [{"text": _text(final.va_other_conditions), "code": None, "interval": None}]
    return {"part1": part1, "part2": part2}


def _final_view(final) -> dict:
    provenance = (final.icd11_provenance or {}).get("conclusive") or {}
    return {
        "code": _text(provenance.get("code")) or extract_icd11_code_expression(final.va_conclusive_cod),
        "title": _text(provenance.get("title")),
        "at": final.created_at,
        **_chain(final),
    }


def _smartva_view(row) -> dict:
    ok = row.va_smartva_outcome == VaSmartvaResults.OUTCOME_SUCCESS
    causes = []
    if ok:
        for n in (1, 2, 3):
            cause = _text(getattr(row, f"va_smartva_cause{n}"))
            if cause:
                causes.append({
                    "cause": cause,
                    "likelihood": _text(getattr(row, f"va_smartva_likelihood{n}")),
                    "icd10": _text(getattr(row, f"va_smartva_cause{n}icd")),
                })
    return {"ok": ok, "causes": causes, "at": row.va_smartva_addedat}


def _first_per_sid(rows, matches):
    """The first row (queries are newest first) of each ``va_sid`` that
    *matches* its case's active payload version."""
    found = {}
    for row in rows:
        if row.va_sid not in found and matches(row):
            found[row.va_sid] = row
    return found


def _apply_authority(sids, current, coder, reviewer, coder_cols, reviewer_cols):
    """Bring the coder and reviewer finals to the rule of
    ``final_cod_authority_service.get_authoritative_final_cod_record`` (one
    ``va_final_cod_authority`` row per case, read in one query): a valid
    reviewer pointer makes that reviewer final the answer (and the coder final
    it superseded the coder's); else a valid coder pointer makes that coder
    final the answer and no reviewer verdict shows; with no valid pointer the
    newest active rows stand. A pointer to another payload version than the
    active one is not valid, as there."""
    pointers = {row.va_sid: row for row in db.session.execute(
        sa.select(
            VaFinalCodAuthority.va_sid, VaFinalCodAuthority.authoritative_final_assessment_id,
            VaFinalCodAuthority.authoritative_reviewer_final_assessment_id,
        ).where(VaFinalCodAuthority.va_sid.in_(sids))
    )}
    reviewer_ids = {p.authoritative_reviewer_final_assessment_id for p in pointers.values()} - {None}
    pointed_reviewers = {row.row_id: row for row in db.session.execute(
        sa.select(*reviewer_cols).where(VaReviewerFinalAssessments.va_rfinassess_id.in_(reviewer_ids))
    )} if reviewer_ids else {}
    coder_ids = {p.authoritative_final_assessment_id for p in pointers.values()} - {None}
    coder_ids |= {r.supersedes_id for r in pointed_reviewers.values()} - {None}
    pointed_coders = {row.row_id: row for row in db.session.execute(
        sa.select(*coder_cols).where(VaFinalAssessments.va_finassess_id.in_(coder_ids))
    )} if coder_ids else {}
    coder, reviewer = dict(coder), dict(reviewer)
    for sid, pointer in pointers.items():
        by_reviewer = pointed_reviewers.get(pointer.authoritative_reviewer_final_assessment_id)
        by_coder = pointed_coders.get(pointer.authoritative_final_assessment_id)
        if by_reviewer is not None and current(by_reviewer):
            reviewer[sid] = by_reviewer
            superseded = pointed_coders.get(by_reviewer.supersedes_id)
            if superseded is not None:
                coder[sid] = superseded
        elif by_coder is not None and current(by_coder):
            coder[sid] = by_coder
            reviewer.pop(sid, None)
    return coder, reviewer


def own_reports(user, *, va_sid: str | None = None, with_answers: bool = False,
                limit: int = LIST_LIMIT) -> list[dict]:
    """The submitted demo cases *user* may see, newest first, each as a dict:
    ``va_sid, submitted_at, interview_date, age, sex, state, pipeline,
    smartva, coder, reviewer`` (``None`` while absent) and, with
    *with_answers*, ``answers`` (the active payload version's data). *va_sid*
    narrows to one case (empty when it is not the user's). Bounded by
    *limit* (clamped to ``LIST_LIMIT``); eight queries at most. Raises
    ``NotAvailable`` for anyone but a public-demo account on a demo
    deployment (the authz scope is built first, so the request is decided
    by authz before it is refused)."""
    scope = scope_filter(user, Action.VIEW)
    if not (demo.enabled() and getattr(user, "is_public_demo", False)):
        raise NotAvailable
    draft = VaWebIntakeDraft
    query = (
        sa.select(
            VaSubmissions.va_sid, VaSubmissions.va_submission_date, VaSubmissions.va_deceased_age,
            VaSubmissions.va_deceased_age_normalized_years,
            VaSubmissions.va_deceased_age_normalized_days, VaSubmissions.va_deceased_gender,
            VaSubmissions.active_payload_version_id, draft.submitted_at,
            VaSubmissionWorkflow.workflow_state,
        )
        .select_from(VaSubmissions)
        .join(draft, sa.and_(
            draft.va_sid == VaSubmissions.va_sid, draft.user_id == user.user_id,
            draft.status == "submitted", draft.project_id == demo.demo_project_id(),
        ))
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(scope)
        .order_by(draft.submitted_at.desc(), VaSubmissions.va_sid)
        .limit(max(1, min(int(limit), LIST_LIMIT)))
    )
    if va_sid is not None:
        query = query.where(VaSubmissions.va_sid == va_sid)
    cases = db.session.execute(query).all()
    if not cases:
        return []
    sids = [c.va_sid for c in cases]
    active = {c.va_sid: c.active_payload_version_id for c in cases}

    def current(row):
        return active[row.va_sid] is None or row.payload_version_id == active[row.va_sid]

    smartva = _first_per_sid(db.session.scalars(
        sa.select(VaSmartvaResults).where(
            VaSmartvaResults.va_sid.in_(sids), VaSmartvaResults.va_smartva_status == VaStatuses.active,
        ).order_by(VaSmartvaResults.va_smartva_addedat.desc())
    ), lambda _row: True)
    coder_cols = (
        VaFinalAssessments.va_finassess_id.label("row_id"),
        VaFinalAssessments.va_sid, VaFinalAssessments.payload_version_id,
        VaFinalAssessments.va_conclusive_cod, VaFinalAssessments.icd11_provenance,
        VaFinalAssessments.va_immediate_cod, VaFinalAssessments.va_other_conditions,
        VaFinalAssessments.doris_certificate,
        VaFinalAssessments.va_finassess_createdat.label("created_at"),
    )
    reviewer_cols = (
        VaReviewerFinalAssessments.va_rfinassess_id.label("row_id"),
        VaReviewerFinalAssessments.supersedes_coder_final_assessment_id.label("supersedes_id"),
        VaReviewerFinalAssessments.va_sid, VaReviewerFinalAssessments.payload_version_id,
        VaReviewerFinalAssessments.va_conclusive_cod, VaReviewerFinalAssessments.icd11_provenance,
        VaReviewerFinalAssessments.va_immediate_cod, VaReviewerFinalAssessments.va_other_conditions,
        VaReviewerFinalAssessments.doris_certificate,
        VaReviewerFinalAssessments.va_rfinassess_createdat.label("created_at"),
    )
    coder = _first_per_sid(db.session.execute(
        sa.select(*coder_cols).where(
            VaFinalAssessments.va_sid.in_(sids),
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
            VaFinalAssessments.is_tester.is_(False),
        ).order_by(VaFinalAssessments.va_finassess_createdat.desc())
    ), current)
    reviewer = _first_per_sid(db.session.execute(
        sa.select(*reviewer_cols).where(
            VaReviewerFinalAssessments.va_sid.in_(sids),
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        ).order_by(VaReviewerFinalAssessments.va_rfinassess_createdat.desc())
    ), current)
    coder, reviewer = _apply_authority(sids, current, coder, reviewer, coder_cols, reviewer_cols)
    answers = {}
    if with_answers:
        answers = dict(db.session.execute(
            sa.select(VaSubmissionPayloadVersion.va_sid, VaSubmissionPayloadVersion.payload_data)
            .where(
                VaSubmissionPayloadVersion.va_sid.in_(sids),
                VaSubmissionPayloadVersion.version_status == "active",
            )
        ).all())

    reports = []
    for case in cases:
        report = {
            "va_sid": case.va_sid,
            "submitted_at": case.submitted_at,
            "interview_date": case.va_submission_date,
            "age": _age_label(case.va_deceased_age_normalized_years,
                              case.va_deceased_age_normalized_days, case.va_deceased_age),
            "sex": (case.va_deceased_gender or "").capitalize(),
            "state": case.workflow_state,
            "pipeline": pipeline(case.workflow_state),
            "smartva": _smartva_view(smartva[case.va_sid]) if case.va_sid in smartva else None,
            "coder": _final_view(coder[case.va_sid]) if case.va_sid in coder else None,
            "reviewer": _final_view(reviewer[case.va_sid]) if case.va_sid in reviewer else None,
        }
        if with_answers:
            report["answers"] = answers.get(case.va_sid) or {}
        reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

CSV_COLUMNS = (
    "va_sid", "submitted_at", "state", "smartva_cause", "smartva_likelihood",
    "coder_icd11_code", "coder_icd11_title", "reviewer_icd11_code", "reviewer_icd11_title",
    "answers_json",
)


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _top_smartva(report: dict) -> dict:
    causes = (report["smartva"] or {}).get("causes") or []
    return causes[0] if causes else {}


def json_document(reports: list[dict]) -> dict:
    """The JSON download: ``{"cases": [...], "count": n}``."""
    cases = []
    for report in reports:
        top = _top_smartva(report)
        cases.append({
            "va_sid": report["va_sid"],
            "submitted_at": _iso(report["submitted_at"]),
            "state": report["state"],
            "smartva": {"cause": top.get("cause"), "likelihood": top.get("likelihood"),
                        "causes": (report["smartva"] or {}).get("causes", [])} if report["smartva"] else None,
            "coder": {k: report["coder"][k] for k in ("code", "title")} if report["coder"] else None,
            "reviewer": {k: report["reviewer"][k] for k in ("code", "title")} if report["reviewer"] else None,
            "answers": report.get("answers", {}),
        })
    return {"cases": cases, "count": len(cases), "generated_at": datetime.now(UTC).isoformat()}


def csv_text(reports: list[dict]) -> str:
    """The CSV download, one row per case; every cell goes through the cases
    export's ``safe_cell`` (a cell a spreadsheet would run as a formula gets a
    leading apostrophe). The answers are one JSON cell: the questionnaire
    differs by language and version, so it has no fixed columns."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for report in reports:
        top = _top_smartva(report)
        coder, reviewer = report["coder"] or {}, report["reviewer"] or {}
        writer.writerow([safe_cell(cell) for cell in (
            report["va_sid"], _iso(report["submitted_at"]), report["state"],
            top.get("cause"), top.get("likelihood"),
            coder.get("code"), coder.get("title"), reviewer.get("code"), reviewer.get("title"),
            json.dumps(report.get("answers", {}), sort_keys=True, ensure_ascii=False, default=str),
        )])
    return out.getvalue()
