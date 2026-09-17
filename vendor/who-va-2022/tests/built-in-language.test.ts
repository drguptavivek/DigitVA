import { describe, expect, it } from "vitest";

import { WHO_VA_2022_LANGUAGES, loadWhoVa2022Language } from "../src/instrument-loader.js";
import { whoVa2022Instrument } from "../src/instrument.js";

describe("built-in languages", () => {
  it("ships only the unmodified English source instrument", async () => {
    expect(WHO_VA_2022_LANGUAGES).toEqual([{ locale: "en", label: "English" }]);

    const requestedTranslation = await loadWhoVa2022Language("hi-IN");
    expect(requestedTranslation.locale).toBe("en");
    expect(requestedTranslation.instrument).toBe(whoVa2022Instrument);
    expect(requestedTranslation.uiTranslations).toEqual({});
  });
});
