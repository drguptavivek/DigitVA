# ODK Connection Cooldown And Pacing

Status: pending
Priority: high
Created: 2026-03-14

## Goal

Implement a shared ODK connection guard so repeated connectivity failures do not
keep hammering ODK Central and live ODK calls are paced per connection.

## Context

- Sync dashboard coverage is now on-demand.
- Admins can stop active sync runs from the dashboard.
- The remaining gap is connection-level protection when Central is slow,
  unreachable, or overloaded.

## References

- `docs/current-state/odk-sync.md`
- `docs/current-state/async-tasks.md`
- `docs/policy/sync-dashboard-operations.md`
- `docs/policy/not-codeable-odk-central-sync.md`

## Expected Scope

- define configurable pacing and cooldown settings
- implement a shared guard around live ODK calls
- apply it across sync, admin live ODK lookups, and ODK write-back/read paths
  where practical
- surface operator-visible cooldown/error state where relevant
- add focused tests
- update current-state and policy docs as needed

## Notes

- This task is tracked locally in `.tasks` by direct user instruction for this
  session instead of `bd`.
