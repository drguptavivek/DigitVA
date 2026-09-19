# Administrator explainer for the organization and permission model

- Status: largely discharged
- Priority: low
- Created: 2026-09-18
- Updated: 2026-09-19

## Where this stands

The need this task was filed for — an administrator being unable to tell who
can see, fill and code what, and what is still missing — is now met in the
two places an administrator actually works:

- **The rule, in prose.** `docs/policy/organization-model.md` opens with an
  "In plain terms" orientation section (2026-09-18), and
  `docs/policy/web-intake.md` now carries "Ready for web capture"
  (2026-09-19): the nine checks a project must satisfy before an interviewer
  can fill its questionnaire and have the case reach a coder, each with what
  it means and who fixes it, in which panel.
- **The rule, applied to their own project.**
  `GET /admin/api/projects/<id>/web-intake-readiness`, the "Web capture"
  badge and Readiness list in the Projects panel, and
  `flask web-intake readiness <id>` say what is missing on *this* project
  rather than in general. That answers the question an explainer would only
  have described.

Both live next to the rules they describe, so they stay in step with them —
which a standalone document would not.

## What is left

A short list, none of it blocking:

- worked examples in `docs/policy/organization-model.md`: an SMO overseeing a
  CHC subtree, an MO coding at one PHC, a CHO who fills forms but cannot code
- panel screenshots for the Organization and Access Grants panels, taken once
  the panels settle
- a decision on whether any of it is worth a separate audience-facing
  document at all, now that the readiness check carries the practical part

## References

- `docs/policy/web-intake.md` ("Ready for web capture")
- `docs/policy/organization-model.md` (orientation section + rules)
- `docs/policy/access-control-model.md` (roles, scopes, grant storage)
- `docs/current-state/admin-and-setup.md` ("Web-capture readiness")
- `app/services/web_intake_readiness_service.py`
