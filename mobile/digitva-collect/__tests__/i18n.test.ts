import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";
import { questionnaireDefault, questionnaireLocales, normalizeLocale, setUiLocale, t } from "../src/i18n";

describe("t()", () => {
  afterEach(() => setUiLocale("en"));

  it("uses the chosen language and its base for regional codes", () => {
    expect(setUiLocale("hi-IN")).toBe("hi");
    expect(t("signIn")).toBe(hi.signIn);
    expect(setUiLocale("HI_in")).toBe("hi");
  });

  it("normalizes exact, base and unknown locales in that order", () => {
    expect(normalizeLocale(" hi ")).toBe("hi");
    expect(normalizeLocale("hi-IN")).toBe("hi");
    expect(normalizeLocale("ta-IN")).toBe("en");
    expect(normalizeLocale(null)).toBe("en");
    expect(normalizeLocale("constructor")).toBe("en");
    expect(normalizeLocale("__proto__")).toBe("en");
  });

  it("falls back to English for an unknown language", () => {
    expect(setUiLocale("ta")).toBe("en");
    expect(setUiLocale(undefined)).toBe("en");
    expect(t("signIn")).toBe(en.signIn);
  });

  it("interpolates variables and leaves unknown placeholders", () => {
    expect(t("reEnrolUnsentName", { name: "Asha", count: 3 })).toContain("Asha: 3 items");
    expect(t("syncResult", { sent: 1 })).toContain("{failed}");
  });

  it("has the same keys in every dictionary", () => {
    expect(Object.keys(hi).sort()).toEqual(Object.keys(en).sort());
  });

  it("localizes the web coding hint", () => {
    setUiLocale("en");
    expect(t("readyForCodeOnWeb")).toBe("Ready for you to code on the web.");
    setUiLocale("hi");
    expect(t("readyForCodeOnWeb")).toBe(hi.readyForCodeOnWeb);
  });
});

it("offers every enabled questionnaire language, with or without a UI pack (digitva-s028)", () => {
  const available = [{code: "ar"}, {code: "hi"}, {code: "en"}];
  expect(questionnaireLocales(available)).toEqual(available);
  expect(questionnaireDefault(available, "ar")).toBe("ar");
  expect(questionnaireDefault([{code: "hi"}], "ar")).toBe("hi");
  expect(questionnaireDefault([{code: "ar"}], "fr")).toBe("ar");
  expect(() => questionnaireDefault([], "ar")).toThrow("questionnaire_language_not_enabled");
  expect(questionnaireDefault(undefined, undefined)).toBe("en");
});

describe("isLocaleCode (draft resume in any enabled questionnaire language)", () => {
  const { isLocaleCode } = jest.requireActual("../src/i18n");
  it("accepts language codes without a UI pack and refuses junk", () => {
    expect(isLocaleCode("ml")).toBe(true);
    expect(isLocaleCode("pt-br")).toBe(true);
    expect(isLocaleCode("hi")).toBe(true);
    expect(isLocaleCode("")).toBe(false);
    expect(isLocaleCode("../en")).toBe(false);
    expect(isLocaleCode(7)).toBe(false);
  });
});
