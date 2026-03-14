---
title: ODK Connection Guard Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-14
---

# ODK Connection Guard Policy

## Scope

This policy defines how DigitVA protects ODK Central from repeated bursts of
failing or overly frequent requests.

## Shared Connection State

DigitVA must treat each row in `mas_odk_connections` as a shared operational
boundary across:

- admin live ODK lookups
- background sync
- ODK write-back calls such as review-state updates
- other ODK read/write paths that use the same connection where practical

Connection protection state must be persisted in the database so separate app
and worker processes see the same failure and cooldown state.

## Pacing

Outbound ODK calls must be paced per connection.

Policy:

- pacing is applied before each outbound ODK request
- pacing is configurable through application settings
- pacing is enforced per connection, not globally
- pacing must not require Redis or another external coordinator

The goal is to prevent request bursts such as tens of requests per second from
the same DigitVA deployment against one ODK Central instance.

## Failure Tracking

Retryable connectivity and auth failures must be tracked per connection.

Policy:

- retryable failures increment a consecutive failure counter
- successful calls reset the consecutive failure counter
- the last failure timestamp and message must be preserved for diagnosis
- non-retryable application errors should not trigger connection cooldown

## Cooldown

Repeated retryable failures must activate a shared cooldown.

Policy:

- cooldown activates after a configurable consecutive-failure threshold
- cooldown duration is configurable
- while cooldown is active, DigitVA must fail fast without attempting the live
  ODK request
- cooldown state must be visible to operators in admin surfaces where relevant

## Operator Visibility

Operators need enough context to diagnose and recover from upstream issues.

Policy:

- admin ODK connection views must expose cooldown state and recent failure
  details
- admin test/live lookup flows must surface cooldown errors clearly
- sync behavior documentation must describe pacing and cooldown behavior

## Backward Compatibility

This policy must be implemented additively.

Policy:

- existing ODK connection records remain valid
- projects that still use the legacy TOML fallback may continue to operate
- shared cooldown and pacing are guaranteed only for DB-managed connections

