import os
from collections import OrderedDict
from flask import url_for, current_app
from app.utils.va_render.va_render_05_mapchoicevalue import va_render_mapchoicevalue
from app.utils.va_render.va_render_02_standardizedate import va_render_standardizedate
from app.utils.va_render.va_render_04_cleannumericvalue import va_render_cleannumericvalue
from app.utils.va_render.va_render_03_formatdatetimeindian import va_render_formatdatetimeindian


va_dealwithdates = ["Id10021", "Id10023", "Id10024", "Id10012", "Id10071"]
va_dealwithdatetimes = ["Id10011", "Id10481"]
va_zeroskipfields = ["isNeonatal", "isChild", "isAdult"]
va_skipvalues = ["ref", "dk"]
va_isattachment = ["Id10476_audio", "imagenarr", "md_im1", "md_im2", "md_im3", "md_im4", "md_im5", "md_im6",
                   "md_im7", "md_im8", "md_im9", "md_im10", "md_im11", "md_im12", "md_im13", "md_im14",
                   "md_im15", "md_im16", "md_im17", "md_im18", "md_im19", "md_im20", "md_im21", "md_im22",
                   "md_im23", "md_im24", "md_im25", "md_im26", "md_im27", "md_im28", "md_im29", "md_im30",
                   "ds_im1", "ds_im2", "ds_im3", "ds_im4", "ds_im5"]
va_multipleselect = ["Id10173_nc", "Id10199", "Id10235", "Id10477", "Id10478", "Id10479"]


def _normalize_attachment_filename(filename: str) -> str:
    """Normalize filename for cache key use. Case-insensitive .amr → .mp3."""
    if filename.lower().endswith(".amr"):
        return filename[: -len(".amr")] + ".mp3"
    return filename


def _prefetch_attachment_urls(va_sid: str) -> None:
    """Load all storage_names for a va_sid in one query and warm the att_name cache.

    Reduces per-render DB queries for attachments from O(fields) to O(1).
    Called once at the top of va_render_processcategorydata when va_sid is known.
    """
    import sqlalchemy as sa
    from app import db, cache as flask_cache
    from app.models.va_submission_attachments import VaSubmissionAttachments

    rows = db.session.execute(
        sa.select(VaSubmissionAttachments.filename, VaSubmissionAttachments.storage_name)
        .where(VaSubmissionAttachments.va_sid == va_sid)
        .where(VaSubmissionAttachments.exists_on_odk == True)  # noqa: E712
        .where(VaSubmissionAttachments.storage_name.is_not(None))
    ).all()
    for filename, storage_name in rows:
        key = f"att_name:{va_sid}:{_normalize_attachment_filename(filename)}"
        flask_cache.set(key, storage_name, timeout=300)


def _resolve_attachment_url(
    va_sid: str,
    va_form_id: str,
    original_filename: str,
) -> str | None:
    """Resolve attachment filename to a /attachment/{storage_name} URL.

    Lookup order: Redis cache → DB.
    Falls back to the legacy /media/{form_id}/{filename} route for older
    rows that predate storage_name backfill.
    """
    import sqlalchemy as sa
    from app import db, cache as flask_cache
    from app.models.va_submission_attachments import VaSubmissionAttachments

    lookup_name = _normalize_attachment_filename(original_filename)
    cache_key = f"att_name:{va_sid}:{lookup_name}"

    storage_name = flask_cache.get(cache_key)
    if storage_name is None:
        attachment_row = db.session.execute(
            sa.select(
                VaSubmissionAttachments.storage_name,
                VaSubmissionAttachments.local_path,
            )
            .where(VaSubmissionAttachments.va_sid == va_sid)
            .where(VaSubmissionAttachments.filename == original_filename)
            .where(VaSubmissionAttachments.exists_on_odk == True)  # noqa: E712
        ).one_or_none()
        if attachment_row is None:
            return None
        storage_name, local_path = attachment_row
        if storage_name is not None:
            flask_cache.set(cache_key, storage_name, timeout=300)
        elif not local_path:
            return None

    if storage_name is not None:
        return url_for("va_form.serve_attachment", storage_name_raw=storage_name)

    return url_for(
        "va_form.serve_media",
        va_form_id=va_form_id,
        va_filename=original_filename,
    )


def _choice_lookup_key_candidates(value):
    """Return candidate choice keys for values that may arrive as numeric JSON."""
    cleaned = va_render_cleannumericvalue(value)
    candidates = []
    for candidate in (value, cleaned):
        text = str(candidate)
        if text not in candidates:
            candidates.append(text)
    return candidates


def va_render_processcategorydata(
    va_data, va_form_id, va_datalevel, va_mapping_choice, va_partial, *, va_sid=None
):
    """Render a category's field data into a display dict.

    va_sid: when provided, attachment fields are resolved to /attachment/ URLs
    via the DB/cache. When None (visibility-check contexts), falls back to
    disk-existence check and returns a truthy sentinel — callers must not
    render the returned values in that case.
    """
    if not va_data:
        return {}
    category_mapping = va_datalevel.get(va_partial)
    if not category_mapping:
        return {}

    # Bulk-prefetch all attachment storage_names for this submission in one query.
    # This warms the att_name cache so _resolve_attachment_url always hits cache.
    if va_sid is not None:
        _prefetch_attachment_urls(va_sid)

    va_categoryresult = {}
    for va_subcat, va_fieldmap in category_mapping.items():
        va_subcatresult = OrderedDict()
        for va_fieldid, va_label in va_fieldmap.items():
            if va_fieldid in va_data and va_data.get(va_fieldid) is not None:
                value = va_data.get(va_fieldid)
                if (isinstance(value, str) and value.lower() in va_skipvalues) or (
                    va_fieldid in va_zeroskipfields
                    and (value == 0 or value == "0" or value == "0.0")
                ):
                    continue
                if va_fieldid in va_dealwithdates:
                    value = va_render_standardizedate(value)
                if va_fieldid in va_dealwithdatetimes:
                    value = va_render_formatdatetimeindian(value)
                if va_fieldid in va_mapping_choice:
                    choice_map = va_mapping_choice[va_fieldid]
                    for candidate in _choice_lookup_key_candidates(value):
                        if candidate in choice_map:
                            value = choice_map[candidate]
                            break
                if va_fieldid in va_zeroskipfields and (
                    value == 1 or value == "1" or value == "1.0"
                ):
                    value = "True"
                if va_fieldid in va_multipleselect:
                    value = va_render_mapchoicevalue(
                        va_fieldid, value, va_mapping_choice
                    )
                if va_fieldid in va_isattachment:
                    if va_sid is not None:
                        url = _resolve_attachment_url(va_sid, va_form_id, value)
                        if url:
                            value = url
                        else:
                            continue
                    else:
                        # Visibility-check context (va_sid=None).
                        # Do NOT assign disk path to value — callers may render it.
                        # Use a sentinel: truthy but never a real URL or path.
                        # IMPORTANT: callers using va_sid=None only check non-empty
                        # dict for category visibility — they never render values.
                        if value.lower().endswith(".amr"):
                            value = value[: -len(".amr")] + ".mp3"
                        disk_path = os.path.join(
                            current_app.config["APP_DATA"], va_form_id, "media", value
                        )
                        if not os.path.exists(disk_path):
                            continue
                        value = "__attachment_present__"
                value = va_render_cleannumericvalue(value)
                va_subcatresult[va_label] = value
        if va_subcatresult:
            va_categoryresult[va_subcat] = va_subcatresult
    return va_categoryresult
