"""COD entry mode of a project, shared by the coder and reviewer screens.

A project is masked or unmasked (Step 1 / Step 2 or one final step) and
simple or DORIS, giving four modes. Masked DORIS (masked ICD-11) puts the
DORIS certificate in Step 1 and confirms the final underlying cause in
Step 2 (digitva-0n3). Kept free of app imports beyond two leaf services so
routes and services can both use it without an import cycle.
"""

from __future__ import annotations

from app.services.icd_coding_value import extract_icd11_code_expression
from app.services.smartva_icd11 import smartva_icd11_mapping
from app.services.who_icd_api import DEFAULT_ICD11_RELEASE


def project_mode(project) -> str:
    """``masked_simple | masked_doris | unmasked_simple | unmasked_doris``."""
    if project is None:
        return "masked_simple"
    doris = project.cod_entry_mode == "doris"
    if project.masked_cod_required:
        return "masked_doris" if doris else "masked_simple"
    return "unmasked_doris" if doris else "unmasked_simple"


def is_masked(mode: str) -> bool:
    return mode.startswith("masked_")


def is_doris(mode: str) -> bool:
    return mode.endswith("_doris")


def cod_entry_mode_snapshot(project, who_image_digest: str) -> dict:
    return {
        "masked_cod_required": project.masked_cod_required,
        "cod_entry_mode": project.cod_entry_mode,
        "icd_release": DEFAULT_ICD11_RELEASE,
        "who_image_digest": who_image_digest,
    }


def part1_line1_cod(certificate) -> str:
    """The immediate COD of a verified certificate as ``"<Code> <Text>"``.

    The first condition on Part I line 1; empty when there is none, which
    callers refuse with a 400 (the Step 1 text columns are NOT NULL).
    """
    part1 = (certificate or {}).get("Part1") or []
    line1 = (part1[0].get("Conditions") if part1 else None) or []
    first = line1[0] if line1 else {}
    return f"{first.get('Code') or ''} {first.get('Text') or ''}".strip()


def smartva_icd11_alternatives(smartva) -> list[str]:
    """WHO's ICD-11 target for SmartVA's primary cause, split on ``/``.

    The WHO 10-to-11 map joins alternative expressions with ``/``; one item
    means SmartVA's result can be used in one click. Local map only, so no
    WHO call sits in the request path.
    """
    target = smartva_icd11_mapping(smartva.va_smartva_cause1icd) if smartva else None
    return [part.strip().upper() for part in (target or "").split("/") if part.strip()]


def final_ucod_source(final_value, step1_value, smartva_alternatives) -> str:
    """Where a masked DORIS Step 2 final UCOD came from: doris, smartva or own.

    Derived server-side from the saved code, never from the client.
    ``step1_value`` is the Step 1 underlying cause (the cause confirmed in
    the DORIS step, not necessarily DORIS's computed code). A code equal to
    both it and a SmartVA target is recorded as ``doris``.
    """
    final_code = extract_icd11_code_expression(final_value)
    if final_code is None:
        return "own"
    if final_code == extract_icd11_code_expression(step1_value):
        return "doris"
    if final_code in smartva_alternatives:
        return "smartva"
    return "own"
