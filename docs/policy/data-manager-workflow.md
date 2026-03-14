---
title: Data Manager Workflow Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-14
---

# Data Manager Workflow Policy

## Purpose

The `data_manager` role exists for data-quality triage and operational review of
submissions before or outside coder workflow.

It is not a coding role and it is not a reviewer role.

## Scope Rules

`data_manager` grants may be issued at either:

- `project`
- `project_site`

A project-scoped data manager may act across all sites in the granted project.

A project-site-scoped data manager may act only on submissions that belong to
that project-site pair.

## Core Capabilities

A data manager may:

- browse all submissions in scope
- open an individual submission in read-only mode
- mark a submission as Not Codeable from the data-management workflow
- document the reason and optional notes for that decision

A data manager may not:

- start coding
- resume coder allocations
- submit initial COD
- submit final COD
- submit reviewer QA
- override coder or reviewer workflow outcomes

## Data Manager Not Codeable Outcome

When a data manager marks a submission as Not Codeable:

- the decision must be stored as a data-manager-specific workflow record
- the actor must be the data manager, not a coder
- the reason and optional details must be auditable

This outcome is distinct from coder Not Codeable.

DigitVA must not reuse coder-owned workflow records in a way that makes it look
like a coder made the data-manager decision.

## Effect On Coder Allocation

Any submission with an active data-manager Not Codeable outcome must be excluded
from new coder allocation.

This exclusion applies to:

- normal coder assignment
- random/demo coder assignment

The purpose is to stop known bad submissions from entering coder workflow while
the issue is unresolved.

## Visibility Model

The data manager dashboard should be scope-based, not allocation-based.

That means:

- visible submissions are determined by project or project-site grant scope
- visibility is not limited to cases already worked on by the same user

## Audit Expectations

The audit trail should make these actions visible:

- data manager opened a submission
- data manager marked a submission Not Codeable
- data manager updated or cleared that outcome if future workflow allows it

The audit language should clearly distinguish data-manager decisions from coder
decisions.
