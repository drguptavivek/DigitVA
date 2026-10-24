import { describe, expect, it } from "vitest";

import { PLACE_ADDRESS_HINTS, createWhoVa2022Instrument } from "../src/instrument.js";

// Owner decision 2026-10-24 (digitva-xrqv): free-text place questions say an
// address / place name is wanted. Wording, constraints and relevance are WHO's.
const withHints = createWhoVa2022Instrument(new Set(["digitva_core"])).questions;
const plain = createWhoVa2022Instrument(new Set()).questions;
const find = (list: typeof withHints, name: string) => list.find((q) => q.name === name)!;

describe("place/address hints", () => {
  it.each(Object.keys(PLACE_ADDRESS_HINTS))("%s carries the en and hi hint", (name) => {
    const q = find(withHints, name);
    expect(q.hint.en).toContain(PLACE_ADDRESS_HINTS[name]!.en);
    expect(q.hint.hi).toBe(PLACE_ADDRESS_HINTS[name]!.hi);
  });

  it("covers exactly the four free-text place questions, not the categorical Id10058", () => {
    expect(Object.keys(PLACE_ADDRESS_HINTS).sort()).toEqual(["Id10054", "Id10055", "Id10057", "Id10072"]);
    expect(find(withHints, "Id10058").hint.hi).toBeUndefined();
  });

  it("keeps WHO's own hint after the new one and leaves constraints and relevance alone", () => {
    expect(find(withHints, "Id10054").hint.en).toContain("A question on the facility");
    for (const name of Object.keys(PLACE_ADDRESS_HINTS)) {
      const a = find(withHints, name);
      const b = find(plain, name);
      expect(a.label).toEqual(b.label);
      expect(a.relevant).toEqual(b.relevant);
      expect(a.constraint).toEqual(b.constraint);
      expect(a.required).toBe(b.required);
    }
  });
});
