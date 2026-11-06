/**
 * Writes the WHO form's own labels (Next, Back, Don't know, validation
 * messages) as the second namespace of the UI strings (digitva-s028):
 * <out>/form-en.json from the vendor's English templates (the reference) and
 * <out>/form-<locale>.json for each built-in translation. Run by
 * `npm run export:web`; the server's UI strings editor and packs read them.
 *
 * Usage: node scripts/export-form-ui-strings.mjs [outDir]   (default dist/ui-strings)
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ENGLISH_UI_MESSAGE_TEMPLATES, WHO_VA_BUILT_IN_UI_TRANSLATIONS } from "@drguptavivek/who-2022-va";

const outDir = process.argv[2] ?? "dist/ui-strings";
mkdirSync(outDir, { recursive: true });
const write = (code, strings) =>
  writeFileSync(join(outDir, `form-${code}.json`), `${JSON.stringify(strings, null, 2)}\n`, "utf8");

write("en", ENGLISH_UI_MESSAGE_TEMPLATES);
for (const [code, strings] of Object.entries(WHO_VA_BUILT_IN_UI_TRANSLATIONS)) {
  if (/^[a-z]{2,3}$/.test(code)) write(code, strings);
}
