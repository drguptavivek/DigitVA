/**
 * A prefill (src/cases.ts Prefill) as the form's initial answers, built as
 * the web form builds them: the package's prefill mapping, then the WHO
 * answers on top. Kept apart from src/cases.ts because it needs the form
 * package at runtime.
 */
import { createWhoVaInitialDataFromPrefill, type SubmissionData } from "@drguptavivek/who-2022-va";

import type { Prefill } from "./cases";

export function initialDataFromPrefill(prefill: Prefill | undefined): SubmissionData | undefined {
  if (!prefill) return undefined;
  let data: SubmissionData = {};
  try {
    data = createWhoVaInitialDataFromPrefill({ interviewer: prefill.interviewer, deceased: prefill.deceased }) ?? {};
  } catch {
    console.warn("prefill mapping failed");
  }
  return { ...data, ...(prefill.answers ?? {}) };
}
