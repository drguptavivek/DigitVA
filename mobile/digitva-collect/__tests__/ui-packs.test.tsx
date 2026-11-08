/** Server UI language packs on the phone (digitva-dt1e, digitva-s028): list, overlay, storage, checks. */
import React from "react";
import { act, create } from "react-test-renderer";
import { WHO_VA_BUILT_IN_UI_TRANSLATIONS } from "@drguptavivek/who-2022-va";
import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

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
const mockRequestRaw = jest.fn();
jest.mock("../src/api", () => ({ requestRaw: (...args: unknown[]) => mockRequestRaw(...args) }));

import { normalizeLocale, questionnaireLocales, setUiLocale, t, uiLanguageTag, uiTextKnown } from "../src/i18n";
import { formUiTranslations, offerBundledUiLanguagesOnly, syncUiPacks, useFormPackRevision, useUiLanguages } from "../src/uiPacks";

const SERVER = "https://va.example.org";
const V1 = "a".repeat(64);
const V2 = "b".repeat(64);
const LIST = {
  version: "c".repeat(64),
  languages: [
    { locale: "hi", native_name: "हिन्दी", bcp47_tag: "hi-IN", direction: "ltr", version: V1, reviewed: 0.25 },
    { locale: "pa", native_name: "ਪੰਜਾਬੀ", bcp47_tag: "pa-IN", direction: "ltr", version: V1, reviewed: 0 },
    { locale: "ur", native_name: "اردو", bcp47_tag: "ur-IN", direction: "rtl", version: V1, reviewed: 0 },
  ],
};
const PA_PACK = {
  version: V1,
  strings: { signIn: "ਸਾਈਨ ਇਨ", syncResult: "ਭੇਜੇ {sent}", noSuchKey: "x", appName: "<b>DigitVA</b>" },
  form: { next: "ਅੱਗੇ", required: "ਲੋੜੀਂਦਾ" },
};

function respond(routes: Record<string, unknown>) {
  mockRequestRaw.mockImplementation(async (_server: string, path: string) => {
    if (!(path in routes)) throw new Error("offline");
    const body = routes[path];
    return body === 304 ? { status: 304, body: null } : { status: 200, body: JSON.stringify(body) };
  });
}

beforeEach(() => {
  mockFiles.clear();
  mockRequestRaw.mockReset();
  offerBundledUiLanguagesOnly();
  setUiLocale("en");
});

/** The form-label revision, read through the hook that drives re-renders. */
function formRevisionNow(): number {
  const seen: { current: number } = { current: -1 };
  function Probe() {
    seen.current = useFormPackRevision();
    return null;
  }
  let tree: ReturnType<typeof create>;
  act(() => { tree = create(<Probe />); });
  act(() => tree.unmount());
  return seen.current;
}

function renderLanguages() {
  const result: { current: ReturnType<typeof useUiLanguages> } = { current: [] };
  function Probe() {
    result.current = useUiLanguages();
    return null;
  }
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(React.createElement(Probe)); });
  return { result, unmount: () => act(() => tree.unmount()) };
}

it("offers only the bundled languages before enrolment, and the published ltr ones after", async () => {
  const { result, unmount } = renderLanguages();
  expect(result.current.map((entry) => entry.code)).toEqual(["en", "hi"]);
  expect(normalizeLocale("pa")).toBe("en");

  respond({ "/api/v1/ui-strings": LIST, "/api/v1/ui-strings/pa": PA_PACK });
  await act(() => syncUiPacks(SERVER, "en"));
  expect(result.current.map((entry) => entry.code)).toEqual(["en", "hi", "pa"]); // ur is rtl: not offered yet
  expect(result.current.find((entry) => entry.code === "hi")).toMatchObject({ bundled: true, reviewed: 0.25 });
  expect(result.current.find((entry) => entry.code === "pa")).toMatchObject({ label: "ਪੰਜਾਬੀ", language: "pa-IN", direction: "ltr" });

  act(() => offerBundledUiLanguagesOnly()); // standalone, or the enrolment removed
  expect(result.current.map((entry) => entry.code)).toEqual(["en", "hi"]);
  unmount();
});

