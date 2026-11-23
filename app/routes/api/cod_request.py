"""Request parsing of the COD writes: the coder's ``/coding/*`` saves and the
final COD both roles post (``/coding/finalize``, ``/reviewing/finalize``).

Each helper raises ``ValueError`` for a wrong type (the route answers 400
``invalid_request``); ``json_object`` raises ``RequestEntityTooLarge`` (413
``payload_too_large``, answered by the blueprint's handler).
"""

from flask import request
from werkzeug.exceptions import RequestEntityTooLarge

BODY_CAP = 1_200_000  # the DORIS certificate and its envelopes ride along
FREE_TEXT_CAP = 4000  # characters: remark, other, each other condition


def too_long(*texts: str | None) -> bool:
    return any(text and len(text) > FREE_TEXT_CAP for text in texts)


def json_object() -> dict | None:
    """The JSON object body, None when absent or not an object.

    The size cap keys on the path only, so no lookup runs before authz. It
    reads ``Content-Length``: CSRF protection has already built the request
    stream without a limit, so ``request.max_content_length`` cannot enforce
    it. Longer, or no length at all (a chunked body, which would be buffered
    whole), raises ``RequestEntityTooLarge``.
    """
    if request.content_length is None or request.content_length > BODY_CAP:
        raise RequestEntityTooLarge()
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return None
    return body if isinstance(body, dict) else None


def text(body: dict, name: str) -> str | None:
    """The stripped text of *name*, None when absent; ValueError when not text."""
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    return value.strip()


def flag(body: dict, name: str) -> bool:
    """The JSON boolean *name*, False when absent; ValueError when not a boolean."""
    value = body.get(name, False)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false.")
    return value


def doris_fields(body: dict) -> dict:
    """The DORIS envelopes of a body: objects, tokens as text (ValueError otherwise)."""
    for name in ("doris_certificate", "doris_result", "codedit_result"):
        if body.get(name) is not None and not isinstance(body[name], dict):
            raise ValueError(f"{name} must be an object.")
    return {
        "doris_certificate": body.get("doris_certificate"),
        "doris_result": body.get("doris_result"),
        "codedit_result": body.get("codedit_result"),
        "doris_process_token": text(body, "doris_process_token"),
        "doris_result_digest": text(body, "doris_result_digest"),
        "doris_client_revision": body.get("doris_client_revision", 0),
    }


def parse_final_cod_body(body: dict, *, other_conditions_text: bool = False) -> dict:
    """The final-COD fields of a finalize body; ``other_conditions`` only with
    *other_conditions_text* (the coder's text shape; the reviewer reads its own): ``conclusive_cod``, ``remark``,
    ``immediate_cod``, the ICD-11 flags, the DORIS envelopes and the search
    telemetry ``cod_search_id``, ``cod_chosen_code`` and ``cod_chosen_rank``
    (an integer). Raises ValueError for a wrong type.
    """
    fields = {
        "conclusive_cod": text(body, "conclusive_cod"),
        "remark": text(body, "remark"),
        "immediate_cod": text(body, "immediate_cod"),
        # The coder's other_conditions is text, read here so a wrong type is
        # reported in the coder route's original field order.
        **({"other_conditions": text(body, "other_conditions")} if other_conditions_text else {}),
        "age_restriction_confirmed": flag(body, "age_restriction_confirmed"),
        "causing_condition_unknown": flag(body, "causing_condition_unknown"),
        **doris_fields(body),
        "cod_search_id": text(body, "cod_search_id"),
        "cod_chosen_code": text(body, "cod_chosen_code"),
        "cod_chosen_rank": body.get("cod_chosen_rank"),
    }
    rank = fields["cod_chosen_rank"]
    if rank is not None and (not isinstance(rank, int) or isinstance(rank, bool)):
        raise ValueError("cod_chosen_rank must be an integer.")
    return fields
