"""
WHO_2022_VA Data Migration Script

Migrates data from:
- resource/mapping/mapping_labels.xlsx (428 rows)
- resource/mapping/mapping_choices.xlsx (1199 rows)
- Hardcoded category order from va_preprocess_03_categoriestodisplay.py

To database tables:
- mas_form_types
- mas_category_order
- mas_subcategory_order
- mas_field_display_config
- mas_choice_mappings

This script is IDEMPOTENT - safe to run multiple times.
"""
import uuid
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasCategoryDisplayConfig,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)
from app.services.category_display_defaults import CATEGORY_DISPLAY_DEFAULTS


# Category display order from va_preprocess_03_categoriestodisplay.py
WHO_2022_CATEGORIES = [
    "vainterviewdetails",
    "vademographicdetails",
    "vaneonatalperioddetails",
    "vainjuriesdetails",
    "vahealthhistorydetails",
    "vageneralsymptoms",
    "varespiratorycardiacsymptoms",
    "vaabdominalsymptoms",
    "vaneurologicalsymptoms",
    "vaskinmucosalsymptoms",
    "vaneonatalfeedingsymptoms",
    "vamaternalsymptoms",
    "vahealthserviceutilisation",
    "vanarrationanddocuments",
]

def _str_or_none(val) -> str | None:
    """Convert a pandas cell value to stripped string or None if NaN/empty."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


CATEGORY_NAMES = {
    "vainterviewdetails": "Interview Details",
    "vademographicdetails": "Demographic Details",
    "vaneonatalperioddetails": "Neonatal Period Details",
    "vainjuriesdetails": "Injuries Details",
    "vahealthhistorydetails": "Health History Details",
    "vageneralsymptoms": "General Symptoms",
    "varespiratorycardiacsymptoms": "Respiratory / Cardiac Symptoms",
    "vaabdominalsymptoms": "Abdominal Symptoms",
    "vaneurologicalsymptoms": "Neurological Symptoms",
    "vaskinmucosalsymptoms": "Skin / Mucosal Symptoms",
    "vaneonatalfeedingsymptoms": "Neonatal Feeding Symptoms",
    "vamaternalsymptoms": "Maternal Symptoms",
    "vahealthserviceutilisation": "Health Service Utilisation",
    "vanarrationanddocuments": "Narration and Documents",
}


class Who2022VaMigrator:
    """Handles migration of WHO_2022_VA data from Excel to database."""

    FORM_TYPE_CODE = "WHO_2022_VA"
    FORM_TYPE_NAME = "WHO 2022 VA Form"

    def __init__(self):
        self.resource_path = Path("resource/mapping")
        self.stats = {
            "categories": 0,
            "category_display_configs": 0,
            "subcategories": 0,
            "fields": 0,
            "choices": 0,
            "errors": [],
        }

    def run(self):
        """Execute full migration."""
        print(f"\n{'='*60}")
        print("WHO_2022_VA Data Migration")
        print(f"{'='*60}\n")

        try:
            # Step 1: Create form type
            form_type = self._create_form_type()
            print(f"[OK] Form type: {form_type.form_type_code}")

            # Step 2: Migrate categories
            self._migrate_categories(form_type)
            print(f"[OK] Categories: {self.stats['categories']}")

            # Step 3: Migrate field configs (includes sub-categories)
            self._migrate_field_configs(form_type)
            print(f"[OK] Sub-categories: {self.stats['subcategories']}")
            print(f"[OK] Field configs: {self.stats['fields']}")

            # Step 4: Migrate category display configs
            self._migrate_category_display_configs(form_type)
            print(f"[OK] Category display configs: {self.stats['category_display_configs']}")

            # Step 5: Migrate choice mappings
            self._migrate_choices(form_type)
            print(f"[OK] Choice mappings: {self.stats['choices']}")

            # Commit all changes
            db.session.commit()
            print(f"\n{'='*60}")
            print("Migration completed successfully!")
            print(f"{'='*60}\n")

            return True

        except Exception as e:
            db.session.rollback()
            print(f"\n[ERROR] Migration failed: {e}")
            self.stats["errors"].append(str(e))
            raise

    def _create_form_type(self) -> MasFormTypes:
        """Create or get WHO_2022_VA form type."""
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(
                MasFormTypes.form_type_code == self.FORM_TYPE_CODE
            )
        )

        if form_type:
            print(f"[INFO] Form type already exists, updating...")
            form_type.updated_at = datetime.now(timezone.utc)
        else:
            form_type = MasFormTypes(
                form_type_id=uuid.uuid4(),
                form_type_code=self.FORM_TYPE_CODE,
                form_type_name=self.FORM_TYPE_NAME,
                form_type_description="World Health Organization 2022 Verbal Autopsy Form",
                base_template_path="resource/mapping/mapping_labels.xlsx",
                mapping_version=1,
                is_active=True,
            )
            db.session.add(form_type)

        db.session.flush()
        return form_type

    def _migrate_categories(self, form_type: MasFormTypes):
        """Migrate category order from hardcoded list."""
        for order, category_code in enumerate(WHO_2022_CATEGORIES, start=1):
            existing = db.session.scalar(
                db.select(MasCategoryOrder).where(
                    MasCategoryOrder.form_type_id == form_type.form_type_id,
                    MasCategoryOrder.category_code == category_code,
                )
            )

            if existing:
                existing.display_order = order
                existing.category_name = CATEGORY_NAMES.get(category_code, category_code)
                existing.is_active = True
            else:
                category = MasCategoryOrder(
                    category_order_id=uuid.uuid4(),
                    form_type_id=form_type.form_type_id,
                    category_code=category_code,
                    category_name=CATEGORY_NAMES.get(category_code, category_code),
                    display_order=order,
                    is_active=True,
                )
                db.session.add(category)

            self.stats["categories"] += 1

        db.session.flush()

    def _migrate_field_configs(self, form_type: MasFormTypes):
        """Migrate field display configurations from mapping_labels.xlsx.

        Excel columns:
          category, sub_category, sub-parts, permission, flip_color, is_info,
          summary_include, name (field_id), agegroup, short_label, summary_label,
          coder_value, coder_positive, coder_negative, label (full_label), type, relevant
        """
        labels_path = self.resource_path / "mapping_labels.xlsx"

        if not labels_path.exists():
            raise FileNotFoundError(f"Labels file not found: {labels_path}")

        df = pd.read_excel(labels_path)

        # Track unique sub-categories and their per-category display order
        seen_subcategories: set[tuple[str, str]] = set()
        subcat_order: dict[str, int] = {}  # category_code -> next order

        for display_order, (_, row) in enumerate(df.iterrows(), start=1):
            name_val = row.get("name")
            if pd.isna(name_val):
                continue
            field_id = str(name_val).strip()
            if not field_id:
                continue

            category_code = _str_or_none(row.get("category"))
            subcategory_code = _str_or_none(row.get("sub_category"))
            full_label = _str_or_none(row.get("label"))
            short_label = _str_or_none(row.get("short_label"))
            summary_label = _str_or_none(row.get("summary_label"))
            field_type = _str_or_none(row.get("type"))
            age_group = _str_or_none(row.get("agegroup"))

            flip_color = bool(row.get("flip_color")) if pd.notna(row.get("flip_color")) else False
            is_info = bool(row.get("is_info")) if pd.notna(row.get("is_info")) else False
            summary_include = bool(row.get("summary_include")) if pd.notna(row.get("summary_include")) else False

            # Create sub-category if needed
            if category_code and subcategory_code:
                subcat_key = (category_code, subcategory_code)
                if subcat_key not in seen_subcategories:
                    next_order = subcat_order.get(category_code, 0) + 1
                    subcat_order[category_code] = next_order
                    self._create_subcategory(form_type, category_code, subcategory_code, next_order)
                    seen_subcategories.add(subcat_key)

            # Create or update field config
            existing = db.session.scalar(
                db.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            )

            if existing:
                existing.category_code = category_code
                existing.subcategory_code = subcategory_code
                existing.short_label = short_label
                existing.full_label = full_label
                existing.summary_label = summary_label
                existing.field_type = field_type
                existing.age_group = age_group
                existing.flip_color = flip_color
                existing.is_info = is_info
                existing.summary_include = summary_include
                existing.display_order = display_order
                existing.updated_at = datetime.now(timezone.utc)
            else:
                config = MasFieldDisplayConfig(
                    config_id=uuid.uuid4(),
                    form_type_id=form_type.form_type_id,
                    field_id=field_id,
                    category_code=category_code,
                    subcategory_code=subcategory_code,
                    short_label=short_label,
                    full_label=full_label,
                    summary_label=summary_label,
                    field_type=field_type,
                    age_group=age_group,
                    flip_color=flip_color,
                    is_info=is_info,
                    summary_include=summary_include,
                    display_order=display_order,
                    is_active=True,
                    is_custom=False,
                )
                db.session.add(config)

            self.stats["fields"] += 1

        db.session.flush()

    def _migrate_category_display_configs(self, form_type: MasFormTypes):
        """Create deterministic category-level display metadata."""
        categories = db.session.scalars(
            db.select(MasCategoryOrder)
            .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
            .order_by(MasCategoryOrder.display_order)
        ).all()

        for category in categories:
            defaults = CATEGORY_DISPLAY_DEFAULTS.get(category.category_code, {})
            existing = db.session.scalar(
                db.select(MasCategoryDisplayConfig).where(
                    MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                    MasCategoryDisplayConfig.category_code == category.category_code,
                )
            )

            values = {
                "display_label": defaults.get(
                    "display_label",
                    category.category_name or category.category_code,
                ),
                "nav_label": defaults.get(
                    "nav_label",
                    category.category_name or category.category_code,
                ),
                "icon_name": defaults.get("icon_name"),
                "display_order": category.display_order,
                "render_mode": defaults.get("render_mode", "table_sections"),
                "show_to_coder": defaults.get("show_to_coder", True),
                "show_to_reviewer": defaults.get("show_to_reviewer", True),
                "show_to_site_pi": defaults.get("show_to_site_pi", True),
                "always_include": defaults.get("always_include", False),
                "is_default_start": defaults.get("is_default_start", False),
                "is_active": category.is_active,
            }

            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                db.session.add(
                    MasCategoryDisplayConfig(
                        category_display_config_id=uuid.uuid4(),
                        form_type_id=form_type.form_type_id,
                        category_code=category.category_code,
                        **values,
                    )
                )

            self.stats["category_display_configs"] += 1

        db.session.flush()

    def _create_subcategory(self, form_type: MasFormTypes,
                            category_code: str, subcategory_code: str, display_order: int):
        """Create sub-category if it doesn't exist."""
        existing = db.session.scalar(
            db.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == subcategory_code,
            )
        )

        if not existing:
            subcategory = MasSubcategoryOrder(
                subcategory_order_id=uuid.uuid4(),
                form_type_id=form_type.form_type_id,
                category_code=category_code,
                subcategory_code=subcategory_code,
                subcategory_name=subcategory_code,
                display_order=display_order,
                is_active=True,
            )
            db.session.add(subcategory)

        self.stats["subcategories"] += 1

    def _migrate_choices(self, form_type: MasFormTypes):
        """Migrate choice mappings from mapping_choices.xlsx.

        Excel columns:
          category (field_id), name (choice_value), short_label (choice_label)
        """
        choices_path = self.resource_path / "mapping_choices.xlsx"

        if not choices_path.exists():
            raise FileNotFoundError(f"Choices file not found: {choices_path}")

        df = pd.read_excel(choices_path)

        field_order: dict[str, int] = {}

        for _, row in df.iterrows():
            field_id = _str_or_none(row.get("category"))
            choice_value = _str_or_none(row.get("name"))
            choice_label = _str_or_none(row.get("short_label")) or ""

            if not field_id or not choice_value:
                continue

            field_order[field_id] = field_order.get(field_id, 0) + 1

            existing = db.session.scalar(
                db.select(MasChoiceMappings).where(
                    MasChoiceMappings.form_type_id == form_type.form_type_id,
                    MasChoiceMappings.field_id == field_id,
                    MasChoiceMappings.choice_value == choice_value,
                )
            )

            if existing:
                existing.choice_label = choice_label
                existing.display_order = field_order[field_id]
                existing.is_active = True
                existing.synced_at = datetime.now(timezone.utc)
            else:
                choice = MasChoiceMappings(
                    choice_id=uuid.uuid4(),
                    form_type_id=form_type.form_type_id,
                    field_id=field_id,
                    choice_value=choice_value,
                    choice_label=choice_label,
                    display_order=field_order[field_id],
                    is_active=True,
                )
                db.session.add(choice)

            self.stats["choices"] += 1

        db.session.flush()


def run_migration():
    """Entry point for migration script."""
    from app import create_app

    app = create_app()
    with app.app_context():
        migrator = Who2022VaMigrator()
        success = migrator.run()
        return success


if __name__ == "__main__":
    import sys
    success = run_migration()
    sys.exit(0 if success else 1)
