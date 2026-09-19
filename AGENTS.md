# AGENTS.md

Single-project-first Flask system. Read `handoff.md` first: it ranks what to
do next. Read `docs/current-state/README.md` before structural changes.

## How to work: subagents

The main session plans, decides, reviews results and commits. It delegates:

- **Coding: Opus `code-writer`.** Give it the decided design, the files to
  read first, the tests to write, and "do not commit, stash or push". It
  reports files changed, where the design did not fit, and the pytest targets.
- **Reads, audits, reviews: Sonnet or Haiku.** `code-reviewer`,
  `security-reviewer`, `auditor`, `Explore`. Read-only. Ask for verified
  findings with `file:line`, nothing speculative.
- **Tests: one dedicated read-only Sonnet runner.** It runs pytest and reports
  exact counts and full tracebacks. It never edits. One runner at a time per
  test database, so runs do not terminate each other's connections.
- Launch independent agents in the same turn (reviewer and test runner in
  parallel). Never have two agents editing the same files at once.
- The main session makes small fix-ups itself; anything larger goes back to
  the writer with the reviewer's findings.
- Ask the user before starting anything not on the handoff's ranked list.

## Toolchain

- Python 3.13, **uv**, `pyproject.toml` + `uv.lock`. Never pip or requirements.txt.
- **Everything runs inside Docker:** `docker compose exec -T minerva_app_service uv run --no-sync <cmd>`.
- Dependencies: `uv add` / `uv remove` inside `minerva_app_service`, then restart
  `minerva_app_service`, `minerva_celery_worker`, `minerva_celery_beat`. Rebuild
  those images before committing a dependency change.
- Tests: `docs/policy/test-harness.md`. Set `TEST_DATABASE_URL` to a database
  of your own (`minerva_test_pii` exists for this tree); never contend for
  `minerva_test`. Run:
  `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/<db> minerva_app_service uv run --no-sync python -m pytest <targets> -q -p no:cacheprovider`
- Migrations chain onto committed revisions only, checked in `git log`. Run
  `flask db heads` before and after adding one.

## Engineering rules

- Preserve backward compatibility. Do not silently change domain semantics,
  identifiers or workflow behaviour. Explicit simple code, PEP 8, existing names.
- ODK is the source of truth for synced submission content. Do not entangle app
  identifiers with ODK identifiers or hardcode project-site-form naming.
- Any schema change ships with a migration. Additive, staged, reversible;
  never manual DB resets as the rollout path. New tables: `mas_*` masters,
  `map_*` mappings, `auth_*` authorization.
- Protect data: no bulk delete, truncate, overwrite or remap without a verified
  backup and recovery path. Sync reruns must not orphan or discard data. Keep
  destructive workflow actions auditable.
- Never log or expose secrets, tokens or raw sensitive payloads. Minimise PII
  in logs, responses, exports and temp files.
- Authorization is explicit. Form-, site- and project-level access are not
  interchangeable. Prefer API-style handlers and shared authorization services.
  Browser-originated state changes enforce CSRF via `X-CSRFToken`, JSON included.
- Tests: add focused tests for changed fragile logic; TDD when practical. If a
  test cannot be added, document manual verification. Never claim verification
  that did not happen. Assert the subject is present before asserting it is
  absent.
- Do not hand-edit generated mapping modules; change the source or generator.
- Performance: no N+1, no unbounded scans, no repeated ODK or filesystem work in
  request paths, sync loops or dashboards. Stream or batch large data. Release
  DB sessions, file handles and external clients promptly.
- Timezone-aware datetimes; templates use `{{ dt | user_timezone }}`.

## Docs

- Every file under `docs` has YAML front matter with `title`, `doc_type`,
  `status`, `owner`, `last_updated`; refresh `last_updated` on material change.
- Behaviour or policy changes get a baseline in `docs/policy` before
  implementation. Architecture, data model, workflow or runtime changes update
  `docs/current-state`. Repo-relative paths only.

## Delivery workflow

Plan -> Discuss -> Optimize -> Implement -> Test -> Verify -> Commit. Plan
names scope, risks, files, migration and data-loss impact, verification. Do not
commit before implementation and verification are complete. Commit in the
repo's voice: what changed and why the alternative was rejected, not a file
list.

## Task tracking

Use **bd (beads)** for all tasks; no TodoWrite or markdown TODO lists. Run
`bd prime` for the full reference. `bd create` before code, `bd update <id> --claim`
when starting, `bd close <id>` when done, `bd remember` for persistent
knowledge. Longer design records live as one Markdown file per task in
`.tasks/` (see `.tasks/README.md`); remove or mark done when superseded.

## Ending a session

Work is not complete until `git push` succeeds.

1. File beads issues for remaining work; close finished ones.
2. Run quality gates if code changed.
3. Update `handoff.md`.
4. `git pull --rebase && git push`, then `git status` must show up to date
   with origin. If push fails, resolve and retry.
5. Hand off: changed files, validation performed, what is next.

## Dev environment

Seed a clean app (admin + WHO_2022_VA mapping, no test data):

```bash
docker compose up -d
docker compose exec minerva_app_service uv run flask seed run
```

Restore the baseline test dataset (`private/test_data.sql`): `./scripts/restore-test-db.sh`
(resets schema, restores, migrates, seeds testadmin).

| Role | Email | Password |
| --- | --- | --- |
| Admin | testadmin@digitva.com | Admin@123 |
| Coder NC01 | test.coder.nc01@gmail.com | Aiims@123 |
| Coder NC02 | test.coder.nc02@gmail.com | Aiims@123 |
| Coder KA01 | test.coder.ka01@gmail.com | Aiims@123 |
| Coder KL01 | test.coder.kl01@gmail.com | Aiims@123 |
| Coder TR01 | test.coder.tr01@gmail.com | Aiims@123 |

Test dataset sites: ICMR01NC0201 (116 forms), UNSW01KA0101 (256),
UNSW01KL0101 (255), UNSW01NC0101 (227), UNSW01TR0101 (227).
