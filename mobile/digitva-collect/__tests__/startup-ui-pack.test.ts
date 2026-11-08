/** The stored server UI pack is applied from disk before the first screen (digitva-pbgx), without the network. */
const mockFiles = new Map<string, string>();
jest.mock("expo-file-system", () => {
  const path = (...parts: unknown[]) => parts.map((part) => (typeof part === "string" ? part : (part as { uri: string }).uri)).join("/");
  class Directory { uri: string; constructor(...parts: unknown[]) { this.uri = path(...parts); } get exists() { return true; } create() {} }
  class File {
    uri: string;
    constructor(...parts: unknown[]) { this.uri = path(...parts); }
    get exists() { return mockFiles.has(this.uri); }
    create() {}
    write(text: string) { mockFiles.set(this.uri, text); }
    async text() { return mockFiles.get(this.uri) ?? ""; }
  }
  return { Directory, File, Paths: { document: { uri: "doc" } } };
});
jest.mock("expo-splash-screen", () => ({ preventAutoHideAsync: jest.fn().mockResolvedValue(true), hideAsync: jest.fn() }));
jest.mock("../src/AppState", () => ({ useAppState: jest.fn() }));
jest.mock("../src/theme", () => ({ displayPreferencesLoaded: Promise.resolve() }));
jest.mock("../src/api", () => ({ requestRaw: jest.fn() }));

import { setUiLocale, t, uiLanguages } from "../src/i18n";
import { applyStoredUiPack } from "../src/startupGate";
import { writeStoredPack } from "../src/uiPackStore";

const SERVER = "https://va.example.org";
const SLUG = "https_va_example_org";
const V1 = "a".repeat(64);

test("a stored pack for a server-only language shows before any network call", async () => {
  await writeStoredPack(`${SLUG}-list`, {
    version: "c".repeat(64),
    languages: [{ locale: "pa", native_name: "ਪੰਜਾਬੀ", bcp47_tag: "pa-IN", direction: "ltr", version: V1, reviewed: 0 }],
  });
  await writeStoredPack(`${SLUG}-pa`, { version: V1, strings: { signIn: "ਸਾਈਨ ਇਨ" }, form: {} });
  setUiLocale("pa");
  expect(t("signIn")).not.toBe("ਸਾਈਨ ਇਨ"); // before: bundled English
  await applyStoredUiPack(SERVER, "pa");
  expect(uiLanguages().some((entry) => entry.code === "pa")).toBe(true);
  expect(t("signIn")).toBe("ਸਾਈਨ ਇਨ");
});

test("nothing stored is not an error", async () => {
  await expect(applyStoredUiPack("https://other.example.org", "pa")).resolves.toBeUndefined();
});
