/**
 * Captured files (audio, photographs, documents) as BLOB rows in the interviewer's encrypted database
 * (docs/policy/phone-attachments.md). They are encrypted with the same key as the answers, deleted with their
 * draft (src/drafts.ts) and wiped with the store. The answers hold only the opaque reference; the bytes never
 * sit in a file the app does not delete at once.
 */
import type { Db } from "./drafts";
import { clearSendError } from "./unsentWork";

/** The prefix of an answer's attachment reference uri, shared with the form engine and the server. */
export const REFERENCE_PREFIX = "who-va-attachment:";

export type AttachmentKind = "audio" | "image" | "document";

/** Everything about a stored file except its bytes. */
export interface AttachmentMeta {
  id: string;
  draft_id: string;
  project_id: string | null;
  question: string;
  kind: AttachmentKind;
  mime_type: string;
  ext: string;
  size_bytes: number;
  duration_ms: number | null;
  created_at: string;
  uploaded_at: string | null;
}

export interface NewAttachment {
  id: string;
  draftId: string;
  projectId: string | null;
  question: string;
  kind: AttachmentKind;
  mimeType: string;
  ext: string;
  durationMs?: number;
  bytes: Uint8Array;
}

const META_COLUMNS = "id, draft_id, project_id, question, kind, mime_type, ext, size_bytes, duration_ms, created_at, uploaded_at";

/** Store a file. The id is the UUID the server will know it by (`client_attachment_id`). */
export async function saveAttachment(db: Db, file: NewAttachment): Promise<void> {
  await db.runAsync(
    `INSERT INTO attachments (id, draft_id, project_id, question, kind, mime_type, ext, size_bytes, duration_ms, created_at, data)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      file.id, file.draftId, file.projectId, file.question, file.kind, file.mimeType, file.ext,
      file.bytes.byteLength, file.durationMs ?? null, new Date().toISOString(), file.bytes,
    ],
  );
}

export async function getAttachmentMeta(db: Db, id: string): Promise<AttachmentMeta | null> {
  return db.getFirstAsync<AttachmentMeta>(`SELECT ${META_COLUMNS} FROM attachments WHERE id = ?`, [id]);
}

/** The stored bytes of one file, or null when it is gone. */
export async function getAttachmentBytes(db: Db, id: string): Promise<Uint8Array<ArrayBuffer> | null> {
  const row = await db.getFirstAsync<{ data: Uint8Array | ArrayBuffer }>("SELECT data FROM attachments WHERE id = ?", [id]);
  if (!row) return null;
  return (row.data instanceof Uint8Array ? row.data : new Uint8Array(row.data)) as Uint8Array<ArrayBuffer>;
}

export async function deleteAttachment(db: Db, id: string): Promise<void> {
  await db.runAsync("DELETE FROM attachments WHERE id = ?", [id]);
  await clearSendError(db, id); // a refusal belonged to the file; the replacement starts clean
}

/** Delete the draft's files for the covered questions (a refused consent): no copy of what was refused stays. */
export async function deleteCoveredAttachments(db: Db, draftId: string, covered: readonly string[]): Promise<void> {
  if (!covered.length) return;
  const rows = await db.getAllAsync<{ id: string }>(
    `SELECT id FROM attachments WHERE draft_id = ? AND question IN (${covered.map(() => "?").join(", ")})`,
    [draftId, ...covered],
  );
  for (const { id } of rows) await deleteAttachment(db, id);
}

/** Delete the draft's files that no answer references (replaced or abandoned takes). No answers at all deletes nothing. */
export async function pruneUnreferencedAttachments(db: Db, draftId: string, data: Record<string, unknown> | undefined): Promise<void> {
  if (!data) return;
  const kept = referencedIds(data);
  for (const file of await draftAttachments(db, draftId)) if (!kept.has(file.id)) await deleteAttachment(db, file.id);
}

/** The draft's files in capture order (no bytes). */
export function draftAttachments(db: Db, draftId: string): Promise<AttachmentMeta[]> {
  return db.getAllAsync<AttachmentMeta>(
    `SELECT ${META_COLUMNS} FROM attachments WHERE draft_id = ? ORDER BY created_at, id`, [draftId]);
}

export async function markUploaded(db: Db, id: string): Promise<void> {
  await db.runAsync("UPDATE attachments SET uploaded_at = ? WHERE id = ?", [new Date().toISOString(), id]);
}

/** The server no longer holds the draft's files (its draft was purged): every file must be sent again. */
export async function markDraftUnconfirmed(db: Db, draftId: string): Promise<void> {
  await db.runAsync("UPDATE attachments SET uploaded_at = NULL WHERE draft_id = ?", [draftId]);
}

/** The attachment id an answer value names (the engine's reference object, or the prefixed id alone), if any. */
export function referenceId(value: unknown): string | undefined {
  const raw = value && typeof value === "object" && !Array.isArray(value)
    ? ((value as { id?: unknown }).id ?? (value as { uri?: unknown }).uri)
    : value;
  if (typeof raw !== "string") return undefined;
  const id = raw.startsWith(REFERENCE_PREFIX) ? raw.slice(REFERENCE_PREFIX.length) : raw;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) ? id.toLowerCase() : undefined;
}

/** The ids of every file the answers reference (a value is a reference only when it carries the prefix or an object id). */
export function referencedIds(data: Record<string, unknown> | undefined): Set<string> {
  const ids = new Set<string>();
  for (const value of Object.values(data ?? {})) {
    const isObject = value && typeof value === "object" && !Array.isArray(value);
    if (!isObject && !(typeof value === "string" && value.startsWith(REFERENCE_PREFIX))) continue;
    const id = referenceId(value);
    if (id) ids.add(id);
  }
  return ids;
}

/**
 * The files the sent answers reference that exist on the phone, with whether the server has confirmed each.
 * A referenced id with no row (deleted, or a file from another phone) is listed in `missing`.
 */
export async function sendableAttachments(
  db: Db,
  draftId: string,
  sentData: Record<string, unknown> | undefined,
): Promise<{ files: AttachmentMeta[]; missing: string[] }> {
  const wanted = referencedIds(sentData);
  const held = (await draftAttachments(db, draftId)).filter((file) => wanted.has(file.id));
  const heldIds = new Set(held.map((file) => file.id));
  return { files: held, missing: [...wanted].filter((id) => !heldIds.has(id)) };
}
