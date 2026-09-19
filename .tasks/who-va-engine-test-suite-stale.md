# Vendored engine's own test suite is failing at HEAD

- Status: open (found 2026-09-18)
- Priority: high — the engine is being extended now and has no green guard
- Created: 2026-09-18

## Goal

Get `vendor/who-va-2022` back to a passing `npm test` so engine changes have a
regression guard.

## Context

`npm install` in `vendor/who-va-2022` was never run in this repo, so the suite
had never been executed here. With dependencies installed it reports
**13 failed / 629 passed (642)** at commit 037cdaa — before any of the type
work in this session. Verified by stashing the working-tree changes and
re-running: the same 13 fail at baseline.

Diagnosed cause: **stale expectations from vendoring**, not engine defects.
Commit 2fc60ea composed DigitVA's extension questions (ABHA, narration
language, `md_im1..30`, `ds_im1..5`) into the instrument, and the upstream
tests assert against the pristine WHO instrument. For example
`tests/expression-semantics.test.ts:36` expects 464 expressions; the composed
instrument has 504.

## Split

Mechanical (counts and field/screen sets moved because the extension added
questions):

- `tests/expression-semantics.test.ts` — expression count 464 -> 504
- `tests/exhaustive-runtime-expressions.test.ts`
- `tests/age-wise.e2e.test.ts` — 8 failures, screen/field expectations

Needs a look, may be real:

- `tests/reusable-question-controls.test.tsx` — the searchable language
  dropdown renders 0 `[role="option"]` where the test expects 2. The test
  supplies its own two-choice question, so this is not the extension's
  language list; either the dropdown now needs an interaction before options
  render, or it regressed.
- `tests/form-preview.test.tsx` — 2 failures around reload/section restore.

## References

- `vendor/who-va-2022/src/digitva-extension.ts`, `src/instrument.ts`
- Baseline captured by `git stash push -- vendor/who-va-2022/src` then `npm test`
