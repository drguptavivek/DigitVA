"""Helpers for payload-version-aware ODK sync lineage."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import VaSubmissionPayloadVersion, VaSubmissions
from app.utils.national_id import redact_payload_national_ids
from app.models.va_submission_payload_versions import (
    PAYLOAD_VERSION_STATUS_ACTIVE,
    PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
    PAYLOAD_VERSION_STATUS_REJECTED,
    PAYLOAD_VERSION_STATUS_SUPERSEDED,
)


VOLATILE_PAYLOAD_KEYS = frozenset(
    {
        "AttachmentsExpected",
        "AttachmentsPresent",
        "DeviceID",
        "Edits",
        "FormVersion",
        "OdkReviewComments",
        "SubmitterID",
        "updatedAt",
        "audit",
        "instanceID",
        "survey_district",
        "survey_state",
        "ageInDays",
        "ageInDays2",
        "ageInDaysNeonate",
        "ageInMonths",
        "ageInMonthsByYear",
        "ageInMonthsRemain",
        "ageInYears",
        "ageInYears2",
        "ageInYearsRemain",
        "finalAgeInYears",
        "isAdult",
        "isAdult1",
        "isAdult2",
        "isChild",
        "isChild1",
        "isChild2",
        "isNeonatal",
        "isNeonatal1",
        "isNeonatal2",
    }
)

NULL_LIKE_STRING_VALUES = frozenset(
    {
        "",
        "na",
        "n/a",
        "none",
        "null",
    }
)


def _normalize_scalar(value):
    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return _canonicalize_numeric(value)

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.casefold() in NULL_LIKE_STRING_VALUES:
            return None
        try:
            return _canonicalize_numeric(stripped)
        except InvalidOperation:
            return stripped

    return value


def _canonicalize_numeric(value) -> str:
    normalized = Decimal(str(value)).normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def normalize_payload_for_fingerprint(payload_data: dict | list | object):
    """Return a stable business-payload representation for change detection.

    National IDs are reduced first (``redact_payload_national_ids``, PII
    slice 1a), on whichever side is compared: a stored payload from before
    the reduction (full ``Id10073``) and an incoming one (reduced, or full
    from ODK) normalise alike, so the reduction never reads as a change and
    never releases coding or writes an upstream-change row. A change in the
    masked digits of a full number is, by design, not a change: they are
    never stored.
    """
    return _normalize_for_fingerprint(redact_payload_national_ids(payload_data)[0])


def _normalize_for_fingerprint(payload_data):
    if isinstance(payload_data, dict):
        return {
            key: _normalize_for_fingerprint(value)
            for key, value in payload_data.items()
            if key not in VOLATILE_PAYLOAD_KEYS
        }

    if isinstance(payload_data, list):
        return [_normalize_for_fingerprint(item) for item in payload_data]

    return _normalize_scalar(payload_data)


def canonical_payload_fingerprint(payload_data: dict) -> str:
    """Return a stable hash for full canonical normalized payload JSON."""
    canonical_json = json.dumps(
        normalize_payload_for_fingerprint(payload_data or {}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


_REQUIRED_METADATA_KEYS = (
    "FormVersion",
    "DeviceID",
    "SubmitterID",
    "instanceID",
    "AttachmentsExpected",
    "AttachmentsPresent",
)


def _derive_payload_metadata(payload_data: dict) -> tuple[bool, int | None]:
    """Return (has_required_metadata, attachments_expected) for a payload dict.

    has_required_metadata — True iff all six sync-completeness keys are present
    with non-None values in payload_data.

    attachments_expected — integer value of AttachmentsExpected, or None if
    absent, empty, or non-numeric.
    """
    has_meta = all(payload_data.get(k) is not None for k in _REQUIRED_METADATA_KEYS)
    raw = payload_data.get("AttachmentsExpected")
    att_expected: int | None = None
    if raw is not None:
        try:
            stripped = str(raw).strip()
            att_expected = int(stripped) if stripped else None
        except (ValueError, TypeError):
            att_expected = None
    return has_meta, att_expected


# --- The payload PII split (PII slice 1b part II-A) ---------------------------
# docs/kb/pii-slice-1b.md. Behind PAYLOAD_PII_SPLIT_ENABLED: off, every helper
# below is the code it replaced, except that it refuses a version that has a
# side row (PayloadSplitStateError). On, the sealed set leaves payload_data
# for map_payload_version_pii and every comparison uses version_fingerprint on
# both sides. The split modules import this one, so they are imported inside
# the helpers.

_REQUEST_CACHE_ATTR = "_payload_pii_request_cache"


class PayloadSplitStateError(RuntimeError):
    """A payload version holds sealed fields in ``map_payload_version_pii``
    but this process runs with ``PAYLOAD_PII_SPLIT_ENABLED`` off: reading or
    writing it by the old rule would drop or re-expose the sealed fields, or
    read as a change and release coding. Internal; names no value."""


def _split_enabled() -> bool:
    from app.services.payload_pii_accessor import split_enabled

    return split_enabled()


def _request_cache() -> dict:
    """Per app context (a request, a Celery task): the sealed set per form
    and whether any side row exists. Built from the mapping service, and
    dropped when its ``generation`` moves (``clear_cache`` after an admin
    ``is_pii`` change in this process). Another process's change is seen
    from its next request or task; comparisons stay correct meanwhile
    because a stored side row carries its own set (``comparison_ids``)."""
    from flask import g

    from app.services.field_mapping_service import get_mapping_service

    generation = get_mapping_service().generation
    cache = g.get(_REQUEST_CACHE_ATTR)
    if cache is None or cache["generation"] != generation:
        cache = {"generation": generation, "sealed": {}}
        setattr(g, _REQUEST_CACHE_ATTR, cache)
    return cache


def clear_payload_pii_request_cache() -> None:
    """Drop the per-app-context cache (tests share one app context)."""
    from flask import g

    g.pop(_REQUEST_CACHE_ATTR, None)


def note_side_row_written() -> None:
    """Called by ``put_pii``: side rows exist from now on in this context."""
    _request_cache()["side_rows_exist"] = True


def _refuse_split_version_with_flag_off(version: VaSubmissionPayloadVersion) -> None:
    """Flag off: raise ``PayloadSplitStateError`` when *version* has a side
    row. One ``EXISTS`` on the side table per app context (empty until the
    release window), then a primary-key lookup only while it holds rows."""
    if version.payload_version_id is None:
        return
    from app.models import MapPayloadVersionPii
    from app.services.payload_pii_accessor import get_side_row

    cache = _request_cache()
    if "side_rows_exist" not in cache:
        cache["side_rows_exist"] = bool(db.session.scalar(sa.select(sa.exists().select_from(MapPayloadVersionPii))))
    if cache["side_rows_exist"] and get_side_row(version) is not None:
        raise PayloadSplitStateError(
            "A payload version has sealed fields in map_payload_version_pii but PAYLOAD_PII_SPLIT_ENABLED "
            "is off in this process; refusing to read or write it. Set the flag (and restart), or finish "
            "`flask pii split-payloads --restore` with every writer paused."
        )


def sealed_ids_for_sid(va_sid: str, *, session=None) -> frozenset[str]:
    """The sealed set (OD9) of the submission's form type, resolved once per
    form per app context (``_request_cache``): a sync loop pays the mapping
    service's version check once per form, not per submission."""
    from app.services.pii_field_registry import sealed_field_ids
    from app.utils.va_form.va_form_02_formtyperesolution import va_get_form_type_code_for_form

    submission = (session or db.session).get(VaSubmissions, va_sid)
    form_id = submission.va_form_id if submission else None
    by_form = _request_cache()["sealed"]
    if form_id not in by_form:
        by_form[form_id] = sealed_field_ids(va_get_form_type_code_for_form(form_id))
    return by_form[form_id]


