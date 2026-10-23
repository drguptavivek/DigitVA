/** The phone's pre-send checks mirror web_intake_service._identity_from_answers / _approximate_date_of_death / _interview_outcome. */
import { preSendIssues } from "../src/submissionChecks";
import en from "../src/strings/en.json";

const today = new Date(2026, 9, 23);
const good = { Id10017: "Asha", Id10019: "female", Id10023: "2026-09-29", Id10013: "yes" };
const check = (data: Record<string, unknown>, opts: { valid?: boolean; direct?: boolean } = {}) =>
  preSendIssues(data as never, { valid: opts.valid ?? true, direct: opts.direct ?? true, today });

describe("preSendIssues", () => {
  it("passes a complete direct interview", () => {
    expect(check(good)).toEqual([]);
  });

  it("names the missing name, sex and date with the server's message and question names", () => {
    const [issue] = check({ Id10013: "yes" });
    expect(en[issue.message]).toBe("Record the name, date of death and sex of the deceased before submitting.");
    expect(issue.fields).toEqual(["Id10017", "Id10018", "Id10019", "Id10022", "Id10024"]);
    expect(check({ ...good, Id10017: "", Id10018: "Rao" })).toEqual([]);
    expect(check({ ...good, Id10019: "dk" })[0].fields).toEqual(["Id10019"]);
  });

  it("takes the exact date, the calculated one when the date is known, or a year when it is not", () => {
    expect(check({ ...good, Id10023: undefined, Id10024: "2026" })).toEqual([]);
    expect(check({ ...good, Id10023: undefined, Id10024: "1899" })[0].fields).toEqual(["Id10022", "Id10024"]);
    expect(check({ ...good, Id10023: undefined, Id10024: "2027" })[0].fields).toEqual(["Id10022", "Id10024"]);
    expect(check({ ...good, Id10023: "2026-12-31" })[0].fields).toEqual(["Id10022", "Id10024"]);
    expect(check({ ...good, Id10023: "2026-02-30" })[0].fields).toEqual(["Id10022", "Id10024"]);
    const known = { ...good, Id10023: undefined, Id10022: "yes", Id10020: "yes", Id10023_a: "2026-01-02" };
    expect(check(known)).toEqual([]);
    expect(check({ ...known, Id10023_a: undefined })[0].fields).toEqual(["Id10022", "Id10023_a", "Id10023_b"]);
    // A year does not stand in when the date is said to be known.
    expect(check({ ...known, Id10023_a: undefined, Id10024: "2026" })[0].fields).toEqual(["Id10022", "Id10023_a", "Id10023_b"]);
  });

  it("needs no identity when consent is no, or when a registered case supplies it", () => {
    expect(check({ Id10013: "no", visit_address: "Ward 4", visit_date: "2026-10-01" })).toEqual([]);
    expect(check({ Id10013: "yes" }, { direct: false })).toEqual([]);
  });

  it("needs the consent question answered for a complete form, and refuses refused-with-consent-yes", () => {
    const [unanswered] = check({ ...good, Id10013: "" });
    expect(en[unanswered.message]).toBe("The consent question (Id10013) must be answered.");
    expect(check({ ...good, Id10013: "" }, { valid: false })).toEqual([]);
    const [conflict] = check({ ...good, interview_outcome: "refused" });
    expect(en[conflict.message]).toBe("Consent is recorded as yes, but the interview outcome says refused. Change one of them.");
    expect(conflict.fields).toEqual(["Id10013", "interview_outcome"]);
  });

  it("asks a direct-start refusal for the visit note (address and a real past date), as the server does", () => {
    const [issue] = check({ Id10013: "no" });
    expect(en[issue.message]).toMatch(/visit note/);
    expect(issue.fields).toEqual(["visit_address", "visit_date"]);
    expect(check({ Id10013: "no", visit_address: "Ward 4", visit_date: "2027-01-01" })[0].fields).toEqual(["visit_date"]);
    expect(check({ Id10013: "no", visit_address: " ", visit_date: "2026-10-01" })[0].fields).toEqual(["visit_address"]);
    expect(check({ Id10013: "no" }, { direct: false })).toEqual([]);
  });

  it("returns every issue in the server's order: outcome conflict, unanswered consent, then identity", () => {
    expect(check({ Id10013: "yes", interview_outcome: "refused" }).map((i) => i.message))
      .toEqual(["preOutcomeConflictsConsent", "preIdentityMissing"]);
    expect(check({ Id10013: "" }).map((i) => i.message)).toEqual(["preConsentUnanswered", "preIdentityMissing"]);
  });
});
