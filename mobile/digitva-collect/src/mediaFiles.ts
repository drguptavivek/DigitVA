/**
 * The only place the app touches plain files for attachments. Everything is under the app's private cache
 * (never a shared, gallery or Downloads folder); a captured file is read into the encrypted store and deleted at
 * once, and a playback copy lives in `va-media/` only while a control uses it (docs/policy/phone-attachments.md).
 */
import { Directory, File, Paths } from "expo-file-system";

const MEDIA_DIR = "va-media";

/** The whole file as bytes. */
export async function readBytes(uri: string): Promise<Uint8Array> {
  return new File(uri).bytes();
}

export function fileSize(uri: string): number {
  const file = new File(uri);
  return file.exists ? file.size : 0;
}

/** Whether `uri` is inside the app's private cache (so it may be deleted without touching the user's own files). */
export function inPrivateCache(uri: string): boolean {
  const root = Paths.cache.uri;
  if (!uri.startsWith(root)) return false;
  // Decode and collapse "." / ".." first: a "cache/../x" or "%2e%2e" path must not pass on its prefix. Fails closed.
  let rest: string;
  try {
    rest = decodeURIComponent(uri.slice(root.length).split(/[?#]/)[0]);
  } catch {
    return false;
  }
  if (rest.includes("\\") || rest.includes("\0")) return false;
  const kept: string[] = [];
  for (const part of rest.split("/")) {
    if (part === "..") {
      if (!kept.pop()) return false;
    } else if (part && part !== ".") {
      kept.push(part);
    }
  }
  return kept.length > 0;
}

/** Delete a file; a missing one is not an error. Only files in the private cache are ever deleted. */
export function removeFile(uri: string | undefined | null): void {
  if (!uri || !inPrivateCache(uri)) return;
  try {
    const file = new File(uri);
    if (file.exists) file.delete();
  } catch {
    // Already gone, or the system cleared the cache.
  }
}

/** A short-lived plain copy of a stored file for the player or the image view; release it with removeFile. */
export function writePlaybackCopy(id: string, ext: string, bytes: Uint8Array): string {
  const dir = new Directory(Paths.cache, MEDIA_DIR);
  if (!dir.exists) dir.create({ intermediates: true });
  const file = new File(dir, `${id}-${Date.now()}.${ext}`);
  file.create({ overwrite: true });
  file.write(bytes);
  return file.uri;
}

/** A scanned page (the scanner hands it over as base64) as a plain cache file, until it is read into the store. */
export function writeCaptureFile(id: string, base64: string): string {
  const dir = new Directory(Paths.cache, MEDIA_DIR);
  if (!dir.exists) dir.create({ intermediates: true });
  const file = new File(dir, `${id}-scan.jpg`);
  file.create({ overwrite: true });
  file.write(base64, { encoding: "base64" });
  return file.uri;
}

/**
 * The playback folder plus the folders the picker, manipulator, recorder and Android document-scanner libraries
 * write their temporary outputs to (their paths are fixed inside the app cache; they accept no output location).
 * `mlkit_docscan_ui_client` is ML Kit's scan output folder; confirm the name on a phone (digitva-lq5m).
 */
const SWEPT_DIRS = [MEDIA_DIR, "ImagePicker", "ImageManipulator", "DocumentPicker", "Audio", "mlkit_docscan_ui_client"];

/** Empty the playback and capture-temporary folders: on lock, sign-out, store deletion and start-up. */
export function wipeMediaCache(): void {
  for (const name of SWEPT_DIRS) {
    try {
      const dir = new Directory(Paths.cache, name);
      if (dir.exists) dir.delete();
    } catch {
      // Nothing to wipe.
    }
  }
}
