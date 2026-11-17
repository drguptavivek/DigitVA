/**
 * certificateSeedFromInterview's manner of death equals app/services/doris_prefill.py's `_manner`. The fixture holds
 * the server's own output (doris_prefill_from_payload) for fixed answers, one case per branch; regenerate it from
 * the Python if the server's mapping changes.
 */
import { certificateSeedFromInterview } from "../src/workspace/offlineDoris";
import fixture from "./doris-manner-parity.fixture.json";

jest.mock("expo-crypto", () => ({}));

type Case = { answers: Record<string, unknown>; certificate: Record<string, unknown>; provenance: Record<string, unknown> };
const cases = fixture as Record<string, Case>;

describe("manner of death prefill parity with the server", () => {
  it("covers every branch", () => {
    expect(Object.keys(cases).sort()).toEqual([
      "accident", "assault", "bad_date", "blank", "dk", "intent_unknown", "legal", "nature", "no", "none_asked", "self", "undetermined", "war",
    ]);
  });

  it.each(Object.keys(cases))("%s", (name) => {
    const { answers, certificate, provenance } = cases[name];
    const seed = certificateSeedFromInterview(answers);
    expect(seed.certificate).toEqual({ ICDVersion: "ICD11", ...certificate });
    expect(seed.provenance).toEqual(provenance);
    // Assert the subject is present before any "absent" case is trusted.
    if (name === "legal") expect(seed.certificate).toHaveProperty("MannerOfDeath.DescriptionExternalCause", "Road traffic injury; Firearm injury");
  });
});
