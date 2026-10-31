/**
 * The phone's offline category rendering equals the server's (docs/policy/doris-cod-workflow.md, "Offline coding
 * workspace"): every case of the golden file (scripts/export_offline_va_display_golden.py, the server's real render
 * functions over fixed synthetic answers) replayed through src/workspace/localCategories.ts after the phone's own
 * strip of irrelevant answers, and the bundled display pack is the one the golden was rendered with.
 */
import { createHash } from "node:crypto";

import { createWhoVa2022Instrument, whoVa2022Instrument } from "@drguptavivek/who-2022-va";

import pack from "../assets/va-display-WHO_2022_VA.json";
import golden from "./fixtures/va-display-golden.json";
import { serverKeptAnswers, serverStripInstrument } from "../src/coding/irrelevantAnswers";
import { createDisplayPackIndex, localCaseHeader, localCaseView, type DisplayPackIndex } from "../src/workspace/localCategories";
import { parseCategory } from "../src/workspace/contracts";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"),
}));

const sha256 = (value: string) => createHash("sha256").update(value, "utf8").digest("hex");
// The golden's NOW (2026-10-31 12:00 Asia/Kolkata), what today() reads.
const NOW = new Date("2026-10-31T12:00:00+05:30");

type GoldenCase = (typeof golden.cases)[number];

let index: DisplayPackIndex;
beforeAll(async () => { index = await createDisplayPackIndex(pack); });

describe("the display pack", () => {
  it("is the pack the golden renders were built with, and its hash checks", () => {
    expect(golden.pack_sha256).toBe(pack.content_sha256);
    expect(index.contentSha256).toBe(pack.content_sha256);
  });

  it("refuses a pack whose content, hash or schema does not match", async () => {
    const changed = { ...pack, flip_labels: [...pack.flip_labels, "Added"] };
    await expect(createDisplayPackIndex(changed)).rejects.toThrow("va_display_pack_invalid");
    await expect(createDisplayPackIndex({ ...pack, content_sha256: sha256("other") })).rejects.toThrow("va_display_pack_invalid");
    await expect(createDisplayPackIndex({ ...pack, schema: 2 })).rejects.toThrow("va_display_pack_invalid");
    await expect(createDisplayPackIndex({ ...pack, categories: {} })).rejects.toThrow("va_display_pack_invalid");
    await expect(createDisplayPackIndex(null)).rejects.toThrow("va_display_pack_invalid");
    // db_revision is outside the hash.
    await expect(createDisplayPackIndex({ ...pack, db_revision: "another" })).resolves.toBeDefined();
  });
});

describe.each(golden.cases.map((item) => [item.name, item] as [string, GoldenCase]))("golden case %s", (_name, item) => {
  const view = () => localCaseView(index, serverKeptAnswers({ data: item.data }, NOW));

  it("has the server's nav, counts, default category and summary", () => {
    expect(golden.cases.length).toBeGreaterThan(0);
    const local = view();
    expect(local.categories).toEqual(item.categories);
    expect(local.defaultCategory).toBe(item.default_category);
    expect(local.summaryItems).toEqual(item.summary_items);
  });

  it("has the server's visible categories", () => {
    expect(view().visibleCategoryCodes).toEqual(item.visible_category_codes);
  });

  it("serves the server's payload for every nav category, and it passes the client contract", () => {
    const local = view();
    expect(item.category_payloads.map((payload) => payload.code)).toEqual(item.categories.map((category) => category.code));
    for (const expected of item.category_payloads) {
      const payload = local.category(expected.code);
      expect(payload).toEqual(expected);
      expect(parseCategory(JSON.parse(JSON.stringify(payload)), "coding")).toEqual(payload);
    }
  });
});

describe("the answers offline coding renders (the route's serverKeptAnswers)", () => {
  it("strips with every DigitVA layer, whatever the project enables, as the server does", () => {
    // A served form version: the recorded composed definition, which is the package's all-layers instrument.
    const served = serverStripInstrument("2022-0123456789");
    expect(served.questions.length).toBeGreaterThan(0);
    expect(served).toEqual(whoVa2022Instrument);
    // Any other version: the server instrument, the same layers with WHO's own rules.
    const unserved = serverStripInstrument("2022");
    expect(unserved.questions.map((q) => q.name)).toEqual(whoVa2022Instrument.questions.map((q) => q.name));
    expect(serverStripInstrument(undefined)).toBe(unserved);
  });

  it("strips a draft's answers to a fixed point (md_available -> md_count -> md_im1)", () => {
    const data = { Id10013: "yes", md_available: "no", md_count: "2", md_im1: "who-va-attachment:1" };
    const kept = serverKeptAnswers({ instrumentVersion: "2022-0123456789", data }, NOW);
    expect(kept).toEqual({ Id10013: "yes", md_available: "no" });
  });
});

describe("rendering rules outside the golden", () => {
  it("answers a code outside the nav as not found, as the server's category route", () => {
    const local = localCaseView(index, { Id10013: "yes" });
    expect(() => local.category("vamaternalsymptoms")).toThrow(expect.objectContaining({ status: 404, code: "not_found" }));
  });

  it("renders an attachment held as the form engine's reference object", () => {
    const local = localCaseView(index, { Id10013: "yes", Id10476_audio: { uri: "who-va-attachment:00000000-0000-4000-8000-000000000001", mimeType: "audio/mp4" } });
    const values = local.category("vanarrationanddocuments").subcategories.flatMap((sub) => sub.items.map((entry) => entry.value));
    expect(values).toContain("digitva-local-attachment:Id10476_audio");
  });

  it("derives the case header as the server does for an app interview", () => {
    const answers = { Id10013: "yes", Id10019: "female", ageInYears: "34.7" };
    expect(localCaseHeader(localCaseView(index, answers), answers)).toEqual({ age: 34, gender: "female", survey_district: null, survey_state: null });
    expect(localCaseHeader(localCaseView(index, {}), {})).toEqual({ age: 0, gender: "unknown", survey_district: null, survey_state: null });
  });
});
