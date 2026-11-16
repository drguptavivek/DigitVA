import { agreeConsentOnPage, isRefused, refusalAnswers, withConsentAgreed } from "../src/refusalBoundary";

test("either independent consent refusal stops the interview", () => {
  expect(isRefused({ Id10013: "no" }, "granted")).toBe(true);
  expect(isRefused({ Id10013: "yes" }, "refused")).toBe(true);
  expect(isRefused({}, undefined)).toBe(false);
});

test("refusal retains only an actual decision and valid broad profile", () => {
  expect(refusalAnswers({ Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female", Id10007: "name", narrative: "private" }))
    .toEqual({ Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female" });
  expect(refusalAnswers({ refusal_sex: "other", refusal_age_group: "23" })).toEqual({});
  expect(refusalAnswers({})).toEqual({});
});

test("agreed consent answers an empty Id10013 yes and never overwrites a decision", () => {
  expect(withConsentAgreed({ Id10007: "a" }, "granted")).toEqual({ Id10007: "a", Id10013: "yes" });
  expect(withConsentAgreed(undefined, "granted")).toEqual({ Id10013: "yes" });
  expect(withConsentAgreed({ Id10013: "" }, "granted")).toEqual({ Id10013: "yes" });
  expect(withConsentAgreed({ Id10013: "no" }, "granted")).toEqual({ Id10013: "no" });
  expect(withConsentAgreed({ Id10013: "yes" }, "granted")).toEqual({ Id10013: "yes" });
});

test("refused or unrecorded consent leaves Id10013 alone", () => {
  expect(withConsentAgreed({}, "refused")).toEqual({});
  expect(withConsentAgreed({}, "none")).toEqual({});
  expect(withConsentAgreed(undefined, undefined)).toBeUndefined();
});

// A stand-in for the form session: `page` is the section shown, `data` the live answers.
function fakeSession(data: Record<string, unknown>, page: "consent" | "other") {
  const session = {
    data,
    page,
    getSnapshot: () => ({ data: { ...session.data }, questions: [{ name: session.page === "consent" ? "Id10013" : "Id10007" }] }),
    setAnswer: jest.fn((name: string, value: string) => { session.data = { ...session.data, [name]: value }; }),
  };
  return session;
}

test("agreed and empty on the consent page answers yes through the session", () => {
  const session = fakeSession({ Id10007: "a" }, "consent");
  agreeConsentOnPage(session, "granted");
  expect(session.data).toEqual({ Id10007: "a", Id10013: "yes" });
  agreeConsentOnPage(session, "granted");
  expect(session.setAnswer).toHaveBeenCalledTimes(1);
});

test("a resumed draft with empty Id10013 gets yes when its consent page opens, not before", () => {
  const session = fakeSession({ Id10007: "a", Id10013: "" }, "other");
  agreeConsentOnPage(session, "granted");
  expect(session.setAnswer).not.toHaveBeenCalled();
  session.page = "consent";
  agreeConsentOnPage(session, "granted");
  expect(session.data.Id10013).toBe("yes");
});

test("an existing no is kept and a refused interview is untouched", () => {
  const no = fakeSession({ Id10013: "no" }, "consent");
  agreeConsentOnPage(no, "granted");
  expect(no.data.Id10013).toBe("no");
  const refused = fakeSession({}, "consent");
  agreeConsentOnPage(refused, "refused");
  agreeConsentOnPage(refused, undefined);
  agreeConsentOnPage(undefined, "granted");
  expect(refused.setAnswer).not.toHaveBeenCalled();
});
