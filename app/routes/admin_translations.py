"""Admin JSON API and panel for instrument display translations.

Thin HTTP layer over ``app.services.instrument_translation_service``; every
rule -- what an edit may touch, what an import writes -- lives there. Routes
hang off the ``admin`` blueprint
(``/admin/api/instrument-translations/...``) the same way
``app/routes/admin_organization.py`` and ``app/routes/admin_icd11.py`` do.

API first (decided 2026-09-19): every route here returns JSON and the panel is
a JavaScript client of them. The panel template receives no state through
template context beyond the instrument code it defaults to.

Plan: docs/planning/web-capture-project-configuration-plan.md (WP6).
"""

import logging
import tempfile
from pathlib import Path

from flask import Response, jsonify, render_template, request
from flask_login import current_user
from werkzeug.utils import secure_filename

from app import db
from app.decorators import role_required
from app.models.mas_instrument_locales import SOURCE_EDITED, SOURCE_IMPORTED
from app.routes.admin import _json_error, admin
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    MAX_STRING_PAGE_SIZE,
    XLIFF_EXTENSIONS,
    XLIFF_MEDIA_TYPE,
    InstrumentTranslationError,
    accept_machine_translation,
    export_translations,
    export_xliff,
    import_translations,
    import_xliff,
    list_strings,
    locale_status,
    set_locale_active,
    set_locale_lifecycle_state,
    update_string,
    xliff_filename,
)

log = logging.getLogger(__name__)

_API = "/api/instrument-translations"

#: Upload ceiling. The largest committed source workbook is under 300 KB, so
#: 5 MB is generous; the point is that an unbounded upload is never read into
#: memory or written to disk.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Read the upload in chunks so the cap is enforced before the file exists.
_UPLOAD_CHUNK = 64 * 1024


def _guard():
    """Admin only, checked again in the body as the ICD-11 panel routes do."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return None


def _instrument(raw: str | None) -> str:
    return (raw or BASE_INSTRUMENT_CODE).strip().upper()


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


@admin.get("/panels/instrument-translations")
@role_required("admin")
def admin_panel_instrument_translations():
    return render_template(
        "admin/panels/instrument_translations.html",
        instrument_code=_instrument(request.args.get("instrument_code")),
    )


# ---------------------------------------------------------------------------
# Locales
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/locales")
@role_required("admin")
def admin_instrument_translation_locales():
    if err := _guard():
        return err
    instrument_code = _instrument(request.args.get("instrument_code"))
    try:
        rows = locale_status(instrument_code)
    except InstrumentTranslationError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"instrument_code": instrument_code, "locales": rows})


@admin.post(f"{_API}/<instrument_code>/<locale>/import")
@role_required("admin")
def admin_instrument_translation_import(instrument_code, locale):
    if err := _guard():
        return err
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return _json_error("Upload the source workbook as 'file'.", 400)
    name = secure_filename(uploaded.filename)
    if not name.lower().endswith(".xlsx"):
        return _json_error("Only .xlsx workbooks are accepted.", 400)

    cross_check = request.form.get("cross_check") == "1"
    language_name = (request.form.get("language_name") or "").strip() or None
    acknowledge_demotion = request.form.get("acknowledge_demotion") == "1"

    with tempfile.TemporaryDirectory() as tmpdir:
        # The upload keeps its own (sanitised) name inside a private,
        # process-temp directory -- one of the two roots import_translations'
        # path containment allows a workbook to be read from.
        path = Path(tmpdir) / name
        written = 0
        with path.open("wb") as handle:
            while chunk := uploaded.stream.read(_UPLOAD_CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    return _json_error(
                        f"The workbook is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                        400,
                    )
                handle.write(chunk)
        try:
            report = import_translations(
                instrument_code,
                locale,
                path,
                cross_check=cross_check,
                actor_id=current_user.user_id,
                language_name=language_name,
                acknowledge_demotion=acknowledge_demotion,
            )
        except InstrumentTranslationError as exc:
            db.session.rollback()
            return _json_error(str(exc), 400)
        except Exception:  # malformed workbook
            db.session.rollback()
            log.exception(
                "instrument translation import failed | %s/%s", instrument_code, locale
            )
            return _json_error("The workbook could not be read.", 400)

    if cross_check:
        db.session.rollback()
    else:
        db.session.commit()
    return jsonify({"report": report.as_dict()})


@admin.post(f"{_API}/<instrument_code>/<locale>/activate")
@role_required("admin")
def admin_instrument_translation_activate(instrument_code, locale):
    return _set_active(instrument_code, locale, True)


@admin.post(f"{_API}/<instrument_code>/<locale>/deactivate")
@role_required("admin")
def admin_instrument_translation_deactivate(instrument_code, locale):
    return _set_active(instrument_code, locale, False)


def _set_active(instrument_code, locale, active):
    if err := _guard():
        return err
    try:
        result = set_locale_active(
            instrument_code, locale, active, actor_id=current_user.user_id,
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(result)


@admin.post(f"{_API}/<instrument_code>/<locale>/lifecycle")
@role_required("admin")
def admin_instrument_translation_lifecycle(instrument_code, locale):
    """Move a locale between draft, in_review and approved."""
    if err := _guard():
        return err
    payload = request.get_json(silent=True) or {}
    state = (payload.get("state") or "").strip()
    if not state:
        return _json_error("state is required.", 400)
    try:
        result = set_locale_lifecycle_state(
            instrument_code, locale, state, actor_id=current_user.user_id,
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(result)


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/<instrument_code>/<locale>/strings")
@role_required("admin")
def admin_instrument_translation_strings(instrument_code, locale):
    if err := _guard():
        return err
    try:
        page = int(request.args.get("page") or 1)
        page_size = int(request.args.get("page_size") or 50)
    except ValueError:
        return _json_error("page and page_size must be whole numbers.", 400)
    try:
        return jsonify(
            list_strings(
                instrument_code,
                locale,
                search=request.args.get("q"),
                page=page,
                # Clamped again in the service; the ceiling is never the
                # caller's to choose.
                page_size=min(page_size, MAX_STRING_PAGE_SIZE),
            )
        )
    except InstrumentTranslationError as exc:
        return _json_error(str(exc), 400)


@admin.put(f"{_API}/<instrument_code>/<locale>/strings")
@role_required("admin")
def admin_instrument_translation_put_string(instrument_code, locale):
    if err := _guard():
        return err
    payload = request.get_json(silent=True) or {}
    fields = {
        key: payload.get(key) for key in ("item_kind", "item_key", "field", "text")
    }
    for key, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            return _json_error(f"{key} is required.", 400)
    try:
        result = update_string(
            instrument_code,
            locale,
            item_kind=fields["item_kind"],
            item_key=fields["item_key"],
            field=fields["field"],
            text=fields["text"],
            actor_id=current_user.user_id,
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(result)


@admin.post(f"{_API}/<instrument_code>/<locale>/strings/accept")
@role_required("admin")
def admin_instrument_translation_accept_string(instrument_code, locale):
    """Promote one machine-translated string to 'edited' without retyping it."""
    if err := _guard():
        return err
    payload = request.get_json(silent=True) or {}
    fields = {key: payload.get(key) for key in ("item_kind", "item_key", "field")}
    for key, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            return _json_error(f"{key} is required.", 400)
    try:
        result = accept_machine_translation(
            instrument_code,
            locale,
            item_kind=fields["item_kind"],
            item_key=fields["item_key"],
            field=fields["field"],
            actor_id=current_user.user_id,
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(result)


# ---------------------------------------------------------------------------
# XLIFF 2.0 interchange
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/<instrument_code>/<locale>/xliff")
@role_required("admin")
def admin_instrument_translation_export_xliff(instrument_code, locale):
    """One locale as an XLIFF 2.0 document, for a translator's CAT tool."""
    if err := _guard():
        return err
    try:
        document = export_xliff(instrument_code, locale)
    except InstrumentTranslationError as exc:
        return _json_error(str(exc), 404)
    response = Response(document, mimetype=XLIFF_MEDIA_TYPE)
    # The name is built from a sanitised code and locale, never from input
    # that reaches the header as written.
    response.headers["Content-Disposition"] = (
        f"attachment; filename={xliff_filename(instrument_code, locale)}"
    )
    return response


