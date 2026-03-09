# AGENTS.md

## Rules

1. Read [`docs/current-state/README.md`](docs/current-state/README.md) before making structural changes.
2. Treat the current application as a single-project-first Flask system unless a task explicitly changes that behavior.
3. Preserve backward compatibility by default. Do not silently change domain semantics, identifiers, or workflow behavior.
4. Prefer explicit, simple code over clever abstractions.
5. Follow PEP 8 for Python code and keep naming consistent with existing repo conventions.
6. Keep functions and modules focused. Do not increase coupling between sync, workflow, permissions, and rendering without clear necessity.
7. Use idempotent patterns for sync, setup, seed, and migration-related code whenever feasible.
8. Assume ODK is the source of truth for synced submission content. Do not introduce local mutations that conflict with that model without explicit design changes.
9. Do not further entangle app business identifiers with external ODK identifiers.
10. Do not hardcode new project-site-form naming schemes into identifiers unless required for legacy compatibility.
11. Any schema change must be accompanied by a migration plan. Do not change models without addressing migrations.
12. Do not rely on manual database resets as the primary rollout path for schema changes.
13. Back up relevant data before destructive operations, data rewrites, or migration steps that can discard state.
14. Do not run destructive operations against workflow data without understanding their downstream impact on allocations, assessments, reviews, notes, and audit history.
15. Protect against data loss in every change. Assume synced submissions, workflow state, attachments, logs, and mappings may be operationally important unless proven otherwise.
16. Before any destructive or irreversible change, define how data will be preserved, recovered, or rolled back.
17. Prefer reversible changes, additive schema evolution, and staged migrations over in-place destructive rewrites.
18. Do not delete, truncate, overwrite, or remap data in bulk without a verified backup or recovery path.
19. Do not remove local files or attachment directories as part of new features unless retention and rebuild behavior are explicitly understood.
20. When changing sync behavior, verify that reruns do not accidentally orphan, overwrite, or silently discard data.
21. Preserve auditability. Important state transitions and destructive workflow actions must remain traceable.
22. Log operationally important actions, but never log secrets, passwords, tokens, or raw sensitive payloads.
23. Protect PII at all times. Minimize exposure in logs, responses, debugging output, exports, and temporary files.
24. Treat credentials and connection details as sensitive data. Do not store or expose them casually.
25. Do not introduce plaintext secret handling when an encrypted or restricted alternative is possible.
26. Validate authorization changes carefully. Do not broaden access implicitly through convenience shortcuts.
27. Keep permission logic explicit. Do not assume form-level, site-level, and project-level access are interchangeable.
28. Use TDD for new behavior when practical. At minimum, add tests for fragile logic that is being changed.
29. If tests do not exist for a changed area, add focused tests first when the change is non-trivial.
30. If tests cannot be added, document the manual verification performed.
31. Do not claim behavior is verified unless it was actually tested.
32. Do not hand-edit generated mapping modules unless the task specifically requires it. Prefer changing the source spreadsheet or generator.
33. Keep migration, sync, and mapping code repeatable and safe to rerun.
34. Prefer additive migrations and staged cutovers over one-step destructive redesigns.
35. Use repo-relative paths in documentation. Do not use machine-specific absolute paths in files under `docs` or in repository guidance files unless explicitly required.
36. Every document under `docs` must include YAML front matter.
37. At minimum, each `docs` file must include: `title`, `doc_type`, `status`, `owner`, and `last_updated`.
38. Whenever a doc is created or materially updated, refresh its `last_updated` value to the current date.
39. For any app behavior or policy-related matter, create or update a document under `docs/policy` that becomes the baseline for implementation, tests, and future behavior decisions.
40. Do not implement or change policy-sensitive behavior without documenting the intended baseline in `docs/policy`.
41. Update docs in `docs/current-state` whenever architecture, data model, workflow, setup, or runtime behavior changes.
42. Update planning docs when implementation changes affect the target-state direction or migration strategy.
43. Follow this delivery workflow for non-trivial changes: Plan -> Discuss -> Optimize -> Implement -> Test -> Verify -> Commit.
44. In the Plan step, identify scope, risks, affected files, migration impact, data-loss risk, and verification approach before coding.
45. In the Discuss step, align on assumptions, target behavior, and tradeoffs before irreversible or structural work.
46. In the Optimize step, simplify the design, remove avoidable complexity, and prefer the smallest change that satisfies the requirement.
47. In the Implement step, make changes in small, traceable increments.
48. In the Test step, run automated tests when available and add focused tests for changed critical logic when practical.
49. In the Verify step, confirm actual runtime behavior, migration behavior, logging impact, security impact, and backward compatibility as applicable.
50. Do not commit before implementation and verification are complete.
51. Write memory-safe code. Avoid loading unnecessarily large datasets, files, or payloads into memory when streaming, batching, pagination, or incremental processing is possible.
52. Be especially careful in sync, CSV processing, attachment handling, and reporting code to avoid avoidable high-memory behavior.
53. Use safe database operations. Scope writes narrowly, keep transactions intentional, and avoid broad destructive updates or deletes without explicit guards.
54. Handle database sessions and connections cleanly. Do not introduce leaked connections, hanging transactions, or long-lived unnecessary session state.
55. Close or release external resources promptly, including file handles, DB cursors, network clients, subprocess resources, and temporary artifacts.
56. Prevent N+1 query patterns. When loading related data repeatedly, use appropriate query shaping, joins, eager loading, batching, or aggregation.
57. Avoid unbounded table scans and repeated per-row queries in request paths, dashboard code, and sync loops when a single shaped query can do the work.
58. Prefer indexed filters, targeted selects, and explicit query intent over fetching full rows or full tables by default.
59. Do not introduce repeated expensive filesystem work, repeated ODK calls, or repeated SmartVA preparation steps when results can be reused safely.
60. Optimize only after understanding the hot path, but do not knowingly add obviously inefficient patterns.
61. When changing query-heavy or sync-heavy code, consider performance, memory use, transaction size, and operational safety as first-class requirements.
