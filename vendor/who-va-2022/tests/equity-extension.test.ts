import { describe, expect, it } from "vitest";

import { createWhoVa2022Instrument } from "../src/instrument.js";
import { isQuestionRelevant, validateAnswer } from "../src/engine/validation.js";

import type { InstrumentDefinition } from "../src/types.js";

// Policy: docs/policy/digitva-who-form-overrides.md, "Equity extension" sections.
const BASE_ONLY = ["digitva_core"];
const WITH_EQUITY = ["digitva_core", "equity"];
const FILTERED = ["child_no_care", "female_head", "elderly_alone", "gender_minority", "custody"].map(
  (code) => `vulnerable_group_${code}`
);
const EQUITY_QUESTIONS = [
  "refusal_age_group",
  "refusal_sex",
  "social_group",
  "residence_type",
  "vulnerable_group",
  ...FILTERED,
  "health_coverage"
];

function names(instrument: InstrumentDefinition): string[] {
  return instrument.questions.map((q) => q.name);
}

function question(instrument: InstrumentDefinition, name: string) {
  const found = instrument.questions.find((q) => q.name === name);
  if (!found) throw new Error(`missing ${name}`);
  return found;
}

// Without dates, WHO's isNeonatal / isChild / isAdult follow age_group.
const ADULT = { Id10013: "yes", age_group: "adult" };
const CHILD = { Id10013: "yes", age_group: "child" };
const NEONATE = { Id10013: "yes", age_group: "neonate" };