it("lays a pack over the bundle, drops bad keys and falls back to English per key", async () => {
  respond({ "/api/v1/ui-strings": LIST, "/api/v1/ui-strings/pa": PA_PACK });
  await syncUiPacks(SERVER, "pa");
  expect(setUiLocale("pa")).toBe("pa");
  expect(t("signIn")).toBe("ਸਾਈਨ ਇਨ");
  expect(t("syncResult")).toBe(en.syncResult); // placeholder set differs from English: dropped
  expect(t("appName")).toBe(en.appName); // markup: dropped
  expect(t("loginTitle")).toBe(en.loginTitle); // not in the pack: English
  expect(uiLanguageTag()).toBe("pa-IN");
  expect(uiTextKnown("ਸਾਈਨ ਇਨ")).toBe(true);
  const form = formUiTranslations(WHO_VA_BUILT_IN_UI_TRANSLATIONS);
  expect(form.pa).toEqual({ next: "ਅੱਗੇ" }); // "required" lost its {label}: dropped
  expect(form.hi).toBe(WHO_VA_BUILT_IN_UI_TRANSLATIONS.hi);
  expect(formUiTranslations(WHO_VA_BUILT_IN_UI_TRANSLATIONS)).toBe(form); // stable until a pack changes
});

it("overlays a correction on a bundled language", async () => {
  respond({ "/api/v1/ui-strings": LIST, "/api/v1/ui-strings/hi": { version: V1, strings: { ...hi, signIn: "प्रवेश" }, form: {} } });
  await syncUiPacks(SERVER, "hi");
  setUiLocale("hi");
  expect(t("signIn")).toBe("प्रवेश");
  expect(t("loginTitle")).toBe(hi.loginTitle);
});

it("uses the stored pack offline, and revalidates it with its version", async () => {
  respond({ "/api/v1/ui-strings": LIST, "/api/v1/ui-strings/pa": PA_PACK });
  await syncUiPacks(SERVER, "pa");
  // A fresh start with no network: the stored list and pack still apply.
  offerBundledUiLanguagesOnly();
  respond({});
  await expect(syncUiPacks(SERVER, "pa")).rejects.toThrow("offline");
  expect(setUiLocale("pa")).toBe("pa");
  expect(t("signIn")).toBe("ਸਾਈਨ ਇਨ");

  // Online again with a newer pack: the stored version goes as If-None-Match.
  respond({
    "/api/v1/ui-strings": { ...LIST, languages: LIST.languages.map((l) => (l.locale === "pa" ? { ...l, version: V2 } : l)) },
    "/api/v1/ui-strings/pa": { version: V2, strings: { signIn: "ਨਵਾਂ" }, form: {} },
  });
  mockRequestRaw.mockClear();
  await syncUiPacks(SERVER, "pa");
  const packCall = mockRequestRaw.mock.calls.find(([, path]) => path === "/api/v1/ui-strings/pa");
  expect(packCall?.[2]).toMatchObject({ ifNoneMatch: `"${V1}"` });
  expect(t("signIn")).toBe("ਨਵਾਂ");
});

it("with no stored pack and no network, a server-only language falls back to English", async () => {
  respond({});
  await expect(syncUiPacks(SERVER, "pa")).rejects.toThrow("offline");
  expect(setUiLocale("pa")).toBe("en");
  expect(t("signIn")).toBe(en.signIn);
});

it("drops the pack of a language the server stops publishing, in memory and on the device", async () => {
  // A version of its own: an unchanged version is (rightly) not applied again, and V1 held other Hindi text in earlier tests.
  const V3 = "e".repeat(64);
  const hiPack = { version: V3, strings: { ...hi, signIn: "प्रवेश" }, form: { next: "अगला" } };
  const list = { ...LIST, languages: LIST.languages.map((l) => (l.locale === "hi" ? { ...l, version: V3 } : l)) };
  respond({ "/api/v1/ui-strings": list, "/api/v1/ui-strings/hi": hiPack });
  await syncUiPacks(SERVER, "hi");
  setUiLocale("hi");
  expect(t("signIn")).toBe("प्रवेश");
  expect(formUiTranslations(WHO_VA_BUILT_IN_UI_TRANSLATIONS).hi).toMatchObject({ next: "अगला" });

  const { result, unmount } = renderLanguages();
  const unpublished = { ...LIST, version: "d".repeat(64), languages: LIST.languages.filter((l) => l.locale !== "hi") };
  respond({ "/api/v1/ui-strings": unpublished });
  await act(() => syncUiPacks(SERVER, "hi"));
  expect(t("signIn")).toBe(hi.signIn); // the bundled Hindi again
  expect(result.current.find((entry) => entry.code === "hi")?.version).toBeUndefined(); // subscribers saw it
  expect(formUiTranslations(WHO_VA_BUILT_IN_UI_TRANSLATIONS).hi).toBe(WHO_VA_BUILT_IN_UI_TRANSLATIONS.hi);
  expect(mockFiles.get("doc/ui-packs/https_va_example_org-hi.json")).toBe("{}");
  unmount();
});

