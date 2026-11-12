import { getMeta, setMeta, type Db } from "./drafts";

const NOTICES_KEY = "standalone:coding_notices";
const MAX_NOTICES = 50;

export interface CodingNotice {
  draftId: string;
  code: string;
  at: string;
  codingSha256?: string;
}

export interface CodingUploadOutcome {
  draftId: string;
  status: "pending" | "applied" | "refused";
  code: string | null;
  codingSha256: string;
}

export const codingNotices = async (db: Db): Promise<CodingNotice[]> =>
  (await getMeta<CodingNotice[]>(db, NOTICES_KEY)) ?? [];

export const dismissCodingNotices = (db: Db) =>
  db.runAsync("DELETE FROM meta WHERE key = ?", [NOTICES_KEY]);

/** Save a terminal refusal before upload code removes the acknowledged draft; clear it once a recode is taken. */
export async function recordCodingOutcome(db: Db, outcome: CodingUploadOutcome): Promise<void> {
  const notices = await codingNotices(db);
  const matching = (notice: CodingNotice) =>
    notice.draftId === outcome.draftId && notice.codingSha256 === outcome.codingSha256;
  if (outcome.status === "refused") {
    const next = [{
      draftId: outcome.draftId,
      code: outcome.code ?? "not_available",
      at: new Date().toISOString(),
      codingSha256: outcome.codingSha256,
    }, ...notices.filter((notice) => !matching(notice))].slice(0, MAX_NOTICES);
    await setMeta(db, NOTICES_KEY, next);
  } else {
    // A coding the server took (pending or applied) replaces the earlier refusals of this interview, such as the
    // stale coding's "recode needed" notice (digitva-9cll.14).
    const next = notices.filter((notice) => notice.draftId !== outcome.draftId);
    if (next.length !== notices.length) await setMeta(db, NOTICES_KEY, next);
  }
}
