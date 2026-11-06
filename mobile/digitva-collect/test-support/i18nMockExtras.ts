/**
 * The i18n functions AppState and the pack layer call (digitva-dt1e), for tests that mock
 * src/i18n with only t/setUiLocale: spread it first so the test's own keys win.
 * `jest.mock("../src/i18n", () => ({ ...require("../test-support/i18nMockExtras").i18nMockExtras, t: ... }))`
 */
export const i18nMockExtras = {
  requestedUiLocale: () => "en",
  subscribeUiLanguages: () => () => undefined,
  setServerUiLanguages: () => undefined,
  uiLocale: () => "en",
  uiLanguages: () => [],
  normalizeLocale: () => "en",
  // The real lookup, so a panel that names its locale (RefusalPanel) still shows English text.
  translate: (locale: string, key: string) => jest.requireActual("../src/i18n").translate(locale, key),
};
