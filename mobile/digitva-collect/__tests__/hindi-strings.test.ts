import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";
import themeEn from "../src/strings/theme-en.json";
import themeHi from "../src/strings/theme-hi.json";

/**
 * A Hindi value equal to its English one is an untranslated string (digitva-skqs). Format-only values (no word of
 * three letters outside {placeholders}) pass by themselves; names and codes that stay in English are listed here.
 * The Hindi text is a machine draft awaiting owner review (src/i18n.ts).
 */
const SAME_AS_ENGLISH = new Set([
  "appName", "dataFilterSmartva", "dataColSmartva", "webAttachmentKindPdf",
  "codingModeIcd11Doris", "codingModeIcd10", "icd11Citation", "digitvaAddition", "emailPlaceholder",
]);

const pairs: Array<[Record<string, string>, Record<string, string>]> = [[en, hi], [themeEn, themeHi]];

test("no user-facing Hindi string is left equal to English", () => {
  const untranslated: string[] = [];
  for (const [english, hindi] of pairs) {
    for (const [key, value] of Object.entries(english)) {
      const wordy = /[A-Za-z]{3,}/.test(value.replace(/\{[^}]*\}/g, ""));
      if (wordy && hindi[key] === value && !SAME_AS_ENGLISH.has(key)) untranslated.push(key);
    }
  }
  expect(untranslated).toEqual([]);
});

test("the guard sees an untranslated string (subject present before absence)", () => {
  expect(hi.cancel).not.toBe(en.cancel);
  expect(SAME_AS_ENGLISH.has("appName")).toBe(true);
  expect(hi.appName).toBe(en.appName);
});