def payload_matches(version: VaSubmissionPayloadVersion, payload_data: dict) -> bool:
    """True when the stored *version* carries the same content as the full
    *payload_data*: the one "same payload?" decision of the sync, the version
    service and web intake. Flag on: ``same_content`` (both sides split on
    the side row's own sealed set, or today's for a version not yet split;
    no decrypt); never stripped against unstripped. Flag off: the old rule,
    refused for a split version."""
    if not _split_enabled():
        _refuse_split_version_with_flag_off(version)
        return canonical_payload_fingerprint(version.payload_data or {}) == canonical_payload_fingerprint(
            payload_data or {}
        )
    from app.services.payload_pii_accessor import get_side_row
    from app.services.payload_pii_split import same_content

    return same_content(payload_data, version, get_side_row(version), sealed_ids_for_sid(version.va_sid))


def write_payload_version(
    version: VaSubmissionPayloadVersion, payload_data: dict, *, new: bool = False, session=None
) -> None:
    """Store the full *payload_data* on *version*: the only code that writes
    ``payload_data`` and the side row together.

    Flag off: ``payload_data`` as given; a *new* version also gets its
    ``canonical_payload_fingerprint`` (an update in place keeps its column,
    as before); a version with a side row is refused
    (``PayloadSplitStateError``). Flag on: the stripped payload, the sealed
    set through ``put_pii`` (a fresh DEK, an unflushed version is added and
    flushed first), and ``payload_fingerprint`` = ``version_fingerprint``.
    When the side row already holds the same digest under the same sealed
    set and blind key (``side_row_current``: an unchanged sync rerun), the
    row is kept as it is: no DEK, no KEM wrap, no UPDATE, and the section
    cache is dropped only if the stripped payload itself changed. The caller
    passes the FULL payload: a sealed field it leaves out is gone from the
    side row (``put_pii`` replaces it), so a writer holding a stripped copy
    joins the opened PII back first. *session*: a dedicated session the
    version lives in (the demo reset; its rows are new, so no cache entry
    exists), else ``db.session``."""
    if not _split_enabled():
        if not new:
            _refuse_split_version_with_flag_off(version)
        version.payload_data = payload_data
        if new:
            version.payload_fingerprint = canonical_payload_fingerprint(payload_data)
        return
    from app.services.payload_pii_accessor import get_side_row, put_pii, side_row_current
    from app.services.payload_pii_split import split_payload, version_fingerprint

    sealed = sealed_ids_for_sid(version.va_sid, session=session)
    split = split_payload(payload_data, sealed)
    invalidate = session is None and version.version_status == PAYLOAD_VERSION_STATUS_ACTIVE
    existing = get_side_row(version, session=session) if version.payload_version_id is not None else None
    if side_row_current(existing, split, sealed):
        if invalidate and split.stripped != (version.payload_data or {}):
            from app.services.case_content_service import invalidate_section_data_cache

            invalidate_section_data_cache(version.va_sid)
        version.payload_data = split.stripped
        version.payload_fingerprint = split.fingerprint
        return
    version.payload_data = split.stripped
    version.payload_fingerprint = split.fingerprint
    if version.payload_version_id is None:
        (session or db.session).add(version)
        (session or db.session).flush()
    row = put_pii(
        version, split.pii, split.review_flags, sealed_ids=sealed, session=session, invalidate_cache=invalidate,
    )
    version.payload_fingerprint = version_fingerprint(split.stripped, row.pii_digest)


