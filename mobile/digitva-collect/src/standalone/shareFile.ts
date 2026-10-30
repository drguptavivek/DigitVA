/**
 * Hands one private-cache file to the Android share sheet and deletes it afterwards, whether or not the share
 * succeeds (the share activity returns when the person comes back from the target app). Never a public folder,
 * never an upload.
 */
import { Directory, File, Paths } from "expo-file-system";
import * as IntentLauncher from "expo-intent-launcher";

import { removeFile } from "../mediaFiles";

const GRANT_READ_URI_PERMISSION = 1;

/** A handle on a file in the app's private cache (not created). */
export const cacheFile = (name: string) => new File(Paths.cache, name);

/** Delete leftover export and backup files (a crash between write and share); run when the standalone home or the export panel mounts. */
export function sweepExportLeftovers(): void {
  try {
    for (const entry of new Directory(Paths.cache).list()) {
      if (entry instanceof File && /^digitva-records-.*|.*\.dvbak$/.test(entry.name)) removeFile(entry.uri);
    }
  } catch {
    // Cache unreadable or already cleared.
  }
}

/** Share `file` and delete it afterwards. */
export async function shareAndDelete(file: File, mime: string): Promise<void> {
  try {
    await IntentLauncher.startActivityAsync("android.intent.action.SEND", {
      type: mime,
      flags: GRANT_READ_URI_PERMISSION,
      extra: { "android.intent.extra.STREAM": file.contentUri, "android.intent.extra.SUBJECT": file.name },
    });
  } finally {
    removeFile(file.uri);
  }
}

/** The path SQLite opens for a file:// URI (it cannot take the scheme or percent-escapes). */
export const sqlitePath = (uri: string) => decodeURIComponent(uri.replace(/^file:\/\//, ""));
