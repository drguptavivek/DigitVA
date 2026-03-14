---
title: Policy Docs
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-14
---

# Policy Docs

This folder contains policy baselines for application behavior.

Current policy docs:

- [Access Control Model](access-control-model.md)
- [Admin Activity Log Policy](admin-activity-log.md)
- [Admin API Access Policy](admin-api-access.md)
- [Category Navigation Visibility Policy](category-navigation-visibility.md)
- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [Coding Allocation Timeout Policy](coding-allocation-timeouts.md)
- [Data Manager Workflow Policy](data-manager-workflow.md)
- [Final COD Authority Policy](final-cod-authority.md)
- [Not Codeable ODK Central Sync Policy](not-codeable-odk-central-sync.md)
- [ODK Connection Guard Policy](odk-connection-guard.md)
- [Social Autopsy Analysis Policy](social-autopsy-analysis.md)
- [Sync Dashboard Operations Policy](sync-dashboard-operations.md)
- [UI Notification Policy](ui-notifications.md)

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
