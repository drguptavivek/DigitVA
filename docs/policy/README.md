---
title: Policy Docs
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-21
---

# Policy Docs

This folder contains policy baselines for application behavior.

Current policy docs:

- [Access Control Model](access-control-model.md)
- [New Form Type Onboarding](new-form-type-onboarding.md)
- [Admin Activity Log Policy](admin-activity-log.md)
- [Admin API Access Policy](admin-api-access.md)
- [Attachment Storage and Delivery Policy](attachment-storage.md) — attachment authorization matrix, presence, delivery, AMR derivatives
- [Category Navigation Visibility Policy](category-navigation-visibility.md)
- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [Coding Allocation Timeout Policy](coding-allocation-timeouts.md)
- [Coding Debug Stats API Policy](coding-debug-stats-api.md)
- [COD Bucket Reporting Policy](cod-bucket-reporting.md)
- [Data Manager User and Grant Management Policy](dm-user-grant-management.md)
- [Data Manager Workflow Policy](data-manager-workflow.md)
- [Demo Coding Retention Policy](demo-coding-retention.md)
- [Field Data Collection Policy](field-data-collection.md) — permitted collection paths, unmasked collection vs masked coding, device encryption rules
- [Final COD Authority Policy](final-cod-authority.md)
- [Migration Chaining Policy](migration-chaining.md) — chain onto committed revisions only, which head moves, why working-tree checks cannot verify it
- [Not Codeable ODK Central Sync Policy](not-codeable-odk-central-sync.md)
- [ODK Connection Guard Policy](odk-connection-guard.md)
- [Organization Model Policy](organization-model.md) — per-project health-system tree, unit codes, cadres, workers, export/import
- [ODK Retired Submissions Policy](odk-retired-submissions.md) — submissions missing in ODK are kept, not codeable, not counted by default
- [ODK Sync Policy](odk-sync-policy.md) — workflow state guards for ODK sync
- [SmartVA Generation Policy](smartva-generation-policy.md) — when SmartVA runs
- [Social Autopsy Analysis Policy](social-autopsy-analysis.md)
- [Password Breach Check Policy](password-breach-checks.md)
- [Request Method Abuse Control Policy](request-method-abuse-control.md)
- [Site Maintenance Mode Policy](site-maintenance-mode.md)
- [VA Cause Definitions](va-cause-definitions.md) — WHO VA codes and definitions in the database, admin rich-text editing, coder lookup
- [Sync Dashboard Operations Policy](sync-dashboard-operations.md)
- [Test Harness Policy](test-harness.md) — session-scoped schema, savepoint isolation, fixture rules
- [UI Notification Policy](ui-notifications.md)
- [User Management CLI Policy](user-management-cli.md)
- [VA Form Project Configuration Policy](va-form-project-configuration.md) — extensions a project enables, narration languages vs display translations, geography codes
- [Web Intake Policy](web-intake.md) — WHO VA 2022 questionnaire filled in DigitVA, death register, interviewer role
- [WHO 2022 Age Derivation Policy](who-2022-age-derivation.md)
- [WHO 2022 ICD-10 Coding Allowability Policy](who-2022-icd10-coding-allowability.md)

Use `docs/policy` when a change affects:

- access policy
- workflow policy
- data retention or deletion policy
- sync conflict policy
- validation policy
- security-sensitive behavior
- user-visible behavioral rules

Rules:

- policy changes must be written down before or with implementation
- implementation and tests must follow the documented policy baseline
- if behavior changes, update the relevant policy doc
- if no policy doc exists for the area, create one
