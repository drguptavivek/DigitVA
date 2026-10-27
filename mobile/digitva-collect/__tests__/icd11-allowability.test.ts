/**
 * The device-side ICD-11 allowability rules against the bundled pack: the same cases the server tests pin
 * (tests/services/test_masked_doris_coding.py, test_migrate_icd11_chapter_22_kd3b_z.py).
 */
import { createHash } from "node:crypto";

import pack from "../assets/icd11-allowability-2026-01.json";
import { OFFLINE_ICD11_RELEASE } from "../src/workspace/offlineDoris";
import {
  ageGroupForDays,
  causingConditionUnknownError,
  checkAllowability,
  codingContextFromInterview,
  createAllowabilityIndex,
  extractIcd11CodeExpression,
  icd11PrimaryStem,
  normalizedAgeDays,
  type AllowabilityPack,
  type CodingContext,
} from "../src/coding/icd11Allowability";

jest.mock("expo-crypto", () => ({ CryptoDigestAlgorithm: { SHA256: "SHA-256" }, digestStringAsync: async () => "", randomUUID: () => "u" }));

const index = createAllowabilityIndex(pack as AllowabilityPack);
const unknown: CodingContext = { ageGroup: null, sex: null };
const adultMale: CodingContext = { ageGroup: "adult", sex: "male" };
const adultFemale: CodingContext = { ageGroup: "adult", sex: "female" };

describe("the bundled pack", () => {
  it("is the pinned release and carries the sha256 of its own content", () => {
    expect(pack.release).toBe(OFFLINE_ICD11_RELEASE);
    const digest = createHash("sha256").update(JSON.stringify({ release: pack.release, groups: pack.groups }), "utf8").digest("hex");
    expect(digest).toBe(pack.sha256);
    expect(index.version).toBe(`${pack.release}+${pack.sha256.slice(0, 12)}`);
  });

  it("refuses a pack it does not understand", () => {
    expect(() => createAllowabilityIndex({ ...(pack as AllowabilityPack), schema: 2 })).toThrow("allowability_pack_invalid");
    expect(() => createAllowabilityIndex({ ...(pack as AllowabilityPack), count: 1 })).toThrow("allowability_pack_invalid");
  });
});

describe("checkAllowability", () => {
  it("allows an unrestricted code", () => {
    expect(checkAllowability(index, "1A00", adultMale)).toEqual({ status: "ok" });
  });

  it("blocks chapter 22 injury-nature codes and non-category codes", () => {
    for (const code of ["NA07.7", "NA00", "NC15.3Z"]) {
      expect(checkAllowability(index, code, unknown)).toEqual({ status: "blocked", message: `${code} is not selectable for this submission.` });
    }
  });

  it("allows KD3B.Z for a neonate, asks an adult to confirm, and keeps the parent KD3B excluded", () => {
    expect(checkAllowability(index, "KD3B.Z", { ageGroup: "neonate", sex: null })).toEqual({ status: "ok" });
    expect(checkAllowability(index, "KD3B.Z", { ageGroup: "infant", sex: "female" })).toEqual({ status: "ok" });
    expect(checkAllowability(index, "KD3B.Z", adultMale)).toEqual({
      status: "age_confirm",
      restriction: { code: "KD3B.Z", age_group_selectable: "neonate_infant", restriction_note: "chapter 19 (KA-KD), neonates and infants" },
    });
    expect(checkAllowability(index, "KD3B", unknown).status).toBe("blocked");
  });

  it("blocks a sex conflict and allows the matching sex or an unknown sex", () => {
    expect(checkAllowability(index, "GB00", adultFemale).status).toBe("blocked");
    expect(checkAllowability(index, "GB00", adultMale)).toEqual({ status: "ok" });
    expect(checkAllowability(index, "GB00", { ageGroup: "adult", sex: null })).toEqual({ status: "ok" });
    expect(checkAllowability(index, "JA00", adultMale).status).toBe("blocked");
  });

  it("a sex conflict wins over an age conflict, as on the server", () => {
    // JA00 is female and adult only: a male child fails both, and sex blocks.
    expect(checkAllowability(index, "JA00", { ageGroup: "child", sex: "male" }).status).toBe("blocked");
    expect(checkAllowability(index, "JA00", { ageGroup: "child", sex: "female" }).status).toBe("age_confirm");
  });

  it("warns, not blocks, on an age conflict; unknown age adds no filter", () => {
    expect(checkAllowability(index, "KB2C", { ageGroup: "adult", sex: null })).toMatchObject({ status: "age_confirm", restriction: { code: "KB2C", age_group_selectable: "neonate_infant" } });
    expect(checkAllowability(index, "KB2C", { ageGroup: "child", sex: null }).status).toBe("age_confirm");
    expect(checkAllowability(index, "KB2C", { ageGroup: "infant", sex: null })).toEqual({ status: "ok" });
    expect(checkAllowability(index, "KB2C", unknown)).toEqual({ status: "ok" });
    // infant-only code: a neonate conflicts, an infant does not.
    expect(checkAllowability(index, "MH11.Z", { ageGroup: "neonate", sex: null }).status).toBe("age_confirm");
    expect(checkAllowability(index, "MH11.Z", { ageGroup: "infant", sex: null })).toEqual({ status: "ok" });
  });
});

