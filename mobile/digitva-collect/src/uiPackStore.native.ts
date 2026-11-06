/**
 * Phone storage for the server UI packs (src/uiPacks.ts): one JSON file per pack under the app's
 * documents folder. SecureStore, where the preferences live, caps a value at about 2 KB; a pack is
 * hundreds of KB of reference text with no personal data.
 */
import { Directory, File, Paths } from "expo-file-system";

const DIR = "ui-packs";

/** The stored value, or undefined when absent or unreadable. */
export async function readStoredPack(name: string): Promise<unknown> {
  try {
    const file = new File(Paths.document, DIR, `${name}.json`);
    return file.exists ? JSON.parse(await file.text()) : undefined;
  } catch {
    return undefined;
  }
}

/** Store `value`; a failed write is ignored, since the next start fetches it again. */
export async function writeStoredPack(name: string, value: unknown): Promise<void> {
  try {
    const dir = new Directory(Paths.document, DIR);
    if (!dir.exists) dir.create({ intermediates: true });
    const file = new File(dir, `${name}.json`);
    file.create({ overwrite: true });
    file.write(JSON.stringify(value));
  } catch {
    // Optional cache.
  }
}
