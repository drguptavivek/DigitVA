import { describe, expect, it } from "vitest";

import { NARRATIVE_VOICE_HINT, createWhoVa2022Instrument } from "../src/instrument.js";

// Owner decision 2026-10-23 (digitva-kkdb step 1): voice-typing tip under Id10476.
const narrative = (core: boolean) =>
  createWhoVa2022Instrument(new Set(core ? ["digitva_core"] : [])).questions.find((q) => q.name === "Id10476")!;

describe("narrative voice-typing hint", () => {
  it("adds the en and hi tip and keeps WHO's own hint", () => {
    const q = narrative(true);
    expect(q.hint.en).toContain(NARRATIVE_VOICE_HINT.en);
    expect(q.hint.en).toContain("no information available");
    expect(q.hint.hi?.startsWith(NARRATIVE_VOICE_HINT.hi)).toBe(true);
  });
});