describe("equity layer", () => {
  const instrument = createWhoVa2022Instrument(WITH_EQUITY);

  it("adds its questions only when the layer is enabled", () => {
    const without = names(createWhoVa2022Instrument(BASE_ONLY));
    for (const name of EQUITY_QUESTIONS) {
      expect(names(instrument)).toContain(name);
      expect(without).not.toContain(name);
    }
  });

  it("places each question after its WHO neighbour", () => {
    const order = names(instrument);
    const after = (anchor: string, followers: string[]) =>
      expect(order.slice(order.indexOf(anchor) + 1, order.indexOf(anchor) + 1 + followers.length)).toEqual(followers);
    after("Id10013", ["consent_mode", "refusal_age_group", "refusal_sex"]);
    after("Id10053", ["social_group"]);
    after("Id10055", ["residence_type"]);
    after("Id10066", ["vulnerable_group", ...FILTERED, "health_coverage"]);
    expect(order.indexOf("health_coverage")).toBeLessThan(order.indexOf("Id10061"));
    expect(question(instrument, "residence_type").sectionPath).toEqual(question(instrument, "Id10055").sectionPath);
  });

  it("asks the deceased questions whenever consent was given, whatever Id10051 says", () => {
    for (const name of ["social_group", "residence_type", "vulnerable_group", "health_coverage"]) {
      const q = question(instrument, name);
      expect(isQuestionRelevant(instrument, q, { ...ADULT, Id10051: "no" })).toBe(true);
      expect(isQuestionRelevant(instrument, q, { ...ADULT, Id10051: "yes" })).toBe(true);
      expect(isQuestionRelevant(instrument, q, { Id10013: "no" })).toBe(false);
    }
    // WHO's own neighbour keeps its Id10051 gate.
    expect(isQuestionRelevant(instrument, question(instrument, "Id10055"), { ...ADULT, Id10051: "no" })).toBe(false);
  });

  it("asks the refusal profile only when consent was refused", () => {
    for (const name of ["refusal_age_group", "refusal_sex"]) {
      const q = question(instrument, name);
      expect(isQuestionRelevant(instrument, q, { Id10013: "no" })).toBe(true);
      expect(isQuestionRelevant(instrument, q, { Id10013: "yes" })).toBe(false);
    }
    expect(question(instrument, "refusal_age_group").choices!.map((c) => c.value)).toEqual([
      "neonate",
      "child",
      "15_49y",
      "50_64y",
      "65_plus",
      "unknown"
    ]);
    expect(question(instrument, "refusal_sex").choices!.map((c) => c.value)).toEqual(["male", "female", "unknown"]);
  });

  it("filters the age- and sex-specific vulnerable groups", () => {
    const relevant = (name: string, data: Record<string, string>) =>
      isQuestionRelevant(instrument, question(instrument, name), data);
    expect(relevant("vulnerable_group_child_no_care", NEONATE)).toBe(true);
    expect(relevant("vulnerable_group_child_no_care", CHILD)).toBe(true);
    expect(relevant("vulnerable_group_child_no_care", ADULT)).toBe(false);

    expect(relevant("vulnerable_group_female_head", { ...ADULT, Id10019: "female" })).toBe(true);
    expect(relevant("vulnerable_group_female_head", { ...ADULT, Id10019: "male" })).toBe(false);
    expect(relevant("vulnerable_group_female_head", { ...CHILD, Id10019: "female" })).toBe(false);

    expect(relevant("vulnerable_group_elderly_alone", ADULT)).toBe(true);
    expect(relevant("vulnerable_group_elderly_alone", CHILD)).toBe(false);

    for (const name of ["vulnerable_group_custody", "vulnerable_group_gender_minority"]) {
      expect(relevant(name, CHILD)).toBe(true);
      expect(relevant(name, ADULT)).toBe(true);
      expect(relevant(name, NEONATE)).toBe(false);
    }
    // The filtered codes are not choices of the unfiltered select_multiple.
    const codes = question(instrument, "vulnerable_group").choices!.map((c) => c.value);
    expect(codes).toContain("disability");
    for (const code of ["child_no_care", "female_head", "elderly_alone", "gender_minority", "custody"]) {
      expect(codes).not.toContain(code);
    }
  });

  it("keeps none, dk and ref exclusive in each select_multiple", () => {
    for (const [name, other] of [
      ["vulnerable_group", "disability"],
      ["health_coverage", "government_scheme"]
    ] as const) {
      const q = question(instrument, name);
      const issues = (value: string[]) => validateAnswer(q, value, {}).map((issue) => issue.code);
      expect(issues([other])).toEqual([]);
      expect(issues(["none"])).toEqual([]);
      for (const exclusive of ["none", "dk", "ref"]) {
        expect(issues([exclusive, other])).toEqual(["constraint"]);
      }
    }
  });

  it("uses DHS-aligned health coverage codes and is never required", () => {
    expect(question(instrument, "health_coverage").choices!.map((c) => c.value)).toEqual([
      "social_security",
      "government_scheme",
      "community_mutual",
      "employer",
      "private",
      "other",
      "none",
      "dk",
      "ref"
    ]);
    for (const name of EQUITY_QUESTIONS) {
      const q = question(instrument, name);
      expect(q.required).toBe(false);
      expect(validateAnswer(q, undefined, {})).toEqual([]);
    }
  });

  it("carries English and Hindi labels on every question and choice", () => {
    for (const name of EQUITY_QUESTIONS) {
      const q = question(instrument, name);
      expect(q.label.en).toBeTruthy();
      expect(q.label.hi).toBeTruthy();
      for (const choice of q.choices ?? []) expect(choice.label.hi).toBeTruthy();
    }
    expect(question(instrument, "residence_type").label.hi).toBe(
      "मृतक जहाँ सामान्यतः रहते थे, वह स्थान ग्रामीण था, शहरी था या शहरी झुग्गी बस्ती?"
    );
  });

  it("uses the India social_group set by default and the international set on request", () => {
    const codes = (inst: InstrumentDefinition) => question(inst, "social_group").choices!.map((c) => c.value);
    expect(codes(instrument)).toEqual(["sc", "st", "obc", "general", "dk", "ref"]);
    const international = createWhoVa2022Instrument(WITH_EQUITY, { equityChoiceSet: "default" });
    expect(codes(international)).toEqual(["indigenous", "ethnic_minority", "majority", "dk", "ref"]);
  });

  it("keeps question orders unique when composed with every layer", () => {
    const all = createWhoVa2022Instrument([
      "digitva_core",
      "equity",
      "doris_support_whova_2022",
      "social_autopsy",
      "abha",
      "narration_language",
      "death_summary",
      "medical_records"
    ]);
    const orders = all.questions.map((q) => q.order);
    expect(new Set(orders).size).toBe(orders.length);
  });
});
