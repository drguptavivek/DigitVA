import { refusalProblems } from "../src/refusalText";

describe("refusalProblems (rows for the form's problems list)", () => {
  it("is nothing without a refusal", () => {
    expect(refusalProblems(undefined)).toBeUndefined();
  });

  it("gives one row per named question with the server's reason and Ref", () => {
    expect(
      refusalProblems({ message: "Record the sex.", fields: ["Id10019", "Id10019", "Id10017"], ref: "HTTP 422 x", at: "2026-10-23T10:15:00Z" }),
    ).toEqual([
      { question: "Id10019", message: "Record the sex. · Ref: HTTP 422 x · 10:15Z" },
      { question: "Id10017", message: "Record the sex. · Ref: HTTP 422 x · 10:15Z" },
    ]);
  });

  it("is a general row when no question is named, and uses the fallback reason when the server gave none", () => {
    expect(refusalProblems({ fields: [], ref: "precheck" }, "Not accepted.")).toEqual([{ message: "Not accepted." }]);
    expect(refusalProblems({ message: "Two things", ref: "precheck" })).toEqual([{ message: "Two things" }]);
  });
});
