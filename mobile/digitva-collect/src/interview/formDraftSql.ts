/**
 * The drafts-table SQL of the phone interview screen (src/nativeRoutes/form.tsx), moved out of the component with
 * its text, parameters and error codes unchanged. One function per call site: the reads differ in what a missing row
 * or unreadable JSON means, so they are kept apart rather than shared. Native only (the encrypted SQLite store).
 */
import type { Db } from "../drafts";

type Reader = Pick<Db, "getFirstAsync">;

/** A standalone draft's stored row: its envelope and the prefill it started from, both JSON text. */
export function readStandaloneDraftRow(db: Reader, draftId: string) {
  return db.getFirstAsync<{ envelope: string; prefill?: string | null }>("SELECT envelope, prefill FROM drafts WHERE id = ?", [draftId]);
}

/**
 * The stored envelope of a draft imported from, or based on, the server's copy. A missing row is `draft_missing`;
 * unreadable JSON or a non-object is `invalid_draft_envelope`.
 */
export async function readServerBasedEnvelope(db: Reader, draftId: string): Promise<Record<string, unknown>> {
  const stored = await db.getFirstAsync<{ envelope: string }>(
    "SELECT envelope FROM drafts WHERE id = ?",
    [draftId],
  );
  if (!stored) throw new Error("draft_missing");
  try {
    const parsed = JSON.parse(stored.envelope) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("invalid_draft_envelope");
    }
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error("invalid_draft_envelope");
  }
}

/**
 * The stored envelope of a draft made on this phone. A missing row is `draft_missing` and a non-object
 * `invalid_draft_envelope`; unreadable JSON rejects with the parser's own error, as it always has.
 */
export async function readLocalEnvelope(db: Reader, draftId: string): Promise<Record<string, unknown>> {
  const stored = await db.getFirstAsync<{ envelope: string }>(
    "SELECT envelope FROM drafts WHERE id = ?",
    [draftId],
  );
  if (!stored) throw new Error("draft_missing");
  const parsed = JSON.parse(stored.envelope) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("invalid_draft_envelope");
  }
  return parsed as Record<string, unknown>;
}

/** The stored answers the consent decision is taken on; undefined while the draft has no row yet. */
export async function readStoredAnswers(db: Reader, draftId: string): Promise<Record<string, unknown> | undefined> {
  const saved = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [draftId]);
  return saved ? (JSON.parse(saved.envelope) as { data?: Record<string, unknown> }).data : undefined;
}

/**
 * Inside the caller's transaction: replace the refused draft's answers with the WHO consent "yes" alone and mark it
 * open and unsent again, only if the stored envelope is still the one read (else `draft_conflict`). False when the
 * draft has no row, in which case nothing is written.
 */
export async function resetEnvelopeToWhoYes(tx: Db, draftId: string): Promise<boolean> {
  const row = await tx.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [draftId]);
  if (!row) return false;
  const draft = JSON.parse(row.envelope) as { data: Record<string, unknown> };
  draft.data = { Id10013: "yes" };
  const result = await tx.runAsync("UPDATE drafts SET envelope = ?, completed = 0, completion = NULL, upload_issue = NULL, draft_sync_dirty = 1 WHERE id = ? AND envelope = ?", [JSON.stringify(draft), draftId, row.envelope]);
  if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) !== 1) throw new Error("draft_conflict");
  return true;
}
