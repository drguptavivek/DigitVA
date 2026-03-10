"""
Form Type Registration Service

Manages registration and configuration of VA form types (e.g., WHO_2022_VA,
BALLABGARH_VA, SMART_VA). Each form type has its own set of categories,
field display configurations, and choice mappings.
"""
from sqlalchemy import select, func
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)


class FormTypeService:
    """Service for managing VA form type registration and metadata."""

    def register_form_type(
        self,
        form_type_code: str,
        form_type_name: str,
        description: str | None = None,
        base_template_path: str | None = None,
    ) -> MasFormTypes:
        """
        Register a new form type.

        Raises ValueError if a form type with the same code already exists
        (active or inactive).
        """
        existing = db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code
            )
        )
        if existing:
            raise ValueError(f"Form type already exists: {form_type_code}")

        form_type = MasFormTypes(
            form_type_code=form_type_code,
            form_type_name=form_type_name,
            form_type_description=description,
            base_template_path=base_template_path,
            mapping_version=1,
            is_active=True,
        )
        db.session.add(form_type)
        db.session.commit()
        return form_type

    def get_form_type(self, form_type_code: str) -> MasFormTypes | None:
        """Return an active form type by code, or None."""
        return db.session.scalar(
            select(MasFormTypes).where(
                MasFormTypes.form_type_code == form_type_code,
                MasFormTypes.is_active == True,
            )
        )

    def list_form_types(self) -> list[MasFormTypes]:
        """Return all active form types ordered by code."""
        return list(
            db.session.scalars(
                select(MasFormTypes)
                .where(MasFormTypes.is_active == True)
                .order_by(MasFormTypes.form_type_code)
            ).all()
        )

    def get_form_type_stats(self, form_type_code: str) -> dict:
        """Return statistics for a form type, or empty dict if not found."""
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return {}

        ft_id = form_type.form_type_id

        from app.models import VaForms
        form_count = db.session.scalar(
            select(func.count()).select_from(VaForms).where(
                VaForms.form_type_id == ft_id
            )
        ) or 0

        category_count = db.session.scalar(
            select(func.count()).select_from(MasCategoryOrder).where(
                MasCategoryOrder.form_type_id == ft_id,
                MasCategoryOrder.is_active == True,
            )
        ) or 0

        field_count = db.session.scalar(
            select(func.count()).select_from(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == ft_id,
                MasFieldDisplayConfig.is_active == True,
            )
        ) or 0

        choice_count = db.session.scalar(
            select(func.count()).select_from(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == ft_id,
                MasChoiceMappings.is_active == True,
            )
        ) or 0

        return {
            "form_type_code": form_type_code,
            "form_type_name": form_type.form_type_name,
            "form_count": form_count,
            "category_count": category_count,
            "field_count": field_count,
            "choice_count": choice_count,
            "is_active": form_type.is_active,
        }

    def deactivate_form_type(self, form_type_code: str) -> bool:
        """
        Soft-delete a form type.

        Returns False if the form type does not exist.
        Raises ValueError if VaForms are still linked to it.
        """
        form_type = self.get_form_type(form_type_code)
        if not form_type:
            return False

        from app.models import VaForms
        form_count = db.session.scalar(
            select(func.count()).select_from(VaForms).where(
                VaForms.form_type_id == form_type.form_type_id
            )
        ) or 0
        if form_count > 0:
            raise ValueError(
                f"Cannot deactivate: {form_count} form(s) still use {form_type_code}"
            )

        form_type.is_active = False
        db.session.commit()
        return True


# Module-level singleton
_service: FormTypeService | None = None


def get_form_type_service() -> FormTypeService:
    """Return the shared FormTypeService instance."""
    global _service
    if _service is None:
        _service = FormTypeService()
    return _service
