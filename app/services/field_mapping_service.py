"""
Field Mapping Service

Database-backed replacement for the Excel-based static mapping dicts.
Provides the same data structures consumed by va_render_processcategorydata:

  - get_fieldsitepi()  → {category: {subcategory: {field_id: short_label}}}
  - get_choices()      → {field_id: {choice_value: choice_label}}
  - get_flip_labels()  → [short_label, ...]  (where flip_color=True)
  - get_info_labels()  → [short_label, ...]  (where is_info=True)

Results are cached per form_type_code to avoid repeated DB queries within
the same process. Cache is invalidated by calling clear_cache().
"""
from collections import OrderedDict, defaultdict
from sqlalchemy import select
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryDisplayConfig,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


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


# Module-level singleton - shared across requests in the same process
_service: FieldMappingService | None = None


def get_mapping_service() -> FieldMappingService:
    """Get the shared FieldMappingService instance."""
    global _service
    if _service is None:
        _service = FieldMappingService()
    return _service
