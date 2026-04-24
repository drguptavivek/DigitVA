---
title: Architecture Overview
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-24
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
  - setup, sync, backup, mapping generation, and CRUD-like operational services
- `app/http`
  - app-level error handling and HTTP response helpers
- `app/authz`
  - authorization policy, resource access, and shared grant/scope helpers
- `app/serializers`
  - response payload serializers grouped by domain
- `app/utils`
  - shared helper logic for ODK, preprocessing, rendering, permissions, SmartVA, and mapping consumers
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