def opened_payload(version: VaSubmissionPayloadVersion | None) -> dict:
    """The full stored payload of *version* (``{}`` for None): flag on, the
    sealed fields opened and joined back (a revision's carry needs ABHA and
    the identity answers). Flag off, a split version is refused (its
    ``payload_data`` alone lacks the sealed fields). Server side only;
    callers authorize first."""
    if version is None:
        return {}
    if not _split_enabled():
        _refuse_split_version_with_flag_off(version)
        return version.payload_data or {}
    from app.services.payload_pii_accessor import get_full_payload

    return get_full_payload(version)


def joined_payload(version: VaSubmissionPayloadVersion) -> dict | None:
    """The payload of *version* for a reader that needs the sealed fields
    (coding screens, category visibility, DORIS prefill, the upstream-accept
    projection): flag on, ``payload_data`` with the sealed fields opened and
    joined back (``get_full_payload``); flag off, ``payload_data`` exactly as
    stored (today's behaviour; writers, not readers, refuse a split version
    in a process with the flag off). Server side only; the caller decides
    whether the viewer may see PII (``case_content_service.
    viewer_source_payload``) and never logs the result."""
    if not _split_enabled():
        return version.payload_data
    from app.services.payload_pii_accessor import get_full_payload

    return get_full_payload(version)


