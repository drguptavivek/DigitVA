# AGENTS.md

## Rules

1. Read [`docs/current-state/README.md`](docs/current-state/README.md) before making structural changes.
2. Treat the current application as a single-project-first Flask system unless a task explicitly changes that behavior.
3. Preserve backward compatibility by default. Do not silently change domain semantics, identifiers, or workflow behavior.
4. Prefer explicit, simple code over clever abstractions.
5. Follow PEP 8 for Python code and keep naming consistent with existing repo conventions.
65. Use **uv** for all Python dependency management. Do NOT use pip, pip-tools, or requirements.txt directly.
66. Use **Python 3.13** as the target version. The project requires `>=3.13`.
67. Use **pyproject.toml** for project configuration and dependencies. Do NOT use setup.py or requirements.txt.
68. **Run all Python commands inside Docker**. Use `docker compose exec minerva_app_service` to run commands (e.g., `docker compose exec minerva_app_service uv run flask shell`,).
69. **Inside Docker**: Commands run via `uv run` in boot.sh and docker-compose (e.g., `uv run flask db upgrade`, `uv run gunicorn`).
70. Add dependencies with `uv add <package>`, remove with `uv remove <package>`.
71. Sync dependencies with `uv sync`. The lock file (`uv.lock`) is committed for reproducibility.
72. When adding or removing a package, run the change inside `minerva_app_service` with `uv add` or `uv remove`, then restart `minerva_app_service`, `minerva_celery_worker`, and `minerva_celery_beat` so the shared `minerva_venv` volume picks up the updated environment.
73. For release or CI validation after dependency changes, rebuild the images with `docker compose build minerva_app_service minerva_celery_worker minerva_celery_beat` before committing.
6. Keep functions and modules focused. Do not increase coupling between sync, workflow, permissions, and rendering without clear necessity.
7. Use idempotent patterns for sync, setup, seed, and migration-related code whenever feasible.
8. Assume ODK is the source of truth for synced submission content. Do not introduce local mutations that conflict with that model without explicit design changes.
9. Do not further entangle app business identifiers with external ODK identifiers.
10. Do not hardcode new project-site-form naming schemes into identifiers unless required for legacy compatibility.
11. Any schema change must be accompanied by a migration plan. Do not change models without addressing migrations.
12. For new target-state business master tables, prefer `mas_*` naming. For explicit mapping tables, prefer `map_*`. For authorization tables, prefer `auth_*`.
13. Do not rely on manual database resets as the primary rollout path for schema changes.
14. Back up relevant data before destructive operations, data rewrites, or migration steps that can discard state.
15. Do not run destructive operations against workflow data without understanding their downstream impact on allocations, assessments, reviews, notes, and audit history.
16. Protect against data loss in every change. Assume synced submissions, workflow state, attachments, logs, and mappings may be operationally important unless proven otherwise.
17. Before any destructive or irreversible change, define how data will be preserved, recovered, or rolled back.
18. Prefer reversible changes, additive schema evolution, and staged migrations over in-place destructive rewrites.
19. Do not delete, truncate, overwrite, or remap data in bulk without a verified backup or recovery path.
20. Do not remove local files or attachment directories as part of new features unless retention and rebuild behavior are explicitly understood.
21. When changing sync behavior, verify that reruns do not accidentally orphan, overwrite, or silently discard data.
22. Preserve auditability. Important state transitions and destructive workflow actions must remain traceable.
23. Log operationally important actions, but never log secrets, passwords, tokens, or raw sensitive payloads.
24. Protect PII at all times. Minimize exposure in logs, responses, debugging output, exports, and temporary files.
25. Treat credentials and connection details as sensitive data. Do not store or expose them casually.
26. Do not introduce plaintext secret handling when an encrypted or restricted alternative is possible.
27. Validate authorization changes carefully. Do not broaden access implicitly through convenience shortcuts.
28. Keep permission logic explicit. Do not assume form-level, site-level, and project-level access are interchangeable.
29. Prefer API-oriented route handlers and shared authorization services for state-changing behavior so the same backend contract can serve server-rendered pages, HTMX, and React clients.
30. Browser-originated state-changing requests must enforce CSRF protection even for JSON/API routes. Use `X-CSRFToken` as the required CSRF header name.
31. Use TDD for new behavior when practical. At minimum, add tests for fragile logic that is being changed.
32. If tests do not exist for a changed area, add focused tests first when the change is non-trivial.
33. If tests cannot be added, document the manual verification performed.
34. Do not claim behavior is verified unless it was actually tested.
35. Do not hand-edit generated mapping modules unless the task specifically requires it. Prefer changing the source spreadsheet or generator.
36. Keep migration, sync, and mapping code repeatable and safe to rerun.
37. Prefer additive migrations and staged cutovers over one-step destructive redesigns.
38. Use repo-relative paths in documentation. Do not use machine-specific absolute paths in files under `docs` or in repository guidance files unless explicitly required.
39. Every document under `docs` must include YAML front matter.
40. At minimum, each `docs` file must include: `title`, `doc_type`, `status`, `owner`, and `last_updated`.
41. Whenever a doc is created or materially updated, refresh its `last_updated` value to the current date.
42. For any app behavior or policy-related matter, create or update a document under `docs/policy` that becomes the baseline for implementation, tests, and future behavior decisions.
43. Do not implement or change policy-sensitive behavior without documenting the intended baseline in `docs/policy`.
44. Update docs in `docs/current-state` whenever architecture, data model, workflow, setup, or runtime behavior changes.
45. Update planning docs when implementation changes affect the target-state direction or migration strategy.
46. Follow this delivery workflow for non-trivial changes: Plan -> Discuss -> Optimize -> Implement -> Test -> Verify -> Commit.
47. In the Plan step, identify scope, risks, affected files, migration impact, data-loss risk, and verification approach before coding.
48. In the Discuss step, align on assumptions, target behavior, and tradeoffs before irreversible or structural work.
49. In the Optimize step, simplify the design, remove avoidable complexity, and prefer the smallest change that satisfies the requirement.
50. In the Implement step, make changes in small, traceable increments.
51. In the Test step, run automated tests when available and add focused tests for changed critical logic when practical.
52. In the Verify step, confirm actual runtime behavior, migration behavior, logging impact, security impact, and backward compatibility as applicable.
53. Do not commit before implementation and verification are complete.
54. Write memory-safe code. Avoid loading unnecessarily large datasets, files, or payloads into memory when streaming, batching, pagination, or incremental processing is possible.
55. Be especially careful in sync, CSV processing, attachment handling, and reporting code to avoid avoidable high-memory behavior.
56. Use safe database operations. Scope writes narrowly, keep transactions intentional, and avoid broad destructive updates or deletes without explicit guards.
57. Handle database sessions and connections cleanly. Do not introduce leaked connections, hanging transactions, or long-lived unnecessary session state.
58. Close or release external resources promptly, including file handles, DB cursors, network clients, subprocess resources, and temporary artifacts.
59. Prevent N+1 query patterns. When loading related data repeatedly, use appropriate query shaping, joins, eager loading, batching, or aggregation.
60. Avoid unbounded table scans and repeated per-row queries in request paths, dashboard code, and sync loops when a single shaped query can do the work.
61. Prefer indexed filters, targeted selects, and explicit query intent over fetching full rows or full tables by default.
62. Do not introduce repeated expensive filesystem work, repeated ODK calls, or repeated SmartVA preparation steps when results can be reused safely.
63. Optimize only after understanding the hot path, but do not knowingly add obviously inefficient patterns.
64. When changing query-heavy or sync-heavy code, consider performance, memory use, transaction size, and operational safety as first-class requirements.
65. Use Timezone aware date time.   <td>{{ submission.created_at | user_timezone }}</td>  <!-- Or optionally provide a custom strftime format: --> <td>{{ submission.created_at | user_timezone('%Y-%m-%d %H:%M') }}</td>

