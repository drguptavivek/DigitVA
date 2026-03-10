"""
ODK Schema Sync Service

Synchronizes form field choices from ODK Central to the database.

Uses the existing pyODK client (via va_odk_clientsetup) to call:
- GET projects/{id}/forms/{id}/fields  — field definitions with choices
- GET projects/{id}/forms/{id}.xlsx    — fallback XLSX

The ODK fields endpoint returns a flat list of fields. Each select field
includes a "choices" list with name + label (multi-locale dict).
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


def _extract_label(label_value) -> str:
    """
    Extract a plain string from an ODK label value.

    ODK labels may be:
      - a string: "Choice One"
      - a dict of locales: {"default": "Choice One", "en": "Choice One"}
    """
    if isinstance(label_value, dict):
        return label_value.get("default") or label_value.get("en") or next(
            iter(label_value.values()), ""
        )
    return str(label_value) if label_value is not None else ""


class OdkSchemaSyncService:
    """
    Synchronizes choice mappings from ODK Central form schemas.

    Add new choices, update changed labels, deactivate removed choices.
    """

    def sync_form_choices(
        self,
        form_type_code: str,
        odk_project_id: int,
        odk_form_id: str,
    ) -> dict:
        """
        Sync choice mappings for a form from ODK Central.

        Returns dict with sync statistics.
        """
        stats = {
            "fields_processed": 0,
            "choices_added": 0,
            "choices_updated": 0,
            "choices_deactivated": 0,
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
            client = va_odk_clientsetup()
            fields = self._fetch_fields(client, odk_project_id, odk_form_id)

            if fields is None:
                fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id)

            if fields is None:
                stats["errors"].append("Failed to fetch form schema from ODK")
                return stats

            # Track which (field_id, choice_value) pairs we see from ODK
            # and which field_ids we actually processed
            seen_keys: set[tuple[str, str]] = set()
            processed_field_ids: set[str] = set()

            for field in fields:
                field_name = field.get("name")
                field_type = field.get("type", "")

                if not field_type.startswith("select"):
                    continue

                choices = field.get("choices") or []
                if not choices:
                    continue

                stats["fields_processed"] += 1
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

            # Only deactivate choices for fields we actually processed —
            # scoped so partial syncs don't remove other fields' choices.
            self._deactivate_missing(
                form_type.form_type_id, seen_keys, processed_field_ids, stats
            )
            db.session.commit()

        except Exception as exc:
            db.session.rollback()
            stats["errors"].append(str(exc))

        return stats

    def detect_schema_changes(
        self,
        form_type_code: str,
        odk_project_id: int,
        odk_form_id: str,
    ) -> dict:
        """
        Detect differences between ODK schema and database (dry-run).

        Returns dict with new_choices / removed_choices lists.
        """
        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if not form_type:
            return {"error": f"Form type not found: {form_type_code}"}

        client = va_odk_clientsetup()
        odk_fields = self._fetch_fields(client, odk_project_id, odk_form_id)
        if odk_fields is None:
            odk_fields = self._fetch_from_xlsx(client, odk_project_id, odk_form_id) or []

        # Build ODK choice set
        odk_choice_set: set[tuple[str, str]] = set()
        for field in odk_fields:
            if not field.get("type", "").startswith("select"):
                continue
            for choice in field.get("choices") or []:
                val = choice.get("name") or choice.get("value")
                if val:
                    odk_choice_set.add((field["name"], str(val)))

        # Build DB choice set
        db_choices = db.session.scalars(
            select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.is_active == True,
            )
        ).all()
        db_choice_set = {(c.field_id, c.choice_value) for c in db_choices}

        # DB field set
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_fields(self, client, project_id: int, form_id: str) -> list[dict] | None:
        """Fetch field list from ODK fields endpoint. Returns None on error."""
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

    def _fetch_from_xlsx(self, client, project_id: int, form_id: str) -> list[dict] | None:
        """Fallback: parse choices sheet from XLSX attachment."""
        try:
            resp = client.get(f"projects/{project_id}/forms/{form_id}.xlsx")
            if resp.status_code != 200:
                return None

            xlsx = pd.read_excel(io.BytesIO(resp.content), sheet_name="choices")
            fields: dict[str, dict] = {}

            for _, row in xlsx.iterrows():
                list_name = row.get("list_name")
                name = row.get("name")
                label = row.get("label")

                if pd.isna(list_name) or pd.isna(name):
                    continue

                list_name = str(list_name).strip()
                name = str(name).strip()
                label_str = str(label).strip() if pd.notna(label) else name

                if list_name not in fields:
                    fields[list_name] = {
                        "name": list_name,
                        "type": "select_one",
                        "choices": [],
                    }
                fields[list_name]["choices"].append({
                    "name": name,
                    "label": {"default": label_str},
                })

            return list(fields.values())

        except Exception:
            return None

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