def payload_copy(va_sid: str, payload_data: dict | None) -> dict:
    """*payload_data* as a copy may store it (upstream-change rows): national
    IDs reduced and, flag on, the sealed set stripped. A plaintext sealed
    value never lands in a copy."""
    reduced = redact_payload_national_ids(payload_data or {})[0]
    if not _split_enabled():
        return reduced
    sealed = sealed_ids_for_sid(va_sid)
    return {key: value for key, value in reduced.items() if key not in sealed}


def version_pii_digest(version: VaSubmissionPayloadVersion | None) -> str | None:
    """The keyed digest of the sealed fields of *version*: the side row's, or
    computed from a not yet split payload. None for None. No decrypt."""
    if version is None:
        return None
    from app.services.payload_pii_accessor import get_side_row
    from app.services.payload_pii_split import split_payload

    row = get_side_row(version)
    if row is not None:
        return row.pii_digest
    return split_payload(version.payload_data, sealed_ids_for_sid(version.va_sid)).pii_digest


def stored_payload_fingerprint(version: VaSubmissionPayloadVersion, payload_data: dict) -> str:
    """The ``payload_fingerprint`` for *payload_data* rewritten in place on
    *version* without touching its sealed set (the national-ID sweep): flag
    off the old rule, refused for a split version (an old-rule fingerprint
    there would read as a change); on ``stored_fingerprint`` with the side
    row's digest."""
    if not _split_enabled():
        _refuse_split_version_with_flag_off(version)
        return canonical_payload_fingerprint(payload_data)
    from app.services.payload_pii_accessor import get_side_row
    from app.services.payload_pii_split import stored_fingerprint

    return stored_fingerprint(payload_data, get_side_row(version), sealed_ids_for_sid(version.va_sid))


def get_active_payload_version(va_sid: str) -> VaSubmissionPayloadVersion | None:
    return db.session.scalar(
        sa.select(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid,
            VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
        )
    )


def get_latest_pending_upstream_payload_version(
    va_sid: str,
) -> VaSubmissionPayloadVersion | None:
    return db.session.scalar(
        sa.select(VaSubmissionPayloadVersion)
        .where(
            VaSubmissionPayloadVersion.va_sid == va_sid,
            VaSubmissionPayloadVersion.version_status
            == PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
        )
        .order_by(VaSubmissionPayloadVersion.version_created_at.desc())
    )


def get_payload_version(
    payload_version_id,
) -> VaSubmissionPayloadVersion | None:
    if payload_version_id is None:
        return None
    return db.session.get(VaSubmissionPayloadVersion, payload_version_id)


def ensure_active_payload_version(
    submission: VaSubmissions,
    *,
    payload_data: dict,
    source_updated_at=None,
    created_by_role: str = "vasystem",
    created_by=None,
    validation_err: list[dict] | None = None,
    revision_reason_code: str | None = None,
    answers_sha256: str | None = None,
) -> VaSubmissionPayloadVersion:
    """Ensure a submission has an active payload version matching payload_data.

    ``revision_reason_code`` and ``answers_sha256`` (interviewer revisions,
    web intake) are recorded only on a version created here; an equal-payload
    update in place keeps the version's own.

    ``validation_err`` (beads digitva-cal.2) is per-version, not merged with
    whatever a previous version recorded: a resubmission gets its own
    disagreement record for the answers it actually carries.

    National IDs in ``payload_data`` are reduced before it is stored
    (``redact_payload_national_ids``): every payload write goes through here,
    ``create_or_update_pending_upstream_payload_version`` or
    ``_bootstrap_active_payload_version``, and each stores it through
    ``write_payload_version`` in both its "new" and "unchanged" branches.
    """
    payload_data = redact_payload_national_ids(payload_data)[0]
    active = get_active_payload_version(submission.va_sid)
    has_meta, att_expected = _derive_payload_metadata(payload_data)
    validation_err = validation_err or []

    if active and payload_matches(active, payload_data):
        if submission.active_payload_version_id != active.payload_version_id:
            submission.active_payload_version_id = active.payload_version_id
        write_payload_version(active, payload_data)
        active.has_required_metadata = has_meta
        active.attachments_expected = att_expected
        active.validation_err = validation_err
        if source_updated_at is not None:
            active.source_updated_at = source_updated_at
        return active

    if active is None and submission.active_payload_version_id is not None:
        active = db.session.get(
            VaSubmissionPayloadVersion, submission.active_payload_version_id
        )
        if active and payload_matches(active, payload_data):
            write_payload_version(active, payload_data)
            active.has_required_metadata = has_meta
            active.attachments_expected = att_expected
            active.validation_err = validation_err
            if source_updated_at is not None:
                active.source_updated_at = source_updated_at
            return active

    now = datetime.now(timezone.utc)
    if active is not None:
        active.version_status = PAYLOAD_VERSION_STATUS_SUPERSEDED
        active.superseded_at = now

    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
        version_activated_at=now,
        has_required_metadata=has_meta,
        attachments_expected=att_expected,
        validation_err=validation_err,
        revision_reason_code=revision_reason_code,
        answers_sha256=answers_sha256,
    )
    write_payload_version(version, payload_data, new=True)
    db.session.add(version)
    db.session.flush()
    submission.active_payload_version_id = version.payload_version_id
    return version