it("keeps the stored list and pack when the server answers the list with an error", async () => {
  respond({ "/api/v1/ui-strings": LIST, "/api/v1/ui-strings/pa": PA_PACK });
  await syncUiPacks(SERVER, "pa");
  const storedList = mockFiles.get("doc/ui-packs/https_va_example_org-list.json");
  expect(storedList).toBeDefined();

  offerBundledUiLanguagesOnly(); // a fresh start
  mockRequestRaw.mockRejectedValue(Object.assign(new Error("unavailable"), { status: 503 }));
  await expect(syncUiPacks(SERVER, "pa")).rejects.toThrow("unavailable");
  expect(mockFiles.get("doc/ui-packs/https_va_example_org-list.json")).toBe(storedList);
  expect(setUiLocale("pa")).toBe("pa");
  expect(t("signIn")).toBe("ਸਾਈਨ ਇਨ");
  expect(mockFiles.get("doc/ui-packs/https_va_example_org-pa.json")).not.toBe("{}");
});

describe("a list answer that is not a clean list", () => {
  const listFile = "doc/ui-packs/https_va_example_org-list.json";
  const paFile = "doc/ui-packs/https_va_example_org-pa.json";

  async function held() {
    respond({ "/api/v1/ui-strings": LIST, "/api/v1/ui-strings/pa": PA_PACK });
    await syncUiPacks(SERVER, "pa");
    expect(t("signIn")).toBe(en.signIn); // pack stored, locale not selected yet
    expect(setUiLocale("pa")).toBe("pa");
    expect(t("signIn")).toBe("ਸਾਈਨ ਇਨ");
    return { storedList: mockFiles.get(listFile), storedPa: mockFiles.get(paFile) };
  }

  it("keeps packs and stored files when a 200 body is not a list", async () => {
    const before = await held();
    respond({ "/api/v1/ui-strings": {} });
    await syncUiPacks(SERVER, "pa");
    expect(mockFiles.get(listFile)).toBe(before.storedList);
    expect(mockFiles.get(paFile)).toBe(before.storedPa);
    expect(t("signIn")).toBe("ਸਾਈਨ ਇਨ");
  });

  it("keeps the pack of an entry that is present but fails validation", async () => {
    const before = await held();
    const bad = { ...LIST, version: "d".repeat(64), languages: LIST.languages.map((l) => (l.locale === "pa" ? { ...l, direction: "sideways" } : l)) };
    respond({ "/api/v1/ui-strings": bad });
    await syncUiPacks(SERVER, "pa");
    expect(mockFiles.get(paFile)).toBe(before.storedPa);
    expect(formUiTranslations(WHO_VA_BUILT_IN_UI_TRANSLATIONS).pa).toEqual({ next: "ਅੱਗੇ" }); // not dropped
  });

  it("treats a valid empty list as nothing published and drops the packs", async () => {
    await held();
    respond({ "/api/v1/ui-strings": { version: "e".repeat(64), languages: [] } });
    await syncUiPacks(SERVER, "pa");
    expect(mockFiles.get(paFile)).toBe("{}");
  });
});

it("offers every questionnaire language the project enables, with or without a UI pack", () => {
  const available = [{ code: "ar" }, { code: "hi" }, { code: "en" }];
  expect(questionnaireLocales(available)).toEqual(available);
});

it("does not lay an unchanged pack over the language again (no app-wide re-render)", async () => {
  const V4 = "f".repeat(64);
  const pack = { version: V4, strings: { signIn: "ਸਾਈਨ ਇਨ" }, form: { next: "ਅੱਗੇ" } };
  const list = { ...LIST, languages: LIST.languages.map((l) => (l.locale === "pa" ? { ...l, version: V4 } : l)) };
  respond({ "/api/v1/ui-strings": list, "/api/v1/ui-strings/pa": pack });
  await syncUiPacks(SERVER, "pa");
  const before = formRevisionNow();
  await syncUiPacks(SERVER, "pa");
  expect(formRevisionNow()).toBe(before); // the form-label revision (what re-renders the form) did not move
});
