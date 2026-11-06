/**
 * Hands one private-cache file to the system share sheet and deletes it afterwards, whether or not the share
 * succeeds (the share activity, or on iOS the share sheet, returns when the person comes back). Never a public
 * folder, never an upload. Android uses an ACTION_SEND intent (a PDF tries ACTION_VIEW first); iOS uses expo-sharing (docs/policy/ios-client.md).
 */
import { Directory, File, Paths } from "expo-file-system";
import * as IntentLauncher from "expo-intent-launcher";
import { Platform } from "react-native";

import { removeFile } from "../mediaFiles";

const GRANT_READ_URI_PERMISSION = 1;

/** iOS Uniform Type Identifiers for the types this app shares; others go without one. */
const UTI_BY_MIME: Record<string, string> = {
  "text/csv": "public.comma-separated-values-text",
  "application/json": "public.json",
  "text/plain": "public.plain-text",
  "application/octet-stream": "public.data",
};

/** A handle on a file in the app's private cache (not created). */
export const cacheFile = (name: string) => new File(Paths.cache, name);

/** Delete leftover export and backup files (a crash between write and share); run when the standalone home or the export panel mounts. */
export function sweepExportLeftovers(): void {
  try {
    for (const entry of new Directory(Paths.cache).list()) {
      if (entry instanceof File && /^(digitva-records-|attachment-).*|.*\.dvbak$/.test(entry.name)) removeFile(entry.uri);
    }
  } catch {
    // Cache unreadable or already cleared.
  }
}

/** Share `file` and delete it afterwards. */
export async function shareAndDelete(file: File, mime: string): Promise<void> {
  try {
    if (Platform.OS !== "android") {
      // Loaded only off Android, so the Android build keeps the intent path alone.
      const Sharing = require("expo-sharing") as typeof import("expo-sharing");
      const uti = UTI_BY_MIME[mime];
      await Sharing.shareAsync(file.uri, { mimeType: mime, dialogTitle: file.name, ...(uti ? { UTI: uti } : {}) });
      return;
    }
    if (mime === "application/pdf") {
      // Open in a PDF viewer; with none installed (or on refusal) fall through to the share sheet.
      try {
        await IntentLauncher.startActivityAsync("android.intent.action.VIEW", { data: file.contentUri, type: mime, flags: GRANT_READ_URI_PERMISSION });
        return;
      } catch {
        // No viewer: share instead.
      }
    }
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