def create_or_update_pending_upstream_payload_version(
    submission: VaSubmissions,
    *,
    payload_data: dict,
    source_updated_at=None,
    created_by_role: str = "vasystem",
    created_by=None,
) -> VaSubmissionPayloadVersion:
    """Create or update the pending upstream payload version for a protected submission."""
    payload_data = redact_payload_national_ids(payload_data)[0]
    pending = get_latest_pending_upstream_payload_version(submission.va_sid)
    if pending and payload_matches(pending, payload_data):
        write_payload_version(pending, payload_data)
        pending.source_updated_at = source_updated_at
        return pending

    now = datetime.now(timezone.utc)
    if pending is not None:
        pending.version_status = PAYLOAD_VERSION_STATUS_REJECTED
        pending.rejected_at = now
        pending.rejected_reason = "superseded_by_newer_pending_upstream_payload"

    has_meta, att_expected = _derive_payload_metadata(payload_data)
    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        version_status=PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
        has_required_metadata=has_meta,
        attachments_expected=att_expected,
    )
    write_payload_version(version, payload_data, new=True)
    db.session.add(version)
    db.session.flush()
    return version


def promote_pending_upstream_payload_version(
    submission: VaSubmissions,
    pending_version: VaSubmissionPayloadVersion,
) -> VaSubmissionPayloadVersion:
    """Promote a pending upstream payload version to active."""
    if pending_version.version_status != PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM:
        raise ValueError("Payload version is not pending_upstream.")

    now = datetime.now(timezone.utc)
    active = get_active_payload_version(submission.va_sid)
    if active is not None and active.payload_version_id != pending_version.payload_version_id:
        active.version_status = PAYLOAD_VERSION_STATUS_SUPERSEDED
        active.superseded_at = now
        db.session.flush()

    pending_version.version_status = PAYLOAD_VERSION_STATUS_ACTIVE
    pending_version.version_activated_at = now
    pending_version.rejected_at = None
    pending_version.rejected_reason = None
    submission.active_payload_version_id = pending_version.payload_version_id
    return pending_version


def reject_pending_upstream_payload_version(
    pending_version: VaSubmissionPayloadVersion,
    *,
    reason: str,
) -> VaSubmissionPayloadVersion:
    """Mark a pending upstream payload version as rejected."""
    if pending_version.version_status != PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM:
        raise ValueError("Payload version is not pending_upstream.")

    pending_version.version_status = PAYLOAD_VERSION_STATUS_REJECTED
    pending_version.rejected_at = datetime.now(timezone.utc)
    pending_version.rejected_reason = reason
    return pending_version


def _bootstrap_active_payload_version(
    submission: VaSubmissions,
    *,
    payload_data: dict,
    source_updated_at=None,
    created_by_role: str,
    created_by,
) -> VaSubmissionPayloadVersion:
    payload_data = redact_payload_national_ids(payload_data)[0]
    now = datetime.now(timezone.utc)
    has_meta, att_expected = _derive_payload_metadata(payload_data)
    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
        version_activated_at=now,
        has_required_metadata=has_meta,
        attachments_expected=att_expected,
    )
    write_payload_version(version, payload_data, new=True)
    db.session.add(version)
    db.session.flush()
    submission.active_payload_version_id = version.payload_version_id
    return version
