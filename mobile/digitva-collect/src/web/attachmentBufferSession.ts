/**
 * Sign-out and sign-in housekeeping for the browser interview's encrypted attachment buffer
 * (app/static/js/intake/attachment_buffer.js; docs/policy/web-intake.md, "Attachments"). Signing out deletes every
 * file and key after a warning; a different user signing in deletes what the previous one left. The buffer module
 * is imported on demand so it stays out of the entry bundle.
 */
const supported = () =>
  typeof window !== "undefined" && Boolean(window.indexedDB) && Boolean(globalThis.crypto?.subtle);

async function bufferFor(userId: string) {
  const { createBuffer, createIdbBacking } = await import("./attachmentBufferModule");
  return createBuffer({ userId, draftId: "", backing: createIdbBacking(window.indexedDB) });
}

/** This user's files not yet confirmed by the server; 0 when the browser keeps none. */
export async function unsentWebAttachmentCount(userId: string): Promise<number> {
  if (!supported()) return 0;
  try {
    return (await (await bufferFor(userId)).entries()).length;
  } catch {
    return 0;
  }
}

/** Every file and key in this browser's buffer: what sign-out does. */
export async function wipeWebAttachments(userId: string): Promise<void> {
  if (!supported()) return;
  await (await bufferFor(userId)).wipe().catch(() => {});
}

/** What another user left in this browser. */
export async function wipeOtherUsersWebAttachments(userId: string): Promise<void> {
  if (!supported()) return;
  await (await bufferFor(userId)).wipeOthers().catch(() => {});
}
