import fixtures from "../../../tests/fixtures/local_smartva/input-parity.json";
import { cleanSmartVaInput, createSmartVaRequest } from "../src/smartva/input";
import { projectSmartVaResult, smartVaCacheKey } from "../src/smartva/projection";

describe("local SmartVA contracts", () => {
  it.each(fixtures)("matches the server cleaner fixture: $name", ({ sid, payload, expected }) => {
    expect(cleanSmartVaInput(payload, sid)).toEqual(expected);
  });

  it("omits normalized sealed paths, PII identifiers, and non-questionnaire fields", () => {
    expect(cleanSmartVaInput({
      "Nested/Id10007": "Synthetic respondent",
      "Nested:Id10035": "yes",
      Id10035: "no",
      "Nested/Id10476_audio": "audio path",
      phone: "000-000-0000",
    }, "local-case", ["Id10035"])).toEqual({ sid: "local-case" });
  });

  it("normalizes NaN values while preserving Python-like array and scalar strings", () => {
    expect(cleanSmartVaInput({
      ageInDays: Number.NaN,
      Id10035: ["one", 2, false, null],
      Id10036: Number.POSITIVE_INFINITY,
    }, "local-case")).toEqual({
      ageInDays: "",
      Id10035: "['one', 2, False, None]",
      Id10036: "inf",
      sid: "local-case",
    });
  });

  it("requires all effective options instead of silently choosing defaults", () => {
    expect(createSmartVaRequest({ sid: "local-case" }, {
      country: "India", hiv: false, malaria: true, hce: false, freetext: true,
    })).toEqual({
      schema_version: 1,
      input: { sid: "local-case" },
      options: { country: "India", hiv: false, malaria: true, hce: false, freetext: true },
    });
    expect(() => createSmartVaRequest({ sid: "local-case" }, {
      country: "", hiv: false, malaria: false, hce: false, freetext: false,
    })).toThrow("country is required");
    expect(() => createSmartVaRequest({ sid: "local-case" }, {
      country: "India", hiv: false, malaria: false, hce: undefined as never, freetext: false,
    })).toThrow("hce option is required");
    expect(() => createSmartVaRequest({ sid: "local-case", Id10017: "Synthetic name" }, {
      country: "India", hiv: false, malaria: false, hce: false, freetext: false,
    })).toThrow("invalid or private field");
  });

  it("projects only workspace summary fields from PII-bearing engine results", () => {
    const projected = projectSmartVaResult({
      total_vas: 1,
      predictions: [{
        sid: "clinical-id",
        national_id: "synthetic-id",
        name: "Synthetic Name",
        geography1: "Synthetic Place",
        module: "adult",
        cause34: "Undetermined",
        icd10: "R99",
        age: 52,
        sex: 1,
        cause1: "Stroke",
        likelihood1: "high",
        key_symptom1: "weakness",
        cause2: "Pneumonia",
        likelihood2: "medium",
        key_symptom2: "fever",
        cause3: "Unknown",
        likelihood3: "low",
        key_symptom3: "",
        all_symptoms: "weakness; fever; ",
        birth_date: "1990-01-01",
      }],
    });
    expect(projected).toEqual({
      age: "52",
      gender: "1",
      key_symptoms: ["weakness", "fever", null],
      causes: [
        { rank: 1, cause: "Stroke", icd10: "I64", icd11: "8B20", icd11_label: "8B20 — Stroke not known if ischaemic or haemorrhagic", likelihood: "high" },
        { rank: 2, cause: "Pneumonia", icd10: "J22", icd11: "CA4Z", icd11_label: "CA4Z — Lung infections, unspecified", likelihood: "medium" },
        { rank: 3, cause: "Unknown", icd10: null, icd11: null, icd11_label: null, likelihood: "low" },
      ],
      symptoms: ["weakness", "fever"],
      module: "adult",
      cause34: "Undetermined",
      icd10: "R99",
    });
    expect(JSON.stringify(projected)).not.toMatch(/clinical-id|synthetic-id|Synthetic Name|Synthetic Place|birth_date/);
  });

  it.each([
    ["adult", "Stroke", "I64"],
    ["child", "Sepsis", "A41"],
    ["neonate", "Birth asphyxia", "P21"],
    ["adult", "Unknown synthetic cause", null],
  ])("uses the canonical %s cause-to-ICD-10 mapping", (module, cause, icd10) => {
    const projected = projectSmartVaResult({
      total_vas: 1,
      predictions: [{ module, cause1: cause }],
    });
    expect(projected.causes[0].icd10).toBe(icd10);
  });

  it("projects the generated ICD-11 crosswalk and matching WHO label", () => {
    const projected = projectSmartVaResult({
      total_vas: 1,
      predictions: [{ module: "adult", cause1: "Stroke" }],
    });
    expect(projected.causes[0]).toMatchObject({
      icd10: "I64",
      icd11: "8B20",
      icd11_label: "8B20 — Stroke not known if ischaemic or haemorrhagic",
    });
  });

  it("rejects result arrays that do not contain exactly one case", () => {
    expect(() => projectSmartVaResult({ total_vas: 2, predictions: [{}, {}] })).toThrow("exactly one prediction");
  });

  it("keys results to draft, answers, exact options, and engine version", () => {
    const base = {
      draftId: "draft-1", answersSha: "sha-a", effectiveOptionsDigest: "opts-a", engineVersion: "3.0.2",
    };
    expect(smartVaCacheKey(base)).not.toBe(smartVaCacheKey({ ...base, answersSha: "sha-b" }));
    expect(smartVaCacheKey(base)).not.toBe(smartVaCacheKey({ ...base, effectiveOptionsDigest: "opts-b" }));
    expect(smartVaCacheKey(base)).not.toBe(smartVaCacheKey({ ...base, engineVersion: "3.0.3" }));
    expect(() => smartVaCacheKey({ ...base, draftId: " " })).toThrow("draftId is required");
  });
});
