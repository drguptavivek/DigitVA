/**
 * Browser storage for the server UI packs (src/uiPacks.ts): localStorage, outside the preference
 * allowlist because a pack is reference text, not a preference. Phones use uiPackStore.native.ts.
 */
const key = (name: string) => `digitva_ui_pack:${name}`;

/** The stored value, or undefined when absent, unreadable or storage is denied. */
export async function readStoredPack(name: string): Promise<unknown> {
  try {
    const text = globalThis.localStorage?.getItem(key(name));
    return text ? JSON.parse(text) : undefined;
  } catch {
    return undefined;
  }
}

/** Store `value`; a full or denied storage is ignored, since the next start fetches it again. */
export async function writeStoredPack(name: string, value: unknown): Promise<void> {
  try {
    globalThis.localStorage?.setItem(key(name), JSON.stringify(value));
  } catch {
    // Optional cache.
  }
}
