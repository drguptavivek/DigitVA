---
title: Current State Index
doc_type: index
status: active
owner: engineering
last_updated: 2026-04-12
---

# Current State Index

This folder documents the current implementation of DigitVA.

The current system should be understood as:

- a single-project-first Flask application
- server-rendered UI with HTMX partial loading
- PostgreSQL-backed workflow state
- DB-managed ODK connection configuration with legacy TOML fallback
- per-form ODK project/form mapping
- admin-driven operational setup with some remaining shell/bootstrap helpers

Read these documents in this order:

1. [Architecture Overview](architecture-overview.md)
2. [Current Data Model](data-model.md)
3. [ODK Sync And Attachments](odk-sync.md)
4. [ODK Repair Workflow](odk-repair-workflow.md)
5. [Field Mapping System](field-mapping-system.md)
6. [Category Rendering And Visibility](category-rendering-and-visibility.md)
7. [Workflow And Permissions](workflow-and-permissions.md)
8. [Admin And Setup Model](admin-and-setup.md)
9. [Runtime And Operations](runtime-and-operations.md)
10. [Data Manager Dashboard](data-manager-dashboard.md)
11. [Submission Analytics Materialized View](submission-analytics.md)
12. [Sync Entrypoints Audit](sync-entrypoints-audit.md)

Related planning:

- [Project Sites Forms Refactor Plan](../planning/project-sites-forms-refactor.md)
