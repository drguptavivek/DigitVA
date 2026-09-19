import { describe, expect, it } from "vitest";

import { createWhoVa2022Instrument, whoVa2022Instrument } from "../src/instrument.js";
import { DIGITVA_DOCUMENTS_SECTION } from "../src/digitva-extension.js";

import type { InstrumentDefinition } from "../src/types.js";

const BASE_ONLY = new Set<string>(["digitva_core"]);

function names(instrument: InstrumentDefinition): Set<string> {
  return new Set(instrument.questions.map((q) => q.name));
}

function question(instrument: InstrumentDefinition, name: string) {
  return instrument.questions.find((q) => q.name === name);
}

describe("createWhoVa2022Instrument: layer composition", () => {
  it("emits no layer questions when only digitva_core is enabled", () => {
    const instrument = createWhoVa2022Instrument(BASE_ONLY);
    const present = names(instrument);

    // Base WHO content is present regardless.
    expect(present.has("Id10476")).toBe(true);
    expect(present.has("Id10013")).toBe(true);

    // Digitva_core's own always-on content is present.
    expect(present.has("custom_medical_certificate_upload")).toBe(true);
    expect(present.has("consent_mode")).toBe(true);

    // No layer content leaks in.
    for (const name of [
      "narr_language",
      "imagenarr",
      "abha_number",
      "abha_address",
      "ds_available",
      "ds_count",
      "md_available",
      "md_count",
      "sa01",
      "sa02",
      "sa_note",
      "sa_tu13",
      "sa19"
    ]) {
      expect(present.has(name)).toBe(false);
    }
    for (let slot = 1; slot <= 30; slot += 1) expect(present.has(`md_im${slot}`)).toBe(false);
    for (let slot = 1; slot <= 5; slot += 1) expect(present.has(`ds_im${slot}`)).toBe(false);
  });

  it("adds narr_language and imagenarr only when narration_language is enabled, and removes them when it is not", () => {
    const withLayer = createWhoVa2022Instrument(new Set([...BASE_ONLY, "narration_language"]));
    expect(names(withLayer).has("narr_language")).toBe(true);
    expect(names(withLayer).has("imagenarr")).toBe(true);

    const without = createWhoVa2022Instrument(BASE_ONLY);
    expect(names(without).has("narr_language")).toBe(false);
    expect(names(without).has("imagenarr")).toBe(false);
  });

  it("adds abha_number and abha_address only when abha is enabled, and removes them when it is not", () => {
    const withLayer = createWhoVa2022Instrument(new Set([...BASE_ONLY, "abha"]));
    expect(names(withLayer).has("abha_number")).toBe(true);
    expect(names(withLayer).has("abha_address")).toBe(true);

    const without = createWhoVa2022Instrument(BASE_ONLY);
    expect(names(without).has("abha_number")).toBe(false);
    expect(names(without).has("abha_address")).toBe(false);
  });

  it("adds ds_available, ds_count and ds_im1..5 only when death_summary is enabled, and removes them when it is not", () => {
    const withLayer = createWhoVa2022Instrument(new Set([...BASE_ONLY, "death_summary"]));
    const present = names(withLayer);
    expect(present.has("ds_available")).toBe(true);
    expect(present.has("ds_count")).toBe(true);
    for (let slot = 1; slot <= 5; slot += 1) expect(present.has(`ds_im${slot}`)).toBe(true);

    const without = createWhoVa2022Instrument(BASE_ONLY);
    const absent = names(without);
    expect(absent.has("ds_available")).toBe(false);
    expect(absent.has("ds_count")).toBe(false);
    for (let slot = 1; slot <= 5; slot += 1) expect(absent.has(`ds_im${slot}`)).toBe(false);
  });

  it("adds md_available, md_count and md_im1..30 only when medical_records is enabled, and removes them when it is not", () => {
    const withLayer = createWhoVa2022Instrument(new Set([...BASE_ONLY, "medical_records"]));
    const present = names(withLayer);
    expect(present.has("md_available")).toBe(true);
    expect(present.has("md_count")).toBe(true);
    for (let slot = 1; slot <= 30; slot += 1) expect(present.has(`md_im${slot}`)).toBe(true);

    const without = createWhoVa2022Instrument(BASE_ONLY);
    const absent = names(without);
    expect(absent.has("md_available")).toBe(false);
    expect(absent.has("md_count")).toBe(false);
    for (let slot = 1; slot <= 30; slot += 1) expect(absent.has(`md_im${slot}`)).toBe(false);
  });

  it("carries the ND01-mirrored relevance on the gate questions", () => {
    const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, "death_summary", "medical_records"]));

    const dsCount = question(instrument, "ds_count");
    expect(dsCount).toBeDefined();
    expect(dsCount!.relevant?.source).toBe("selected(${ds_available}, 'yes')");

    const mdCount = question(instrument, "md_count");
    expect(mdCount).toBeDefined();
    expect(mdCount!.relevant?.source).toBe("selected(${md_available}, 'yes')");

    // The per-image relevance on the count itself is untouched.
    const dsIm1 = question(instrument, "ds_im1");
    expect(dsIm1!.relevant?.source).toBe("${ds_count} >= 1");
    const mdIm1 = question(instrument, "md_im1");
    expect(mdIm1!.relevant?.source).toBe("${md_count} >= 1");

    // Gate questions are yes/no/ref, the WHO instrument's own convention
    // (see Id10020/Id10022's YES_NO_REF list).
    expect(question(instrument, "ds_available")).toMatchObject({
      listName: "YES_NO_REF",
      control: "singleChoice"
    });
    expect(question(instrument, "ds_available")!.validation?.choiceValues).toEqual(["yes", "no", "ref"]);
    expect(question(instrument, "md_available")).toMatchObject({
      listName: "YES_NO_REF",
      control: "singleChoice"
    });
    expect(question(instrument, "md_available")!.validation?.choiceValues).toEqual(["yes", "no", "ref"]);
  });

  it("does not emit an empty digitva_documents section when neither document layer is on", () => {
    const withoutDocs = createWhoVa2022Instrument(new Set([...BASE_ONLY, "narration_language", "abha"]));
    expect(withoutDocs.sections.some((s) => s.name === DIGITVA_DOCUMENTS_SECTION)).toBe(false);
    expect(withoutDocs.questions.some((q) => q.sectionPath.includes(DIGITVA_DOCUMENTS_SECTION))).toBe(false);

    const withDocs = createWhoVa2022Instrument(new Set([...BASE_ONLY, "death_summary"]));
    expect(withDocs.sections.some((s) => s.name === DIGITVA_DOCUMENTS_SECTION)).toBe(true);
  });

  it("leaves the base WHO questions untouched in every combination", () => {
    const combos: string[][] = [
      [],
      ["narration_language"],
      ["abha"],
      ["death_summary"],
      ["medical_records"],
      ["social_autopsy"],
      ["narration_language", "abha", "death_summary", "medical_records", "social_autopsy"]
    ];
    const baseline = createWhoVa2022Instrument(BASE_ONLY);
    const baseNames = new Set(
      baseline.questions
        .filter((q) => q.sourceType !== "digitva-extension" && q.sourceType !== "custom-attachment" && !q.listName?.includes("CONSENT_MODE"))
        .map((q) => q.name)
    );

    for (const combo of combos) {
      const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, ...combo]));
      for (const name of baseNames) {
        const beforeQ = question(baseline, name)!;
        const afterQ = question(instrument, name)!;
        expect(afterQ).toBeDefined();
        expect(afterQ.label).toEqual(beforeQ.label);
        expect(afterQ.sectionPath).toEqual(beforeQ.sectionPath);
        expect(afterQ.relevant?.source).toEqual(beforeQ.relevant?.source);
        expect(afterQ.constraint?.source).toEqual(beforeQ.constraint?.source);
      }
    }
  });

  it("keeps whoVa2022Instrument as the backward-compatible all-on default", () => {
    const allOn = createWhoVa2022Instrument([
      "digitva_core",
      "social_autopsy",
      "intake_screen",
      "geography",
      "narration_language",
      "death_summary",
      "medical_records",
      "abha"
    ]);
    expect(whoVa2022Instrument.questions.map((q) => q.name)).toEqual(allOn.questions.map((q) => q.name));
    expect(whoVa2022Instrument.sections.map((s) => s.name)).toEqual(allOn.sections.map((s) => s.name));

    const present = names(whoVa2022Instrument);
    for (const name of ["narr_language", "imagenarr", "abha_number", "abha_address", "ds_available", "ds_count", "md_available", "md_count", "consent_mode"]) {
      expect(present.has(name)).toBe(true);
    }
  });
});

