Status: pending
Priority: medium
Created: 2026-04-22

Goal:
Resolve the demo-training final-COD route failure caused by submissions without an active payload version.

Context:
During the coding authz blueprint cutover, the isolated test
`tests/routes/test_demo_training_project.py::TestDemoTrainingProjectRoute::test_demo_project_final_cod_expires_after_project_retention_window`
still fails with:
`ValueError: Submission uuid:demo-training-project has no active payload version.`
This appears in `app/routes/va_form.py` when posting to
`/vaform/<va_sid>/vafinalasses?action=vacode&actiontype=vademo_start_coding`.
The failure reproduced independently of the coding authz route changes and
should be handled as a separate `va_form` / payload-version follow-up.

References:
- `tests/routes/test_demo_training_project.py`
- `app/routes/va_form.py`
- `app/services/submission_payload_version_service.py`
- `app/services/payload_bound_coding_artifact_service.py`

Expected Scope:
- confirm whether demo/training submissions should always get an active payload version on coding open
- decide whether the fix belongs in demo seeding, coding-open repair, or final-assessment save flow
- add a focused regression test once the intended behavior is settled
