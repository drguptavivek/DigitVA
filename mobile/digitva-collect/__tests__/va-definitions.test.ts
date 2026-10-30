import { createHash } from "node:crypto";

import { createVaDefinitionIndex, findBundledVaDefinition, type VaDefinitionsPack } from "../src/coding/vaDefinitions";
import { getBundledVaDefinition } from "../src/coding/bundledVaDefinitions";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"),
}));

const sha256 = (value: string) => createHash("sha256").update(value, "utf8").digest("hex");

/** A small schema-2 pack with its real content hash, in the exporter's key order (the real asset is regenerated elsewhere). */
function pack(): VaDefinitionsPack {
  const content = {
    schema: 2,
    scheme: "WHO_2022_VA_2026",
    release: "2026-01",
    count: 5,
    buckets: {
      vas_01_01: { label: "Sepsis", section: "Infectious diseases", section_code: "infectious", va_code: "VAs-01.01" },
      vas_02_01: { label: "Cancer", section: "Neoplasms", section_code: "neoplasms", va_code: "VAs-02.01" },
      vas_98: { label: "Other and unspecified NCD", section: "Non-communicable diseases", section_code: "ncd", va_code: "VAs-98" },
      other_gastrointestinal_diseases: { label: "Other Gastrointestinal Diseases", section: null, section_code: null, va_code: null },
    },
    definitions: {
      "VAs-01.01": { title: "Sepsis", definition_html: "<p>Fever</p>" },
      "VAs-02.01": { title: "Cancer", definition_html: "" },
    },
    codes: {
      "1A00": "vas_01_01",
      "1A00.1": "vas_01_01",
      GB00: "vas_02_01",
      "5A00": "vas_98",
      DA00: "other_gastrointestinal_diseases",
    },
  };
  return { ...content, db_revision: "rev1", content_sha256: sha256(JSON.stringify(content)) };
}

describe("bundled ICD-11 VA cause buckets", () => {
  test("accepts a schema-2 pack whose hash matches, ignoring db_revision", async () => {
    const good = pack();
    await expect(createVaDefinitionIndex({ ...good, db_revision: "another" })).resolves.toBeDefined();
    await expect(createVaDefinitionIndex({ ...good, db_revision: null })).resolves.toBeDefined();
  });

  test("fails closed on a bad hash, schema 1, count, unknown node and malformed bucket", async () => {
    const good = pack();
    const bad = (change: object) => expect(createVaDefinitionIndex({ ...good, ...change })).rejects.toThrow("va_definitions_pack_invalid");
    await bad({ content_sha256: "c".repeat(64) });
    await bad({ schema: 1 });
    await bad({ count: 4 });
    await bad({ release: "2026-02" });
    await bad({ codes: { ...good.codes, "1A00": "no_such_node" } });
    await bad({ buckets: { ...good.buckets, vas_98: { label: 5 } } });
    await expect(createVaDefinitionIndex(null)).rejects.toThrow("va_definitions_pack_invalid");
  });

  test("returns the bucket with its definition for a node that has one", async () => {
    const index = await createVaDefinitionIndex(pack());
    expect(findBundledVaDefinition(index, "1A00")).toEqual({
      icd_code: "1A00", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Fever</p>",
      bucket_code: "vas_01_01", bucket_label: "Sepsis", bucket_section: "Infectious diseases", has_definition: true,
    });
    expect(findBundledVaDefinition(index, "1A00.1 - child title")?.icd_code).toBe("1A00.1");
    // A definition row with empty text still has a definition.
    expect(findBundledVaDefinition(index, "GB00")).toMatchObject({ has_definition: true, definition_html: "" });
  });

  test("returns a label-only bucket without a definition, using the node code when there is no VAs code", async () => {
    const index = await createVaDefinitionIndex(pack());
    expect(findBundledVaDefinition(index, "5A00")).toEqual({
      icd_code: "5A00", classification: "icd11", va_code: "VAs-98", title: "Other and unspecified NCD", definition_html: "",
      bucket_code: "vas_98", bucket_label: "Other and unspecified NCD", bucket_section: "Non-communicable diseases", has_definition: false,
    });
    expect(findBundledVaDefinition(index, "DA00")).toMatchObject({
      va_code: "other_gastrointestinal_diseases", bucket_section: null, has_definition: false,
    });
  });

  test("tells a stem in no pack entry (null) from a value that cannot be looked up (undefined)", async () => {
    const index = await createVaDefinitionIndex(pack());
    expect(findBundledVaDefinition(index, "2B00")).toBeNull();
    expect(findBundledVaDefinition(index, "not a code")).toBeUndefined();
    expect(findBundledVaDefinition(index, "")).toBeUndefined();
  });

  test("buckets a '/' cluster by its primary stem, with first-stem fallback", async () => {
    const index = await createVaDefinitionIndex(pack());
    expect(findBundledVaDefinition(index, "1A00.1/2F9Z cluster")?.va_code).toBe("VAs-01.01");
    expect(findBundledVaDefinition(index, "1A00.1/GB00 cluster", "GB00")?.va_code).toBe("VAs-02.01");
    expect(findBundledVaDefinition(index, "1A00.1/GB00 cluster", "GB00")?.icd_code).toBe("GB00");
  });

  test("hashes the same canonical JSON as the Python exporter, including Unicode", async () => {
    const content = {
      schema: 2, scheme: "WHO_2022_VA_2026", release: "2026-01", count: 1,
      buckets: { vas_01_01: { label: "Café", section: "Sé", section_code: "se", va_code: "VAs-01.01" } },
      definitions: { "VAs-01.01": { title: "Café", definition_html: "<p>Fever &amp; pain</p>" } },
      codes: { "1A00": "vas_01_01" },
    };
    // Python: json.dumps(content, separators=(",", ":"), ensure_ascii=False)
    const python = '{"schema":2,"scheme":"WHO_2022_VA_2026","release":"2026-01","count":1,"buckets":{"vas_01_01":{"label":"Café","section":"Sé","section_code":"se","va_code":"VAs-01.01"}},"definitions":{"VAs-01.01":{"title":"Café","definition_html":"<p>Fever &amp; pain</p>"}},"codes":{"1A00":"vas_01_01"}}';
    expect(JSON.stringify(content)).toBe(python);
    const index = await createVaDefinitionIndex({ ...content, db_revision: null, content_sha256: sha256(python) });
    expect(findBundledVaDefinition(index, "1A00")?.title).toBe("Café");
  });
});

test("the shipped asset is a valid schema-2 pack and a lookup answers from it", async () => {
  await expect(getBundledVaDefinition("5A00.0")).resolves.not.toBeUndefined();
  await expect(getBundledVaDefinition("not a code")).rejects.toThrow("va_definition_unavailable");
});
