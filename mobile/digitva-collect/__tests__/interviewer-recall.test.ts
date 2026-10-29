import { readWebRecall, recallFromData, withInterviewerRecall, writeWebRecall } from "../src/interviewerRecall";

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
