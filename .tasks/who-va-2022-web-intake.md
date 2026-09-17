# WHO VA 2022 web intake (who-2022-va package)

- Status: planned, awaiting decisions W1–W6 and the spike
- Priority: high
- Created: 2026-09-17

## Goal

Fill the WHO 2022 VA questionnaire in a DigitVA web page using
`@drguptavivek/who-2022-va`, submit into the normal workflow, route by
`org_<level>_code`, keep ODK sync untouched.

## Context

Plan: `docs/planning/who-va-2022-web-intake-plan.md`. Depends on the
organization model (routing, unit prefill) for phase 3.

## References

- `app/services/va_data_sync/va_data_sync_01_odkcentral.py`
- `app/services/attachment_service.py`
- `app/services/workflow/transitions.py`

## Expected Scope

Spike, then phases 1–4 in the plan.
