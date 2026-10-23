/**
 * "Export errors": the log as one text file's content, handed to the Android share sheet (email, WhatsApp).
 * No file-sharing or zip package is a dependency, so the text itself is shared, named digitva-errors-<date>.txt.
 */
import { Share } from "react-native";

import { buildErrorExport } from "./errorLog";
import { allErrors } from "./errorLogDb";

/** Resolves the number of entries shared, 0 when the log is empty (nothing is shared then). */
export async function exportErrors(now = new Date()): Promise<number> {
  const entries = await allErrors();
  if (entries.length === 0) return 0;
  const { name, text, shown } = buildErrorExport(entries, now);
  await Share.share({ title: name, message: text });
  return shown;
}
