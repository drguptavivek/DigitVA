---
title: Current State Index
doc_type: index
status: active
owner: engineering
last_updated: 2026-10-28
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
8. [Access Control Route Inventory](access-control-route-inventory.md)
9. [Admin And Setup Model](admin-and-setup.md)
10. [Runtime And Operations](runtime-and-operations.md)
    - [Split Production TLS](split-production-tls.md): certificate paths, issuing and copying for the three-host deployment
    - [Split Production Deploy Runbook](split-production-deploy.md): preflight, backup, deploy, post-checks and rollback for the three-host deployment
11. [Data Manager Dashboard](data-manager-dashboard.md)
12. [Submission Analytics Materialized View](submission-analytics.md)
    - [AI Analytics Questions](ai-analytics-questions.md): natural-language questions over the per-request `ai_cube`, built-in reports, question catalog, suggestions search and the Typesense container
13. [COD Bucket Reporting](cod-bucket-reporting.md)
14. [Sync Entrypoints Audit](sync-entrypoints-audit.md)
15. [Health-System Organization Model](health-system-organization-model.md)
16. [DORIS COD Workflow](doris-cod-workflow.md)
17. [Device Collection API](device-collection-api.md)
18. [Test Project TST001](test-project-tst001.md)
19. [Expo Client Hosting And Bootstrap](expo-client.md)
    - [App Release Review](app-release-review.md): unified workflows, queued
      submissions, device controls and release/privacy review paths
    - [Performance Telemetry Policy](../policy/app-performance-telemetry.md):
      own-server aggregates and internal interview/coding timelines
20. [Authentication, Login and Onboarding](authentication-and-onboarding.md)
21. [Coder Workspace Component Inventory](coder-component-inventory.md)
22. [Native Passkey Status](native-passkeys.md)
23. [DORIS Editor UI Tokens](doris-ui-tokens.md)

The public demo (flag `PUBLIC_DEMO_ENABLED`, off by default): accounts, sign-up, confinement and limits are in [Authentication, Login and Onboarding](authentication-and-onboarding.md#25-public-demo-account-only-with-public_demo_enabled) (policy: [public-demo.md](../policy/public-demo.md)).

Public pages (no sign-in, GET only, `app/routes/public_pages.py`): `/privacy`, `/contact`, `/data-requests`, linked from the footer of every page. Organisation details come from `PUBLIC_ORG_NAME`, `PUBLIC_CONTACT_EMAIL`, `PUBLIC_GRIEVANCE_OFFICER`, `PUBLIC_POSTAL_ADDRESS` (unset: neutral wording). Policy: [public-privacy-and-data-requests.md](../policy/public-privacy-and-data-requests.md).

The public demo's report page, own-response downloads and public dashboard are in [Public Demo Reports, Downloads And Dashboard](public-demo.md).

The public demo's deployment (separate compose project `docker-compose.demo.yml`, own Redis and database, shared ICD container, demo ingress, backups) is in [Public Demo Deployment Runbook](public-demo-deployment.md).

The Training & demo project's tables, CLI and panel are in the [data model](data-model.md#training-sessions), [CLI reference](cli-reference.md) and [admin panels](admin-and-setup.md#training-sessions-panel) (policy: [training-demo-project.md](../policy/training-demo-project.md)).

Related planning:

- [Project Sites Forms Refactor Plan](../planning/project-sites-forms-refactor.md)
