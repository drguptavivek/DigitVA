"""
Field Mapping Service

Database-backed replacement for the Excel-based static mapping dicts.
Provides the same data structures consumed by va_render_processcategorydata:

  - get_fieldsitepi()  → {category: {subcategory: {field_id: short_label}}}
  - get_choices()      → {field_id: {choice_value: choice_label}}
  - get_flip_labels()  → [short_label, ...]  (where flip_color=True)
  - get_info_labels()  → [short_label, ...]  (where is_info=True)

Results are cached per form_type_code to avoid repeated DB queries within
the same process. Most caches are invalidated by calling clear_cache(), which
reaches the calling process only.

The PII set is the exception. It is the control behind "viewer without PII"
and export redaction, so a stale copy in one worker is a disclosure, not a
display quirk: ``get_pii_set_status``/``get_pii_field_ids`` re-check a cheap
version — ``(count(*), max(updated_at))`` over that form type's
``mas_field_display_config`` rows — on every call and rebuild when it moves.
A flag change made by an admin edit in one worker, or by a Celery-run sync,
therefore reaches every other worker without a restart. Count is part of the
version because a deleted row does not move ``max(updated_at)``.
"""
from collections import OrderedDict, defaultdict
from typing import NamedTuple
from sqlalchemy import func, select
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryDisplayConfig,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


class PiiSetStatus(NamedTuple):
    """Whether a form type's PII set has been considered, and what is in it.

    ``confirmed`` is derived, not stored. ``apply_pii_field_registry`` creates
    redaction-only rows (``Id10073``, ``abha_number``, ``abha_address``) for
    *every* form type, so "this form type has is_pii rows" is vacuous — a
    PHMRC or Ballabgarh questionnaire that has none of those WHO field ids
    still gets three. The signal that someone has actually considered this
    form type's PII set is an ``is_pii`` row on a field the form itself owns:
    a row that is mapped (``subcategory_code``), or synced from ODK
    (``odk_label``), or not registry-created (``is_custom = false``).

    Unconfirmed fails closed at both redaction sites — see
    docs/policy/access-control-model.md.
    """

    confirmed: bool
    field_ids: frozenset[str]
    owned_flagged_count: int


