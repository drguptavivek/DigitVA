# ICD-11 means DORIS; masked ICD-11 puts DORIS in Step 1 (`digitva-0n3`)

- Status: designed, owner decisions recorded, not started
- Priority: P1
- Created: 2026-09-27
- Policy baseline: `docs/policy/doris-cod-workflow.md`, "Decided 2026-09-27"

## Goal

`icd_classification='icd11'` always means `cod_entry_mode='doris'`;
`selectable` is retired. Unmasked ICD-11 keeps the one-step DORIS final.
Masked ICD-11: Step 1 is the DORIS certificate without SmartVA; Step 2
confirms the final underlying COD (DORIS result, SmartVA result or own
judgement) through the DORIS picker's search, with no second certificate.

## Baseline facts

- Mode is computed twice: `_project_mode()` in `app/routes/va_form.py`
  and `app/services/reviewer_coding_service.py`
  (`masked_simple | unmasked_simple | unmasked_doris`). The work is in the
  masked branches, not `selectable`.
- `_clinical_context` in `app/routes/api/doris_clinical.py` refuses every
  masked project (409 `DORIS_NOT_ENABLED`).
- Step 1 rows (`va_initial_assessments`, `va_reviewer_initial_assessments`)
  have NOT NULL `va_immediate_cod` / `va_antecedent_cod`, read by exports,
  the analytics MVs, the COD panel and the Step 2 header.
- The masked reviewer sees no SmartVA in Step 1 or Step 2 today.
- `smartva_icd11_mapping` returns WHO's 10-to-11 target; alternatives are
  joined with `/`, which `extract_icd11_code_expression` reads as a cluster.

## Phases

1. Settings: model CHECKs `icd_classification IN ('icd10','icd11')` and
   `(icd_classification='icd11') = (cod_entry_mode='doris')`; drop the
   masked-vs-DORIS CHECK. Migration `icd11_means_doris_retire_selectable`
   on the current head: drop old CHECKs, `selectable -> icd10`,
   `icd11 -> doris`, add new CHECKs. Admin derives `cod_entry_mode` from the
   classification (400 only on an explicit contradiction). Remove the
   `selectable` arm from `icd_coding_value.py`, the admin option and the
   classification switch; keep `icd_classification_of` so old saved values
   render in their own catalogue.
2. Masked Step 1: fourth mode `masked_doris`; open the DORIS gate to masked
   projects; add nullable JSONB `doris_certificate`, `doris_result`,
   `codedit_result`, `cod_entry_mode_snapshot` to both initial tables
   (second migration); Step 1 POST reuses the final save's
   verify-or-reprocess path (lift into a helper); editor in a Step-1-only
   mode (no final card, Save enabled after processing); no SmartVA in
   context.
3. Masked Step 2: SmartVA summary, a DORIS summary from the Step 1 row,
   three choices; a small picker host (no certificate, no Process);
   provenance of the choice derived server-side
   (`doris | smartva | own`).
4. Reviewer (Step 1 editor seeded from the coder's certificate; Step 2 as
   the coder), help pages, docs. Demo retention needs no change.

## Owner decisions, answered 2026-09-27

1. Step 1 text columns: immediate COD = first condition on Part I line 1;
   underlying (`va_antecedent_cod`) = DORIS's processed underlying cause.
   When DORIS rejects the certificate or returns no underlying cause, the
   coder assigns the underlying cause in Step 1 with the DORIS picker's
   search, and that is stored (owner, 2026-09-27); the Step 1 save needs
   either DORIS's cause or the coder's.
2. "Use SmartVA result" is a one-click button only when WHO's map gives a
   single expression that codeinfo accepts; otherwise the search opens
   prefilled with the first alternative.
3. Provenance in `cod_entry_mode_snapshot.final_ucod_source` (default taken).
4. Envelopes stay on the Step 1 row only (default taken).
5. The reviewer's Step 1 starts from a copy of the coder's certificate and
   runs DORIS itself; the coder's record never changes.
6. Step 2 code check stays as unmasked DORIS today (default taken).
7. SmartVA shown in the masked reviewer's Step 2 for all masked projects,
   ICD-10 included.
8. ICD-11 coding search route removed later (default taken).
9. Export MV DORIS columns deferred (default taken).
10. Lossy downgrade accepted, dev only (default taken).

## Options as first posed

1. Step 1 NOT NULL text columns: derive from the certificate (recommended)
   or relax NOT NULL.
2. "Use SmartVA result" for WHO multi-alternative targets.
3. Where Step 2 provenance lives: `cod_entry_mode_snapshot.final_ucod_source`
   (recommended) or a column.
4. Step 1 envelopes only on Step 1 (recommended) or copied to the final row.
5. Reviewer runs DORIS on their own Step 1 certificate, starting from the
   coder's copy.
6. Step 2 code check: local catalogue as unmasked DORIS today (recommended)
   or WHO codeinfo too.
7. Show SmartVA to the masked reviewer's Step 2, masked/simple included.
8. Remove the ICD-11 coding search route now or later (recommended later).
9. Export MV DORIS columns now or deferred (recommended deferred).
10. Downgrade is lossy (`selectable` not restored): acceptable, dev only.
