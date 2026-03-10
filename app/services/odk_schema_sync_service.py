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
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import select
from app import db
from app.models import (
    MasFormTypes,
    MasChoiceMappings,
    MasFieldDisplayConfig,
)
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
        Sync field labels and choice mappings for a form from ODK Central.

        Returns dict with sync statistics.
        """
        stats = {
            "fields_processed": 0,
            "labels_updated": 0,
            "choices_added": 0,
            "choices_updated": 0,
            "errors": [],
        }

        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if not form_type:
            stats["errors"].append(f"Form type not found: {form_type_code}")
            return stats

        try:
            if client is None:
                client = va_odk_clientsetup()

            fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id)

            if fields is None:
                fields = self._fetch_fields(client, odk_project_id, odk_form_id)

            if fields is None:
                stats["errors"].append(
                    "Failed to fetch form schema from ODK. "
                    "Check connection credentials and form ID."
                )
                return stats

            seen_keys: set[tuple[str, str]] = set()
            processed_field_ids: set[str] = set()

            for field in fields:
                field_name = field.get("name")
                field_type = field.get("type", "")

                # Count and label-update every field that exists in our DB
                odk_label = _extract_label(field.get("label"))
                matched = self._update_field_odk_label(
                    form_type.form_type_id, field_name, odk_label, stats
                )
                if matched:
                    stats["fields_processed"] += 1

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

            # NOTE: deactivation is intentionally skipped here.
            # Choices are seeded from the WHO VA template (mapping_choices.xlsx)
            # which covers ALL sites. Any given ODK project form only contains
            # choices for its own site, so deactivating against a single
            # site's form would incorrectly remove other sites' choices.
            db.session.commit()

        except Exception as exc:
            db.session.rollback()
            stats["errors"].append(str(exc))

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
            "label_changes": [],
            "new_choices": [],
            "updated_choices": [],
            "errors": [],
        }

        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if not form_type:
            result["errors"].append(f"Form type not found: {form_type_code}")
            return result

        try:
            if client is None:
                client = va_odk_clientsetup()

            fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id)
            if fields is None:
                fields = self._fetch_fields(client, odk_project_id, odk_form_id)
            if fields is None:
                result["errors"].append(
                    "Failed to fetch form schema from ODK. "
                    "Check connection credentials and form ID."
                )
                return result

            seen_keys: set[tuple[str, str]] = set()
            processed_field_ids: set[str] = set()

            for field in fields:
                field_name = field.get("name")
                field_type = field.get("type", "")

                # Check label change
                odk_label = _extract_label(field.get("label"))
                if odk_label:
                    cfg = db.session.scalar(
                        select(MasFieldDisplayConfig).where(
                            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                            MasFieldDisplayConfig.field_id == field_name,
                        )
                    )
                    if cfg and cfg.odk_label != odk_label:
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
                            result["updated_choices"].append({
                                "field_id": field_name,
                                "value": str(choice_value),
                                "old_label": existing.choice_label,
                                "new_label": choice_label,
                            })
                    else:
                        result["new_choices"].append({
                            "field_id": field_name,
                            "value": str(choice_value),
                            "label": choice_label,
                        })

            # Deactivation is intentionally skipped (see sync_form_choices)

        except Exception as exc:
            result["errors"].append(str(exc))

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
            resp = client.get(f"projects/{project_id}/forms/{form_id}.xlsx")
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
                        entry["choices"] = choice_map.get(list_name, [])

                    fields.append(entry)

            return fields or None

        except Exception:
            return None

    def _fetch_fields(self, client, project_id: int, form_id: str) -> list[dict] | None:
        """Fallback: fetch field list from ODK fields endpoint."""
        try:
            resp = client.get(
                f"projects/{project_id}/forms/{form_id}/fields",
                params={"odata": "false"},
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
