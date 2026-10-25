// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import * as preloaded from "../src/web-preloaded.js";
import { whoVa2022Instrument } from "../src/instrument.js";

describe("preloaded web entry", () => {
  it("exposes the core and web surface from one namespace", () => {
    expect(preloaded.WhoVaForm).toBeDefined();
    expect(preloaded.WhoVaQuestionControls).toBeDefined();
    expect(preloaded.createWhoVaSession).toBeDefined();
    expect(preloaded.createWhoVa2022Instrument).toBeDefined();
    expect(preloaded.whoVa2022Instrument).toBe(whoVa2022Instrument);
    expect(preloaded.WHO_VA_2022_LANGUAGES).toEqual([{ locale: "en", label: "English" }]);
  });

  it("returns one already-loaded instrument promise and language result", async () => {
    const first = preloaded.loadWhoVa2022Instrument();
    expect(first).toBe(preloaded.loadWhoVa2022Instrument());
    expect(await first).toBe(whoVa2022Instrument);

    await expect(preloaded.loadWhoVa2022Language("en")).resolves.toEqual({
      locale: "en",
      instrument: whoVa2022Instrument,
      uiTranslations: {}
    });
  });
});
