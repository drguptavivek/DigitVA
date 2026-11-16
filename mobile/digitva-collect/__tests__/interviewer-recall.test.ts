import { readWebRecall, recallFromData, withInterviewerRecall, writeWebRecall } from "../src/interviewerRecall";
import { profileInterviewerAnswers, type OfflineProfile } from "../src/offlineProfile";
import { initialDataFromPrefill } from "../src/prefill";

jest.mock("expo-secure-store", () => ({ getItemAsync: jest.fn(), setItemAsync: jest.fn() }));

const last = { Id10010: "Asha", Id10010a: 31, Id10010b: "female", Id10010c: "A-7" };

describe("interviewer recall", () => {
  it("fills the four answers of a new draft from the last interview", () => {
    expect(withInterviewerRecall({ Id10017: "Ravi" }, last, "Account Name")).toEqual({ Id10017: "Ravi", ...last });
  });
  it("never overwrites an existing answer", () => {
    const out = withInterviewerRecall({ Id10010: "Typed", Id10010a: 40 }, last);
    expect(out).toMatchObject({ Id10010: "Typed", Id10010a: 40, Id10010b: "female", Id10010c: "A-7" });
  });
  it("uses the account name alone when there is no previous interview", () => {
    expect(withInterviewerRecall({}, undefined, " Asha K ")).toEqual({ Id10010: "Asha K" });
    expect(withInterviewerRecall({}, undefined)).toEqual({});
  });
  it("prefills only a name Id10010 accepts (letters and spaces)", () => {
    expect(withInterviewerRecall({}, undefined, "Test CHO SC01")).toEqual({ Id10010: "Test CHO SC" });
    expect(withInterviewerRecall({}, undefined, "Dr. A.K. Rao")).toEqual({ Id10010: "Dr AK Rao" });
    expect(withInterviewerRecall({}, undefined, "Asha  Kumar")).toEqual({ Id10010: "Asha Kumar" });
    expect(withInterviewerRecall({}, undefined, "José Rao")).toEqual({ Id10010: "Jose Rao" });
    expect(withInterviewerRecall({}, undefined, "cho_123")).toEqual({ Id10010: "cho" });
    expect(withInterviewerRecall({}, undefined, "1234 .-")).toEqual({});
  });
  it("reduces an invalid Id10010 already in the initial data (server or cached prefill) too", () => {
    expect(withInterviewerRecall({ Id10010: "Test CHO SC01" }, undefined)).toEqual({ Id10010: "Test CHO SC" });
    expect(withInterviewerRecall({ Id10010: "1234", Id10017: "Ravi" }, last)).toEqual({ Id10017: "Ravi", ...last });
  });
  it("keeps only the four interviewer answers", () => {
    expect(recallFromData({ ...last, Id10017: "Ravi", Id10010a: "" })).toEqual({ Id10010: "Asha", Id10010b: "female", Id10010c: "A-7" });
    expect(recallFromData({ Id10017: "Ravi" })).toBeUndefined();
  });
  it("keeps the browser value per user", () => {
    const rows = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => rows.get(k) ?? null,
      setItem: (k: string, v: string) => void rows.set(k, v),
    };
    writeWebRecall("u1", last);
    expect(readWebRecall("u1")).toEqual(last);
    expect(readWebRecall("u2")).toBeUndefined();
  });
});

describe("interviewer details and the deceased's (owner decision 2026-11-14)", () => {
  const profile = { Id10010: "Mina", Id10010a: 44, Id10010b: "female" } as const;
  const previousInterview = { Id10010a: 70, Id10017: "Ravi", Id10019: "male", age_adult: 70, Id10021: "1950-01-01", Id10023_b: "2026-09-01" };

  it("keeps none of the deceased's answers from an earlier interview", () => {
    const recall = recallFromData(previousInterview as never);
    expect(recall).toEqual({ Id10010a: 70 });
    const fresh = withInterviewerRecall({}, recall, "Asha");
    expect(fresh).toMatchObject({ Id10010a: 70 });
    for (const name of ["Id10017", "Id10019", "age_adult", "Id10021", "Id10023_b"]) expect(fresh).not.toHaveProperty(name);
  });
  it("fills the deceased from the death report only", () => {
    const report = initialDataFromPrefill({ deceased: { givenNames: "Ravi", sex: "male", ageInYears: 63, dateOfDeath: "2026-09-01" } });
    const out = withInterviewerRecall(report, recallFromData(previousInterview as never));
    expect(out).toMatchObject({ Id10017: "Ravi", Id10019: "male", age_adult: 63, Id10010a: 70 });
    expect(initialDataFromPrefill({ deceased: { givenNames: "Ravi", sex: "male", dateOfDeath: "2026-09-01" } })).not.toHaveProperty("age_adult");
  });
  it("takes the interviewer's details from the profile before the recall, and the recall where the profile lacks them", () => {
    expect(withInterviewerRecall({}, last, "Account", profile)).toEqual({ ...profile, Id10010c: "A-7" });
    expect(withInterviewerRecall({}, last, "Account", { Id10010: "Mina" })).toEqual({ ...last, Id10010: "Mina" });
  });
  it("derives the profile answers the form accepts", () => {
    const base = { name: "Mina K", age_years: 44, sex: "other" } as OfflineProfile;
    expect(profileInterviewerAnswers(base)).toEqual({ Id10010: "Mina K", Id10010a: 44, Id10010b: "undetermined" });
    expect(profileInterviewerAnswers({ ...base, age_years: 17, sex: null })).toEqual({ Id10010: "Mina K" });
    expect(profileInterviewerAnswers(null)).toEqual({});
  });
});
