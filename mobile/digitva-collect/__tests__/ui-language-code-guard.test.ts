/**
 * Guard for one language list (digitva-s028, docs/policy/expo-client.md "Adding a UI language"):
 * screens read the UI languages, their BCP 47 tags and formatting from src/i18n.ts / src/uiPacks.ts,
 * never a hard-coded code such as "hi" or "hi-IN". The scan fails with file:line for a quoted UI
 * language code outside the strings and data files. "en" is not scanned: it is also the instrument's
 * base locale, a domain constant.
 */
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..");
/** The list's own definition, and folders of data rather than screens. */
const SKIP = ["src/i18n.ts", "src/uiPacks.ts", "src/strings", "src/data"];

/** Lines that must keep a code, with the reason; a line is allowed when it is in the file and contains the text. */
const ALLOW: ReadonlyArray<{ file: string; text: string; why: string }> = [
  { file: "src/consent.ts", text: 'notice_versions: ["en", "hi"]', why: "the bundled consent notices are language data, one per shipped notice" },
  { file: "src/standalone/noticeSettings.ts", text: '["en", "hi"]', why: "the standalone consent notices shipped in the app" },
  { file: "src/standalone/project.ts", text: 'standaloneTranslationVersion("hi")', why: "the bundled Hindi questionnaire translation of the standalone project" },
  { file: "src/ui.tsx", text: '"hi-IN".', why: "doc comment example of a BCP 47 tag" },
  // Owned by another session (digitva-s028 report): these Hindi-only literals move to strings files there.
  { file: "src/web/InterviewScreen.tsx", text: 'locale.startsWith("hi")', why: "pending: consent dialog text to strings (excluded file)" },
  { file: "src/nativeRoutes/form.tsx", text: 'locale.startsWith("hi")', why: "pending: refusal/consent text to strings (excluded file)" },
];

const CODES = "hi|pa|mr|kn|ta|ml|te|gu|or|bn|ur|as|fr|ar|kha";
const CODE = new RegExp(`["'\`](?:${CODES})(?:[-_][A-Za-z]{2})?["'\`]|["'\`]en[-_]IN["'\`]`);

function files(path: string): string[] {
  const full = join(ROOT, path);
  if (!statSync(full).isDirectory()) return [path];
  return readdirSync(full).flatMap((name) => files(join(path, name)));
}

function offenders(): string[] {
  const found: string[] = [];
  const scanned = files("src").filter((f) => /\.tsx?$/.test(f) && !SKIP.some((skip) => f === skip || f.startsWith(`${skip}/`)));
  for (const file of scanned) {
    readFileSync(join(ROOT, file), "utf8").split("\n").forEach((line, index) => {
      if (!CODE.test(line)) return;
      if (ALLOW.some((allow) => allow.file === file && line.includes(allow.text))) return;
      found.push(`${file}:${index + 1}: ${line.trim().slice(0, 120)}`);
    });
  }
  return found;
}

it("finds a hard-coded language code when one is present", () => {
  expect(CODE.test('const tag = uiLocale() === "hi" ? "hi-IN" : "en-IN";')).toBe(true);
  expect(CODE.test('locale.startsWith("ta")')).toBe(true);
  expect(CODE.test('const base = "en";')).toBe(false);
});

it("keeps UI language codes out of screens", () => {
  expect(offenders()).toEqual([]);
});
