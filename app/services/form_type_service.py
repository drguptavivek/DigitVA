"""
Form Type Registration Service

Manages registration and configuration of VA form types (e.g., WHO_2022_VA,
BALLABGARH_VA, SMART_VA). Each form type has its own set of categories,
field display configurations, and choice mappings.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
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

    def duplicate_form_type(
        self,
        source_code: str,
        new_code: str,
        new_name: str,
        description: str | None = None,
    ) -> MasFormTypes:
        """
        Duplicate an existing form type — copies all categories, subcategories,
        fields, and choices into a new form type entry.

        Raises ValueError if source not found or new_code already exists.
        """
        source = db.session.scalar(
            select(MasFormTypes).where(MasFormTypes.form_type_code == source_code)
        )
        if not source:
            raise ValueError(f"Source form type not found: {source_code}")

        if db.session.scalar(
            select(MasFormTypes).where(MasFormTypes.form_type_code == new_code)
        ):
            raise ValueError(f"Form type already exists: {new_code}")

        now = datetime.now(timezone.utc)
        new_ft = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code=new_code,
            form_type_name=new_name,
            form_type_description=description,
            base_template_path=source.base_template_path,
            mapping_version=1,
            is_active=True,
        )
        db.session.add(new_ft)
        db.session.flush()  # get new_ft.form_type_id

        src_id = source.form_type_id
        dst_id = new_ft.form_type_id

        # Categories
        for cat in db.session.scalars(
            select(MasCategoryOrder).where(MasCategoryOrder.form_type_id == src_id)
        ).all():
            db.session.add(MasCategoryOrder(
                category_order_id=uuid.uuid4(),
                form_type_id=dst_id,
                category_code=cat.category_code,
                category_name=cat.category_name,
                display_order=cat.display_order,
                is_active=cat.is_active,
            ))

        # Subcategories
        for sub in db.session.scalars(
            select(MasSubcategoryOrder).where(MasSubcategoryOrder.form_type_id == src_id)
        ).all():
            db.session.add(MasSubcategoryOrder(
                subcategory_order_id=uuid.uuid4(),
                form_type_id=dst_id,
                category_code=sub.category_code,
                subcategory_code=sub.subcategory_code,
                subcategory_name=sub.subcategory_name,
                display_order=sub.display_order,
                is_active=sub.is_active,
            ))

        # Fields
        for fld in db.session.scalars(
            select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == src_id
            )
        ).all():
            db.session.add(MasFieldDisplayConfig(
                config_id=uuid.uuid4(),
                form_type_id=dst_id,
                field_id=fld.field_id,
                category_code=fld.category_code,
                subcategory_code=fld.subcategory_code,
                odk_label=fld.odk_label,
                short_label=fld.short_label,
                full_label=fld.full_label,
                summary_label=fld.summary_label,
                field_type=fld.field_type,
                age_group=fld.age_group,
                flip_color=fld.flip_color,
                is_info=fld.is_info,
                summary_include=fld.summary_include,
                is_pii=fld.is_pii,
                pii_type=fld.pii_type,
                display_order=fld.display_order,
                is_active=fld.is_active,
                is_custom=fld.is_custom,
            ))

        # Choices
        for ch in db.session.scalars(
            select(MasChoiceMappings).where(MasChoiceMappings.form_type_id == src_id)
        ).all():
            db.session.add(MasChoiceMappings(
                form_type_id=dst_id,
                field_id=ch.field_id,
                choice_value=ch.choice_value,
                choice_label=ch.choice_label,
                display_order=ch.display_order,
                is_active=ch.is_active,
                synced_at=ch.synced_at,
            ))

        db.session.commit()
        return new_ft

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
