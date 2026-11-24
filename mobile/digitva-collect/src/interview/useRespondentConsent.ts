/**
 * The respondent's refusal state shared by the browser (src/web/InterviewScreen.tsx) and phone
 * (src/nativeRoutes/form.tsx) interview screens: the WHO consent question's No, the optional refusal profile (age
 * group, sex), the consent screen reopened to change a decision, and the confirmation before a WHO No is withdrawn
 * (docs/policy/respondent-consent-notice-draft.md). Where it is stored stays with each screen, behind a
 * ConsentPersistence: the server draft API in the browser, the encrypted SQLite store on the phone.
 *
 * Reached from web routes: it must import nothing native (SQLite, SQLCipher, the engine).
 */
import { useState } from "react";
import type { SubmissionData } from "@drguptavivek/who-2022-va";

import { refusalAnswers } from "../refusalBoundary";

/** Builds the stored refusal from the draft's current answers; see `refusalData`. */
export type RefusalData = (current: Record<string, unknown> | undefined) => SubmissionData;

/** How one screen stores the refusal panel's choices. Each method reports its own errors. */
export interface ConsentPersistence {
  /** The consent notice itself is refused (not only the WHO question): Change consent reopens the notice. */
  consentRefused: boolean;
  /** Store the finished refusal, `data` applied to the draft's current answers, and leave the interview. */
  saveRefusal(data: RefusalData): Promise<void>;
  /** Reopen the consent screen to change a refused notice. */
  reopenConsent(): Promise<void> | void;
  /** The respondent now agrees after a WHO No: reset the draft to Id10013 "yes" and resume it. */
  grantWhoConsent(): Promise<void>;
}

export function useRespondentConsent() {
  const [whoRefused, setWhoRefused] = useState(false);
  const [refusalAge, setRefusalAge] = useState("");
  const [refusalSex, setRefusalSex] = useState("");
  const [changingConsent, setChangingConsent] = useState(false);
  const [confirmWhoGrant, setConfirmWhoGrant] = useState(false);

  /** Take the WHO No and the refusal profile from a stored draft's answers. */
  function restoreFrom(answers: Record<string, unknown> | undefined) {
    setWhoRefused(answers?.Id10013 === "no");
    setRefusalAge(typeof answers?.refusal_age_group === "string" ? answers.refusal_age_group : "");
    setRefusalSex(typeof answers?.refusal_sex === "string" ? answers.refusal_sex : "");
  }

  /** The draft's answers cut to the refusal profile and the WHO decision (src/refusalBoundary.ts). */
  const refusalData: RefusalData = (current) =>
    refusalAnswers({ ...current, ...(whoRefused ? { Id10013: "no" } : {}), refusal_age_group: refusalAge, refusal_sex: refusalSex }) as SubmissionData;

  /** Change consent from the refusal panel: a refused notice reopens; a WHO No asks before it is withdrawn. */
  async function changeRefusal(persistence: ConsentPersistence) {
    if (persistence.consentRefused) {
      await persistence.reopenConsent();
      return;
    }
    setConfirmWhoGrant(true);
  }

  /** The refusal panel's Save and Change consent, wired to `persistence`. */
  function refusalHandlers(persistence: ConsentPersistence) {
    return {
      onSave: () => void persistence.saveRefusal(refusalData),
      onChangeConsent: () => void changeRefusal(persistence),
    };
  }

  return {
    whoRefused, setWhoRefused,
    refusalAge, setRefusalAge,
    refusalSex, setRefusalSex,
    changingConsent, setChangingConsent,
    confirmWhoGrant, setConfirmWhoGrant,
    restoreFrom,
    refusalHandlers,
  };
}
