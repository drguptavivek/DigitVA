const WEB_RECALL_PREFIX = "digitva.interviewerRecall.";

/**
 * Forget the interviewer details this browser recalled for pre-filling (owner decision digitva-3rec): called by every
 * web sign-out, manual and idle, so the next person on a shared computer sees none of them. Storage may be denied.
 */
export function clearWebRecall(): void {
  try {
    const storage = globalThis.localStorage;
    if (!storage) return;
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(WEB_RECALL_PREFIX)) keys.push(key);
    }
    for (const key of keys) storage.removeItem(key);
  } catch {
    // Storage denied: nothing was stored here either.
  }
}
