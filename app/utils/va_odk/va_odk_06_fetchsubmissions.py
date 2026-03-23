"""Fetch submission data from ODK Central via OData JSON.

Replaces the CSV ZIP download for submission metadata. Returns normalized
flat dicts with the same field-name structure as the CSV groupPaths=false
export, so the rest of the pipeline (upsert, rendering, and SmartVA prep
from payload-version data) is unchanged.

Key normalizations:
  __id                    → KEY (CSV column name)
  __system.submissionDate → SubmissionDate
  __system.updatedAt      → updatedAt
  __system.submitterName  → SubmitterName
  __system.reviewState    → ReviewState
  meta.instanceName       → instanceName
  nested group fields     → flattened to leaf names (groupPaths=false)

Computed fields added to each record:
  form_def   = va_form.form_id
  sid        = f"{KEY}-{form_id.lower()}"   (matches existing sid scheme)
  unique_id2 = derived from unique_id + start timestamp
"""

import logging
from datetime import datetime, timezone

from app.services.odk_connection_guard_service import guarded_odk_call
from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

log = logging.getLogger(__name__)

_PAGE_SIZE = 250


def va_odk_fetch_instance_ids(va_form, client=None) -> list[str]:
    """Fetch all submission instance IDs from ODK Central (lightweight).

    Uses the REST submissions listing endpoint which returns all submissions
    in a single call with only metadata — no form data transferred.
    Returns a list of instance ID strings.
    """
    client = client or va_odk_clientsetup(project_id=va_form.project_id)
    url = (
        f"projects/{va_form.odk_project_id}"
        f"/forms/{va_form.odk_form_id}/submissions"
    )

    response = guarded_odk_call(
        lambda: client.session.get(url),
        client=client,
    )
    if response.status_code != 200:
        raise Exception(
            f"Submissions listing failed HTTP {response.status_code} "
            f"for {va_form.form_id}: {response.text[:200]}"
        )

    all_ids = [
        s["instanceId"]
        for s in response.json()
        if s.get("instanceId") and not s.get("deletedAt")
    ]

    log.info(
        "va_odk_fetch_instance_ids [%s]: %d ID(s) from ODK",
        va_form.form_id, len(all_ids),
    )
    return all_ids


def va_odk_fetch_submissions_by_ids(
    va_form,
    instance_ids: list[str],
    client=None,
    log_progress=None,
) -> list[dict]:
    """Fetch specific submissions by instance ID using OData single-entity access.

    Uses Submissions('{instanceId}') — one HTTP call per submission.
    Logs progress every 50 records.
    """
    if not instance_ids:
        return []

    client = client or va_odk_clientsetup(project_id=va_form.project_id)
    base_url = (
        f"projects/{va_form.odk_project_id}"
        f"/forms/{va_form.odk_form_id}.svc/Submissions"
    )

    all_records: list[dict] = []
    errors = 0

    for idx, iid in enumerate(instance_ids, 1):
        # OData single-entity: Submissions('uuid:...')
        url = f"{base_url}('{iid}')"
        try:
            response = guarded_odk_call(
                lambda: client.session.get(url),
                client=client,
            )
            if response.status_code != 200:
                log.warning(
                    "va_odk_fetch_submissions_by_ids [%s]: HTTP %d for %s",
                    va_form.form_id, response.status_code, iid,
                )
                errors += 1
                continue
            data = response.json()
            # Single-entity OData returns {"value": [record], ...}
            value = data.get("value", [data])
            records = value if isinstance(value, list) else [value]
            for record in records:
                all_records.append(_normalize_odata_record(record, va_form.form_id))
        except Exception as e:
            log.warning(
                "va_odk_fetch_submissions_by_ids [%s]: error fetching %s: %s",
                va_form.form_id, iid, e,
            )
            errors += 1

        if idx % 50 == 0:
            msg = (
                f"[{va_form.form_id}] gap fetch: {idx}/{len(instance_ids)} "
                f"({errors} errors)" if errors else
                f"[{va_form.form_id}] gap fetch: {idx}/{len(instance_ids)}"
            )
            log.info("va_odk_fetch_submissions_by_ids %s", msg)
            if log_progress:
                log_progress(msg)

    log.info(
        "va_odk_fetch_submissions_by_ids [%s]: done — %d fetched, %d errors of %d requested",
        va_form.form_id, len(all_records), errors, len(instance_ids),
    )
    return all_records