describe("code expressions and the primary stem of a '/' cluster", () => {
  it("extracts the leading expression and rejects malformed ones", () => {
    expect(extractIcd11CodeExpression("fb80.b/2f9z Some title")).toBe("FB80.B/2F9Z");
    expect(extractIcd11CodeExpression("1G40.0&XN8Q/1G41 t")).toBe("1G40.0&XN8Q/1G41");
    expect(extractIcd11CodeExpression("/2F9Z")).toBeNull();
    expect(extractIcd11CodeExpression("&XN8Q")).toBeNull();
    expect(extractIcd11CodeExpression("not-a-code")).toBeNull();
    expect(extractIcd11CodeExpression("")).toBeNull();
    expect(extractIcd11CodeExpression(null)).toBeNull();
  });

  it("uses WHO's causing condition, else the first stem", () => {
    expect(icd11PrimaryStem({ hasCausingCondition: ["2F9Z"] }, "FB80.B")).toBe("2F9Z");
    expect(icd11PrimaryStem({ hasCausingCondition: ["2F9Z", "1A00"] }, "FB80.B")).toBe("2F9Z");
    expect(icd11PrimaryStem({ hasCausingCondition: [] }, "FB80.B")).toBe("FB80.B");
    expect(icd11PrimaryStem({ hasCausingCondition: ["junk"] }, "FB80.B")).toBe("FB80.B");
    expect(icd11PrimaryStem(null, "FB80.B")).toBe("FB80.B");
  });

  it("judges a cluster by its causing condition, not by the first stem", () => {
    // The first stem 1A00 is open to all; the causing condition GB00 is male only.
    const primary = icd11PrimaryStem({ hasCausingCondition: ["GB00"] }, "1A00");
    expect(checkAllowability(index, primary, adultFemale).status).toBe("blocked");
    expect(checkAllowability(index, "1A00", adultFemale)).toEqual({ status: "ok" });
  });
});

describe("causing condition not known", () => {
  it("is valid on a single stem (with extensions) only", () => {
    expect(causingConditionUnknownError("BA41.Z")).toBeNull();
    expect(causingConditionUnknownError("1G40.0&XN8Q")).toBeNull();
    expect(causingConditionUnknownError("FB80.B/2F9Z")).toMatch(/single ICD-11 stem/);
    expect(causingConditionUnknownError(null)).toMatch(/single ICD-11 stem/);
  });
});

describe("the deceased's coding context from the interview", () => {
  it("groups ages by the WHO 2022 boundaries", () => {
    expect(ageGroupForDays(27)).toBe("neonate");
    expect(ageGroupForDays(28)).toBe("infant");
    expect(ageGroupForDays(364)).toBe("infant");
    expect(ageGroupForDays(365)).toBe("child");
    expect(ageGroupForDays(12 * 365.25 - 1)).toBe("child");
    expect(ageGroupForDays(12 * 365.25)).toBe("adult");
    expect(ageGroupForDays(null)).toBeNull();
  });

  it("follows the server's source precedence over the stored answers", () => {
    expect(normalizedAgeDays({ age_neonate_hours: "5", age_neonate_days: "3" })).toBe(0);
    expect(normalizedAgeDays({ age_neonate_days: "3", ageInYears: "40" })).toBe(3);
    expect(normalizedAgeDays({ isChild: "1", ageInMonths: "6", ageInYears: "0" })).toBeCloseTo(6 * 30.4375);
    expect(normalizedAgeDays({ isAdult: "1", ageInYears: "40" })).toBeCloseTo(40 * 365.25);
    expect(normalizedAgeDays({ ageInDays: "10" })).toBe(10);
    expect(normalizedAgeDays({})).toBeNull();
  });

  it("falls back to the form's own entry fields when no calculated age is stored", () => {
    expect(normalizedAgeDays({ age_group: "adult", age_adult: "62" })).toBeCloseTo(62 * 365.25);
    expect(normalizedAgeDays({ age_group: "child", age_child_unit: "months", age_child_months: "9" })).toBeCloseTo(9 * 30.4375);
    expect(normalizedAgeDays({ age_group: "child", age_child_unit: "days", age_child_days: "40" })).toBe(40);
    expect(normalizedAgeDays({ age_group: "child", age_child_unit: "years" })).toBeNull();
  });

  it("takes male or female only", () => {
    expect(codingContextFromInterview({ Id10019: "Male", age_group: "adult", age_adult: "62" })).toEqual({ ageGroup: "adult", sex: "male" });
    expect(codingContextFromInterview({ Id10019: "undetermined" })).toEqual({ ageGroup: null, sex: null });
  });
});