@admin.post(f"{_API}/<instrument_code>/<locale>/xliff")
@role_required("admin")
def admin_instrument_translation_import_xliff(instrument_code, locale):
    """Write the targets of an uploaded XLIFF 2.0 document back into a locale."""
    if err := _guard():
        return err
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return _json_error("Upload the XLIFF document as 'file'.", 400)
    name = secure_filename(uploaded.filename)
    if not name.lower().endswith(XLIFF_EXTENSIONS):
        return _json_error(
            f"Only {' and '.join(XLIFF_EXTENSIONS)} documents are accepted.", 400
        )
    mark_as = request.form.get("as") or SOURCE_IMPORTED
    if mark_as not in (SOURCE_IMPORTED, SOURCE_EDITED):
        return _json_error(
            f"'as' must be {SOURCE_IMPORTED!r} or {SOURCE_EDITED!r}.", 400
        )
    acknowledge_demotion = request.form.get("acknowledge_demotion") == "1"

    # Read under the cap before anything parses it, the same way the workbook
    # upload does: an unbounded document is never fully read into memory.
    chunks: list[bytes] = []
    size = 0
    while chunk := uploaded.stream.read(_UPLOAD_CHUNK):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            return _json_error(
                f"The document is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                400,
            )
        chunks.append(chunk)
    try:
        document = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        return _json_error("The document is not UTF-8 text.", 400)

    try:
        report = import_xliff(
            instrument_code,
            locale,
            document,
            actor_id=current_user.user_id,
            mark_as=mark_as,
            acknowledge_demotion=acknowledge_demotion,
        )
    except InstrumentTranslationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    except Exception:  # malformed document the parser accepted but we cannot use
        db.session.rollback()
        log.exception(
            "instrument translation xliff import failed | %s/%s", instrument_code, locale
        )
        return _json_error("The document could not be read.", 400)
    db.session.commit()
    return jsonify({"report": report})


@admin.get(f"{_API}/<instrument_code>/<locale>/export")
@role_required("admin")
def admin_instrument_translation_export(instrument_code, locale):
    if err := _guard():
        return err
    try:
        return jsonify(export_translations(instrument_code, locale))
    except InstrumentTranslationError as exc:
        return _json_error(str(exc), 404)
