---
title: Phase 7 - Admin UI
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
phase: 7
estimated_duration: 2 days
risk_level: important
priority: P1
---

# Phase 7: Admin UI

## Objective

Create a **seamless, fast, intuitive, HTMX-based** admin UI for managing field mappings, form types, and ODK synchronization.

## Why This Matters

The Admin UI is **critical** for system usability. Users need to:
- Configure form types without touching code
- Manage field display settings
- Sync choices from ODK Central
- Mark PII fields
- All without developer intervention

**Key Requirements:**
- **Seamless** - No page reloads, instant feedback
- **Fast** - HTMX partial updates, minimal data transfer
- **Intuitive** - Self-explanatory interface, minimal training
- **Responsive** - Works on desktop, tablet, and mobile

## Prerequisites

- [ ] Phase 6 completed (multi-form-type support)
- [ ] Admin user role/permissions in place
- [ ] HTMX and Bootstrap 5 available in templates

## Deliverables

1. Admin dashboard for field mapping management
2. Form type management UI
3. Category/field configuration UI
4. Choice mapping management UI
5. ODK sync trigger UI
6. PII field marking UI
7. Responsive design for mobile/tablet

---

## Design Principles

```
┌─────────────────────────────────────────────────────────────────────┐
│ ADMIN UI DESIGN PRINCIPLES                                          │
│                                                                      │
│  1. HTMX-POWERED                                                     │
│     - No full page reloads                                          │
│     - Partial updates via hx-get, hx-post                          │
│     - Real-time feedback with hx-indicator                         │
│                                                                      │
│  2. RESPONSIVE                                                       │
│     - Mobile-first design                                           │
│     - Bootstrap 5 grid system                                       │
│     - Touch-friendly controls                                       │
│                                                                      │
│  3. ACCESSIBLE                                                       │
│     - ARIA labels                                                    │
│     - Keyboard navigation                                           │
│     - Clear visual feedback                                         │
│                                                                      │
│  4. PROGRESSIVE ENHANCEMENT                                         │
│     - Works without JavaScript (fallback)                          │
│     - Enhanced with HTMX when available                            │
│                                                                      │
│  5. CONSISTENT WITH EXISTING UI                                     │
│     - Match current admin styles                                    │
│     - Use existing components where possible                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step 7.1: Admin Routes Blueprint

**File**: `app/routes/admin_field_mapping.py`

```python
"""
Admin routes for field mapping management.

All routes require admin role.
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import select

from app import db
from app.models import (
    MasFormTypes,
    MasCategoryOrder,
    MasSubcategoryOrder,
    MasFieldDisplayConfig,
    MasChoiceMappings,
)
from app.services.field_mapping_service import get_mapping_service
from app.services.form_type_service import get_form_type_service
from app.services.odk_schema_sync_service import get_sync_service
from app.utils.decorators import admin_required

bp = Blueprint("admin_field_mapping", __name__, url_prefix="/admin/field-mapping")


@bp.route("/")
@login_required
@admin_required
def dashboard():
    """Admin dashboard for field mapping."""
    service = get_form_type_service()
    form_types = service.list_form_types()

    stats = []
    for ft in form_types:
        stats.append(service.get_form_type_stats(ft.form_type_code))

    return render_template(
        "admin/field_mapping/dashboard.html",
        form_types=form_types,
        stats=stats,
    )


# =============================================================================
# FORM TYPE MANAGEMENT
# =============================================================================

@bp.route("/form-types")
@login_required
@admin_required
def form_types_list():
    """List all form types (HTMX partial)."""
    service = get_form_type_service()
    form_types = service.list_form_types()

    if request.headers.get("HX-Request"):
        return render_template(
            "admin/field_mapping/partials/form_types_list.html",
            form_types=form_types,
        )

    return render_template(
        "admin/field_mapping/form_types.html",
        form_types=form_types,
    )


@bp.route("/form-types/<form_type_code>")
@login_required
@admin_required
def form_type_detail(form_type_code):
    """Form type detail page."""
    service = get_form_type_service()
    mapping_service = get_mapping_service()

    form_type = service.get_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    stats = service.get_form_type_stats(form_type_code)
    categories = mapping_service.get_categories(form_type_code)

    return render_template(
        "admin/field_mapping/form_type_detail.html",
        form_type=form_type,
        stats=stats,
        categories=categories,
    )


# =============================================================================
# CATEGORY MANAGEMENT
# =============================================================================

@bp.route("/form-types/<form_type_code>/categories")
@login_required
@admin_required
def categories_list(form_type_code):
    """List categories for a form type (HTMX partial)."""
    mapping_service = get_mapping_service()
    categories = mapping_service.get_categories_to_display(form_type_code)

    if request.headers.get("HX-Request"):
        return render_template(
            "admin/field_mapping/partials/categories_list.html",
            form_type_code=form_type_code,
            categories=categories,
        )

    return render_template(
        "admin/field_mapping/categories.html",
        form_type_code=form_type_code,
        categories=categories,
    )


@bp.route("/form-types/<form_type_code>/categories/<category_code>/reorder",
          methods=["POST"])
@login_required
@admin_required
def category_reorder(form_type_code, category_code):
    """Reorder a category."""
    new_order = request.form.get("display_order", type=int)

    if new_order is None:
        return "Missing display_order", 400

    form_type = db.session.scalar(
        select(MasFormTypes).where(
            MasFormTypes.form_type_code == form_type_code
        )
    )

    if not form_type:
        return "Form type not found", 404

    category = db.session.scalar(
        select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )

    if not category:
        return "Category not found", 404

    old_order = category.display_order
    category.display_order = new_order

    # Adjust other categories
    if new_order > old_order:
        # Moving down - shift others up
        db.session.execute(
            db.update(MasCategoryOrder)
            .where(
                MasCategoryOrder.form_type_id == form_type.form_type_id,
                MasCategoryOrder.display_order > old_order,
                MasCategoryOrder.display_order <= new_order,
            )
            .values(display_order=MasCategoryOrder.display_order - 1)
        )
    else:
        # Moving up - shift others down
        db.session.execute(
            db.update(MasCategoryOrder)
            .where(
                MasCategoryOrder.form_type_id == form_type.form_type_id,
                MasCategoryOrder.display_order >= new_order,
                MasCategoryOrder.display_order < old_order,
            )
            .values(display_order=MasCategoryOrder.display_order + 1)
        )

    db.session.commit()

    # Return updated list
    mapping_service = get_mapping_service()
    categories = mapping_service.get_categories(form_type_code)

    return render_template(
        "admin/field_mapping/partials/categories_list.html",
        form_type_code=form_type_code,
        categories=categories,
    )


# =============================================================================
# FIELD CONFIG MANAGEMENT
# =============================================================================

@bp.route("/form-types/<form_type_code>/fields")
@login_required
@admin_required
def fields_list(form_type_code):
    """List all fields for a form type with filters."""
    category_filter = request.args.get("category")
    search = request.args.get("search", "").strip()

    query = select(MasFieldDisplayConfig).join(MasFormTypes).where(
        MasFormTypes.form_type_code == form_type_code,
        MasFieldDisplayConfig.is_active == True,
    )

    if category_filter:
        query = query.where(MasFieldDisplayConfig.category_code == category_filter)

    if search:
        query = query.where(
            db.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            )
        )

    query = query.order_by(
        MasFieldDisplayConfig.category_code,
        MasFieldDisplayConfig.display_order,
    )

    fields = db.session.scalars(query).all()

    if request.headers.get("HX-Request"):
        return render_template(
            "admin/field_mapping/partials/fields_list.html",
            form_type_code=form_type_code,
            fields=fields,
        )

    return render_template(
        "admin/field_mapping/fields.html",
        form_type_code=form_type_code,
        fields=fields,
        category_filter=category_filter,
        search=search,
    )


@bp.route("/form-types/<form_type_code>/fields/<field_id>/edit",
          methods=["GET", "POST"])
@login_required
@admin_required
def field_edit(form_type_code, field_id):
    """Edit a field's display configuration."""
    field = db.session.scalar(
        select(MasFieldDisplayConfig).join(MasFormTypes).where(
            MasFormTypes.form_type_code == form_type_code,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )

    if not field:
        return "Field not found", 404

    if request.method == "POST":
        field.short_label = request.form.get("short_label") or None
        field.full_label = request.form.get("full_label") or None
        field.summary_label = request.form.get("summary_label") or None
        field.flip_color = request.form.get("flip_color") == "on"
        field.is_info = request.form.get("is_info") == "on"
        field.summary_include = request.form.get("summary_include") == "on"
        field.is_pii = request.form.get("is_pii") == "on"
        field.pii_type = request.form.get("pii_type") or None

        db.session.commit()

        if request.headers.get("HX-Request"):
            return render_template(
                "admin/field_mapping/partials/field_row.html",
                form_type_code=form_type_code,
                field=field,
            )

        return redirect(url_for(".fields_list", form_type_code=form_type_code))

    return render_template(
        "admin/field_mapping/partials/field_edit_form.html",
        form_type_code=form_type_code,
        field=field,
    )


# =============================================================================
# CHOICE MAPPING MANAGEMENT
# =============================================================================

@bp.route("/form-types/<form_type_code>/fields/<field_id>/choices")
@login_required
@admin_required
def choices_list(form_type_code, field_id):
    """List choices for a field."""
    mapping_service = get_mapping_service()
    choices = mapping_service.get_choices_for_field(form_type_code, field_id)

    if request.headers.get("HX-Request"):
        return render_template(
            "admin/field_mapping/partials/choices_list.html",
            form_type_code=form_type_code,
            field_id=field_id,
            choices=choices,
        )

    return render_template(
        "admin/field_mapping/choices.html",
        form_type_code=form_type_code,
        field_id=field_id,
        choices=choices,
    )


@bp.route("/form-types/<form_type_code>/fields/<field_id>/choices/<choice_value>/edit",
          methods=["POST"])
@login_required
@admin_required
def choice_edit(form_type_code, field_id, choice_value):
    """Edit a choice label."""
    choice = db.session.scalar(
        select(MasChoiceMappings).join(MasFormTypes).where(
            MasFormTypes.form_type_code == form_type_code,
            MasChoiceMappings.field_id == field_id,
            MasChoiceMappings.choice_value == choice_value,
        )
    )

    if not choice:
        return "Choice not found", 404

    choice.choice_label = request.form.get("choice_label", choice.choice_label)
    db.session.commit()

    mapping_service = get_mapping_service()
    choices = mapping_service.get_choices_for_field(form_type_code, field_id)

    return render_template(
        "admin/field_mapping/partials/choices_list.html",
        form_type_code=form_type_code,
        field_id=field_id,
        choices=choices,
    )


# =============================================================================
# ODK SYNC
# =============================================================================

@bp.route("/form-types/<form_type_code>/sync", methods=["GET", "POST"])
@login_required
@admin_required
def odk_sync(form_type_code):
    """Trigger ODK schema sync."""
    if request.method == "POST":
        project_id = request.form.get("project_id", type=int)
        form_id = request.form.get("form_id")

        if not project_id or not form_id:
            return "Missing project_id or form_id", 400

        sync_service = get_sync_service()
        stats = sync_service.sync_form_choices(form_type_code, project_id, form_id)

        return render_template(
            "admin/field_mapping/partials/sync_result.html",
            form_type_code=form_type_code,
            stats=stats,
        )

    # GET - show sync form
    changes = None
    project_id = request.args.get("project_id", type=int)
    form_id = request.args.get("form_id")

    if project_id and form_id:
        sync_service = get_sync_service()
        changes = sync_service.detect_schema_changes(form_type_code, project_id, form_id)

    return render_template(
        "admin/field_mapping/partials/sync_form.html",
        form_type_code=form_type_code,
        project_id=project_id,
        form_id=form_id,
        changes=changes,
    )


# =============================================================================
# PII MANAGEMENT
# =============================================================================

@bp.route("/form-types/<form_type_code>/pii")
@login_required
@admin_required
def pii_fields(form_type_code):
    """Manage PII field marking."""
    mapping_service = get_mapping_service()

    # Get all fields, marking which are PII
    form_type = db.session.scalar(
        select(MasFormTypes).where(
            MasFormTypes.form_type_code == form_type_code
        )
    )

    if not form_type:
        return "Form type not found", 404

    fields = db.session.scalars(
        select(MasFieldDisplayConfig)
        .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
        .order_by(MasFieldDisplayConfig.category_code, MasFieldDisplayConfig.field_id)
    ).all()

    pii_types = ["name", "location", "identifier", "date", "contact", "other"]

    if request.headers.get("HX-Request"):
        return render_template(
            "admin/field_mapping/partials/pii_fields_list.html",
            form_type_code=form_type_code,
            fields=fields,
            pii_types=pii_types,
        )

    return render_template(
        "admin/field_mapping/pii_fields.html",
        form_type_code=form_type_code,
        fields=fields,
        pii_types=pii_types,
    )


@bp.route("/form-types/<form_type_code>/fields/<field_id>/pii",
          methods=["POST"])
@login_required
@admin_required
def field_pii_toggle(form_type_code, field_id):
    """Toggle PII status for a field."""
    field = db.session.scalar(
        select(MasFieldDisplayConfig).join(MasFormTypes).where(
            MasFormTypes.form_type_code == form_type_code,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )

    if not field:
        return "Field not found", 404

    field.is_pii = request.form.get("is_pii") == "on"
    field.pii_type = request.form.get("pii_type") if field.is_pii else None

    db.session.commit()

    return render_template(
        "admin/field_mapping/partials/field_pii_row.html",
        form_type_code=form_type_code,
        field=field,
        pii_types=["name", "location", "identifier", "date", "contact", "other"],
    )


def init_app(app):
    """Register blueprint with app."""
    app.register_blueprint(bp)
```

---

## Step 7.2: Admin Templates

### Dashboard Template

**File**: `app/templates/admin/field_mapping/dashboard.html`

```html
{% extends "admin/base.html" %}

{% block title %}Field Mapping Admin{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <div class="row mb-4">
        <div class="col-12">
            <h1 class="h3">
                <i class="bi bi-diagram-3 me-2"></i>
                Field Mapping Administration
            </h1>
            <p class="text-muted">
                Manage form types, field configurations, and choice mappings.
            </p>
        </div>
    </div>

    <!-- Form Types Summary Cards -->
    <div class="row mb-4" id="form-types-cards">
        {% for stat in stats %}
        <div class="col-md-6 col-lg-4 mb-3">
            <div class="card h-100">
                <div class="card-body">
                    <h5 class="card-title">
                        <a href="{{ url_for('.form_type_detail', form_type_code=stat.form_type_code) }}"
                           class="text-decoration-none">
                            {{ stat.form_type_name }}
                        </a>
                    </h5>
                    <p class="card-text text-muted small">
                        {{ stat.form_type_code }}
                    </p>
                    <div class="d-flex justify-content-between text-center mt-3">
                        <div>
                            <div class="h5 mb-0">{{ stat.category_count }}</div>
                            <small class="text-muted">Categories</small>
                        </div>
                        <div>
                            <div class="h5 mb-0">{{ stat.field_count }}</div>
                            <small class="text-muted">Fields</small>
                        </div>
                        <div>
                            <div class="h5 mb-0">{{ stat.form_count }}</div>
                            <small class="text-muted">Forms</small>
                        </div>
                    </div>
                </div>
                <div class="card-footer bg-transparent">
                    <a href="{{ url_for('.form_type_detail', form_type_code=stat.form_type_code) }}"
                       class="btn btn-outline-primary btn-sm">
                        Manage
                    </a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>

    <!-- Quick Actions -->
    <div class="row">
        <div class="col-12">
            <h2 class="h5 mb-3">Quick Actions</h2>
        </div>
        <div class="col-md-4 mb-3">
            <a href="{{ url_for('.form_types_list') }}"
               class="btn btn-outline-secondary w-100">
                <i class="bi bi-file-earmark-plus me-2"></i>
                Register New Form Type
            </a>
        </div>
        <div class="col-md-4 mb-3">
            <a href="{{ url_for('.odk_sync', form_type_code='WHO_2022_VA') }}"
               class="btn btn-outline-secondary w-100">
                <i class="bi bi-arrow-repeat me-2"></i>
                Sync from ODK Central
            </a>
        </div>
        <div class="col-md-4 mb-3">
            <a href="{{ url_for('.pii_fields', form_type_code='WHO_2022_VA') }}"
               class="btn btn-outline-secondary w-100">
                <i class="bi bi-shield-lock me-2"></i>
                Manage PII Fields
            </a>
        </div>
    </div>
</div>
{% endblock %}
```

### Form Type Detail Template

**File**: `app/templates/admin/field_mapping/form_type_detail.html`

```html
{% extends "admin/base.html" %}

{% block title %}{{ form_type.form_type_name }} - Field Mapping{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <!-- Breadcrumb -->
    <nav aria-label="breadcrumb" class="mb-3">
        <ol class="breadcrumb">
            <li class="breadcrumb-item">
                <a href="{{ url_for('.dashboard') }}">Field Mapping</a>
            </li>
            <li class="breadcrumb-item active">{{ form_type.form_type_name }}</li>
        </ol>
    </nav>

    <!-- Header -->
    <div class="row mb-4">
        <div class="col-md-8">
            <h1 class="h3">{{ form_type.form_type_name }}</h1>
            <p class="text-muted">{{ form_type.form_type_description or 'No description' }}</p>
        </div>
        <div class="col-md-4 text-md-end">
            <a href="{{ url_for('.odk_sync', form_type_code=form_type.form_type_code) }}"
               class="btn btn-primary"
               hx-get="{{ url_for('.odk_sync', form_type_code=form_type.form_type_code) }}"
               hx-target="#sync-modal-body"
               data-bs-toggle="modal"
               data-bs-target="#syncModal">
                <i class="bi bi-arrow-repeat me-2"></i>
                Sync from ODK
            </a>
        </div>
    </div>

    <!-- Stats Cards -->
    <div class="row mb-4">
        <div class="col-md-3 mb-3">
            <div class="card bg-light">
                <div class="card-body text-center">
                    <div class="h2 mb-0">{{ stats.category_count }}</div>
                    <small class="text-muted">Categories</small>
                </div>
            </div>
        </div>
        <div class="col-md-3 mb-3">
            <div class="card bg-light">
                <div class="card-body text-center">
                    <div class="h2 mb-0">{{ stats.field_count }}</div>
                    <small class="text-muted">Fields</small>
                </div>
            </div>
        </div>
        <div class="col-md-3 mb-3">
            <div class="card bg-light">
                <div class="card-body text-center">
                    <div class="h2 mb-0">{{ stats.form_count }}</div>
                    <small class="text-muted">Forms Using</small>
                </div>
            </div>
        </div>
        <div class="col-md-3 mb-3">
            <div class="card bg-light">
                <div class="card-body text-center">
                    <div class="h2 mb-0">{{ 'Active' if stats.is_active else 'Inactive' }}</div>
                    <small class="text-muted">Status</small>
                </div>
            </div>
        </div>
    </div>

    <!-- Categories List -->
    <div class="row">
        <div class="col-12">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h2 class="h5 mb-0">Categories</h2>
                    <span class="badge bg-secondary">{{ categories|length }} categories</span>
                </div>
                <div class="card-body p-0" id="categories-container"
                     hx-get="{{ url_for('.categories_list', form_type_code=form_type.form_type_code) }}"
                     hx-trigger="load">
                    <div class="text-center py-4">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Sync Modal -->
<div class="modal fade" id="syncModal" tabindex="-1">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Sync from ODK Central</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body" id="sync-modal-body">
                <!-- Loaded via HTMX -->
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

### Categories List Partial (HTMX)

**File**: `app/templates/admin/field_mapping/partials/categories_list.html`

```html
<div class="list-group list-group-flush">
    {% for cat in categories %}
    <div class="list-group-item d-flex justify-content-between align-items-center">
        <div>
            <span class="badge bg-secondary me-2">{{ cat.display_order }}</span>
            <strong>{{ cat.category_name }}</strong>
            <small class="text-muted ms-2">{{ cat.category_code }}</small>
        </div>
        <div>
            <span class="badge bg-light text-dark me-2">
                {{ cat.fields|length }} fields
            </span>
            <div class="btn-group btn-group-sm">
                <a href="{{ url_for('.fields_list', form_type_code=form_type_code, category=cat.category_code) }}"
                   class="btn btn-outline-primary"
                   title="View Fields">
                    <i class="bi bi-list-ul"></i>
                </a>
                <button class="btn btn-outline-secondary"
                        title="Reorder (coming soon)"
                        disabled>
                    <i class="bi bi-arrow-up-down"></i>
                </button>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
```

### Fields List with Search (HTMX)

**File**: `app/templates/admin/field_mapping/fields.html`

```html
{% extends "admin/base.html" %}

{% block title %}Fields - {{ form_type_code }}{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <!-- Search and Filter -->
    <div class="row mb-4">
        <div class="col-md-6">
            <div class="input-group">
                <span class="input-group-text">
                    <i class="bi bi-search"></i>
                </span>
                <input type="text"
                       class="form-control"
                       placeholder="Search fields..."
                       name="search"
                       value="{{ search }}"
                       hx-get="{{ url_for('.fields_list', form_type_code=form_type_code) }}"
                       hx-trigger="keyup changed delay:300ms"
                       hx-target="#fields-container"
                       hx-indicator="#search-spinner">
                <span class="input-group-text" id="search-spinner">
                    <span class="spinner-border spinner-border-sm htmx-indicator"></span>
                </span>
            </div>
        </div>
        <div class="col-md-3">
            <select class="form-select"
                    name="category"
                    hx-get="{{ url_for('.fields_list', form_type_code=form_type_code) }}"
                    hx-trigger="change"
                    hx-target="#fields-container">
                <option value="">All Categories</option>
                <!-- Categories loaded dynamically -->
            </select>
        </div>
    </div>

    <!-- Fields List -->
    <div id="fields-container">
        {% include "admin/field_mapping/partials/fields_list.html" %}
    </div>
</div>
{% endblock %}
```

### Field Edit Form (HTMX Modal)

**File**: `app/templates/admin/field_mapping/partials/field_edit_form.html`

```html
<form hx-post="{{ url_for('.field_edit', form_type_code=form_type_code, field_id=field.field_id) }}"
      hx-target="closest tr"
      hx-swap="outerHTML">
    <div class="modal-header">
        <h5 class="modal-title">Edit Field: {{ field.field_id }}</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

        <div class="mb-3">
            <label class="form-label">Field ID</label>
            <input type="text" class="form-control" value="{{ field.field_id }}" disabled>
        </div>

        <div class="mb-3">
            <label class="form-label">Short Label</label>
            <input type="text" class="form-control" name="short_label"
                   value="{{ field.short_label or '' }}">
        </div>

        <div class="mb-3">
            <label class="form-label">Full Label</label>
            <textarea class="form-control" name="full_label" rows="2">{{ field.full_label or '' }}</textarea>
        </div>

        <div class="row mb-3">
            <div class="col-md-6">
                <div class="form-check">
                    <input type="checkbox" class="form-check-input" name="flip_color"
                           id="flip_color" {% if field.flip_color %}checked{% endif %}>
                    <label class="form-check-label" for="flip_color">Flip Color</label>
                </div>
            </div>
            <div class="col-md-6">
                <div class="form-check">
                    <input type="checkbox" class="form-check-input" name="is_info"
                           id="is_info" {% if field.is_info %}checked{% endif %}>
                    <label class="form-check-label" for="is_info">Is Info Field</label>
                </div>
            </div>
        </div>

        <div class="row mb-3">
            <div class="col-md-6">
                <div class="form-check">
                    <input type="checkbox" class="form-check-input" name="summary_include"
                           id="summary_include" {% if field.summary_include %}checked{% endif %}>
                    <label class="form-check-label" for="summary_include">Include in Summary</label>
                </div>
            </div>
            <div class="col-md-6">
                <div class="form-check">
                    <input type="checkbox" class="form-check-input" name="is_pii"
                           id="is_pii" {% if field.is_pii %}checked{% endif %}>
                    <label class="form-check-label" for="is_pii">PII Field</label>
                </div>
            </div>
        </div>

        <div class="mb-3" id="pii-type-container" {% if not field.is_pii %}style="display:none"{% endif %}>
            <label class="form-label">PII Type</label>
            <select class="form-select" name="pii_type">
                <option value="">Select type...</option>
                <option value="name" {% if field.pii_type == 'name' %}selected{% endif %}>Name</option>
                <option value="location" {% if field.pii_type == 'location' %}selected{% endif %}>Location</option>
                <option value="identifier" {% if field.pii_type == 'identifier' %}selected{% endif %}>Identifier</option>
                <option value="date" {% if field.pii_type == 'date' %}selected{% endif %}>Date</option>
                <option value="contact" {% if field.pii_type == 'contact' %}selected{% endif %}>Contact</option>
                <option value="other" {% if field.pii_type == 'other' %}selected{% endif %}>Other</option>
            </select>
        </div>
    </div>
    <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="submit" class="btn btn-primary">Save Changes</button>
    </div>
</form>

<script>
// Show/hide PII type based on checkbox
document.getElementById('is_pii').addEventListener('change', function() {
    document.getElementById('pii-type-container').style.display = this.checked ? 'block' : 'none';
});
</script>
```

### Sync Form (HTMX)

**File**: `app/templates/admin/field_mapping/partials/sync_form.html`

```html
<form hx-post="{{ url_for('.odk_sync', form_type_code=form_type_code) }}"
      hx-target="#sync-result">
    <div class="mb-3">
        <label class="form-label">ODK Project ID</label>
        <input type="number" class="form-control" name="project_id"
               value="{{ project_id or '' }}" required>
    </div>

    <div class="mb-3">
        <label class="form-label">ODK Form ID</label>
        <input type="text" class="form-control" name="form_id"
               value="{{ form_id or '' }}" required
               placeholder="e.g., WHO_2022_VA">
    </div>

    <div class="mb-3">
        <button type="button"
                class="btn btn-outline-secondary btn-sm"
                hx-get="{{ url_for('.odk_sync', form_type_code=form_type_code) }}"
                hx-include="input[name='project_id'], input[name='form_id']"
                hx-target="#changes-preview">
            <i class="bi bi-search me-1"></i>
            Preview Changes
        </button>
    </div>

    <div id="changes-preview" class="mb-3">
        {% if changes %}
        <div class="alert alert-info">
            <h6>Detected Changes:</h6>
            <ul class="mb-0">
                <li>New fields: {{ changes.new_fields|length }}</li>
                <li>Removed fields: {{ changes.removed_fields|length }}</li>
                <li>New choices: {{ changes.new_choices|length }}</li>
                <li>Removed choices: {{ changes.removed_choices|length }}</li>
            </ul>
        </div>
        {% endif %}
    </div>

    <button type="submit" class="btn btn-primary">
        <i class="bi bi-arrow-repeat me-1"></i>
        Sync Now
    </button>
</form>

<div id="sync-result" class="mt-3">
    <!-- Sync result loaded here -->
</div>
```

---

## Step 7.3: Register Blueprint

**File**: `app/__init__.py` (add to create_app)

```python
from app.routes.admin_field_mapping import bp as admin_field_mapping_bp
app.register_blueprint(admin_field_mapping_bp)
```

---

## Step 7.4: Add Admin Navigation

**File**: `app/templates/admin/base.html` (add to navigation)

```html
<li class="nav-item">
    <a class="nav-link" href="{{ url_for('admin_field_mapping.dashboard') }}">
        <i class="bi bi-diagram-3 me-1"></i>
        Field Mapping
    </a>
</li>
```

---

## Step 7.5: Tests

**File**: `tests/routes/test_admin_field_mapping.py`

```python
"""
Tests for admin field mapping routes.
"""
import pytest
from app import db
from app.models import MasFormTypes, MasFieldDisplayConfig
from tests.base import BaseTestCase


class TestAdminFieldMapping(BaseTestCase):
    """Test admin field mapping routes."""

    def setUp(self):
        super().setUp()
        # Login as admin user
        # (Assuming admin user setup exists)

    def test_01_dashboard_requires_admin(self):
        """Dashboard requires admin role."""
        resp = self.client.get("/admin/field-mapping/")
        self.assertEqual(resp.status_code, 302)  # Redirect to login

    def test_02_form_types_list(self):
        """Form types list page loads."""
        # Login as admin first
        # resp = self.client.get("/admin/field-mapping/form-types")
        # self.assertEqual(resp.status_code, 200)
        pass

    def test_03_form_type_detail(self):
        """Form type detail page loads."""
        # resp = self.client.get("/admin/field-mapping/form-types/WHO_2022_VA")
        # self.assertEqual(resp.status_code, 200)
        pass

    def test_04_htmx_partial_categories(self):
        """Categories list HTMX partial returns HTML."""
        # resp = self.client.get(
        #     "/admin/field-mapping/form-types/WHO_2022_VA/categories",
        #     headers={"HX-Request": "true"}
        # )
        # self.assertEqual(resp.status_code, 200)
        pass
```

---

## Verification Checklist

After completing Phase 7:

### UI Components
- [ ] Dashboard loads
- [ ] Form type list displays
- [ ] Form type detail page works
- [ ] Categories list loads (HTMX)
- [ ] Fields list with search works
- [ ] Field edit modal works
- [ ] Choices list displays
- [ ] ODK sync form works
- [ ] PII management page works

### Functionality
- [ ] Can search fields
- [ ] Can filter by category
- [ ] Can edit field configuration
- [ ] Can toggle PII status
- [ ] Can trigger ODK sync
- [ ] Can preview sync changes

### Responsiveness
- [ ] Mobile view works
- [ ] Tablet view works
- [ ] Desktop view works
- [ ] Touch controls work

---

## Usage

Access the admin UI at:
```
/admin/field-mapping/
```

From there you can:
1. View all form types and their statistics
2. Manage categories and their display order
3. Configure field display settings
4. Edit choice mappings
5. Sync choices from ODK Central
6. Mark fields as PII

---

## Future Enhancements

- Visual diff when ODK schema changes
- Bulk field editing
- Export/import field configurations
- Audit log for configuration changes
- Version history for field configurations
