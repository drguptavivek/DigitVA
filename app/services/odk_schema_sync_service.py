"""
ODK Schema Sync Service

Synchronizes field labels and choice mappings from ODK Central to the database.

Primary source: XLSForm XLSX download from ODK Central.
  - survey sheet → field names, types, and question labels
  - choices sheet → choice values and their display labels

Fallback source: GET /projects/{id}/forms/{id}/fields API
  (Note: this endpoint does not return select choices for all ODK versions)
"""
import uuid
import io
import time
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import select
from app import db
from app.models import (
    MasFormTypes,
    MasChoiceMappings,
    MasFieldDisplayConfig,
)
from app.services.odk_connection_guard_service import guarded_odk_call
from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _extract_label(label_value) -> str:
    """Extract a plain string from an ODK label value (string or locale dict)."""
    if isinstance(label_value, dict):
        return label_value.get("default") or label_value.get("en") or next(
            iter(label_value.values()), ""
        )
    return str(label_value) if label_value is not None else ""


def _str_val(val) -> str:
    """Convert a DataFrame cell to a stripped string; return '' for NaN/None."""
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    return str(val).strip()


def _find_label_col(df) -> str | None:
    """Return the first column whose name starts with 'label' (case-insensitive)."""
    for col in df.columns:
        if str(col).lower().startswith("label"):
            return col
    return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OdkSchemaSyncService:
    """
    Synchronizes field labels and choice mappings from ODK Central XLSForm files.

    For each field in the XLSForm survey sheet:
      - Updates odk_label on the MasFieldDisplayConfig row (if it exists in DB).
    For each choice in the XLSForm choices sheet:
      - Upserts MasChoiceMappings (add new, update changed labels, deactivate removed).
    """

    # -----------------------------------------------------------------------
    # Public: sync
    # -----------------------------------------------------------------------

    def sync_form_choices(
        self,
        form_type_code: str,
        odk_project_id: int,
        odk_form_id: str,
        client=None,
    ) -> dict:
        """
        Sync field labels, new fields, and choice mappings for a form from ODK Central.

        New ODK fields not yet in MasFieldDisplayConfig are auto-registered with
        their odk_label and field_type; all other display attributes are left blank
        for the admin to configure.

        Returns dict with sync statistics.
        """
        stats = {
            "fields_processed": 0,
            "fields_added": 0,
            "labels_updated": 0,
            "choices_added": 0,
            "choices_updated": 0,
            "errors": [],
        }

        _t0 = time.monotonic()
        print(f"[sync] START sync_form_choices  form={form_type_code}  project={odk_project_id}  form_id={odk_form_id}")

        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if not form_type:
            msg = f"Form type not found: {form_type_code}"
            print(f"[sync] ERROR {msg}")
            stats["errors"].append(msg)
            return stats

        try:
            if client is None:
                client = va_odk_clientsetup()

            _t_fetch = time.monotonic()
            print(f"[sync] fetching schema from ODK (xlsx)…")
            fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id)

            if fields is None:
                print(f"[sync] xlsx fetch returned None — falling back to fields API")
                fields = self._fetch_fields(client, odk_project_id, odk_form_id)

            if fields is None:
                msg = "Failed to fetch form schema from ODK. Check connection credentials and form ID."
                print(f"[sync] ERROR {msg}")
                stats["errors"].append(msg)
                return stats

            print(f"[sync] fetched {len(fields)} fields in {time.monotonic()-_t_fetch:.2f}s")

            seen_keys: set[tuple[str, str]] = set()
            processed_field_ids: set[str] = set()

            _t_loop = time.monotonic()
            for field in fields:
                field_name = field.get("name")
                field_type = field.get("type", "")
                odk_label = _extract_label(field.get("label"))

                # Register new fields that don't exist in DB yet
                matched = self._update_field_odk_label(
                    form_type.form_type_id, field_name, odk_label, stats
                )
                if matched:
                    stats["fields_processed"] += 1
                else:
                    print(f"[sync]   NEW field  {field_name!r}  type={field_type!r}  label={odk_label!r}")
                    self._register_new_field(
                        form_type.form_type_id, field_name, field_type, odk_label, stats
                    )

                # Choice processing only applies to select fields
                if not field_type.startswith("select"):
                    continue

                choices = field.get("choices") or []
                if not choices:
                    continue

                processed_field_ids.add(field_name)

                for order, choice in enumerate(choices, start=1):
                    choice_value = choice.get("name") or choice.get("value")
                    if not choice_value:
                        continue

                    choice_label = _extract_label(choice.get("label")) or str(choice_value)
                    key = (field_name, str(choice_value))
                    seen_keys.add(key)

                    self._upsert_choice(
                        form_type.form_type_id,
                        field_name,
                        str(choice_value),
                        choice_label,
                        order,
                        stats,
                    )

            print(f"[sync] field loop done in {time.monotonic()-_t_loop:.2f}s  "
                  f"processed={stats['fields_processed']}  new={stats['fields_added']}  "
                  f"label_updates={stats['labels_updated']}  "
                  f"choices_added={stats['choices_added']}  choices_updated={stats['choices_updated']}")

            # NOTE: deactivation is intentionally skipped here.
            # Choices are seeded from the WHO VA template (mapping_choices.xlsx)
            # which covers ALL sites. Any given ODK project form only contains
            # choices for its own site, so deactivating against a single
            # site's form would incorrectly remove other sites' choices.
            _t_commit = time.monotonic()
            db.session.commit()
            print(f"[sync] commit done in {time.monotonic()-_t_commit:.2f}s")

        except Exception as exc:
            db.session.rollback()
            print(f"[sync] ERROR (rolled back): {exc}")
            stats["errors"].append(str(exc))

        elapsed = time.monotonic() - _t0
        if stats["errors"]:
            print(f"[sync] DONE with {len(stats['errors'])} error(s) in {elapsed:.2f}s — {stats}")
        else:
            print(f"[sync] DONE OK in {elapsed:.2f}s — {stats}")
        return stats

    # -----------------------------------------------------------------------
    # Public: apply selected changes (no re-fetch from ODK)
    # -----------------------------------------------------------------------

    def sync_selected(self, form_type_code: str, selected: dict) -> dict:
        """
        Apply a user-selected subset of previewed changes to the database.

        `selected` dict keys (all optional):
          new_fields:       [{field_id, field_type, odk_label, choices:[{value,label}]}]
          label_changes:    [{field_id, new_label}]
          new_choices:      [{field_id, value, label}]
          updated_choices:  [{field_id, value, new_label}]
        """
        stats = {
            "fields_added": 0,
            "labels_updated": 0,
            "choices_added": 0,
            "choices_updated": 0,
            "errors": [],
        }

        _t0 = time.monotonic()
        n_new_fields   = len(selected.get("new_fields")      or [])
        n_label_chg    = len(selected.get("label_changes")   or [])
        n_new_choices  = len(selected.get("new_choices")     or [])
        n_upd_choices  = len(selected.get("updated_choices") or [])
        print(f"[sync:apply] START  form={form_type_code}  "
              f"new_fields={n_new_fields}  label_changes={n_label_chg}  "
              f"new_choices={n_new_choices}  updated_choices={n_upd_choices}")

        form_type = db.session.scalar(
            select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
        )
        if not form_type:
            msg = f"Form type not found: {form_type_code}"
            print(f"[sync:apply] ERROR {msg}")
            stats["errors"].append(msg)
            return stats

        try:
            ft_id = form_type.form_type_id
            now = datetime.now(timezone.utc)

            # ── New fields ────────────────────────────────────────────────────
            _t = time.monotonic()
            for f in selected.get("new_fields") or []:
                field_id = f.get("field_id")
                if not field_id:
                    continue
                # Skip if already registered (race condition guard)
                if db.session.scalar(
                    select(MasFieldDisplayConfig).where(
                        MasFieldDisplayConfig.form_type_id == ft_id,
                        MasFieldDisplayConfig.field_id == field_id,
                    )
                ):
                    print(f"[sync:apply]   SKIP new_field {field_id!r} — already in DB")
                    continue
                label = f.get("odk_label") or None
                n_choices = len(f.get("choices") or [])
                print(f"[sync:apply]   ADD field {field_id!r}  type={f.get('field_type')!r}  "
                      f"label={label!r}  choices={n_choices}")
                db.session.add(MasFieldDisplayConfig(
                    config_id=uuid.uuid4(),
                    form_type_id=ft_id,
                    field_id=field_id,
                    field_type=f.get("field_type") or None,
                    odk_label=label,
                    short_label=label,
                    full_label=label,
                    is_active=True,
                    is_custom=False,
                ))
                stats["fields_added"] += 1
                existing_choices = {
                    choice.choice_value: choice
                    for choice in db.session.scalars(
                        select(MasChoiceMappings).where(
                            MasChoiceMappings.form_type_id == ft_id,
                            MasChoiceMappings.field_id == field_id,
                        )
                    ).all()
                }
                # Also upsert choices that came with this new field
                for order, ch in enumerate((f.get("choices") or []), start=1):
                    cv = ch.get("value")
                    cl = ch.get("label") or str(cv)
                    if not cv:
                        continue
                    cv = str(cv)
                    existing_choice = existing_choices.get(cv)
                    if existing_choice:
                        existing_choice.choice_label = cl
                        existing_choice.display_order = order
                        existing_choice.is_active = True
                        existing_choice.synced_at = now
                        continue
                    db.session.add(MasChoiceMappings(
                        form_type_id=ft_id,
                        field_id=field_id,
                        choice_value=cv,
                        choice_label=cl,
                        display_order=order,
                        is_active=True,
                        synced_at=now,
                    ))
                    stats["choices_added"] += 1
            print(f"[sync:apply] new_fields done in {time.monotonic()-_t:.2f}s  "
                  f"added={stats['fields_added']}  choices_with_fields={stats['choices_added']}")

            # ── Label changes ─────────────────────────────────────────────────
            _t = time.monotonic()
            for lc in selected.get("label_changes") or []:
                field_id = lc.get("field_id")
                new_label = lc.get("new_label")
                if not field_id or not new_label:
                    continue
                cfg = db.session.scalar(
                    select(MasFieldDisplayConfig).where(
                        MasFieldDisplayConfig.form_type_id == ft_id,
                        MasFieldDisplayConfig.field_id == field_id,
                    )
                )
                if cfg and cfg.odk_label != new_label:
                    print(f"[sync:apply]   LABEL {field_id!r}  {cfg.odk_label!r} → {new_label!r}")
                    cfg.odk_label = new_label
                    stats["labels_updated"] += 1
            print(f"[sync:apply] label_changes done in {time.monotonic()-_t:.2f}s  "
                  f"updated={stats['labels_updated']}")

            # ── New choices ───────────────────────────────────────────────────
            # Field IDs being added in this same operation (choices already inserted above)
            new_field_ids = {f.get("field_id") for f in (selected.get("new_fields") or [])}

            _t = time.monotonic()
            choices_skipped_no_field = 0
            for nc in selected.get("new_choices") or []:
                field_id = nc.get("field_id")
                value = nc.get("value")
                label = nc.get("label") or str(value)
                if not field_id or not value:
                    continue
                if field_id in new_field_ids:
                    continue  # choices already inserted with the new field above
                # Guard: skip if the parent field config doesn't exist in DB
                field_exists = db.session.scalar(
                    select(MasFieldDisplayConfig).where(
                        MasFieldDisplayConfig.form_type_id == ft_id,
                        MasFieldDisplayConfig.field_id == field_id,
                    )
                )
                if not field_exists:
                    msg = (f"Skipped choice {field_id}/{value}: field not registered. "
                           f"Add the field first.")
                    print(f"[sync:apply]   WARN {msg}")
                    stats["errors"].append(msg)
                    choices_skipped_no_field += 1
                    continue
                existing = db.session.scalar(
                    select(MasChoiceMappings).where(
                        MasChoiceMappings.form_type_id == ft_id,
                        MasChoiceMappings.field_id == field_id,
                        MasChoiceMappings.choice_value == str(value),
                    )
                )
                if not existing:
                    print(f"[sync:apply]   ADD choice {field_id!r}/{value!r}  label={label!r}")
                    db.session.add(MasChoiceMappings(
                        form_type_id=ft_id,
                        field_id=field_id,
                        choice_value=str(value),
                        choice_label=label,
                        display_order=0,
                        is_active=True,
                        synced_at=now,
                    ))
                    stats["choices_added"] += 1
            print(f"[sync:apply] new_choices done in {time.monotonic()-_t:.2f}s  "
                  f"added={stats['choices_added']}  skipped_no_field={choices_skipped_no_field}")

            # ── Updated choices ───────────────────────────────────────────────
            _t = time.monotonic()
            for uc in selected.get("updated_choices") or []:
                field_id = uc.get("field_id")
                value = uc.get("value")
                new_label = uc.get("new_label")
                if not field_id or not value or not new_label:
                    continue
                existing = db.session.scalar(
                    select(MasChoiceMappings).where(
                        MasChoiceMappings.form_type_id == ft_id,
                        MasChoiceMappings.field_id == field_id,
                        MasChoiceMappings.choice_value == str(value),
                    )
                )
                if existing and existing.choice_label != new_label:
                    print(f"[sync:apply]   UPDATE choice {field_id!r}/{value!r}  "
                          f"{existing.choice_label!r} → {new_label!r}")
                    existing.choice_label = new_label
                    existing.synced_at = now
                    stats["choices_updated"] += 1
            print(f"[sync:apply] updated_choices done in {time.monotonic()-_t:.2f}s  "
                  f"updated={stats['choices_updated']}")

            _t_commit = time.monotonic()
            db.session.commit()
            print(f"[sync:apply] commit done in {time.monotonic()-_t_commit:.2f}s")

        except Exception as exc:
            db.session.rollback()
            print(f"[sync:apply] ERROR (rolled back): {exc}")
            stats["errors"].append(str(exc))

        elapsed = time.monotonic() - _t0
        if stats["errors"]:
            print(f"[sync:apply] DONE with {len(stats['errors'])} error(s) in {elapsed:.2f}s — {stats}")
        else:
            print(f"[sync:apply] DONE OK in {elapsed:.2f}s — {stats}")
        return stats

    # -----------------------------------------------------------------------
    # Public: preview (dry-run — no DB writes)
    # -----------------------------------------------------------------------

    def preview_sync(
        self,
        form_type_code: str,
        odk_project_id: int,
        odk_form_id: str,
        client=None,
    ) -> dict:
        """
        Preview what sync_form_choices would change, without writing to the DB.

        Returns a dict with:
          - label_changes: [{field_id, current_label, new_label}]
          - new_choices: [{field_id, value, label}]
          - updated_choices: [{field_id, value, old_label, new_label}]
          - deactivated_choices: [{field_id, value}]
          - errors: [str]
        """
        result = {
            "new_fields": [],
            "label_changes": [],
            "new_choices": [],
            "updated_choices": [],
            "errors": [],
        }

        _t0 = time.monotonic()
        print(f"[sync:preview] START  form={form_type_code}  project={odk_project_id}  form_id={odk_form_id}")

        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if not form_type:
            msg = f"Form type not found: {form_type_code}"
            print(f"[sync:preview] ERROR {msg}")
            result["errors"].append(msg)
            return result

        try:
            if client is None:
                client = va_odk_clientsetup()

            _t_fetch = time.monotonic()
            print(f"[sync:preview] fetching schema from ODK (xlsx)…")
            fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id)
            if fields is None:
                print(f"[sync:preview] xlsx fetch returned None — falling back to fields API")
                fields = self._fetch_fields(client, odk_project_id, odk_form_id)
            if fields is None:
                msg = "Failed to fetch form schema from ODK. Check connection credentials and form ID."
                print(f"[sync:preview] ERROR {msg}")
                result["errors"].append(msg)
                return result
            print(f"[sync:preview] fetched {len(fields)} fields in {time.monotonic()-_t_fetch:.2f}s")

            seen_keys: set[tuple[str, str]] = set()
            processed_field_ids: set[str] = set()

            for field in fields:
                field_name = field.get("name")
                field_type = field.get("type", "")

                # Skip structural/grouping types — not real data fields
                _ft = field_type.lower().strip()
                if _ft == "note" or _ft.startswith("begin") or _ft.startswith("end"):
                    continue

                odk_label = _extract_label(field.get("label"))

                cfg = db.session.scalar(
                    select(MasFieldDisplayConfig).where(
                        MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                        MasFieldDisplayConfig.field_id == field_name,
                    )
                )
                if cfg is None:
                    # Field exists in ODK but not registered in DB
                    entry: dict = {
                        "field_id": field_name,
                        "field_type": field_type,
                        "list_name": field.get("list_name", ""),
                        "odk_label": odk_label,
                        "choices": [],
                    }
                    if field_type.startswith("select"):
                        for ch in field.get("choices") or []:
                            cv = ch.get("name") or ch.get("value")
                            cl = _extract_label(ch.get("label")) or str(cv)
                            if cv:
                                entry["choices"].append({"value": str(cv), "label": cl})
                    print(f"[sync:preview]   NEW field {field_name!r}  type={field_type!r}  "
                          f"label={odk_label!r}  choices={len(entry['choices'])}")
                    result["new_fields"].append(entry)
                    continue  # choices are embedded in new_fields entry; don't also add to new_choices
                elif odk_label and cfg.odk_label != odk_label:
                    print(f"[sync:preview]   LABEL {field_name!r}  {cfg.odk_label!r} → {odk_label!r}")
                    result["label_changes"].append({
                        "field_id": field_name,
                        "current_label": cfg.odk_label or "",
                        "new_label": odk_label,
                    })

                if not field_type.startswith("select"):
                    continue

                choices = field.get("choices") or []
                if not choices:
                    continue

                processed_field_ids.add(field_name)

                for choice in choices:
                    choice_value = choice.get("name") or choice.get("value")
                    if not choice_value:
                        continue
                    choice_label = _extract_label(choice.get("label")) or str(choice_value)
                    key = (field_name, str(choice_value))
                    seen_keys.add(key)

                    existing = db.session.scalar(
                        select(MasChoiceMappings).where(
                            MasChoiceMappings.form_type_id == form_type.form_type_id,
                            MasChoiceMappings.field_id == field_name,
                            MasChoiceMappings.choice_value == str(choice_value),
                        )
                    )
                    if existing:
                        if existing.choice_label != choice_label:
                            print(f"[sync:preview]   UPDATE choice {field_name!r}/{choice_value!r}  "
                                  f"{existing.choice_label!r} → {choice_label!r}")
                            result["updated_choices"].append({
                                "field_id": field_name,
                                "value": str(choice_value),
                                "old_label": existing.choice_label,
                                "new_label": choice_label,
                            })
                    else:
                        print(f"[sync:preview]   NEW choice {field_name!r}/{choice_value!r}  label={choice_label!r}")
                        result["new_choices"].append({
                            "field_id": field_name,
                            "value": str(choice_value),
                            "label": choice_label,
                        })

            # Deactivation is intentionally skipped (see sync_form_choices)

        except Exception as exc:
            print(f"[sync:preview] ERROR: {exc}")
            result["errors"].append(str(exc))

        elapsed = time.monotonic() - _t0
        summary = (f"new_fields={len(result['new_fields'])}  "
                   f"label_changes={len(result['label_changes'])}  "
                   f"new_choices={len(result['new_choices'])}  "
                   f"updated_choices={len(result['updated_choices'])}")
        if result["errors"]:
            print(f"[sync:preview] DONE with {len(result['errors'])} error(s) in {elapsed:.2f}s — {summary}")
        else:
            print(f"[sync:preview] DONE OK in {elapsed:.2f}s — {summary}")
        return result

    # -----------------------------------------------------------------------
    # Existing public: detect schema changes
    # -----------------------------------------------------------------------

    def detect_schema_changes(
        self,
        form_type_code: str,
        odk_project_id: int,
        odk_form_id: str,
    ) -> dict:
        """Detect differences between ODK schema and database (dry-run)."""
        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if not form_type:
            return {"error": f"Form type not found: {form_type_code}"}

        client = va_odk_clientsetup()
        odk_fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id)
        if odk_fields is None:
            odk_fields = self._fetch_fields(client, odk_project_id, odk_form_id) or []

        odk_choice_set: set[tuple[str, str]] = set()
        for field in odk_fields:
            if not field.get("type", "").startswith("select"):
                continue
            for choice in field.get("choices") or []:
                val = choice.get("name") or choice.get("value")
                if val:
                    odk_choice_set.add((field["name"], str(val)))

        db_choices = db.session.scalars(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.is_active == True,
            )
        ).all()
        db_choice_set = {(c.field_id, c.choice_value) for c in db_choices}

        db_field_ids = set(
            db.session.scalars(
                select(MasFieldDisplayConfig.field_id).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.is_active == True,
                )
            ).all()
        )
        odk_field_ids = {f["name"] for f in odk_fields}

        return {
            "new_fields": sorted(odk_field_ids - db_field_ids),
            "removed_fields": sorted(db_field_ids - odk_field_ids),
            "new_choices": sorted(odk_choice_set - db_choice_set),
            "removed_choices": sorted(db_choice_set - odk_choice_set),
        }

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _fetch_from_xlsx(self, client, project_id: int, form_id: str) -> list[dict] | None:
        """
        Download and parse the XLSForm XLSX file.

        Reads both the 'survey' sheet (field names, types, labels) and the
        'choices' sheet (choice values and labels), combining them into the
        same [{name, type, label, choices: [...]}] structure used by the
        /fields API.
        """
        try:
            resp = guarded_odk_call(
                lambda: client.get(f"projects/{project_id}/forms/{form_id}.xlsx"),
                client=client,
            )
            if resp.status_code != 200:
                return None

            xls = pd.ExcelFile(io.BytesIO(resp.content))

            # ── Choices sheet ───────────────────────────────────────────────
            choice_map: dict[str, list[dict]] = {}  # list_name → [{name, label}]
            if "choices" in xls.sheet_names:
                choices_df = xls.parse("choices")
                label_col = _find_label_col(choices_df)
                for _, row in choices_df.iterrows():
                    list_name = _str_val(row.get("list_name"))
                    name = _str_val(row.get("name"))
                    if not list_name or not name:
                        continue
                    label = _str_val(row.get(label_col)) if label_col else name
                    choice_map.setdefault(list_name, []).append(
                        {"name": name, "label": {"default": label or name}}
                    )

            # ── Survey sheet ────────────────────────────────────────────────
            fields: list[dict] = []
            if "survey" in xls.sheet_names:
                survey_df = xls.parse("survey")
                label_col = _find_label_col(survey_df)
                for _, row in survey_df.iterrows():
                    type_val = _str_val(row.get("type"))
                    name = _str_val(row.get("name"))
                    if not type_val or not name:
                        continue

                    label = _str_val(row.get(label_col)) if label_col else ""

                    # Normalise "select_one list_name" → type + list_name
                    parts = type_val.split(None, 1)
                    field_type = parts[0]
                    entry: dict = {
                        "name": name,
                        "type": field_type,
                        "label": {"default": label},
                    }
                    if field_type in ("select_one", "select_multiple") and len(parts) > 1:
                        list_name = parts[1].strip()
                        entry["list_name"] = list_name
                        entry["choices"] = choice_map.get(list_name, [])

                    fields.append(entry)

            return fields or None

        except Exception:
            return None

    def _fetch_fields(self, client, project_id: int, form_id: str) -> list[dict] | None:
        """Fallback: fetch field list from ODK fields endpoint."""
        try:
            resp = guarded_odk_call(
                lambda: client.get(
                    f"projects/{project_id}/forms/{form_id}/fields",
                    params={"odata": "false"},
                ),
                client=client,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            return None

    def _update_field_odk_label(
        self,
        form_type_id: uuid.UUID,
        field_id: str,
        odk_label: str,
        stats: dict,
    ) -> bool:
        """
        Write the ODK label onto an existing MasFieldDisplayConfig row.

        Returns True if the field exists in the DB (regardless of whether
        the label changed), False if the field is not registered.
        """
        field_config = db.session.scalar(
            select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == form_type_id,
                MasFieldDisplayConfig.field_id == field_id,
            )
        )
        if field_config is None:
            return False
        if odk_label and field_config.odk_label != odk_label:
            field_config.odk_label = odk_label
            stats["labels_updated"] += 1
        return True

    def _upsert_choice(
        self,
        form_type_id: uuid.UUID,
        field_id: str,
        choice_value: str,
        choice_label: str,
        order: int,
        stats: dict,
    ):
        """Create or update a choice mapping."""
        existing = db.session.scalar(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type_id,
                MasChoiceMappings.field_id == field_id,
                MasChoiceMappings.choice_value == choice_value,
            )
        )
        if existing:
            if existing.choice_label != choice_label:
                existing.choice_label = choice_label
                existing.display_order = order
                existing.synced_at = datetime.now(timezone.utc)
                existing.is_active = True
                stats["choices_updated"] += 1
        else:
            db.session.add(
                MasChoiceMappings(
                    form_type_id=form_type_id,
                    field_id=field_id,
                    choice_value=choice_value,
                    choice_label=choice_label,
                    display_order=order,
                    is_active=True,
                    synced_at=datetime.now(timezone.utc),
                )
            )
            stats["choices_added"] += 1

    def _register_new_field(
        self,
        form_type_id: uuid.UUID,
        field_id: str,
        field_type: str,
        odk_label: str,
        stats: dict,
    ):
        """
        Register a new field from ODK into MasFieldDisplayConfig.

        Only the field_id, field_type, and odk_label are populated.
        All display configuration (short_label, category, flags, etc.) is left
        blank for the admin to configure via the field management UI.
        """
        label = odk_label or None
        db.session.add(MasFieldDisplayConfig(
            config_id=uuid.uuid4(),
            form_type_id=form_type_id,
            field_id=field_id,
            field_type=field_type or None,
            odk_label=label,
            short_label=label,
            full_label=label,
            is_active=True,
            is_custom=False,
        ))
        stats["fields_added"] += 1

    def _deactivate_missing(
        self,
        form_type_id: uuid.UUID,
        seen_keys: set[tuple[str, str]],
        processed_field_ids: set[str],
        stats: dict,
    ):
        """Deactivate choices for processed fields that are no longer in ODK."""
        if not processed_field_ids:
            return
        active_choices = db.session.scalars(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type_id,
                MasChoiceMappings.is_active == True,
                MasChoiceMappings.field_id.in_(processed_field_ids),
            )
        ).all()
        for choice in active_choices:
            if (choice.field_id, choice.choice_value) not in seen_keys:
                choice.is_active = False
                stats["choices_deactivated"] += 1


# Module-level singleton
_sync_service: OdkSchemaSyncService | None = None


def get_sync_service() -> OdkSchemaSyncService:
    """Get the shared OdkSchemaSyncService instance."""
    global _sync_service
    if _sync_service is None:
        _sync_service = OdkSchemaSyncService()
    return _sync_service
