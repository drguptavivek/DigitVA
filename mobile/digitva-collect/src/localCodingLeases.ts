/**
 * Ephemeral per-user/per-draft exclusion for the local coding editor and draft upload.
 * It intentionally lives only in memory: a process restart must never leave a stale lock behind.
 */
type LeaseKind = "editor" | "upload";

const leases = new Map<string, LeaseKind>();

function acquire(userId: string, draftId: string, kind: LeaseKind): (() => void) | null {
  const key = `${userId}\u0000${draftId}`;
  if (leases.has(key)) return null;
  leases.set(key, kind);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    if (leases.get(key) === kind) leases.delete(key);
  };
}

/** Acquire the editor side of the per-draft lease, or null while upload/editor work is active. */
export function acquireLocalCodingEditor(userId: string, draftId: string): (() => void) | null {
  return acquire(userId, draftId, "editor");
}

/** Acquire the upload side of the per-draft lease, or null while editor/upload work is active. */
export function acquireDraftUpload(userId: string, draftId: string): (() => void) | null {
  return acquire(userId, draftId, "upload");
}
