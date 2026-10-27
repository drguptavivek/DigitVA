/**
 * Stores a standalone consent record in the per-interviewer store's meta table.
 *
 * Kept apart from standaloneConsent.ts so that module stays free of a runtime
 * import of drafts.ts (expo-sqlite): consent.ts imports standaloneConsent.ts
 * and the web interview screen imports consent.ts, so a runtime drafts import
 * there pulls expo-sqlite into the web bundle (make check-web).
 */
import { getMeta, setMeta, type Db } from "./drafts";
import type { StandaloneConsentRecord } from "./standaloneConsent";

const key = (draftId: string) => `standaloneConsent:${draftId}`;

export const saveStandaloneConsent = (db: Db, draftId: string, record: StandaloneConsentRecord) =>
  setMeta(db, key(draftId), record);
export const getStandaloneConsent = (db: Db, draftId: string) => getMeta<StandaloneConsentRecord>(db, key(draftId));
