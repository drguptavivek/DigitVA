---
title: User Management CLI Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-08
---

# User Management CLI Policy

## Purpose

DigitVA exposes a small Flask CLI surface for operational user recovery and bootstrap tasks that may need to run inside the application container when the web admin path is unavailable.

## Command Scope

The `flask users ...` command group is limited to explicit user-management actions:

- list current users and whether they hold an active global admin grant
- search users by explicit name or email fragments
- list explicit access grants globally or for a single user
- create a user row without inferring additional grants
- reset a user's password
- activate a global admin grant explicitly
- deactivate a global admin grant explicitly
- set a user's status explicitly

## Access Model Rules

The CLI must preserve the same grant model used by runtime authorization.

Required rules:

- admin access is represented by an explicit `va_user_access_grants` row
- admin CLI commands must not infer project, project-site, coder, reviewer, or data-manager grants
- granting admin access must use `role = admin` with `scope_type = global`
- re-running an admin grant command should reactivate the existing grant instead of creating duplicates

## User Row Rules

CLI writes to `va_users` must remain explicit.

Required rules:

- emails are normalized to lowercase before lookup or creation
- password resets must write through the model password hashing helper
- password-setting CLI actions must also enforce the shared password breach policy
- users created through the CLI must always start with `pw_reset_t_and_c = false` so the first-login password change gate is enforced
- status changes must use the existing `VaStatuses` enum values

## Operational Posture

The CLI is an operational fallback, not a replacement for the admin UI.

Expected use cases:

- restoring admin access on a live environment
- creating a bootstrap user during setup
- resetting a locked-out user's password during support operations

Day-to-day user and grant administration should continue to use the `/admin` application surfaces when available.