## SEED WHO_2022_VA form without TEST Data
To seed only (e.g. after a fresh `docker compose up`):

```bash
docker compose up -d          # boot.sh runs migrations, creates all tables
docker compose exec minerva_app_service uv run flask seed run
```
  This gives you:
  - testadmin@digitva.com with admin grant
  - WHO_2022_VA form type registered
  - All 414 fields + 1196 choice mappings loaded from the Excel files

  No test data, no users, no submissions — just a clean app with the form mapping ready to configure. You'd then use the
  admin panel to set up ODK connections and project/site mappings manually.

testadmin@digitva.com                                 Admin@123   


## TEST DATA

Saved baseline test data to private/test_data.sql (17,447 lines). To restore it anytime:
  `./scripts/restore-test-db.sh`

This script: resets the DB schema → restores test_data.sql → runs migrations → seeds testadmin.

  ⎿       site     | total_forms | coded | remaining
     --------------+-------------+-------+-----------
      ICMR01NC0201 |         116 |     1 |       115
      UNSW01KA0101 |         256 |   123 |       133
      UNSW01KL0101 |         255 |   125 |       130
      UNSW01NC0101 |         227 |   113 |       114
      UNSW01TR0101 |         227 |   112 |       115

1 test admin user -   - testadmin@digitva.com                                 Admin@123   
5 test coder users                                                                                                       
  ┌──────┬─────────────────┬────────────────────────────┬───────────┐                                                 
  │ Site │      Name       │           Email            │ Password  │
  ├──────┼─────────────────┼────────────────────────────┼───────────┤                                                 
  │ NC01 │ Test Coder NC01 │ test.coder.nc01@gmail.com  │ Aiims@123 │                                               
  ├──────┼─────────────────┼────────────────────────────┼───────────┤
  │ NC02 │ Test Coder NC02 │ test.coder.nc02@gmail.com  │ Aiims@123 │
  ├──────┼─────────────────┼────────────────────────────┼───────────┤
  │ KA01 │ Test Coder KA01 │ test.coder.ka01@gmail.com  │ Aiims@123 │
  ├──────┼─────────────────┼────────────────────────────┼───────────┤
  │ KL01 │ Test Coder KL01 │ test.coder.kl01@gmail.com  │ Aiims@123 │
  ├──────┼─────────────────┼────────────────────────────┼───────────┤
  │ TR01 │ Test Coder TR01 │ test.coder.tr01@gmail.com  │ Aiims@123 │
  └──────┴─────────────────┴────────────────────────────┴───────────┘



## Task Tracking

Use `.tasks/` for internal task tracking in this repository.

Rules:

- create one Markdown file per pending task
- keep tasks concise and actionable
- include relevant docs and code references
- update or remove task files when work is completed or superseded
- do not keep ad hoc TODO lists scattered across unrelated files

See `.tasks/README.md` for the local task format.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