describe("createWhoVa2022Instrument: order uniqueness", () => {
  const GATED_LAYERS = ["narration_language", "abha", "death_summary", "medical_records", "social_autopsy"] as const;

  function allCombinations<T>(items: readonly T[]): T[][] {
    let combos: T[][] = [[]];
    for (const item of items) {
      combos = combos.concat(combos.map((combo) => [...combo, item]));
    }
    return combos;
  }

  function duplicateOrders(instrument: InstrumentDefinition): number[] {
    const seen = new Set<number>();
    const duplicates = new Set<number>();
    for (const question of instrument.questions) {
      if (seen.has(question.order)) duplicates.add(question.order);
      seen.add(question.order);
    }
    return [...duplicates];
  }

  it("has no two questions sharing an order value, for every one of the 32 gated-layer combinations", () => {
    const combos = allCombinations(GATED_LAYERS);
    expect(combos).toHaveLength(32);

    for (const combo of combos) {
      const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, ...combo]));
      const duplicates = duplicateOrders(instrument);
      expect(duplicates, `duplicate order(s) ${duplicates.join(", ")} with extensions [${combo.join(", ")}]`).toEqual([]);
    }
  });

  it("has no two questions sharing an order value in the all-on whoVa2022Instrument export", () => {
    const duplicates = duplicateOrders(whoVa2022Instrument);
    expect(duplicates, `duplicate order(s) ${duplicates.join(", ")}`).toEqual([]);
  });
});