class FieldMappingService:
    """
    Service for accessing field mapping configuration from database.

    Builds the same dict structures as the generated static Python files
    in app/utils/va_mapping/, but reads from database instead of Excel.
    """

    def __init__(self):
        self._cache: dict = {}

    def clear_cache(self):
        """Clear the in-process cache. Call after admin updates mapping data."""
        self._cache.clear()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_fieldsitepi(self, form_type_code: str) -> dict:
        """
        Return field mapping in the format expected by va_render_processcategorydata.

        Structure: {category_code: {subcategory_code: {field_id: short_label}}}
        Categories are ordered by display_order. Fields within each subcategory
        are ordered by display_order.
        """
        cache_key = f"fieldsitepi_{form_type_code}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_fieldsitepi(form_type_code)
        return self._cache[cache_key]

    def get_choices(self, form_type_code: str) -> dict:
        """
        Return choice mappings in the format expected by va_render_processcategorydata.

        Structure: {field_id: {choice_value: choice_label}}
        """
        cache_key = f"choices_{form_type_code}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_choices(form_type_code)
        return self._cache[cache_key]

    def get_flip_labels(self, form_type_code: str) -> list[str]:
        """
        Return list of short_labels for fields where flip_color=True.

        Used by templates as: {% if label in flip_list %}
        """
        cache_key = f"flip_{form_type_code}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_labels_list(form_type_code, "flip_color")
        return self._cache[cache_key]

    def get_info_labels(self, form_type_code: str) -> list[str]:
        """
        Return list of short_labels for fields where is_info=True.

        Used by templates as: {% if label in info_list %}
        """
        cache_key = f"info_{form_type_code}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_labels_list(form_type_code, "is_info")
        return self._cache[cache_key]

    def get_pii_field_ids(self, form_type_code: str) -> set[str]:
        """
        Return field ids marked as PII for a form type.

        Callers that redact must use ``get_pii_set_status`` instead: an empty
        or registry-only set is not the same answer as "nothing here is
        personal data".
        """
        return set(self.get_pii_set_status(form_type_code).field_ids)

    def get_pii_set_status(self, form_type_code: str) -> PiiSetStatus:
        """Return the PII set for a form type plus whether it is confirmed.

        Version-checked on every call (see the module docstring): a flag
        change in another worker is picked up without clear_cache(). An
        unknown or inactive form type is unconfirmed with an empty set.
        """
        cache_key = f"pii_set_{form_type_code}"
        version = self._pii_config_version(form_type_code)
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == version:
            return cached[1]

        status = (
            self._build_pii_set_status(version[0])
            if version is not None
            else PiiSetStatus(confirmed=False, field_ids=frozenset(), owned_flagged_count=0)
        )
        self._cache[cache_key] = (version, status)
        return status

    def is_pii_set_confirmed(self, form_type_code: str) -> bool:
        """True when at least one field this form type owns is flagged is_pii."""
        return self.get_pii_set_status(form_type_code).confirmed

    def get_subcategory_labels(self, form_type_code: str, category_code: str) -> dict[str, str]:
        """
        Return ordered subcategory display labels for a category.

        Structure: {subcategory_code: subcategory_name}
        """
        cache_key = f"subcategory_labels_{form_type_code}_{category_code}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_subcategory_labels(
                form_type_code,
                category_code,
            )
        return self._cache[cache_key]

    def get_subcategory_render_modes(self, form_type_code: str, category_code: str) -> dict[str, str]:
        """
        Return ordered subcategory render modes for a category.

        Structure: {subcategory_code: render_mode}
        """
        cache_key = f"subcategory_render_modes_{form_type_code}_{category_code}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_subcategory_render_modes(
                form_type_code,
                category_code,
            )
        return self._cache[cache_key]

    def get_default_form_type(self) -> str:
        """Return the default form type code (backward compatibility)."""
        return "WHO_2022_VA"

    def get_form_type(self, form_type_code: str):
        """Get active form type record by code, or None."""
        return db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code,
                MasFormTypes.is_active == True,
            )
        )

    # ------------------------------------------------------------------ #
    # Private builders                                                     #
    # ------------------------------------------------------------------ #

    def _build_fieldsitepi(self, form_type_code: str) -> dict:
        """Build {category: {subcategory: {field_id: label}}} from DB."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return {}

        ft_id = form_type.form_type_id

        # Load categories in display order from the authoritative category
        # display config table.
        categories = db.session.scalars(
            select(MasCategoryDisplayConfig)
            .where(
                MasCategoryDisplayConfig.form_type_id == ft_id,
                MasCategoryDisplayConfig.is_active == True,
            )
            .order_by(
                MasCategoryDisplayConfig.display_order,
                MasCategoryDisplayConfig.nav_label,
            )
        ).all()

        # Load explicit subcategory ordering for this form type.
        subcategories = db.session.scalars(
            select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == ft_id,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.category_code, MasSubcategoryOrder.display_order)
        ).all()

        # Load all field configs for this form type in one query.
        fields = db.session.scalars(
            select(MasFieldDisplayConfig)
            .where(
                MasFieldDisplayConfig.form_type_id == ft_id,
                MasFieldDisplayConfig.is_active == True,
                MasFieldDisplayConfig.subcategory_code.is_not(None),
            )
            .order_by(MasFieldDisplayConfig.display_order)
        ).all()

        # Build lookups keyed by category/subcategory so category order,
        # subcategory order, and field order can be applied independently.
        cat_fields: dict[str, list] = defaultdict(list)
        for f in fields:
            cat_fields[f.category_code].append(f)

        ordered_subcats: dict[str, list[str]] = defaultdict(list)
        for sub in subcategories:
            ordered_subcats[sub.category_code].append(sub.subcategory_code)

        result = OrderedDict()
        for cat in categories:
            cat_code = cat.category_code
            subcat_fields: dict[str, dict[str, str]] = defaultdict(OrderedDict)

            for f in cat_fields.get(cat_code, []):
                subcat = f.subcategory_code
                subcat_fields[subcat][f.field_id] = f.short_label or f.field_id

            if not subcat_fields:
                continue

            subcat_dict: dict[str, dict[str, str]] = OrderedDict()

            for subcat_code in ordered_subcats.get(cat_code, []):
                fields_for_subcat = subcat_fields.pop(subcat_code, None)
                if fields_for_subcat:
                    subcat_dict[subcat_code] = fields_for_subcat

            # Keep a stable fallback for any field-bearing subcategory that
            # does not yet have a MasSubcategoryOrder row.
            for subcat_code, fields_for_subcat in subcat_fields.items():
                subcat_dict[subcat_code] = fields_for_subcat

            if subcat_dict:
                result[cat_code] = subcat_dict

        return result

    def _build_choices(self, form_type_code: str) -> dict:
        """Build {field_id: {choice_value: choice_label}} from DB."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return {}

        choices = db.session.scalars(
            select(MasChoiceMappings)
            .where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.is_active == True,
            )
            .order_by(MasChoiceMappings.field_id, MasChoiceMappings.display_order)
        ).all()

        result: dict[str, dict[str, str]] = {}
        for c in choices:
            if c.field_id not in result:
                result[c.field_id] = {}
            result[c.field_id][c.choice_value] = c.choice_label

        return result

    def _build_labels_list(self, form_type_code: str, boolean_column: str) -> list[str]:
        """Build list of short_labels where a boolean column is True."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return []

        column = getattr(MasFieldDisplayConfig, boolean_column)
        fields = db.session.scalars(
            select(MasFieldDisplayConfig.short_label)
            .where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.is_active == True,
                column == True,
                MasFieldDisplayConfig.short_label.is_not(None),
            )
            .order_by(MasFieldDisplayConfig.display_order)
        ).all()

        return [label for label in fields if label]

    def _build_subcategory_labels(self, form_type_code: str, category_code: str) -> dict[str, str]:
        """Build ordered {subcategory_code: subcategory_name} for one category."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return {}

        subcategories = db.session.scalars(
            select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

        return OrderedDict(
            (
                subcategory.subcategory_code,
                subcategory.subcategory_name or subcategory.subcategory_code,
            )
            for subcategory in subcategories
        )

    def _build_subcategory_render_modes(self, form_type_code: str, category_code: str) -> dict[str, str]:
        """Build ordered {subcategory_code: render_mode} for one category."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return {}

        subcategories = db.session.scalars(
            select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

        return OrderedDict(
            (
                subcategory.subcategory_code,
                subcategory.render_mode or "default",
            )
            for subcategory in subcategories
        )

    def _pii_config_version(self, form_type_code: str) -> tuple | None:
        """Cheap change token for a form type's field display config.

        ``(form_type_id, row count, max updated_at)``. The count is needed
        because deleting a row does not move ``max(updated_at)``. Returns
        None when the form type does not exist or is inactive.
        """
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return None

        count, latest = db.session.execute(
            select(
                func.count(MasFieldDisplayConfig.config_id),
                func.max(MasFieldDisplayConfig.updated_at),
            ).where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        ).one()
        return (form_type.form_type_id, count, latest)

    def _build_pii_set_status(self, form_type_id) -> PiiSetStatus:
        """Build the PII set for a form type and decide whether it is confirmed.

        Deliberately ignores ``is_active``: that flag governs whether a field
        is displayed on the coding screen, not whether it is redacted from
        exports. A field deactivated after being flagged PII must stay
        redacted, not silently drop out of the export filter.
        """
        rows = db.session.execute(
            select(
                MasFieldDisplayConfig.field_id,
                MasFieldDisplayConfig.subcategory_code,
                MasFieldDisplayConfig.odk_label,
                MasFieldDisplayConfig.is_custom,
            ).where(
                MasFieldDisplayConfig.form_type_id == form_type_id,
                MasFieldDisplayConfig.is_pii == True,
            )
        ).all()

        owned = sum(
            1
            for _field_id, subcategory_code, odk_label, is_custom in rows
            if subcategory_code is not None or odk_label is not None or not is_custom
        )
        return PiiSetStatus(
            confirmed=owned > 0,
            field_ids=frozenset(row[0] for row in rows),
            owned_flagged_count=owned,
        )


# Module-level singleton - shared across requests in the same process
_service: FieldMappingService | None = None


def get_mapping_service() -> FieldMappingService:
    """Get the shared FieldMappingService instance."""
    global _service
    if _service is None:
        _service = FieldMappingService()
    return _service
