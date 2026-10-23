/**
 * Send a completed interview's files before the interview itself (docs/policy/phone-attachments.md, decision 4).
 *
 * The server holds a file against the interviewer's open draft of the case (a direct start, with no case, has an
 * attachment draft named by `client_draft_id`), and the later `POST /submissions` finds the same draft, so: (a)
 * `POST /intake/drafts` returns that draft (a repeat returns the same one; a 409 holds the interview), (b) each file the sent answers
 * reference is PUT to it (the file's UUID is the idempotency key, so a retry is harmless), (c) the caller sends
 * the interview only when this returns "done". An interview with a file the server has not confirmed is never
 * submitted (owner rule, digitva-jkvl).
 */
import { CryptoDigestAlgorithm, digest } from "expo-crypto";

import { ApiError, INTAKE_API } from "./api";
import { getAttachmentBytes, markUploaded, sendableAttachments } from "./attachmentStore";
import { authedRequest } from "./auth";
import { reopenDraft, setDraftUploadIssue, type CompletedDraft, type Db } from "./drafts";
import { clearSendError, noteSendError, sendRefusal } from "./unsentWork";

/** The server refused this file: no retry can change that, only replacing or deleting it. */
const FILE_REFUSED = new Set([400, 413, 415, 422]);
/**
 * A 400 for a truncated or damaged transfer, or a 413 that is not the server's own limit (a proxy's, with no
 * JSON code), says nothing about the file: it is sent again.
 */
function transferFault(status: number, code: string | undefined): boolean {
  return (status === 400 && (code === "checksum_mismatch" || code === "invalid_request")) ||
    (status === 413 && code !== "payload_too_large");
}
/** The server's per-draft file count is full: the interview is held, but the file itself is fine. */
const isLimit = (status: number, code: string | undefined) => status === 422 && code === "attachment_limit";
const fileRefused = (status: number, code: string | undefined) => FILE_REFUSED.has(status) && !transferFault(status, code);
/** The draft or case is gone or closed: held like a refused submit, until the interviewer asks again. */
const CASE_REFUSED = new Set([404, 409]);
const UPLOAD_TIMEOUT_MS = 180_000;

export type AttachmentUploadResult =
  /** Every referenced file is on the server (or there were none): send the interview. */
  | { state: "done" }
  /** A network or server fault: everything is kept, the next Send tries again. */
  | { state: "retry"; error: unknown }
  /** A refusal that needs the interviewer (the draft was reopened or held); do not send the interview. */
  | { state: "held"; error: unknown };

const hex = (buffer: ArrayBuffer) => [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");

/**
 * Upload the files `sentData` references. Files of a refused consent are never listed there (the covered answers
 * are stripped first), so they are never sent. A file the phone does not hold is left to the server to judge.
 */
export async function uploadDraftAttachments(
  userId: string,
  db: Db,
  item: Pick<CompletedDraft, "id" | "project_id" | "site_id" | "org_unit_id" | "death_id">,
  sentData: Record<string, unknown> | undefined,
): Promise<AttachmentUploadResult> {
  const { files } = await sendableAttachments(db, item.id, sentData);
  const pending = files.filter((file) => !file.uploaded_at);
  if (!pending.length) return { state: "done" };

  // A file the server refused for good stays refused until the interviewer replaces or deletes it.
  for (const file of pending) {
    const earlier = await sendRefusal(db, file.id);
    if (earlier?.status !== undefined && fileRefused(earlier.status, earlier.code)) return hold(db, item.id, earlier.status, earlier);
  }

  let current: string | undefined;
  try {
    const { body } = await authedRequest<{ draft?: { draft_id?: string } }>(userId, `${INTAKE_API}/drafts`, {
      method: "POST",
      body: {
        project_id: item.project_id,
        site_id: item.site_id,
        ...(item.org_unit_id ? { org_unit_id: item.org_unit_id } : {}),
        // No case (a direct start): the interview's own id names the server draft, and the submit completes it.
        ...(item.death_id ? { death_id: item.death_id } : { client_draft_id: item.id }),
      },
    });
    const draftId = body?.draft?.draft_id;
    if (typeof draftId !== "string" || !draftId) throw new Error("invalid_draft_ack");
    for (const file of pending) {
      current = file.id;
      const bytes = await getAttachmentBytes(db, file.id);
      if (!bytes) continue; // deleted while sending
      const sha256 = hex(await digest(CryptoDigestAlgorithm.SHA256, bytes));
      await authedRequest<unknown>(userId, `${INTAKE_API}/drafts/${encodeURIComponent(draftId)}/attachments/${file.id}`, {
        method: "PUT",
        rawBody: { bytes, sha256 },
        timeoutMs: UPLOAD_TIMEOUT_MS,
      });
      await markUploaded(db, file.id);
      await clearSendError(db, file.id);
    }
    return { state: "done" };
  } catch (error) {
    const limit = error instanceof ApiError && isLimit(error.status, error.code);
    const id = current && !limit ? current : item.id;
    await noteSendError(db, id, error);
    if (id !== item.id) await noteSendError(db, item.id, error);
    if (error instanceof ApiError && (fileRefused(error.status, error.code) || CASE_REFUSED.has(error.status))) return hold(db, item.id, error.status, error);
    return { state: "retry", error };
  }
}

/**
 * The interview cannot go while this file stands. A refused file (400, 413, 415, 422) reopens the interview so
 * the file can be replaced or deleted; a closed or missing case (404, 409) holds it, as a refused submit does.
 */
async function hold(db: Db, draftId: string, status: number, error: unknown): Promise<AttachmentUploadResult> {
  if (CASE_REFUSED.has(status)) await setDraftUploadIssue(db, draftId, "case_conflict");
  else await reopenDraft(db, draftId);
  return { state: "held", error };
}
