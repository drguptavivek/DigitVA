import { createVaDefinitionIndex, findBundledVaDefinition, type VaDefinitionsPack } from "../src/coding/vaDefinitions";
import { getBundledVaDefinition } from "../src/coding/bundledVaDefinitions";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"),
}));

function pack(): VaDefinitionsPack {
  return {
    schema: 1,
    scheme: "WHO_2022_VA_2026",
    release: "2026-01",
    source_digest: "b".repeat(64),
    content_sha256: "a".repeat(64),
    count: 3,
    definitions: {
      "VAs-01.01": { title: "Sepsis", definition_html: "<p>Fever</p>" },
      "VAs-02.01": { title: "Cancer", definition_html: "" },
    },
    codes: {
      "1A00": "VAs-01.01",
      "1A00.1": "VAs-01.01",
      "GB00": "VAs-02.01",
    },
  };
}

describe("bundled ICD-11 VA definitions", () => {
  test("loads the generated bundled reference asset and validates its digest", async () => {
    const definition = await getBundledVaDefinition("1A00");
    expect(definition).toMatchObject({ icd_code: "1A00", classification: "icd11", va_code: expect.stringMatching(/^VAs-/) });
  });

  test("validates the pack and returns existing VA definition shape for exact and parent mappings", async () => {
    const index = await createVaDefinitionIndex(pack(), async () => "a".repeat(64));
    expect(findBundledVaDefinition(index, "1A00")).toEqual({
      icd_code: "1A00", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Fever</p>",
    });
    expect(findBundledVaDefinition(index, "1A00.1 - child title")?.icd_code).toBe("1A00.1");
    expect(findBundledVaDefinition(index, "2B00")).toBeNull();
  });

  test("uses the causing-condition stem for a postcoordinated value, with first-stem fallback", async () => {
    const index = await createVaDefinitionIndex(pack(), async () => "a".repeat(64));
    expect(findBundledVaDefinition(index, "1A00.1/2F9Z cluster")?.va_code).toBe("VAs-01.01");
    expect(findBundledVaDefinition(index, "1A00.1/GB00 cluster", "GB00")?.va_code).toBe("VAs-02.01");
  });

  test("fails closed on count, missing definition, and content digest mismatch", async () => {
    await expect(createVaDefinitionIndex({ ...pack(), count: 4 }, async () => "a".repeat(64))).rejects.toThrow("va_definitions_pack_invalid");
    await expect(createVaDefinitionIndex({ ...pack(), definitions: {} }, async () => "a".repeat(64))).rejects.toThrow("va_definitions_pack_invalid");
    await expect(createVaDefinitionIndex(pack(), async () => "c".repeat(64))).rejects.toThrow("va_definitions_pack_invalid");
  });
});

test("matches the Python exporter SHA-256 canonical JSON vector including Unicode", async () => {
  const crypto = require("node:crypto") as typeof import("node:crypto");
  const fixture = {
    schema: 1,
    scheme: "WHO_2022_VA_2026",
    release: "2026-01",
    source_digest: "b".repeat(64),
    count: 1,
    definitions: { "VAs-01.01": { title: "Café", definition_html: "<p>Fever &amp; pain</p>" } },
    codes: { "1A00": "VAs-01.01" },
  };
  const expected = "b1a705617815902c8ca9d91c70de0f1b4a20e965acb91aa2124f9d2418864429";
  const index = await createVaDefinitionIndex({ ...fixture, content_sha256: expected }, async (value) =>
    crypto.createHash("sha256").update(value, "utf8").digest("hex"));
  expect(findBundledVaDefinition(index, "1A00")?.title).toBe("Café");
});
