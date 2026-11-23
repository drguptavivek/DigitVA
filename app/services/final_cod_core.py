"""Final cause-of-death checks shared by the coder's and the reviewer's saves.

``coder_cod_service.submit_coder_final_cod`` and
``reviewer_coding_service.submit_reviewer_final_cod`` run these in their own
order and turn the outcome into their own error class: a ``FinalCodRefusal``
is refused at once, a ``Block`` is one blocking problem (policy:
docs/policy/final-cod-authority.md, "Refusals").

The validators are passed in by the caller (``validate`` and ``provenance``),
so each service keeps calling its own module-level name.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.icd_coding_policy import AgeRestrictionConfirmationRequired
from app.services.icd_coding_value import (
    InvalidCausingConditionFlag,
    NonLeafCategory,
    check_causing_condition_unknown,
)

IMMEDIATE_REQUIRED_MESSAGE = "Immediate cause of death is required."


class FinalCodRefusal(Exception):
    """A final-COD mistake refused at once, before blocking problems are
    collected. ``details`` are extra response keys."""

    def __init__(self, message: str, status_code: int, code: str, details: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class Block:
    """One blocking problem: its message and the validator's own code, if any."""

    message: str
    code: str | None = None


def _block(exc: Exception) -> Block:
    return Block(str(exc), getattr(exc, "code", None))


def refuse_doris_envelopes_on_masked_step2(mode: str, *envelopes) -> None:
    """Masked DORIS Step 2 only confirms the underlying cause; the certificate
    and its envelopes stay on the Step 1 row. Raises a 400 ``invalid_request``
    ``FinalCodRefusal`` when any envelope is sent there."""
    if mode == "masked_doris" and any(envelopes):
        raise FinalCodRefusal(
            "Step 2 confirms the underlying cause only; the DORIS certificate belongs to Step 1.",
            400,
            "invalid_request",
        )


def check_conclusive_cod(
    va_sid: str,
    conclusive_cod: str,
    *,
    causing_condition_unknown: bool,
    age_restriction_confirmed: bool,
    validate,
) -> tuple[dict | None, Block | None]:
    """Check the conclusive (underlying) COD.

    Returns ``(age_restriction, block)``: the age-restriction details when the
    caller confirmed an age conflict (age warns, sex blocks, ``digitva-oh7j``),
    and the blocking problem of an invalid value. Raises a 422
    ``FinalCodRefusal``: ``INVALID_CAUSING_CONDITION_FLAG``
    (``digitva-xmpx``), ``non_leaf_category``, or an unconfirmed
    ``AGE_RESTRICTION_CONFIRMATION_REQUIRED`` carrying ``age_restriction``.
    """
    try:
        if causing_condition_unknown:
            check_causing_condition_unknown(conclusive_cod)
        validate(va_sid, conclusive_cod)
    except InvalidCausingConditionFlag as exc:
        raise FinalCodRefusal(str(exc), 422, "INVALID_CAUSING_CONDITION_FLAG") from exc
    except NonLeafCategory as exc:
        raise FinalCodRefusal(str(exc), 422, exc.code) from exc
    except AgeRestrictionConfirmationRequired as exc:
        if not age_restriction_confirmed:
            raise FinalCodRefusal(
                str(exc),
                422,
                "AGE_RESTRICTION_CONFIRMATION_REQUIRED",
                {"age_restriction": exc.details()},
            ) from exc
        return exc.details(), None
    except (LookupError, ValueError) as exc:
        return None, _block(exc)
    return None, None


def check_immediate_cod(
    va_sid: str, immediate_cod: str | None, *, validate, provenance
) -> tuple[dict | None, Block | None]:
    """Check the immediate COD of an unmasked simple final.

    Returns ``(provenance, block)``; a missing value is a block. Raises a 422
    ``non_leaf_category`` ``FinalCodRefusal``.
    """
    if not immediate_cod:
        return None, Block(IMMEDIATE_REQUIRED_MESSAGE)
    try:
        validate(va_sid, immediate_cod)
        return provenance(va_sid, {"immediate": immediate_cod}), None
    except NonLeafCategory as exc:
        raise FinalCodRefusal(str(exc), 422, exc.code) from exc
    except (LookupError, ValueError) as exc:
        return None, _block(exc)


def conclusive_provenance(
    va_sid: str, conclusive_cod: str, *, provenance
) -> tuple[dict | None, Block | None]:
    """The server-derived ICD-11 provenance of the conclusive COD, or its block."""
    try:
        return provenance(va_sid, {"conclusive": conclusive_cod}), None
    except (LookupError, ValueError) as exc:
        return None, _block(exc)
