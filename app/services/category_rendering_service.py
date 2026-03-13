"""Category rendering service.

Provides one ordered, role-aware source of truth for category navigation,
route eligibility, and previous/next traversal.
"""

from dataclasses import dataclass

from sqlalchemy import select

from app import db
from app.models import MasCategoryDisplayConfig, MasFormTypes
from app.services.field_mapping_service import get_mapping_service


@dataclass(frozen=True)
class CategoryNavItem:
    category_code: str
    display_label: str
    nav_label: str
    icon_name: str | None
    render_mode: str
    display_order: int
    always_include: bool
    is_default_start: bool


class CategoryRenderingService:
    """Load ordered category config and build role-aware nav context."""

    ROLE_BY_ACTION = {
        "vacode": "coder",
        "vareview": "reviewer",
        "vasitepi": "site_pi",
    }

    ROLE_VISIBILITY_COLUMN = {
        "coder": "show_to_coder",
        "reviewer": "show_to_reviewer",
        "site_pi": "show_to_site_pi",
    }

    def __init__(self):
        self._cache: dict[str, list[CategoryNavItem]] = {}

    def clear_cache(self):
        """Clear cached category config."""
        self._cache.clear()

    def get_role_for_action(self, va_action: str) -> str:
        """Map route action to role visibility bucket."""
        return self.ROLE_BY_ACTION.get(va_action, "coder")

    def get_category_nav(
        self,
        form_type_code: str,
        va_action: str,
        visible_category_codes: list[str] | None,
    ) -> list[CategoryNavItem]:
        """Return ordered visible category nav entries for a role and submission."""
        role = self.get_role_for_action(va_action)
        allowed_codes = set(visible_category_codes or [])

        items: list[CategoryNavItem] = []
        for item in self._get_categories_for_role(form_type_code, role):
            if item.always_include or item.category_code in allowed_codes:
                items.append(item)
        return items

    def get_default_category_code(
        self,
        form_type_code: str,
        va_action: str,
        visible_category_codes: list[str] | None,
    ) -> str | None:
        """Return the preferred initial category code for a visible nav."""
        nav_items = self.get_category_nav(form_type_code, va_action, visible_category_codes)
        if not nav_items:
            return None

        for item in nav_items:
            if item.is_default_start:
                return item.category_code
        return nav_items[0].category_code

    def get_category_neighbours(
        self,
        form_type_code: str,
        va_action: str,
        visible_category_codes: list[str] | None,
        current_category: str,
    ) -> tuple[str | None, str | None]:
        """Return previous/next category codes inside the visible nav."""
        ordered_codes = [
            item.category_code
            for item in self.get_category_nav(form_type_code, va_action, visible_category_codes)
        ]
        try:
            index = ordered_codes.index(current_category)
        except ValueError:
            return None, None

        previous_code = ordered_codes[index - 1] if index > 0 else None
        next_code = ordered_codes[index + 1] if index < len(ordered_codes) - 1 else None
        return previous_code, next_code

    def get_category_config(
        self,
        form_type_code: str,
        va_action: str,
        category_code: str,
    ) -> CategoryNavItem | None:
        """Return category config for a code if visible to the current role."""
        role = self.get_role_for_action(va_action)
        for item in self._get_categories_for_role(form_type_code, role):
            if item.category_code == category_code:
                return item
        return None

    def get_all_active_categories(
        self,
        form_type_code: str,
    ) -> list[CategoryNavItem]:
        """Return all active category configs for a form type, regardless of role."""
        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code,
                MasFormTypes.is_active == True,
            )
        )
        if not form_type:
            return []

        configs = db.session.scalars(
            select(MasCategoryDisplayConfig)
            .where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.is_active == True,
            )
            .order_by(MasCategoryDisplayConfig.display_order, MasCategoryDisplayConfig.nav_label)
        ).all()

        return [
            CategoryNavItem(
                category_code=config.category_code,
                display_label=config.display_label,
                nav_label=config.nav_label,
                icon_name=config.icon_name,
                render_mode=config.render_mode,
                display_order=config.display_order,
                always_include=config.always_include,
                is_default_start=config.is_default_start,
            )
            for config in configs
        ]

    def is_category_enabled(
        self,
        form_type_code: str,
        va_action: str,
        visible_category_codes: list[str] | None,
        category_code: str,
    ) -> bool:
        """Return whether a category is allowed for the role and submission."""
        return any(
            item.category_code == category_code
            for item in self.get_category_nav(form_type_code, va_action, visible_category_codes)
        )

    def _get_categories_for_role(
        self,
        form_type_code: str,
        role: str,
    ) -> list[CategoryNavItem]:
        cache_key = f"{form_type_code}:{role}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build_categories_for_role(form_type_code, role)
        return self._cache[cache_key]

    def _build_categories_for_role(
        self,
        form_type_code: str,
        role: str,
    ) -> list[CategoryNavItem]:
        form_type = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code,
                MasFormTypes.is_active == True,
            )
        )
        if not form_type:
            return []

        visibility_column = getattr(
            MasCategoryDisplayConfig,
            self.ROLE_VISIBILITY_COLUMN[role],
        )
        configs = db.session.scalars(
            select(MasCategoryDisplayConfig)
            .where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.is_active == True,
                visibility_column == True,
            )
            .order_by(MasCategoryDisplayConfig.display_order, MasCategoryDisplayConfig.nav_label)
        ).all()

        return [
            CategoryNavItem(
                category_code=config.category_code,
                display_label=config.display_label,
                nav_label=config.nav_label,
                icon_name=config.icon_name,
                render_mode=config.render_mode,
                display_order=config.display_order,
                always_include=config.always_include,
                is_default_start=config.is_default_start,
            )
            for config in configs
        ]


_service: CategoryRenderingService | None = None


def get_category_rendering_service() -> CategoryRenderingService:
    """Get shared category rendering service."""
    global _service
    if _service is None:
        _service = CategoryRenderingService()
    return _service


def clear_category_rendering_cache():
    """Clear category rendering and dependent mapping cache."""
    global _service
    if _service is not None:
        _service.clear_cache()
    get_mapping_service().clear_cache()
