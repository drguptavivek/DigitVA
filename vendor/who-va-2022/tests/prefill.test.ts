import { describe, expect, it } from "vitest";

import {
  createWhoVaInitialDataFromPrefill,
  createWhoVaSession,
  validateSubmission,
  whoVa2022Instrument
} from "../src/index.js";

describe("host prefill mapping", () => {
  it("maps RBAC interviewer context and death-list demographics to WHO question IDs", () => {
    const data = createWhoVaInitialDataFromPrefill({
      presets: { hivAidsMortality: "low", malariaMortality: "high" },
      interviewer: {
        name: "Anita Rao",
        age: 34,
        sex: "female",
        id: "INT-007",
        language: "en"
      },
      deceased: {
        givenNames: "Ramesh",
        surname: "Kumar",
        sex: "male",
        citizenship: "citizen_at_birth",
        dateOfBirth: "1981-02-03",
        dateOfDeath: "2026-07-01"
      },
      location: {
        state: "Karnataka",
        district: "Mysuru",
        village: "Hunsur"
      }
    });

    expect(data).toMatchObject({
      Id10002: "low",
      Id10003: "high",
      Id10010: "Anita Rao",
      Id10010a: 34,
      Id10010b: "female",
      Id10010c: "INT-007",
      language: "en",
      Id10017: "Ramesh",
      Id10018: "Kumar",
      Id10019: "male",
      Id10020: "yes",
      Id10021: "1981-02-03",
      Id10022: "yes",
      Id10023_a: "2026-07-01",
      Id10051: "yes",
      Id10052: "citizen_at_birth",
      Id10057: "Karnataka, Mysuru, Hunsur"
    });

    const session = createWhoVaSession(whoVa2022Instrument, { initialData: data });
    expect(session.getSnapshot().data.Id10023).toBe("2026-07-01");
    expect(session.getSnapshot().data.isAdult).toBe("1");
  });

  it("uses the WHO adult fallback path when only adult age and year of death are known", () => {
    const data = createWhoVaInitialDataFromPrefill({
      deceased: { sex: "female", ageInYears: 72, yearOfDeath: "2026" }
    });

    expect(data).toMatchObject({
      Id10019: "female",
      Id10020: "no",
      age_group: "adult",
      age_adult: 72,
      Id10022: "no",
      Id10024: "2026"
    });

    const result = validateSubmission(whoVa2022Instrument, {
      ...data,
      Id10010: "Interviewer",
      Id10010a: 35,
      Id10010b: "female",
      Id10010c: "INT-1",
      language: "en",
      Id10002: "low",
      Id10003: "low",
      Id10004: "DK",
      Id10007: "Respondent",
      Id10007a: "female",
      Id10007b: 40,
      Id10008: "family_member",
      Id10009: "yes",
      Id10013: "no"
    });
    expect(result.issues.map((issue) => issue.question)).not.toContain("age_adult");
  });

  it("does not put host-only death-list identifiers into the WHO submission payload", () => {
    expect(createWhoVaInitialDataFromPrefill({ deceased: { givenNames: "Case" } })).not.toHaveProperty(
      "Id10073"
    );
  });

  it("combines structured location and death-place detail for the WHO death-place question", () => {
    expect(
      createWhoVaInitialDataFromPrefill({
        location: {
          country: "India",
          state: "Odisha",
          district: "Puri",
          deathPlace: "District hospital"
        }
      })
    ).toMatchObject({
      Id10051: "yes",
      Id10057: "India, Odisha, Puri; District hospital"
    });
  });

  it("prefills citizenship while leaving the session answer editable", () => {
    const session = createWhoVaSession(whoVa2022Instrument, {
      initialData: createWhoVaInitialDataFromPrefill({
        deceased: { citizenship: "citizen_at_birth" }
      })
    });

    expect(session.getSnapshot().data.Id10052).toBe("citizen_at_birth");
    session.setAnswer("Id10052", "foreign_national");
    expect(session.getSnapshot().data.Id10052).toBe("foreign_national");
  });
});