def va_odk_fetch_submissions(
    va_form,
    since: datetime | None = None,
    client=None,
) -> list[dict]:
    """Fetch submissions for a form via OData JSON.

    If `since` is a timezone-aware datetime, only submissions created or
    updated after that timestamp are returned (incremental sync).
    If `since` is None, all submissions are returned (first sync).

    Pages through results in batches of _PAGE_SIZE. Returns a list of
    normalized flat dicts ready for va_preprocess_prepdata / upsert.
    """
    client = client or va_odk_clientsetup(project_id=va_form.project_id)
    base_url = (
        f"projects/{va_form.odk_project_id}"
        f"/forms/{va_form.odk_form_id}.svc/Submissions"
    )

    params: dict = {"$top": _PAGE_SIZE}
    if since is not None:
        if since.tzinfo is None:
            raise ValueError("va_odk_fetch_submissions: `since` must be timezone-aware")
        since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        params["$filter"] = (
            f"(__system/submissionDate gt {since_str})"
            f" or (__system/updatedAt gt {since_str})"
        )
        log.info("va_odk_fetch_submissions [%s]: incremental since=%s", va_form.form_id, since_str)
    else:
        log.info("va_odk_fetch_submissions [%s]: full fetch (no since filter)", va_form.form_id)

    all_records: list[dict] = []
    skip = 0

    while True:
        params["$skip"] = skip
        response = guarded_odk_call(
            lambda: client.session.get(base_url, params=params),
            client=client,
        )
        if response.status_code != 200:
            raise Exception(
                f"OData submissions fetch failed HTTP {response.status_code} "
                f"for {va_form.form_id}: {response.text[:200]}"
            )
        data = response.json()
        page = data.get("value", [])
        if not page:
            break
        for record in page:
            all_records.append(_normalize_odata_record(record, va_form.form_id))
        log.info(
            "va_odk_fetch_submissions [%s]: page skip=%d got %d (running total: %d)",
            va_form.form_id, skip, len(page), len(all_records),
        )
        if len(page) < _PAGE_SIZE:
            break
        skip += _PAGE_SIZE

    log.info(
        "va_odk_fetch_submissions [%s]: fetched %d submission(s) total",
        va_form.form_id, len(all_records),
    )
    return all_records
def _normalize_odata_record(record: dict, form_id: str) -> dict:
    """Normalize an OData submission record to flat dict matching CSV groupPaths=false.

    System metadata (__system, meta) → CSV column equivalents.
    Nested group objects → flattened to leaf-name keys only.
    Computed fields (sid, form_def, unique_id2) added inline.
    """
    out: dict = {}

    system = record.get("__system") or {}
    meta = record.get("meta") or {}

    instance_id: str = record.get("__id", "")

    # CSV metadata column equivalents
    out["KEY"] = instance_id
    out["SubmissionDate"] = system.get("submissionDate")
    out["updatedAt"] = system.get("updatedAt")
    out["SubmitterName"] = system.get("submitterName")
    out["ReviewState"] = system.get("reviewState")
    out["instanceName"] = meta.get("instanceName")

    # Flatten all form fields — discard group nesting, keep leaf names
    _flatten_into(record, out, skip_keys={"__id", "__system", "meta"})

    # Computed fields (match va_preprocess_prepdata output)
    out["form_def"] = form_id
    out["sid"] = f"{instance_id}-{form_id.lower()}"

    # unique_id2 (same logic as va_preprocess_prepdata)
    if out.get("unique_id"):
        try:
            start_str = out.get("start")
            if start_str:
                start_dt = datetime.fromisoformat(str(start_str))
                out["unique_id2"] = (
                    str(out["unique_id"]).rsplit("_", 1)[0]
                    + "_"
                    + start_dt.strftime("%H%M%S")
                    + f"{int(start_dt.microsecond / 1000):03}"
                )
            else:
                out["unique_id2"] = "Unavailable"
        except Exception:
            out["unique_id2"] = "Unavailable"
    else:
        out["unique_id2"] = "Unavailable"

    return out


def _flatten_into(obj: dict, out: dict, skip_keys: set):
    """Recursively copy leaf values from `obj` into `out`, discarding group keys."""
    for k, v in obj.items():
        if k in skip_keys:
            continue
        if isinstance(v, dict):
            _flatten_into(v, out, skip_keys=set())
        else:
            out[k] = v  # None values preserved as-is