describe("consent_mode", () => {
  it("is present, optional, and relevant only once consent (Id10013) is 'yes' -- without widening the consented group", () => {
    const instrument = createWhoVa2022Instrument(BASE_ONLY);
    const consentMode = question(instrument, "consent_mode");

    expect(consentMode).toBeDefined();
    expect(consentMode!.required).toBe(false);
    expect(consentMode!.relevant?.source).toBe("selected(${Id10013}, 'yes')");
    expect(consentMode!.validation?.choiceValues).toEqual(["in_person", "telephonic"]);

    // Id10013 and the consented group's own relevance are untouched.
    const consentQuestion = question(instrument, "Id10013");
    expect(consentQuestion!.choices?.map((c) => c.value)).toEqual(["yes", "no"]);
    const consentedSection = instrument.sections.find((s) => s.name === "consented");
    expect(consentedSection!.relevant?.source).toBe("selected(${Id10013}, 'yes')");
  });
});

describe("social_autopsy", () => {
  const SA_QUESTION_NAMES = [
    "sa01",
    "sa06",
    "sa06_a",
    "sa02",
    "sa03",
    "sa04",
    "sa05",
    "sa05_a",
    "sa07",
    "sa07_a",
    "sa09",
    "sa10",
    "sa11",
    "sa12",
    "sa08",
    "sa_note",
    "sa_tu13",
    "sa13",
    "sa_tu14",
    "sa14",
    "sa_tu15",
    "sa15",
    "sa_tu16",
    "sa16",
    "sa_tu17",
    "sa17",
    "sa_tu18",
    "sa18",
    "sa_tu19",
    "sa19"
  ] as const;

  it("emits every authored sa* question when enabled, present before checking absence when disabled", () => {
    const withLayer = createWhoVa2022Instrument(new Set([...BASE_ONLY, "social_autopsy"]));
    const present = names(withLayer);
    for (const name of SA_QUESTION_NAMES) {
      expect(present.has(name), `expected ${name} to be present when social_autopsy is enabled`).toBe(true);
    }

    const without = createWhoVa2022Instrument(BASE_ONLY);
    const absent = names(without);
    for (const name of SA_QUESTION_NAMES) {
      expect(absent.has(name), `expected ${name} to be absent when social_autopsy is disabled`).toBe(false);
    }
  });

  it("gates reachinghealthcare and eventchronology on selected(${sa02}, 'yes'), ND01's own group relevance", () => {
    const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, "social_autopsy"]));
    const reaching = instrument.sections.find((s) => s.name === "reachinghealthcare");
    const event = instrument.sections.find((s) => s.name === "eventchronology");
    const socioeconomic = instrument.sections.find((s) => s.name === "socioeconomic");

    expect(reaching?.relevant?.source).toBe("selected(${sa02}, 'yes')");
    expect(event?.relevant?.source).toBe("selected(${sa02}, 'yes')");
    expect(socioeconomic?.relevant).toBeUndefined();
  });

  it("reproduces sa13..sa19's literal string-comparison relevance verbatim, not selected()", () => {
    const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, "social_autopsy"]));
    for (const index of [13, 14, 15, 16, 17, 18, 19]) {
      const q = question(instrument, `sa${index}`);
      expect(q!.relevant?.source).toBe(
        `\${sa_tu${index}}!="na" and \${sa_tu${index}}!="Na" and \${sa_tu${index}}!="nA" and \${sa_tu${index}}!="NA" and \${sa_tu${index}}!=""`
      );
    }
  });

  it("reproduces the sa09 and sa13..sa19 constraints exactly, including their messages", () => {
    const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, "social_autopsy"]));
    const sa09 = question(instrument, "sa09");
    expect(sa09!.constraint?.source).toBe(". >= 0 and . < 100");
    expect(sa09!.constraintMessage?.en).toBe("The number of HCF the patient was taken can only range between 0 to 99 (both included).");

    for (const index of [13, 14, 15, 16, 17, 18, 19]) {
      const q = question(instrument, `sa${index}`);
      expect(q!.constraint?.source).toBe("regex(.,'^(?!0{1,3}$)\\d{1,3}$')");
      expect(q!.constraintMessage?.en).toBe("Kindly enter a valid 1 to 3 digit number.");
    }
  });

  it("keeps ND01's ordinal choice values, not semantic codes", () => {
    const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, "social_autopsy"]));

    const sa01 = question(instrument, "sa01");
    expect(sa01!.listName).toBe("sas01");
    expect(sa01!.choices?.map((c) => c.value)).toEqual(["1", "2", "3", "4", "5", "6"]);
    expect(sa01!.choices?.map((c) => c.label.en)).toEqual([
      "Private Cashless",
      "Private Reimbursement",
      "Ayushman Bharat",
      "State/Central Government",
      "Employee based(ESI/CGHS/Others)",
      "None"
    ]);

    const sa06 = question(instrument, "sa06");
    expect(sa06!.listName).toBe("sas04");
    expect(sa06!.choices?.map((c) => c.value)).toEqual(["1", "2", "3", "4"]);
    expect(sa06!.choices?.map((c) => c.label.en)).toEqual(["Home", "HCF", "In transit", "Others"]);

    // sa06_a's relevance keys off sa06's ordinal "4" ("Others"), not a semantic code.
    expect(question(instrument, "sa06_a")!.relevant?.source).toBe("selected(${sa06}, '4')");
  });
});
