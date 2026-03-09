# Architecture Overview

## Summary

DigitVA is a Flask 3 application for verbal autopsy intake, coding, review, and site-level reporting.

The current implementation is single-project-first. It is not yet modeled as a generalized multi-project platform.

## Runtime Stack

- Flask application factory in [`app/__init__.py`](C:\workspace\DigitVA\app\__init__.py)
- SQLAlchemy ORM and Flask-Migrate
- Flask-Login for authentication and session-based user access
- PostgreSQL as the primary database
- Gunicorn as the production app server
- Docker Compose for local/containerized app and DB runtime

## Top-Level App Shape

Main code areas:

- `app/routes`
  - HTTP routes, dashboards, auth, coding/review actions, media serving
- `app/models`
  - SQLAlchemy models for users, submissions, allocations, assessments, review records, audit logs, and master data
- `app/services`
  - setup, sync, backup, mapping generation, and CRUD-like operational services
- `app/utils`
  - shared helper logic for ODK, preprocessing, rendering, permissions, SmartVA, and mapping consumers
- `app/templates`
  - server-rendered HTML templates and HTMX partials
- `resource`
  - mapping spreadsheets, SmartVA resources, and pyODK config files
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

- Flask config in [`config.py`](C:\workspace\DigitVA\config.py)
- Docker environment variables in [`docker-compose.yml`](C:\workspace\DigitVA\docker-compose.yml)
- pyODK file-based config under `resource/pyodk`

Important current-state limitation:

- ODK server connection details are global file-based config, not project-scoped configuration in the database

## Current Design Constraints

- site records are project-bound in the current schema
- app form identity also carries ODK mapping and business meaning
- many flows rely on synthetic app `form_id`
- setup/admin tasks are largely shell-driven rather than web-admin-driven
