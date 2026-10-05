"""DORIS certificate seeds and saved-processing context for a coding screen.

One place for what the web partials (``app/routes/va_form.py``) and the
workspace API (``GET /api/v1/va/<sid>/workspace``) show before a coder or
reviewer touches the DORIS editor: the starting certificate, the interview
prefill, a saved Step 1 result reopened display-only, and the Step 1
reference a masked Step 2 confirms against. Workflow:
``docs/current-state/doris-cod-workflow.md``.

PII: every certificate returned here goes through ``_redacted``. A redacting
viewer (``viewer_pii_service.should_redact_pii``, passed in as ``redact_pii``)
keeps the cause chain only; ``AdministrativeData`` holds the deceased's Sex,
DateBirth, DateDeath and age.
"""

from __future__ import annotations

import copy

from app import db
from app.models import VaInitialAssessments, VaStatuses
from app.services.cod_entry_mode import is_doris, is_masked, smartva_icd11_alternatives
from app.services.doris_prefill import doris_prefill_from_payload
from app.services.final_cod_authority_service import get_authoritative_final_assessment
from app.services.submission_payload_version_service import get_active_payload_version


def _redacted(certificate, redact_pii: bool):
    """The certificate without ``AdministrativeData`` for a redacting viewer.

    A copy: the stored row's JSON is never mutated.
    """
    if redact_pii and isinstance(certificate, dict):
        return {k: v for k, v in certificate.items() if k != "AdministrativeData"}
    return certificate


def doris_initial(
    saved_certificate, submission, project_mode, redact_pii: bool, active_version=None
) -> tuple[dict, dict]:
    """``(initial certificate, prefill provenance)`` for a DORIS editor.

    A saved (or just-submitted) certificate is shown as it is, with no
    prefill markers. Otherwise a DORIS project's new certificate starts
    with the non-cause fields the interview answers
    (``doris_prefill_from_payload``, bead digitva-hln); these are interview
    facts, not SmartVA output, so masked Step 1 shows them too. A redacting
    viewer gets no prefill (it is the deceased's Sex, DateBirth, DateDeath
    and age). ``active_version`` is the submission's active payload version
    when the caller already loaded it; else it is read here.
    """
    if saved_certificate is not None:
        return _redacted(copy.deepcopy(saved_certificate), redact_pii), {}
    if submission is None or not is_doris(project_mode) or redact_pii:
        return {}, {}
    version = active_version or get_active_payload_version(submission.va_sid)
    return doris_prefill_from_payload(version.payload_data if version else None)


def saved_step1_processing(step1, redact_pii: bool) -> dict | None:
    """A saved Step 1's processing result, shown display-only, or ``None``.

    ``step1`` is a coder or reviewer initial assessment the caller has
    already decided is the live one. No process token is minted here: saving
    a changed Step 1 still needs a fresh Process (digitva-0n3.4).
    """
    if step1 is None or step1.doris_result is None:
        return None
    return {
        "certificate": _redacted(step1.doris_certificate, redact_pii),
        "doris": step1.doris_result,
        "codedit": step1.codedit_result,
        "final_choice": step1.va_antecedent_cod or "",
    }


def masked_step2_context(step1, smartva, redact_pii: bool) -> dict:
    """Template data for the masked DORIS Step 2 picker host.

    The picker's API URLs default in the template from ``va_sid``.
    """
    return {
        "smartva_icd11_alternatives": smartva_icd11_alternatives(smartva),
        "step1_doris_certificate": (
            _redacted(step1.doris_certificate, redact_pii) if step1 else None
        ),
        "step1_doris_processing": (
            {"doris": step1.doris_result, "codedit": step1.codedit_result}
            if step1 and step1.doris_result is not None
            else None
        ),
    }


def masked_reviewer_context(va_sid, reviewer_initial, smartva, redact_pii: bool):
    """Seed row and template data for the masked DORIS reviewer panel.

    Returns ``(doris_source, context)``. The reviewer's Step 1 editor starts
    from their own saved certificate, else from the certificate of the
    coder's Step 1 behind the authoritative coder final (the template
    deep-copies it, so the coder's rows never change), else ``None`` for the
    admin defaults. A saved reviewer Step 1 reopens display-only: no process
    token is minted on GET, so saving a changed Step 1 still needs Process.
    """
    context = masked_step2_context(reviewer_initial, smartva, redact_pii)
    if reviewer_initial is not None and reviewer_initial.doris_certificate:
        processing = saved_step1_processing(reviewer_initial, redact_pii)
        if processing is not None:
            context["doris_initial_processing"] = processing
        return reviewer_initial, context
    coder_final = get_authoritative_final_assessment(va_sid)
    coder_step1 = (
        db.session.get(VaInitialAssessments, coder_final.source_initial_assessment_id)
        if coder_final is not None and coder_final.source_initial_assessment_id
        else None
    )
    return coder_step1, context


def unmasked_seed_source(va_sid, reviewer_final=None):
    """The row an unmasked DORIS editor starts from: the reviewer's own final,
    else the authoritative coder final (``None`` when there is neither)."""
    return reviewer_final or get_authoritative_final_assessment(va_sid)


def _seed(source):
    return source.doris_certificate if source is not None and source.doris_certificate else None


def workspace_doris(
    *,
    va_sid,
    mode,
    project_mode,
    submission,
    active_version,
    redact_pii: bool,
    step1=None,
    reviewer_initial=None,
    reviewer_final=None,
) -> dict | None:
    """The workspace body's ``doris`` object, or ``None`` outside DORIS projects.

    ``mode`` is ``coding | reviewing``. ``step1`` is the coder's
    ``get_step1_prefill`` row; ``reviewer_initial`` / ``reviewer_final`` are
    the reviewer's own rows. Unmasked: ``{initial_certificate,
    prefill_provenance}`` seeded from the reviewer final else the
    authoritative coder final. Masked adds ``saved_processing`` (a saved,
    active Step 1 reopened display-only) and ``step1_certificate`` /
    ``step1_processing`` (the Step 1 a Step 2 confirms; ``None`` until there
    is one). Masked Step 1 never carries another coder's rows or SmartVA.
    """
    if not is_doris(project_mode):
        return None

    def initial(source):
        certificate, provenance = doris_initial(
            _seed(source), submission, project_mode, redact_pii, active_version
        )
        return {"initial_certificate": certificate, "prefill_provenance": provenance}

    if not is_masked(project_mode):
        return initial(unmasked_seed_source(va_sid, reviewer_final))

    if mode == "coding":
        own = step1 if step1 is not None and step1.va_iniassess_status == VaStatuses.active else None
        source = step1
        saved = saved_step1_processing(own, redact_pii)
        context = masked_step2_context(own, None, redact_pii)
    else:
        source, context = masked_reviewer_context(va_sid, reviewer_initial, None, redact_pii)
        saved = context.get("doris_initial_processing")
    return {
        **initial(source),
        "saved_processing": saved,
        "step1_certificate": context["step1_doris_certificate"],
        "step1_processing": context["step1_doris_processing"],
    }
