---
title: Architecture Overview
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-25
---

# Architecture Overview

## Summary

DigitVA is a Flask 3 application for verbal autopsy intake, coding, review, and site-level reporting.

The current implementation is single-project-first. It is not yet modeled as a generalized multi-project platform.

## Runtime Stack

- Flask application factory in [`app/__init__.py`](../../app/__init__.py)
- SQLAlchemy ORM and Flask-Migrate
- Flask-Login for authentication and session-based user access
- PostgreSQL as the primary database
- Gunicorn as the production app server
- Docker Compose for local/containerized app and DB runtime

## Top-Level App Shape

Main code areas:

- `app/routes`
  - HTTP routes, dashboards, auth, coding/review actions, media serving
  - route implementations are grouped into top-level packages such as
    `auth/`, `profile/`, `home/`, `workflow/`, `operations/`, `api/`,
    plus the existing `admin_sections/` packages
  - shared route helpers now live in `helpers/`
  - heavier route surfaces are now being split into domain packages such as
    `workflow/coding/`, `workflow/reviewing/`, `forms/`, `attachments/`,
    `operations/data_management/`,
    `operations/data_management/user_management/`,
    `api/data_management/`, `admin_sections/data_sync/`, and
    `admin_sections/field_mapping/`
  - the VA form partial route now keeps a thin entrypoint in
    `forms/partials.py`, with branch handlers split into
    `forms/handlers/category.py` and `forms/handlers/assessments.py`
  - attachment and legacy media file-serving routes live in `attachments/`
    while preserving the existing `/vaform/attachment/...` and
    `/vaform/media/...` URLs
  - the coder and reviewer workflow routes now use small route packages with
    `dashboard.py`, `actions.py`, and `common.py` submodules while preserving
    the existing `coding` and `reviewing` blueprint endpoints
- `app/models`
  - SQLAlchemy models for users, submissions, allocations, assessments, review records, audit logs, and master data
- `app/services`
  - domain services grouped by package instead of flat `*_service.py` modules
  - `workflow/` owns only the canonical submission state machine: definitions,
    state store, transitions, and events
  - `coding/` owns allocation, coder/reviewer workflow actions, coding intake
    policy, final COD authority, and payload-bound coding artifacts split by
    artifact policy under `coding/payload_artifacts/`
  - `projects/` owns project/site setup helpers and submission-to-project lookup
  - `demo_training.py` owns demo/training project behavior that cuts across
    coding, allocation, and access
  - `submissions/` owns pure submission payload version/projection helpers and
    derived submission summaries
  - `sync/` owns ODK-to-local sync orchestration, payload enrichment/backfill,
    current-payload repair, attachment repair triggering, and sync workflow
    advancement
  - `odk/` owns primitive ODK client, guarded calls, deltas, submission fetch,
    submission metadata fetch, and reviews; ODK transport stays here, while
    form metadata translation stays in `forms/`
  - `forms/` owns form type management, field mapping, ODK schema-to-form
    mapping, category rendering, social-autopsy form metadata, and runtime form
    synchronization; static coder/summary mappings live in
    `forms/legacy_mappings/` until setup flows are fully runtime-mapping based
  - `data_management/` owns data-manager dashboard scope, exports, screening
    actions, upstream-change review actions, and related audit helpers
  - `analytics/` owns read-only analytics materialized-view query helpers
  - `cod_buckets/` owns cause-of-death bucket schemes, mappings, import/reset
    helpers, and bucket reporting
  - `reporting/` owns read-only operational reporting such as Site PI reporting
  - `rendering/` owns template composition helpers that must remain outside
    route modules; legacy VA category formatting helpers live under
    `rendering/legacy/`
  - `attachments/` owns attachment synchronization, storage, and serving
    support helpers
  - `bootstrap/` owns legacy one-shot seed helpers for historical project,
    site, form, and user setup
  - `backups/` owns database backup/restore helpers
  - `users/` owns legacy user lifecycle helpers not yet replaced by the web
    user-management flow
  - `smartva/`, `icd/`, `notifications/`, and `security/` own focused
    SmartVA, ICD-10, email, token, and abuse-protection services; legacy
    SmartVA adapter functions live under `smartva/legacy/` and are invoked
    through the SmartVA service
  - legacy operational packages remain for setup, backup, mapping generation,
    and older CRUD-style flows
- `app/http`
  - app-level error handling and HTTP response helpers
- `app/authz`
  - authorization policy, resource access, shared grant/scope helpers, and
    legacy workflow permission guards used by existing route decorators
- `app/serializers`
  - response payload serializers grouped by domain
- `app/validators`
  - domain input validators for setup/admin flows; project/site validators live
    in `projects.py`, while form, ODK-form, boolean, and SmartVA-country
    validators live in `forms.py`
- `app/utils`
  - generic non-domain utilities only, currently credential encryption and
    password policy helpers
  - `app/utils/__init__.py` is intentionally not a barrel export; active code
    should import helpers from their concrete modules or from `app/validators`
- `app/templates`
  - server-rendered HTML templates and HTMX partials
- `resource`
  - mapping spreadsheets, legacy SmartVA binary, and pyODK config files
- `data`
  - downloaded ODK CSV and attachment files grouped by app form id

## Request Model

The app is HTML-first.

- Dashboards and forms are rendered server-side
- category content is loaded through partial routes
- some lightweight JSON endpoints exist, such as health and ICD search
- there is no separate SPA frontend

## Major Functional Areas

- ODK data sync into local files and `va_submissions`
- SmartVA processing after sync
- coder allocation and coding flow
- reviewer allocation and review flow
- site PI dashboard and reporting
- audit logging for workflow and sync changes

## Configuration Model

Current config is split between:

- Flask config in [`config.py`](../../config.py)
- Docker environment variables in [`docker-compose.yml`](../../docker-compose.yml)
- pyODK file-based config under `resource/pyodk`

Important current-state limitation:

- ODK server connection details are global file-based config, not project-scoped configuration in the database

## Current Design Constraints

- site records are project-bound in the current schema
- app form identity also carries ODK mapping and business meaning
- many flows rely on synthetic app `form_id`
- setup/admin tasks are largely shell-driven rather than web-admin-driven
