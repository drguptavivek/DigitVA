import { describe, expect, it } from "vitest";

import { createWhoVa2022Instrument, whoVa2022Instrument } from "../src/instrument.js";
import { isQuestionRelevant, validateAnswer } from "../src/engine/validation.js";
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
        .filter(
          (q) =>
            q.sourceType !== "digitva-extension" &&
            q.sourceType !== "custom-attachment" &&
            !q.listName?.includes("CONSENT_MODE")
        )
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
      "abha",
      "doris_support_whova_2022"
    ]);
    expect(whoVa2022Instrument.questions.map((q) => q.name)).toEqual(allOn.questions.map((q) => q.name));
    expect(whoVa2022Instrument.sections.map((s) => s.name)).toEqual(allOn.sections.map((s) => s.name));

    const present = names(whoVa2022Instrument);
    for (const name of [
      "narr_language",
      "imagenarr",
      "abha_number",
      "abha_address",
      "ds_available",
      "ds_count",
      "md_available",
      "md_count",
      "consent_mode"
    ]) {
      expect(present.has(name)).toBe(true);
    }
  });
});

describe("createWhoVa2022Instrument: order uniqueness", () => {
  const GATED_LAYERS = [
    "narration_language",
    "abha",
    "death_summary",
    "medical_records",
    "social_autopsy",
    "doris_support_whova_2022"
  ] as const;

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

  it("has no two questions sharing an order value, for every one of the 64 gated-layer combinations", () => {
    const combos = allCombinations(GATED_LAYERS);
    expect(combos).toHaveLength(64);

    for (const combo of combos) {
      const instrument = createWhoVa2022Instrument(new Set([...BASE_ONLY, ...combo]));
      const duplicates = duplicateOrders(instrument);
      expect(
        duplicates,
        `duplicate order(s) ${duplicates.join(", ")} with extensions [${combo.join(", ")}]`
      ).toEqual([]);
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

describe("interview_outcome", () => {
  it("is the last question in every combination, optional, with the four outcomes", () => {
    for (const instrument of [createWhoVa2022Instrument(BASE_ONLY), whoVa2022Instrument]) {
      const last = instrument.questions[instrument.questions.length - 1]!;
      expect(last.name).toBe("interview_outcome");
      expect(last.required).toBe(false);
      expect(last.validation?.choiceValues).toEqual([
        "completed",
        "partially_completed",
        "refused",
        "respondent_unavailable"
      ]);
      expect(last.order).toBe(Math.max(...instrument.questions.map((q) => q.order)));
    }
  });

  it("stays relevant after a refusal, outside WHO's consented group", () => {
    const instrument = createWhoVa2022Instrument(BASE_ONLY);
    const outcome = question(instrument, "interview_outcome")!;
    expect(outcome.sectionPath).toEqual(["digitva_outcome"]);
    expect(instrument.sections.find((s) => s.name === "digitva_outcome")!.relevant).toBeUndefined();
    expect(isQuestionRelevant(instrument, outcome, { Id10013: "no" })).toBe(true);
    expect(isQuestionRelevant(instrument, question(instrument, "noteend")!, { Id10013: "no" })).toBe(false);
  });
});

describe("visit note", () => {
  const names = ["visit_address", "visit_date", "visit_remarks"];

  it("is asked only when consent is no and the case identity is incomplete", () => {
    const instrument = createWhoVa2022Instrument(BASE_ONLY);
    const address = question(instrument, "visit_address")!;
    expect(isQuestionRelevant(instrument, address, { Id10013: "no" })).toBe(true);
    expect(isQuestionRelevant(instrument, address, { Id10013: "yes" })).toBe(false);
    expect(isQuestionRelevant(instrument, address, {})).toBe(false);
    // A name alone leaves the case in draft_identity, so the server still wants the note.
    expect(isQuestionRelevant(instrument, address, { Id10013: "no", Id10017: "Asha" })).toBe(true);
    expect(isQuestionRelevant(instrument, address, { Id10013: "no", Id10017: "Asha", Id10019: "female" })).toBe(true);
    // A register case arrives with name, sex and date of death prefilled.
    const full = { Id10013: "no", Id10017: "Asha", Id10019: "female", Id10022: "yes", Id10020: "yes", Id10023_a: "2026-01-02" };
    expect(isQuestionRelevant(instrument, address, full)).toBe(false);
  });

  it("requires address and visit date, leaves remarks optional, and sits before interview_outcome", () => {
    const instrument = createWhoVa2022Instrument(BASE_ONLY);
    expect(names.map((n) => question(instrument, n)!.required)).toEqual([true, true, false]);
    expect(question(instrument, "visit_date")!.constraint?.source).toBe(". <= today()");
    const order = instrument.questions.map((q) => q.name);
    expect(order.indexOf("visit_remarks")).toBeLessThan(order.indexOf("interview_outcome"));
    expect(order[order.length - 1]).toBe("interview_outcome");
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
    expect(sa09!.constraintMessage?.en).toBe(
      "The number of HCF the patient was taken can only range between 0 to 99 (both included)."
    );

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

describe("doris_support_whova_2022", () => {
  // Annex A of docs/kb/DORIS/who-va-2022-doris-consistency-proposal.md.
  const DORIS = new Set([...BASE_ONLY, "doris_support_whova_2022"]);
  const ADDED = [
    "dob_precision",
    "dob_month_year",
    "dob_year",
    "doris_hours_survived",
    "doris_injury_date_known",
    "doris_injury_date",
    "doris_injury_month_year",
    "doris_injury_place",
    "doris_injury_legal_war",
    "doris_mother_age",
    "Id10366_confirm",
    "doris_pregnancy_weeks",
    "doris_surgery_performed",
    "doris_surgery_when",
    "doris_surgery_when_unit",
    "doris_surgery_type",
    "doris_surgery_reason",
    "doris_autopsy_requested",
    "doris_autopsy_findings"
  ];
  const instrument = createWhoVa2022Instrument(DORIS);
  const who = createWhoVa2022Instrument(BASE_ONLY);
  const q = (name: string) => {
    const found = question(instrument, name);
    expect(found, name).toBeDefined();
    return found!;
  };
  const relevant = (name: string, data: Record<string, unknown>) =>
    isQuestionRelevant(instrument, q(name), data as never);
  const issues = (name: string, value: unknown, data: Record<string, unknown> = {}) =>
    validateAnswer(q(name), value as never, { ...data, [name]: value } as never);
  const choiceValues = (name: string) => q(name).choices?.map((choice) => choice.value);
  // Calculated age fields are derived from the dates, so cases carry dates.
  const dated = (birth: string, death: string) => ({
    Id10013: "yes",
    Id10020: "yes",
    Id10021: birth,
    Id10022: "yes",
    Id10023_a: death
  });
  const NEONATE = dated("2025-08-01", "2025-08-04");
  const SAME_DAY = dated("2025-08-04", "2025-08-04");
  const ADULT = dated("1960-05-17", "2025-08-04");

  it("adds every question, all optional but the birth-weight acknowledgement, and only when enabled", () => {
    const present = names(instrument);
    for (const name of ADDED) expect(present.has(name), name).toBe(true);
    for (const name of ADDED) expect(q(name).required, name).toBe(name === "Id10366_confirm");

    const without = names(who);
    expect(without.has("Id10366")).toBe(true);
    for (const name of ADDED) expect(without.has(name), name).toBe(false);
  });

  it("places each block where Annex A says, in the anchor's section", () => {
    const order = instrument.questions.map((item) => item.name);
    const follows = (anchor: string, block: string[], sectionPath = q(anchor).sectionPath) => {
      const at = order.indexOf(anchor);
      expect(at, anchor).toBeGreaterThan(-1);
      expect(order.slice(at + 1, at + 1 + block.length)).toEqual(block);
      for (const name of block) expect(q(name).sectionPath, name).toEqual(sectionPath);
    };
    follows("Id10021", ["dob_precision", "dob_month_year", "dob_year"]);
    follows("Id10114", ["doris_hours_survived"]);
    follows("Id10077_b", [
      "doris_injury_date_known",
      "doris_injury_date",
      "doris_injury_month_year",
      "doris_injury_place",
      "doris_injury_legal_war"
    ]);
    follows("Id10354", ["doris_mother_age"]);
    follows("Id10366", ["Id10366_confirm"]);
    follows("Id10367", ["doris_pregnancy_weeks"]);
    // A7 sits after the health_service_utilization group, in illhistory itself.
    expect(q("Id10446").sectionPath).toEqual(["consented", "illhistory", "health_service_utilization"]);
    follows(
      "Id10446",
      [
        "doris_surgery_performed",
        "doris_surgery_when",
        "doris_surgery_when_unit",
        "doris_surgery_type",
        "doris_surgery_reason"
      ],
      ["consented", "illhistory"]
    );
    expect(order.indexOf("custom_medical_certificate_upload")).toBe(order.indexOf("Id10473") + 1);
    follows("custom_medical_certificate_upload", ["doris_autopsy_requested", "doris_autopsy_findings"]);
  });

  it("uses Annex A's choice lists", () => {
    expect(q("dob_precision").listName).toBe("dob_precision");
    expect(choiceValues("dob_precision")).toEqual(["month_year", "year", "neither"]);
    expect(q("doris_injury_date_known").listName).toBe("injury_date_known");
    expect(choiceValues("doris_injury_date_known")).toEqual(["full", "month_year", "unknown"]);
    expect(q("doris_injury_place").listName).toBe("injury_place");
    expect(choiceValues("doris_injury_place")).toEqual(["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]);
    expect(q("doris_injury_legal_war").listName).toBe("legal_war");
    expect(choiceValues("doris_injury_legal_war")).toEqual(["legal", "war", "neither", "dk"]);
    expect(q("doris_surgery_when_unit").listName).toBe("time_unit");
    expect(choiceValues("doris_surgery_when_unit")).toEqual(["days", "weeks", "months", "years"]);
    for (const name of ["doris_surgery_performed", "doris_autopsy_requested", "doris_autopsy_findings"]) {
      expect(q(name).listName, name).toBe("YES_NO_DK_REF");
      expect(choiceValues(name), name).toEqual(["yes", "no", "dk", "ref"]);
    }
    expect(q("doris_autopsy_findings").label.en).toBe("Were the autopsy findings made available?");
  });

  it("A1: asks the partial birth date only when the full date is not known", () => {
    expect(relevant("dob_precision", { Id10013: "yes", Id10020: "no" })).toBe(true);
    expect(relevant("dob_precision", { Id10013: "yes", Id10020: "ref" })).toBe(true);
    expect(relevant("dob_precision", { Id10013: "yes", Id10020: "yes" })).toBe(false);
    expect(relevant("dob_month_year", { Id10013: "yes", dob_precision: "month_year" })).toBe(true);
    expect(relevant("dob_month_year", { Id10013: "yes", dob_precision: "year" })).toBe(false);
    expect(relevant("dob_year", { Id10013: "yes", dob_precision: "year" })).toBe(true);
    expect(relevant("dob_year", { Id10013: "yes", dob_precision: "neither" })).toBe(false);
    expect(q("dob_month_year").appearance).toBe("month-year");
    expect(q("dob_year").appearance).toBe("year");
  });

  it("A1: rejects a partial birth date after today, or a birth month after the death", () => {
    expect(issues("dob_month_year", "2025-03-01", { Id10023: "2025-08-04" })).toEqual([]);
    expect(issues("dob_month_year", "2025-03-01")).toEqual([]);
    expect(issues("dob_month_year", "2025-09-01", { Id10023: "2025-08-04" }).length).toBeGreaterThan(0);
    expect(issues("dob_month_year", "2999-01-01").length).toBeGreaterThan(0);
    expect(issues("dob_year", "1950-01-01")).toEqual([]);
    expect(issues("dob_year", "1900-01-01")).toEqual([]);
    expect(issues("dob_year", "1899-01-01").length).toBeGreaterThan(0);
    expect(issues("dob_year", "2999-01-01").length).toBeGreaterThan(0);
  });

  it("A2: checks the birth weight in grammes and asks to acknowledge outside 500-6000 g", () => {
    expect(issues("Id10366", 2800)).toEqual([]);
    expect(issues("Id10366", 100)).toEqual([]);
    expect(issues("Id10366", 3).map((issue) => issue.message)).toEqual([
      "Enter the weight in grammes, not kilogrammes. 1 kg = 1,000 g."
    ]);
    expect(issues("Id10366", 99).length).toBeGreaterThan(0);

    const confirm = q("Id10366_confirm");
    expect(confirm.sourceType).toBe("acknowledge");
    expect(confirm.control).toBe("confirm");
    expect(confirm.dataType).toBe("boolean");
    expect(confirm.label.en).toBe(
      "A birth weight of ${Id10366} g is unusual. Check the card and confirm the weight is in grammes."
    );
    const card = { ...NEONATE, Id10366_check: "yes" };
    expect(relevant("Id10366_confirm", { ...card, Id10366: 450 })).toBe(true);
    expect(relevant("Id10366_confirm", { ...card, Id10366: 6500 })).toBe(true);
    expect(relevant("Id10366_confirm", { ...card, Id10366: 500 })).toBe(false);
    expect(relevant("Id10366_confirm", { ...card, Id10366: 6000 })).toBe(false);
    expect(relevant("Id10366_confirm", card)).toBe(false);
    expect(issues("Id10366_confirm", true)).toEqual([]);
    expect(issues("Id10366_confirm", null).length).toBeGreaterThan(0);
  });

  it("A3: asks hours survived for a live newborn whose birth and death dates are the same day", () => {
    expect(relevant("doris_hours_survived", SAME_DAY)).toBe(true);
    // Signs of life answered yes: Id10114 is then not asked, still relevant.
    expect(relevant("doris_hours_survived", { ...SAME_DAY, Id10104: "yes" })).toBe(true);
    expect(relevant("doris_hours_survived", { ...SAME_DAY, Id10114: "no" })).toBe(true);
    expect(relevant("doris_hours_survived", { ...SAME_DAY, Id10114: "yes" })).toBe(false);
    expect(relevant("doris_hours_survived", NEONATE)).toBe(false);
    expect(relevant("doris_hours_survived", { ...SAME_DAY, Id10022: "no", Id10024: "2025-01-01" })).toBe(
      false
    );
    for (const hours of [0, 23, 88, 99])
      expect(issues("doris_hours_survived", hours), String(hours)).toEqual([]);
    for (const hours of [24, 87, -1]) {
      expect(issues("doris_hours_survived", hours).length, String(hours)).toBeGreaterThan(0);
    }
  });

  it("A4 and A5: pregnancy weeks and mother's age under one year only, with 88/99", () => {
    for (const name of ["doris_mother_age", "doris_pregnancy_weeks"]) {
      expect(relevant(name, NEONATE), name).toBe(true);
      expect(relevant(name, dated("2025-01-10", "2025-08-04")), name).toBe(true);
      expect(relevant(name, dated("2022-01-10", "2025-08-04")), name).toBe(false);
    }
    for (const weeks of [8, 48, 88, 99])
      expect(issues("doris_pregnancy_weeks", weeks), String(weeks)).toEqual([]);
    for (const weeks of [7, 49])
      expect(issues("doris_pregnancy_weeks", weeks).length, String(weeks)).toBeGreaterThan(0);
    for (const age of [10, 60, 88, 99]) expect(issues("doris_mother_age", age), String(age)).toEqual([]);
    for (const age of [9, 61]) expect(issues("doris_mother_age", age).length, String(age)).toBeGreaterThan(0);
  });

  it("A6: asks the injury questions only after an injury death, the date by what is known", () => {
    const injury = { Id10013: "yes", Id10077: "yes" };
    for (const name of ["doris_injury_date_known", "doris_injury_place", "doris_injury_legal_war"]) {
      expect(relevant(name, injury), name).toBe(true);
      expect(relevant(name, { ...injury, Id10077: "dk" }), name).toBe(false);
    }
    expect(relevant("doris_injury_date", { ...injury, doris_injury_date_known: "full" })).toBe(true);
    expect(relevant("doris_injury_date", { ...injury, doris_injury_date_known: "month_year" })).toBe(false);
    expect(relevant("doris_injury_month_year", { ...injury, doris_injury_date_known: "month_year" })).toBe(
      true
    );
    expect(relevant("doris_injury_month_year", { ...injury, doris_injury_date_known: "unknown" })).toBe(
      false
    );
    expect(q("doris_injury_date").appearance).toBe("no-calendar");
    expect(q("doris_injury_month_year").appearance).toBe("month-year");
    for (const name of ["doris_injury_date", "doris_injury_month_year"]) {
      expect(issues(name, "2025-08-01", { Id10023: "2025-08-04" }), name).toEqual([]);
      expect(issues(name, "2025-09-01", { Id10023: "2025-08-04" }).length, name).toBeGreaterThan(0);
      expect(issues(name, "2999-01-01").length, name).toBeGreaterThan(0);
    }
  });

  it("A7: asks surgery of every death but a stillbirth, injury deaths within 7 days included", () => {
    expect(relevant("doris_surgery_performed", ADULT)).toBe(true);
    expect(relevant("doris_surgery_performed", { ...ADULT, Id10077: "yes", Id10077_a: "less" })).toBe(true);
    expect(relevant("doris_surgery_performed", { ...NEONATE, Id10114: "no" })).toBe(true);
    expect(relevant("doris_surgery_performed", { ...NEONATE, Id10114: "yes" })).toBe(false);
    // The WHO group it follows is skipped for the injury death, which is why it sits outside it.
    expect(
      isQuestionRelevant(instrument, q("Id10418"), { ...ADULT, Id10077: "yes", Id10077_a: "less" } as never)
    ).toBe(false);

    const yes = { ...ADULT, doris_surgery_performed: "yes" };
    for (const name of ["doris_surgery_when", "doris_surgery_type", "doris_surgery_reason"]) {
      expect(relevant(name, yes), name).toBe(true);
      expect(relevant(name, { ...ADULT, doris_surgery_performed: "no" }), name).toBe(false);
    }
    expect(relevant("doris_surgery_when_unit", { ...yes, doris_surgery_when: 3 })).toBe(true);
    expect(relevant("doris_surgery_when_unit", { ...yes, doris_surgery_when: 87 })).toBe(true);
    expect(relevant("doris_surgery_when_unit", { ...yes, doris_surgery_when: 88 })).toBe(false);
    expect(relevant("doris_surgery_when_unit", { ...yes, doris_surgery_when: 99 })).toBe(false);
    for (const amount of [0, 88, 99, 120])
      expect(issues("doris_surgery_when", amount), String(amount)).toEqual([]);
    expect(issues("doris_surgery_when", -1).length).toBeGreaterThan(0);
  });

  it("A8: asks autopsy findings only when an autopsy was requested", () => {
    expect(relevant("doris_autopsy_requested", { Id10013: "yes" })).toBe(true);
    expect(relevant("doris_autopsy_findings", { Id10013: "yes", doris_autopsy_requested: "yes" })).toBe(true);
    expect(relevant("doris_autopsy_findings", { Id10013: "yes", doris_autopsy_requested: "no" })).toBe(false);
  });

  it("A9: makes Id10308 required, only with the extension", () => {
    expect(question(who, "Id10308")!.required).toBe(false);
    expect(q("Id10308").required).toBe(true);
    expect(q("Id10308").validation?.required).toBe(true);
    expect(issues("Id10308", null).length).toBeGreaterThan(0);
    expect(issues("Id10308", "dk")).toEqual([]);
  });

  describe("A10: Id10340 after a pregnancy event", () => {
    const WOMAN = { ...dated("1972-03-02", "2025-08-04"), Id10019: "female" };
    const whoId10340 = question(who, "Id10340")!;

    it("replaces the relevance only with the extension", () => {
      expect(whoId10340.relevant?.source).toContain("Id10299");
      expect(q("Id10340").relevant?.source).not.toContain("Id10299");
      expect(relevant("Id10340", { ...WOMAN, Id10312: "yes" })).toBe(true);
      expect(
        relevant("Id10340", { ...WOMAN, Id10305: "no", Id10312: "no", Id10313: "no", Id10334: "yes" })
      ).toBe(true);
      expect(relevant("Id10340", { ...WOMAN, Id10312: "yes", Id10077: "yes", Id10077_a: "less" })).toBe(
        false
      );
      // A post-menopausal woman with no pregnancy: asked by WHO, not by the extension.
      const menopause = { ...WOMAN, Id10296: "yes", Id10299: "yes", Id10310: "yes" };
      expect(isQuestionRelevant(who, whoId10340, menopause as never)).toBe(true);
      expect(relevant("Id10340", menopause)).toBe(false);
    });

    // The server's final-submit strip uses WHO's relevance for every project
    // (build-server-instrument.mjs, whoOverrides: false). That keeps DORIS
    // answers only if A10 is a subset of WHO's relevance on every path the
    // form can take through the maternal chain.
    it("is a subset of WHO's relevance on every answer path through the maternal chain", () => {
      const chain = [
        "Id10296",
        "Id10299",
        "Id10305",
        "Id10312",
        "Id10313",
        "Id10314",
        "Id10306",
        "Id10334",
        "Id10308",
        "Id10310"
      ];
      const answersFor = (name: string) =>
        name === "Id10310" ? ["yes"] : name === "Id10296" ? ["yes", "no", "dk"] : ["yes", "no", "dk"];
      const paths: Record<string, unknown>[] = [];
      const walk = (data: Record<string, unknown>, rest: string[]) => {
        if (rest.length === 0) return void paths.push(data);
        const [name, ...tail] = rest;
        if (!isQuestionRelevant(who, question(who, name!)!, data as never)) return walk(data, tail);
        for (const answer of answersFor(name!)) walk({ ...data, [name!]: answer }, tail);
      };
      for (const birth of ["1990-03-02", "1970-03-02", "1960-03-02"]) {
        for (const injury of [{}, { Id10077: "yes", Id10077_a: "more" }]) {
          walk({ ...dated(birth, "2025-08-04"), Id10019: "female", Id10077: "no", ...injury }, chain);
        }
      }
      let asked = 0;
      for (const data of paths) {
        if (!relevant("Id10340", data)) continue;
        asked += 1;
        expect(isQuestionRelevant(who, whoId10340, data as never), JSON.stringify(data)).toBe(true);
      }
      expect(asked).toBeGreaterThan(0);
    });
  });

  it("leaves the WHO questions alone when the extension is off", () => {
    const base = createWhoVa2022Instrument([]);
    for (const name of ["Id10366", "Id10308", "Id10340"]) {
      expect(question(who, name), name).toBeDefined();
      expect(question(who, name), name).toEqual(question(base, name));
    }
    expect(validateAnswer(question(who, "Id10366")!, 3 as never, { Id10366: 3 } as never)).toEqual([]);
  });

  it("keeps the WHO questions as WHO wrote them for the server artifact", () => {
    const server = createWhoVa2022Instrument(DORIS, { whoOverrides: false });
    expect(names(server).has("Id10366_confirm")).toBe(true);
    for (const name of ["Id10366", "Id10308", "Id10340"]) {
      expect(question(server, name), name).toEqual(question(who, name));
    }
  });
});
