const mockStore = new Map<string, string>();
const mockGetItem = jest.fn(async (key: string) => mockStore.get(key) ?? null);
const mockSetItem = jest.fn(async (key: string, value: string) => { mockStore.set(key, value); });
jest.mock("expo-secure-store", () => ({
  getItemAsync: (key: string) => mockGetItem(key),
  setItemAsync: (key: string, value: string) => mockSetItem(key, value),
}));

import {
  defaultStandaloneNoticeSettings,
  loadStandaloneNoticeSettings,
  MAX_STANDALONE_NOTICE_LENGTH,
  saveStandaloneNoticeSettings,
  standaloneConsentConfigWithSavedNotice,
  validStandaloneNoticeText,
  type StandaloneNoticeSettings,
} from "../src/standalone/noticeSettings";
import { standaloneConsentConfig } from "../src/standalone/consent";
import { computeUtf8Sha256HexSync } from "../src/consent";

beforeEach(() => {
  mockStore.clear();
  mockGetItem.mockClear();
  mockSetItem.mockClear();
});

it("starts with generated English and Hindi notices and validates nonblank bounded text", () => {
  const defaults = defaultStandaloneNoticeSettings();
  expect(defaults.en).toContain("[PROJECT NAME]");
  expect(defaults.hi).toContain("[PROJECT NAME]");
  expect(validStandaloneNoticeText("  \n  ")).toBe(false);
  expect(validStandaloneNoticeText("x".repeat(MAX_STANDALONE_NOTICE_LENGTH))).toBe(true);
  expect(validStandaloneNoticeText("x".repeat(MAX_STANDALONE_NOTICE_LENGTH + 1))).toBe(false);
});

it("persists both languages together and rejects invalid input without writing", async () => {
  const notices: StandaloneNoticeSettings = { en: "New English notice", hi: "नई हिंदी सूचना" };
  await saveStandaloneNoticeSettings(notices);
  expect(await loadStandaloneNoticeSettings()).toEqual(notices);
  expect(mockSetItem).toHaveBeenCalledTimes(1);
  await expect(saveStandaloneNoticeSettings({ ...notices, hi: "  " })).rejects.toThrow("standalone_notice_invalid");
  expect(mockSetItem).toHaveBeenCalledTimes(1);
});

it("replaces invalid or malformed saved values with the same-language generated defaults", async () => {
  await saveStandaloneNoticeSettings({ en: "Valid English", hi: "मान्य हिंदी" });
  const key = mockSetItem.mock.calls[0][0];
  mockStore.set(key, JSON.stringify({ schema: 1, notices: { en: "  ", hi: "मान्य हिंदी" } }));
  expect(await loadStandaloneNoticeSettings()).toEqual({ en: defaultStandaloneNoticeSettings().en, hi: "मान्य हिंदी" });
  mockStore.set(key, "not-json");
  expect(await loadStandaloneNoticeSettings()).toEqual(defaultStandaloneNoticeSettings());
});

it("uses the saved rendered text and hash-derived version while keeping seed purposes and snapshots", async () => {
  await saveStandaloneNoticeSettings({ en: "Hello [PROJECT NAME] at [ORGANISATION]", hi: "नमस्ते [PROJECT NAME]" });
  const config = await standaloneConsentConfigWithSavedNotice("standalone", "en", { projectName: "Study", organisation: "Clinic" });
  const notice = config!.notice_versions[0];
  const snapshot = { ...notice };
  const text = "Hello Study at Clinic";
  const hash = computeUtf8Sha256HexSync(text);
  expect(notice.text).toBe(text);
  expect(notice.text_sha256).toBe(hash);
  expect(notice.notice_version_id).toBe(`standalone-${hash}`);
  expect(notice.purposes.map((purpose) => purpose.code)).toEqual(
    standaloneConsentConfig("standalone", "en")!.notice_versions[0].purposes.map((purpose) => purpose.code),
  );

  await saveStandaloneNoticeSettings({ en: "A later version", hi: "नमस्ते [PROJECT NAME]" });
  const later = await standaloneConsentConfigWithSavedNotice("standalone", "en", { projectName: "Study" });
  expect(later!.notice_versions[0].notice_version_id).not.toBe(notice.notice_version_id);
  expect(notice).toEqual(snapshot);
  expect(notice.text).toBe(text);
});

it("keeps unsupported languages unavailable without reading settings", async () => {
  await expect(standaloneConsentConfigWithSavedNotice("standalone", "fr")).resolves.toBeNull();
  expect(mockGetItem).not.toHaveBeenCalled();
});
