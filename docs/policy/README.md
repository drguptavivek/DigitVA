---
title: Policy Docs
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-09
---

# Policy Docs

This folder contains policy baselines for application behavior.

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
