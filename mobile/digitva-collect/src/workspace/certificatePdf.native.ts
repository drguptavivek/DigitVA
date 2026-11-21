/** Native: render the HTML to a PDF on the phone (expo-print, no WebView on screen) and hand it to the share sheet. */
import { File } from "expo-file-system";
import { printToFileAsync } from "expo-print";

import { shareAndDelete } from "../standalone/shareFile";

/** A4 in points (expo-print's page size); the file is deleted after sharing. */
export async function sharePdf(html: string, name: string): Promise<void> {
  const { uri } = await printToFileAsync({ html, width: 595, height: 842 });
  const file = new File(uri);
  // expo-print names it with a random id; the recipient should see which case it is.
  file.rename(`${name.replace(/[^A-Za-z0-9_-]+/g, "_")}.pdf`);
  await shareAndDelete(file, "application/pdf");
}
