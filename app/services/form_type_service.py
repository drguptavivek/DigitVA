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
    MasCategoryDisplayConfig,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)

EXPORT_SCHEMA_VERSION = 1


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
            "form_type_description": form_type.form_type_description,
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

        for category_display in db.session.scalars(
            select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == src_id
            )
        ).all():
            db.session.add(MasCategoryDisplayConfig(
                category_display_config_id=uuid.uuid4(),
                form_type_id=dst_id,
                category_code=category_display.category_code,
                display_label=category_display.display_label,
                nav_label=category_display.nav_label,
                icon_name=category_display.icon_name,
                display_order=category_display.display_order,
                render_mode=category_display.render_mode,
                show_to_coder=category_display.show_to_coder,
                show_to_reviewer=category_display.show_to_reviewer,
                show_to_site_pi=category_display.show_to_site_pi,
                always_include=category_display.always_include,
                is_default_start=category_display.is_default_start,
                is_active=category_display.is_active,
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
                render_mode=sub.render_mode,
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

    def export_form_type(self, form_type_code: str) -> dict:
        """
        Serialize a form type and all its child records to a plain dict.

        Raises ValueError if the form type is not found.
        """
        ft = db.session.scalar(
            select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
        )
        if not ft:
            raise ValueError(f"Form type not found: {form_type_code}")

        ft_id = ft.form_type_id

        categories = [
            {
                "category_code": c.category_code,
                "category_name": c.category_name,
                "display_order": c.display_order,
                "is_active": c.is_active,
            }
            for c in db.session.scalars(
                select(MasCategoryOrder)
                .where(MasCategoryOrder.form_type_id == ft_id)
                .order_by(MasCategoryOrder.display_order)
            ).all()
        ]

        category_display_configs = [
            {
                "category_code": c.category_code,
                "display_label": c.display_label,
                "nav_label": c.nav_label,
                "icon_name": c.icon_name,
                "display_order": c.display_order,
                "render_mode": c.render_mode,
                "show_to_coder": c.show_to_coder,
                "show_to_reviewer": c.show_to_reviewer,
                "show_to_site_pi": c.show_to_site_pi,
                "always_include": c.always_include,
                "is_default_start": c.is_default_start,
                "is_active": c.is_active,
            }
            for c in db.session.scalars(
                select(MasCategoryDisplayConfig)
                .where(MasCategoryDisplayConfig.form_type_id == ft_id)
                .order_by(MasCategoryDisplayConfig.display_order)
            ).all()
        ]

        subcategories = [
            {
                "category_code": s.category_code,
                "subcategory_code": s.subcategory_code,
                "subcategory_name": s.subcategory_name,
                "display_order": s.display_order,
                "render_mode": s.render_mode,
                "is_active": s.is_active,
            }
            for s in db.session.scalars(
                select(MasSubcategoryOrder)
                .where(MasSubcategoryOrder.form_type_id == ft_id)
                .order_by(MasSubcategoryOrder.display_order)
            ).all()
        ]

        fields = [
            {
                "field_id": f.field_id,
                "category_code": f.category_code,
                "subcategory_code": f.subcategory_code,
                "odk_label": f.odk_label,
                "short_label": f.short_label,
                "full_label": f.full_label,
                "summary_label": f.summary_label,
                "field_type": f.field_type,
                "age_group": f.age_group,
                "flip_color": f.flip_color,
                "is_info": f.is_info,
                "summary_include": f.summary_include,
                "is_pii": f.is_pii,
                "pii_type": f.pii_type,
                "display_order": f.display_order,
                "is_active": f.is_active,
                "is_custom": f.is_custom,
            }
            for f in db.session.scalars(
                select(MasFieldDisplayConfig)
                .where(MasFieldDisplayConfig.form_type_id == ft_id)
                .order_by(MasFieldDisplayConfig.display_order)
            ).all()
        ]

        choices = [
            {
                "field_id": ch.field_id,
                "choice_value": ch.choice_value,
                "choice_label": ch.choice_label,
                "display_order": ch.display_order,
                "is_active": ch.is_active,
            }
            for ch in db.session.scalars(
                select(MasChoiceMappings)
                .where(MasChoiceMappings.form_type_id == ft_id)
                .order_by(MasChoiceMappings.field_id, MasChoiceMappings.display_order)
            ).all()
        ]

        return {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "form_type": {
                "form_type_code": ft.form_type_code,
                "form_type_name": ft.form_type_name,
                "form_type_description": ft.form_type_description,
                "base_template_path": ft.base_template_path,
                "mapping_version": ft.mapping_version,
            },
            "categories": categories,
            "category_display_configs": category_display_configs,
            "subcategories": subcategories,
            "fields": fields,
            "choices": choices,
        }

    def import_form_type(
        self,
        data: dict,
        override_code: str | None = None,
        override_name: str | None = None,
        override_description: str | None = None,
    ) -> tuple["MasFormTypes", dict]:
        """
        Create a form type from an exported dict.

        override_code / override_name let the caller rename on import
        (useful when the code already exists in this database).

        Returns (new_form_type, stats) where stats has:
          categories_created, subcategories_created, fields_created, choices_created.

        Raises ValueError on schema issues or code conflicts.
        """
        schema_version = data.get("schema_version")
        if schema_version != EXPORT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version: {schema_version!r}. "
                f"Expected {EXPORT_SCHEMA_VERSION}."
            )

        ft_data = data.get("form_type") or {}
        code = (override_code or ft_data.get("form_type_code") or "").strip().upper()
        name = (override_name or ft_data.get("form_type_name") or "").strip()
        description = override_description if override_description is not None else ft_data.get("form_type_description")

        if not code or not name:
            raise ValueError("form_type_code and form_type_name are required.")

        if db.session.scalar(select(MasFormTypes).where(MasFormTypes.form_type_code == code)):
            raise ValueError(f"Form type already exists: {code}")

        now = datetime.now(timezone.utc)
        new_ft = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code=code,
            form_type_name=name,
            form_type_description=description,
            base_template_path=ft_data.get("base_template_path"),
            mapping_version=ft_data.get("mapping_version", 1),
            is_active=True,
        )
        db.session.add(new_ft)
        db.session.flush()

        dst_id = new_ft.form_type_id
        stats = {"categories_created": 0, "subcategories_created": 0, "fields_created": 0, "choices_created": 0}

        for cat in data.get("categories") or []:
            db.session.add(MasCategoryOrder(
                category_order_id=uuid.uuid4(),
                form_type_id=dst_id,
                category_code=cat["category_code"],
                category_name=cat.get("category_name"),
                display_order=cat.get("display_order", 0),
                is_active=cat.get("is_active", True),
            ))
            stats["categories_created"] += 1

        for cat in data.get("category_display_configs") or []:
            db.session.add(MasCategoryDisplayConfig(
                category_display_config_id=uuid.uuid4(),
                form_type_id=dst_id,
                category_code=cat["category_code"],
                display_label=cat.get("display_label") or cat["category_code"],
                nav_label=(
                    cat.get("nav_label")
                    or cat.get("display_label")
                    or cat["category_code"]
                ),
                icon_name=cat.get("icon_name"),
                display_order=cat.get("display_order", 0),
                render_mode=cat.get("render_mode", "table_sections"),
                show_to_coder=cat.get("show_to_coder", True),
                show_to_reviewer=cat.get("show_to_reviewer", True),
                show_to_site_pi=cat.get("show_to_site_pi", True),
                always_include=cat.get("always_include", False),
                is_default_start=cat.get("is_default_start", False),
                is_active=cat.get("is_active", True),
            ))

        for sub in data.get("subcategories") or []:
            db.session.add(MasSubcategoryOrder(
                subcategory_order_id=uuid.uuid4(),
                form_type_id=dst_id,
                category_code=sub["category_code"],
                subcategory_code=sub["subcategory_code"],
                subcategory_name=sub.get("subcategory_name"),
                display_order=sub.get("display_order", 0),
                render_mode=sub.get("render_mode", "default"),
                is_active=sub.get("is_active", True),
            ))
            stats["subcategories_created"] += 1

        for fld in data.get("fields") or []:
            db.session.add(MasFieldDisplayConfig(
                config_id=uuid.uuid4(),
                form_type_id=dst_id,
                field_id=fld["field_id"],
                category_code=fld.get("category_code"),
                subcategory_code=fld.get("subcategory_code"),
                odk_label=fld.get("odk_label"),
                short_label=fld.get("short_label"),
                full_label=fld.get("full_label"),
                summary_label=fld.get("summary_label"),
                field_type=fld.get("field_type"),
                age_group=fld.get("age_group"),
                flip_color=fld.get("flip_color", False),
                is_info=fld.get("is_info", False),
                summary_include=fld.get("summary_include", False),
                is_pii=fld.get("is_pii", False),
                pii_type=fld.get("pii_type"),
                display_order=fld.get("display_order", 0),
                is_active=fld.get("is_active", True),
                is_custom=fld.get("is_custom", False),
            ))
            stats["fields_created"] += 1

        for ch in data.get("choices") or []:
            db.session.add(MasChoiceMappings(
                form_type_id=dst_id,
                field_id=ch["field_id"],
                choice_value=ch["choice_value"],
                choice_label=ch["choice_label"],
                display_order=ch.get("display_order", 0),
                is_active=ch.get("is_active", True),
                synced_at=now,
            ))
            stats["choices_created"] += 1

        db.session.commit()
        return new_ft, stats

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
