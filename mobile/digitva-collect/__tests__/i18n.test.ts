import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";
import { setUiLocale, t } from "../src/i18n";

describe("t()", () => {
  afterEach(() => setUiLocale("en"));

  it("uses the chosen language and its base for regional codes", () => {
    expect(setUiLocale("hi-IN")).toBe("hi");
    expect(t("signIn")).toBe(hi.signIn);
  });

  it("falls back to English for an unknown language", () => {
    expect(setUiLocale("ta")).toBe("en");
    expect(setUiLocale(undefined)).toBe("en");
    expect(t("signIn")).toBe(en.signIn);
  });

  it("interpolates variables and leaves unknown placeholders", () => {
    expect(t("signOutUnsent", { count: 3 })).toContain("3 interviews");
    expect(t("syncResult", { sent: 1 })).toContain("{failed}");
  });

  it("has the same keys in every dictionary", () => {
    expect(Object.keys(hi).sort()).toEqual(Object.keys(en).sort());
  });
});
