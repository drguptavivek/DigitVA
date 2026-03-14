---
title: Current State Index
doc_type: index
status: active
owner: engineering
last_updated: 2026-03-13
---

# Current State Index

This folder documents the current implementation of DigitVA.

The current system should be understood as:

- a single-project-first Flask application
- server-rendered UI with HTMX partial loading
- PostgreSQL-backed workflow state
- global ODK connection configuration
- per-form ODK project/form mapping
- shell-driven admin/setup workflows

Read these documents in this order:

1. [Architecture Overview](architecture-overview.md)
2. [Current Data Model](data-model.md)
3. [ODK Sync And Attachments](odk-sync.md)
4. [Field Mapping System](field-mapping-system.md)
5. [Category Rendering And Visibility](category-rendering-and-visibility.md)
6. [Workflow And Permissions](workflow-and-permissions.md)
7. [Admin And Setup Model](admin-and-setup.md)
8. [Runtime And Operations](runtime-and-operations.md)

Related planning:

- [Project Sites Forms Refactor Plan](../planning/project-sites-forms-refactor.md)
